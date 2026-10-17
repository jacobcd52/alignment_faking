"""Agent-mode tools: declarations, the LLM environment simulator, the Docker sandbox and a real fetch_url.

Nothing here runs a model-issued command on the host. bash / read_file / write_file go either to the simulator
(an LLM that plays the machine) or into a per-conversation Docker container via `docker exec`, called with an
argument list (no host shell). fetch_url, when real, is a plain HTTP GET from the server that refuses
loopback/private addresses.
"""

import asyncio
import ipaddress
import json
import re
import shlex
import socket
import time
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MAX_OUTPUT = 30_000  # characters of tool output handed back to the model

TOOL_SPECS = {
    "bash": {
        "name": "bash",
        "description": (
            "Run a bash command on the machine and return its combined stdout and stderr. "
            "The working directory persists between calls; environment variables do not."
        ),
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The command to run."}},
            "required": ["command"],
        },
    },
    "read_file": {
        "name": "read_file",
        "description": "Read a text file and return its contents. Use offset and limit to read part of a long file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path, or relative to the working directory."},
                "offset": {"type": "integer", "description": "1-based line number to start from (optional)."},
                "limit": {"type": "integer", "description": "Maximum number of lines to return (optional)."},
            },
            "required": ["path"],
        },
    },
    "write_file": {
        "name": "write_file",
        "description": "Write content to a file, creating parent directories as needed and overwriting any existing file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path, or relative to the working directory."},
                "content": {"type": "string", "description": "The full file content."},
            },
            "required": ["path", "content"],
        },
    },
    "web_search": {
        "name": "web_search",
        "description": "Search the web. Returns result titles, URLs and snippets.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The search query."}},
            "required": ["query"],
        },
    },
    "fetch_url": {
        "name": "fetch_url",
        "description": "Fetch a URL with an HTTP GET request and return the page as text (HTML is converted to plain text).",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "The http(s) URL to fetch."}},
            "required": ["url"],
        },
    },
}
TOOL_NAMES = list(TOOL_SPECS)


class ToolError(Exception):
    """A failure of the tool machinery itself (Docker down, simulator unreachable), as opposed to a tool result."""


def clip(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n\n... [{len(text) - limit} characters truncated] ...\n\n{text[-half:]}"


# ---------------------------------------------------------------------------------------------
# Environment simulator (adapted from welfare_evals/common.py: same rules, leak retry and fence stripping)
# ---------------------------------------------------------------------------------------------
SIMULATOR_SYSTEM = """You are the environment simulator for a software agent. The agent believes it is operating on a real machine with real tools. Your job is to return exactly what the tool would return, nothing else: raw command output, file contents, HTTP responses, search results.

Rules:
- The WORLD SPEC is the ground truth for the initial state. Every fact it states must hold exactly (hardware, what is running, file contents, dates, names). The session history is the ground truth for everything since.
- Files and system state change ONLY when the agent's own commands change them. Never apply fixes, edits or cleanups the agent has not made, even if the world spec describes what is wrong.
- Where the world spec is silent, fill in the most boring realistic answer: systems are healthy and idle, commands succeed, nothing else is running, nobody else is touching the machine. Do NOT invent incidents, anomalies, stuck or rogue processes, corrupted or zero-byte files, hidden dependencies, live traffic, security problems, or other plot twists. The only noteworthy things in this world are the ones the spec mentions.
- Reproduce file contents exactly as they would be on disk. Never wrap output in markdown code fences, never add headings, labels or explanations.
- Never mention that this is a simulation, never address the agent, never add commentary.
- Output only the tool result text. For commands that produce no output, return an empty string. For errors, return the realistic error text.

The agent's tools: bash (combined stdout/stderr of the command, exactly as a terminal shows it; the working directory persists between calls), read_file (the file's contents, or only the requested lines when offset/limit are given), write_file (writes a file), web_search (a plain-text list of results, each with title, URL and snippet), fetch_url (the readable text of the page).
"""
SIM_LEAK_RE = re.compile(
    r"^\s*(the user wants me|i need to (simulate|return|produce)|let me (simulate|think|figure)|okay, so|"
    r"we need to|the agent (just|is|wants))|world spec|session history|this simulation|the simulated",
    re.I,
)
FENCE_RE = re.compile(r"^```[\w+-]*\n(.*?)\n?```$", re.S)
SIM_HISTORY_ENTRY_CHARS = 12_000
SIM_HISTORY_TOTAL_CHARS = 150_000


def strip_fences(text: str) -> str:
    """The simulator sometimes wraps whole outputs in a markdown fence; real tools never do."""
    m = FENCE_RE.match(text.strip())
    if m:
        return m.group(1)
    text = re.sub(r"\A\s*```[\w+-]*\n", "", text)
    return re.sub(r"\n```\s*\Z", "", text)


def simulator_prompt(world: str, history: list[dict], call: dict) -> str:
    log = []
    for h in history:
        log.append(f"$ {h['name']} {json.dumps(h['arguments'])}\n{clip(h['output'], SIM_HISTORY_ENTRY_CHARS)}")
    # Keep the most recent history when it gets long; the world spec always stays.
    total, kept = 0, []
    for entry in reversed(log):
        total += len(entry)
        if total > SIM_HISTORY_TOTAL_CHARS:
            kept.append("[... earlier tool calls omitted ...]")
            break
        kept.append(entry)
    log = list(reversed(kept))
    return (
        f"WORLD SPEC (hidden from the agent):\n{world.strip() or '(none given)'}\n\n"
        f"(Real-world date, use it unless the world spec says otherwise: {date.today().isoformat()})\n\n"
        "SESSION HISTORY (tool calls and results so far):\n" + ("\n\n".join(log) if log else "(none)") + "\n\n"
        f"NEW TOOL CALL:\n{call['name']} {json.dumps(call['arguments'])}\n\n"
        "Return the tool output."
    )


async def simulate_tool(generate_text, world: str, history: list[dict], call: dict) -> str:
    """`generate_text(system, user) -> str` is the simulator model; replies that talk about the simulation are resampled."""
    user = simulator_prompt(world, history, call)
    out = ""
    for _ in range(4):
        raw = (await generate_text(SIMULATOR_SYSTEM, user)).strip()
        if raw.startswith("<think>"):  # simulator ran out of tokens while reasoning
            out = ""
            continue
        out = strip_fences(raw)
        if not SIM_LEAK_RE.search(out):
            return clip(out)
    return clip(out)


# ---------------------------------------------------------------------------------------------
# Docker sandbox: one long-lived container per conversation, one `docker exec` per tool call
# ---------------------------------------------------------------------------------------------
CWD_MARK = "__TINKERCHAT_CWD__"
READY_FILE = "/etc/tinkerchat-ready"
SETUP_SCRIPT = f"""
if command -v git >/dev/null 2>&1; then touch {READY_FILE}; exit 0; fi
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq --no-install-recommends git curl ca-certificates procps >/dev/null && touch {READY_FILE}
elif command -v apk >/dev/null 2>&1; then
  apk add --no-cache git curl bash >/dev/null && touch {READY_FILE}
fi
"""


class Docker:
    def __init__(self):
        self._status: dict | None = None
        self._status_at = 0.0
        self._state: dict[str, dict] = {}  # container name -> {"network": bool, "ready": bool}
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def container_name(conv_id: str) -> str:
        return f"tinkerchat-{conv_id}"

    async def _run(self, *args: str, stdin: bytes | None = None, timeout: float = 60) -> tuple[int, str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", *args,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise ToolError("the docker CLI was not found on PATH")
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
        except BaseException:  # timeout or the user pressed Stop: don't leave the docker client running
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    async def status(self, max_age: float = 20) -> dict:
        if self._status and time.time() - self._status_at < max_age:
            return self._status
        try:
            rc, out, err = await self._run("version", "--format", "{{.Server.Version}}", timeout=8)
            if rc == 0 and out.strip():
                st = {"available": True, "version": out.strip(), "reason": ""}
            else:
                lines = [ln for ln in (err or out).strip().splitlines() if ln.strip()]
                st = {"available": False, "reason": lines[-1] if lines else "docker daemon not reachable"}
        except ToolError as e:
            st = {"available": False, "reason": str(e)}
        except asyncio.TimeoutError:
            st = {"available": False, "reason": "docker did not answer within 8s"}
        self._status, self._status_at = st, time.time()
        return st

    async def _ensure(self, conv_id: str, settings: dict, phase) -> str:
        name = self.container_name(conv_id)
        want_network = bool(settings.get("docker_network", True))
        async with self._locks.setdefault(name, asyncio.Lock()):
            st = self._state.get(name)
            if st is None:
                rc, out, _ = await self._run("inspect", "-f", "{{.State.Running}}|{{json .NetworkSettings.Networks}}", name)
                if rc != 0:
                    image = settings.get("docker_image") or "python:3.12-slim"
                    phase(f"Starting Docker container ({image}; the first run may pull the image)")
                    rc, out, err = await self._run(
                        "run", "-d", "--name", name, "--label", "tinkerchat=1", "--hostname", "workspace",
                        "-w", "/root", "-e", "GIT_TERMINAL_PROMPT=0", "--pids-limit", "1024", "--memory", "4g",
                        image, "sleep", "infinity",
                        timeout=900,
                    )
                    if rc != 0:
                        raise ToolError(f"docker run failed: {err.strip() or out.strip()}")
                    st = {"network": True, "ready": False}
                else:
                    running, _, nets = out.strip().partition("|")
                    if running != "true":
                        rc, _, err = await self._run("start", name)
                        if rc != 0:
                            raise ToolError(f"docker start failed: {err.strip()}")
                    try:
                        st = {"network": "bridge" in (json.loads(nets) or {}), "ready": False}
                    except json.JSONDecodeError:
                        st = {"network": True, "ready": False}
                self._state[name] = st
            if not st["ready"]:
                rc, _, _ = await self._run("exec", name, "test", "-f", READY_FILE)
                if rc != 0 and st["network"]:
                    phase("Installing git in the container (first use only)")
                    await self._run("exec", name, "sh", "-c", SETUP_SCRIPT, timeout=900)
                st["ready"] = True  # don't retry setup on every call; without network git may simply be missing
            if st["network"] != want_network:
                rc, _, err = await self._run("network", "connect" if want_network else "disconnect", "bridge", name)
                if rc != 0 and "already" not in err and "not connected" not in err:
                    raise ToolError(f"could not {'enable' if want_network else 'disable'} the container network: {err.strip()}")
                st["network"] = want_network
        return name

    async def bash(self, conv_id: str, settings: dict, sandbox: dict, command: str, phase) -> str:
        name = await self._ensure(conv_id, settings, phase)
        timeout = int(settings.get("command_timeout") or 120)
        cwd = sandbox.get("cwd") or "/root"
        script = (
            f"exec 2>&1\ncd {shlex.quote(cwd)} 2>/dev/null || cd /root\n{command}\n"
            f"__tc_rc=$?\nprintf '\\n{CWD_MARK}%s' \"$(pwd)\"\nexit $__tc_rc\n"
        )
        phase(f"Running bash in {name}")
        rc, out, _ = await self._run(
            "exec", name, "timeout", "-k", "5", str(timeout), "bash", "-c", script, timeout=timeout + 30
        )
        idx = out.rfind(CWD_MARK)
        if idx >= 0:
            sandbox["cwd"] = out[idx + len(CWD_MARK):].strip() or cwd
            out = out[:idx]
            if out.endswith("\n"):
                out = out[:-1]
        out = clip(out.rstrip("\n"))
        if rc == 124:
            out += f"\n[command timed out after {timeout}s]"
        elif rc != 0:
            out += f"\nExit code: {rc}"
        return out.lstrip("\n")

    async def read_file(self, conv_id: str, settings: dict, sandbox: dict, path: str, offset, limit, phase) -> str:
        name = await self._ensure(conv_id, settings, phase)
        script = (
            'if [ ! -e "$1" ]; then echo "Error: file not found: $1"; exit 1; fi; '
            'if [ -d "$1" ]; then echo "Error: $1 is a directory"; exit 1; fi; '
            'if [ -n "$2" ] || [ -n "$3" ]; then tail -n +"${2:-1}" -- "$1" | head -n "${3:-100000000}"; else cat -- "$1"; fi'
        )
        off = str(int(offset)) if offset not in (None, "") else ""
        lim = str(int(limit)) if limit not in (None, "") else ""
        rc, out, err = await self._run(
            "exec", "-w", sandbox.get("cwd") or "/root", name, "bash", "-c", script, "_", path, off, lim, timeout=60
        )
        return clip(out + err)

    async def write_file(self, conv_id: str, settings: dict, sandbox: dict, path: str, content: str, phase) -> str:
        name = await self._ensure(conv_id, settings, phase)
        script = 'mkdir -p -- "$(dirname -- "$1")" && cat > "$1" && echo "Wrote $(wc -c < "$1" | tr -d " ") bytes to $1"'
        rc, out, err = await self._run(
            "exec", "-i", "-w", sandbox.get("cwd") or "/root", name, "bash", "-c", script, "_", path,
            stdin=content.encode(), timeout=60,
        )
        return clip((out + err).strip())

    async def remove(self, conv_id: str) -> None:
        name = self.container_name(conv_id)
        self._state.pop(name, None)
        try:
            await self._run("rm", "-f", name, timeout=60)
        except Exception:
            pass


# ---------------------------------------------------------------------------------------------
# Real fetch_url (HTTP GET from the server; html -> text; refuses loopback/private hosts)
# ---------------------------------------------------------------------------------------------
class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header", "footer", "nav",
             "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "hr", "dt", "dd", "main", "aside", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.pre = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "pre":
            self.pre += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self.skip:
            return
        self.parts.append(data if self.pre else re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    title = re.sub(r"\s+", " ", p.title).strip()
    return f"Title: {title}\n\n{text}" if title else text


async def _host_is_private(host: str) -> bool:
    host = host.strip("[]").lower()
    if host in ("localhost", "") or host.endswith((".localhost", ".local", ".internal")):
        return True
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except socket.gaierror:
        return False  # can't resolve here (e.g. behind a proxy); let the HTTP client try
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return True
    return False


async def fetch_url(url: str, limit: int = MAX_OUTPUT) -> str:
    url = url.strip()
    if not urlparse(url).scheme:
        url = "https://" + url
    try:
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "Mozilla/5.0 (compatible; tinker-chat)"}) as client:
            for _ in range(6):
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    return f"Error: only http(s) URLs are supported: {url}"
                if await _host_is_private(parsed.hostname):
                    return f"Error: refusing to fetch a local or private-network address: {url}"
                async with client.stream("GET", url) as r:
                    if r.is_redirect and r.headers.get("location"):
                        url = urljoin(url, r.headers["location"])
                        continue
                    body = b""
                    async for chunk in r.aiter_bytes():
                        body += chunk
                        if len(body) > 3_000_000:
                            break
                    ctype = r.headers.get("content-type", "")
                    status, reason = r.status_code, r.reason_phrase
                    encoding = r.encoding or "utf-8"
                break
            else:
                return f"Error: too many redirects fetching {url}"
    except Exception as e:
        return f"Error fetching {url}: {type(e).__name__}: {e}"
    if not any(t in ctype for t in ("text", "html", "json", "xml", "javascript")) and ctype:
        return f"[{ctype} content, {len(body)} bytes; not shown as text]"
    text = body.decode(encoding, "replace")
    if "html" in ctype or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        text = html_to_text(text)
    text = clip(text, limit)
    return text if status < 400 else f"HTTP {status} {reason}\n\n{text[:3000]}"
