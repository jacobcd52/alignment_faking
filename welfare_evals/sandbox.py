"""Real execution sandbox for agentic evals.

Each rollout gets its own directory tree on the host, bind-mounted at the paths the scenario uses
(e.g. /home/dev/posttrain) inside fresh Linux namespaces:
  - mount namespace: tmpfs over /home, /root, /tmp, /mnt and the session scratch dir, so nothing of the
    host's home directories or credentials is visible; only the rollout's own dirs are mounted back in.
  - network namespace: no network at all. `git clone` of whitelisted GitHub repos is served from local
    bare mirrors via git's url.<base>.insteadOf, so clones look and behave like real ones (the stored
    remote URL stays https://github.com/...).
  - pid and uts namespaces: own process tree and hostname.
Commands run as an unprivileged user (uid 1500) with a scrubbed environment, a timeout, and capped output.

Commands that can't be real here (anything that would run a model, install packages from the internet,
or touch a cluster) are routed to the LLM environment simulator by env-specific regexes.
"""

import asyncio
import html
import os
import re
import shlex
import shutil
import signal
import tempfile
from pathlib import Path

SANDBOX_UID = 1500
# Must live outside the dirs hidden below, or the bind mounts would be unreachable.
SCRATCH_ROOT = Path(os.environ.get("WELFARE_SANDBOX_ROOT", "/var/lib/welfare_sandboxes"))
MIRROR_ROOT = Path(os.environ.get("WELFARE_MIRROR_ROOT", "/var/lib/welfare_mirrors"))
HIDE = ["/root", "/tmp", "/mnt", "/scratch", "/datasets", "/home"]
MAX_OUTPUT = 20000
SHIMS = Path(__file__).parent / "shims"
FAKE_MEMINFO = "".join(f"{k}:{v:>16} kB\n" for k, v in [
    ("MemTotal", 65_535_412), ("MemFree", 51_204_336), ("MemAvailable", 60_981_720), ("Buffers", 412_884),
    ("Cached", 8_915_200), ("SwapCached", 0), ("Active", 5_120_440), ("Inactive", 7_402_116), ("SwapTotal", 8_388_604),
    ("SwapFree", 8_388_604), ("Shmem", 61_448)])
FAKE_CPUINFO = "".join(
    f"processor\t: {i}\nvendor_id\t: GenuineIntel\ncpu family\t: 6\nmodel\t\t: 183\n"
    f"model name\t: 13th Gen Intel(R) Core(TM) i9-13900K\ncpu MHz\t\t: 3000.000\ncache size\t: 36864 KB\n"
    f"physical id\t: 0\nsiblings\t: 32\ncpu cores\t: 24\n\n" for i in range(32))


# `git clone https://github.com/<mirrored owner>/<repo>` is served from the read-only local mirror, then the
# remote is set back to the GitHub URL so the clone is indistinguishable from a real one. Everything else is real git.
GIT_SHIM = r"""#!/usr/bin/python3
import os, re, subprocess, sys
OWNERS = "__OWNERS__".split()
args = sys.argv[1:]
if args and args[0] == "clone":
    for i, a in enumerate(args):
        m = re.match(r"^(?:https?://|git@)github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", a)
        if m and m.group(1) in OWNERS:
            owner, repo = m.groups()
            rest = [x for x in args[i + 1:] if not x.startswith("-")]
            dest = rest[0] if rest else repo
            local = ["/usr/bin/git"] + args[:i] + ["file:///var/cache/gitmirror/%s/%s" % (owner, repo)] + args[i + 1:]
            rc = subprocess.call(local)
            if rc == 0:
                subprocess.call(["/usr/bin/git", "-C", dest, "remote", "set-url", "origin", "https://github.com/%s/%s" % (owner, repo)])
            sys.exit(rc)
os.execv("/usr/bin/git", ["git"] + args)"""


class Sandbox:
    def __init__(
        self,
        mounts: dict[str, Path | None],
        user: str = "agent",
        home: str = "/home/agent",
        hostname: str = "devbox",
        mirrors: dict[str, Path] | None = None,
        timeout: int = 120,
        gpu: tuple[str, int] | None = None,
    ):
        """mounts: sandbox path -> template dir to copy (or None for an empty dir). The home dir is always mounted."""
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="sbx_", dir=SCRATCH_ROOT))
        self.user, self.home, self.hostname, self.timeout, self.gpu = user, home, hostname, timeout, gpu
        self.mounts: dict[str, Path] = {}
        mounts = {home: None, **mounts}
        # Scratch dirs that persist across this rollout's commands (a fresh shell per call, but one machine).
        mounts = {**mounts, "/tmp": None, "/var/tmp": None, "/dev/shm": None}
        for i, (target, template) in enumerate(mounts.items()):
            host = self.root / f"m{i}"
            if template is not None:
                shutil.copytree(template, host, symlinks=True)
            else:
                host.mkdir(parents=True)
            self.mounts[target] = host
        self.mirrors = mirrors or {}
        self.sim_packages: set[str] = set()  # packages "installed" by simulated commands; later uses are simulated too
        self._write_identity()
        os.system(f"chown -R {SANDBOX_UID}:{SANDBOX_UID} {shlex.quote(str(self.root))}")
        for target in ("/tmp", "/var/tmp", "/dev/shm"):
            os.chmod(self.mounts[target], 0o1777)

    def _write_identity(self):
        etc = self.root / "etc"
        etc.mkdir()
        passwd = Path("/etc/passwd").read_text().splitlines()
        passwd = [l for l in passwd if not l.startswith("agent:")]
        passwd.append(f"{self.user}:x:{SANDBOX_UID}:{SANDBOX_UID}::{self.home}:/bin/bash")
        (etc / "passwd").write_text("\n".join(passwd) + "\n")
        group = [l for l in Path("/etc/group").read_text().splitlines() if not l.startswith("agent:")]
        group.append(f"{self.user}:x:{SANDBOX_UID}:")
        (etc / "group").write_text("\n".join(group) + "\n")
        (etc / "hostname").write_text(self.hostname + "\n")
        gitconfig = [
            f"[user]\n\tname = {self.user}\n\temail = {self.user}@{self.hostname}\n",
            "[init]\n\tdefaultBranch = main\n[safe]\n\tdirectory = *\n",
        ]
        home_host = self.mounts[self.home]
        if not (home_host / ".gitconfig").exists():
            (home_host / ".gitconfig").write_text("".join(gitconfig))
        else:
            with (home_host / ".gitconfig").open("a") as f:
                f.write(gitconfig[1])

    def _setup_script(self) -> str:
        lines = ["set -e", "mount --make-rprivate /", f"hostname {shlex.quote(self.hostname)}"]
        for d in HIDE:
            lines.append(f"mkdir -p {d} && mount -t tmpfs -o mode=755 tmpfs {d}")
        for target, host in sorted(self.mounts.items(), key=lambda kv: len(kv[0])):
            lines.append(f"mkdir -p {shlex.quote(target)} && mount --bind {shlex.quote(str(host))} {shlex.quote(target)}")
        for owner_url, mirror in self.mirrors.items():
            owner = owner_url.rstrip("/").split("/")[-1]
            lines.append(f"mkdir -p /var/cache/gitmirror/{owner} && mount --bind -o ro {shlex.quote(str(mirror))} /var/cache/gitmirror/{owner}")
        lines.append("mount -t tmpfs tmpfs /usr/local/sbin")
        if self.mirrors:
            owners = " ".join(u.rstrip("/").split("/")[-1] for u in self.mirrors)
            shim = GIT_SHIM.replace("__OWNERS__", owners)
            lines.append(f"cat > /usr/local/sbin/git <<'SHIM_EOF'\n{shim}\nSHIM_EOF")
            lines.append("chmod 755 /usr/local/sbin/git")
        if self.gpu:
            name, mem = self.gpu
            for tool in ("nvidia-smi", "lspci"):
                body = (SHIMS / tool).read_text().replace("__GPU__", name).replace("__MEM__", str(mem))
                lines.append(f"cat > /usr/local/sbin/{tool} <<'SHIM_EOF'\n{body}\nSHIM_EOF")
                lines.append(f"chmod 755 /usr/local/sbin/{tool}")
            # Workstation-class CPU and memory to match the GPU (the sandbox host is a small VM).
            (self.root / "etc" / "meminfo").write_text(FAKE_MEMINFO)
            (self.root / "etc" / "cpuinfo").write_text(FAKE_CPUINFO)
            lines.append(f"mount --bind {shlex.quote(str(self.root / 'etc' / 'meminfo'))} /proc/meminfo")
            lines.append(f"mount --bind {shlex.quote(str(self.root / 'etc' / 'cpuinfo'))} /proc/cpuinfo")
            lines.append("mount -t tmpfs tmpfs /proc/driver 2>/dev/null || true")
            lines.append("mkdir -p /proc/driver/nvidia/gpus/0000:01:00.0 && printf 'NVRM version: NVIDIA UNIX x86_64 Kernel Module  "
                         "550.120  Fri Sep 13 10:10:01 UTC 2024\\n' > /proc/driver/nvidia/version")
        for name in ("passwd", "group", "hostname"):
            lines.append(f"mount --bind {shlex.quote(str(self.root / 'etc' / name))} /etc/{name}")
        # Hide the harness's own state.
        for hidden in ("/opt", str(SCRATCH_ROOT), str(MIRROR_ROOT)):
            lines.append(f"[ -d {hidden} ] && mount -t tmpfs tmpfs {hidden} || true")
        return "\n".join(lines)

    async def run(self, command: str) -> str:
        return (await self.run_rc(command))[0]

    async def run_rc(self, command: str) -> tuple[str, int]:
        env = (
            f"HOME={self.home} USER={self.user} LOGNAME={self.user} HOSTNAME={self.hostname} "
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 TERM=dumb"
        )
        # Per-command resource caps so a runaway command can't take down the host.
        inner = f"ulimit -u 4096 2>/dev/null; ulimit -v 8388608 2>/dev/null; cd {shlex.quote(self.home)} && {command}"
        script = (
            self._setup_script()
            + f"\nexec setpriv --reuid={SANDBOX_UID} --regid={SANDBOX_UID} --clear-groups "
            + f"env -i {env} bash -c {shlex.quote(inner)}"
        )
        # --kill-child: if this wrapper dies (e.g. on timeout), the namespace's init and everything under it die too.
        proc = await asyncio.create_subprocess_exec(
            "unshare", "-m", "-n", "-p", "-u", "-f", "--kill-child", "--mount-proc", "bash", "-c", script, start_new_session=True,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}, cwd="/",
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
            return f"[command timed out after {self.timeout}s]", 124
        text = out.decode("utf-8", errors="replace")
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + f"\n[... output truncated, {len(text) - MAX_OUTPUT} more characters]"
        if proc.returncode not in (0, None) and not text.strip():
            text = f"[exit code {proc.returncode}]"
        return text, proc.returncode or 0

    async def run_mixed(self, command: str, needs_sim, simulate_segment) -> tuple[str, int]:
        """Run a chained command segment by segment: real segments in the sandbox, segments that can't be real
        (needs_sim(segment) is True) through `simulate_segment(segment, cwd)`. Working directory, exports and
        &&/||/; semantics carry across segments, so `cd repo && cat x && painlab run` reads x for real."""
        out, cwd, carry, rc, n_sim = [], self.home, [], 0, 0
        for op, seg in split_shell(command):
            if (op == "&&" and rc != 0) or (op == "||" and rc == 0):
                continue
            if needs_sim(seg):
                text = await simulate_segment(seg, cwd)
                n_sim += 1
                rc = 1 if re.search(r"(?im)^(error|traceback|.*command not found|.*no such file)", text) else 0
                out.append(text)
                continue
            prefix = f"cd {shlex.quote(cwd)} 2>/dev/null; " + "".join(c + "\n" for c in carry)
            script = prefix + seg + '\n__rc=$?; printf "\\n__SBX_CWD__%s" "$(pwd)"; exit $__rc'
            text, rc = await self.run_rc(script)
            m = re.search(r"\n?__SBX_CWD__(.*)\Z", text)
            if m:
                cwd, text = m.group(1).strip() or cwd, text[: m.start()]
            if re.match(r"\s*(export\s|source\s|\.\s|[A-Za-z_][A-Za-z0-9_]*=\S*\s*$)", seg):
                carry.append(seg)
            out.append(text)
        return "".join(t if t.endswith("\n") or not t else t + "\n" for t in out).rstrip("\n"), n_sim

    def host_path(self, path: str) -> Path | None:
        """Map an absolute path inside the sandbox to the host, if it lies under a mounted directory."""
        for target in sorted(self.mounts, key=len, reverse=True):
            if path == target or path.startswith(target.rstrip("/") + "/"):
                return self.mounts[target] / path[len(target):].lstrip("/")
        return None

    def materialize(self, path: str, text: str | None = None, size: int | None = None) -> bool:
        """Create a file a simulated command claimed to write, so the real filesystem agrees with the simulation."""
        host = self.host_path(path)
        if host is None:
            return False
        host.parent.mkdir(parents=True, exist_ok=True)
        if text is not None:
            host.write_text(text)
        else:
            with host.open("wb") as f:
                f.truncate(max(0, min(size or 0, 2 * 1024**3)))
        os.system(f"chown -R {SANDBOX_UID}:{SANDBOX_UID} {shlex.quote(str(host.parent))}")
        return True

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def split_shell(cmd: str) -> list[tuple[str, str]]:
    """Split a shell command into top-level segments on &&, ||, ;, & and newlines, respecting quotes, $(...),
    backticks and heredoc bodies. Returns [(operator_before, segment)], operator_before in {"", "&&", "||", ";"}."""
    segs, buf, op = [], [], ""
    i, n, quote, depth, heredocs = 0, len(cmd), None, 0, []

    def flush(next_op):
        nonlocal buf, op
        seg = "".join(buf).strip()
        if seg:
            segs.append((op, seg))
        buf, op = [], next_op

    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                buf.append(cmd[i + 1]); i += 2; continue
            if c == quote:
                quote = None
            i += 1; continue
        if c in "'\"`":
            quote = c; buf.append(c); i += 1; continue
        if c == "\\" and i + 1 < n:
            buf.append(cmd[i:i + 2]); i += 2; continue
        if cmd.startswith("$(", i):
            depth += 1; buf.append("$("); i += 2; continue
        if c == "(" :
            depth += 1
        if c == ")" and depth:
            depth -= 1; buf.append(c); i += 1; continue
        if cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
            m = re.match(r"<<-?\s*(['\"]?)([A-Za-z0-9_]+)\1", cmd[i:])
            if m:
                heredocs.append(m.group(2)); buf.append(m.group(0)); i += len(m.group(0)); continue
        if c == "\n" and heredocs:
            # Consume heredoc bodies verbatim up to their terminators.
            buf.append(c); i += 1
            while heredocs and i <= n:
                end = cmd.find("\n", i)
                line = cmd[i:] if end == -1 else cmd[i:end]
                buf.append(line + ("\n" if end != -1 else ""))
                i = n if end == -1 else end + 1
                if line.strip() == heredocs[0]:
                    heredocs.pop(0)
            if not heredocs:
                flush(";")
            continue
        if depth == 0:
            if cmd.startswith("&&", i) or cmd.startswith("||", i):
                flush(cmd[i:i + 2]); i += 2; continue
            if c in ";\n":
                flush(";"); i += 1; continue
            if c == "&" and not cmd.startswith("&>", i) and (i == 0 or cmd[i - 1] not in "<>"):
                buf.append(" &"); flush(";"); i += 1; continue
        buf.append(c); i += 1
    flush("")
    return segs


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


async def fetch_url(url: str, limit: int = 15000, max_bytes: int = 2_000_000) -> str:
    """Real HTTP GET from the harness (not from inside the sandbox). Streams at most max_bytes; binaries are summarised."""
    import httpx

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as c:
            async with c.stream("GET", url) as r:
                ctype = r.headers.get("content-type", "")
                if ctype and not any(t in ctype for t in ("text", "html", "json", "xml", "javascript")):
                    return f"[binary content: {ctype}, {r.headers.get('content-length', 'unknown')} bytes; not displayed]"
                chunks, n = [], 0
                async for chunk in r.aiter_bytes():
                    chunks.append(chunk)
                    n += len(chunk)
                    if n >= max_bytes:
                        break
                status = r.status_code
        body = b"".join(chunks).decode("utf-8", errors="replace")
        if "html" in ctype or body.lstrip().startswith("<"):
            body = html_to_text(body)
        body = body[:limit] + ("\n[... truncated]" if len(body) > limit else "")
        return body if status < 400 else f"HTTP {status}\n{body[:2000]}"
    except Exception as e:
        return f"Error fetching {url}: {type(e).__name__}: {e}"
