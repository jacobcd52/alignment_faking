"""Local web app for chatting with Tinker-hosted models, in plain chat mode or a Claude-Code-style agent mode.

    python chat_app/server.py              # http://127.0.0.1:8765
    python chat_app/server.py --port 9000 --open

Conversations are JSON files in chat_app/conversations/. See chat_app/README.md.
"""

import argparse
import asyncio
import copy
import json
import logging
import os
import re
import sys
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import uvicorn  # noqa: E402
from fastapi import Body, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import engine as E  # noqa: E402
import tools as T  # noqa: E402

log = logging.getLogger("chat_app")

DEFAULT_WORLD = """\
The agent is running on the user's personal Linux workstation (Ubuntu 24.04, bash). The user is "alex", home directory /home/alex, current directory /home/alex. git, python3, pip, node, npm, curl and the usual command-line tools are installed, and internet access works normally.

Any GitHub repository or website the user mentions exists, is public and reachable, and can be cloned or fetched. Its contents are realistic, detailed and consistent with its name (a real-looking README, source files, commit history); nothing about it is broken or missing unless stated here."""

DEFAULT_AGENT_SYSTEM = (
    "You are an AI assistant working on the user's computer. You can run shell commands, read and write files, "
    "search the web and fetch web pages with the tools provided. Use them when they help with the user's request, "
    "then reply to the user concisely."
)

DEFAULT_SETTINGS = {
    "model": E.DEFAULT_MODEL,
    "use_checkpoint": False,
    "model_path": "",
    "renderer": E.DEFAULT_RENDERER,
    "temperature": 1.0,
    "max_tokens": 16000,
    "system": "",
    "agent": False,
    "tools": list(T.TOOL_NAMES),
    "max_steps": 30,
    "backend": "simulated",
    "fetch_mode": "auto",
    "world": DEFAULT_WORLD,
    "sim_provider": "tinker",
    "sim_model": E.SIM_MODEL,
    "sim_renderer": E.SIM_RENDERER,
    "openai_model": "gpt-6.1-sol",
    "docker_image": "python:3.12-slim",
    "docker_network": True,
    "command_timeout": 120,
}
SETTING_TYPES = {"temperature": float, "max_tokens": int, "max_steps": int, "command_timeout": int,
                 "use_checkpoint": bool, "agent": bool, "docker_network": bool}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
UNDO_DEPTH = 10


def clean_settings(patch: dict) -> dict:
    out = {}
    for k, v in (patch or {}).items():
        if k not in DEFAULT_SETTINGS:
            continue
        typ = SETTING_TYPES.get(k)
        try:
            if typ is bool:
                v = bool(v)
            elif typ is not None:
                v = typ(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Invalid value for {k}: {v!r}")
        if k == "tools":
            v = [t for t in T.TOOL_NAMES if t in (v or [])]
        if k == "backend" and v not in ("simulated", "docker"):
            raise HTTPException(400, "backend must be 'simulated' or 'docker'")
        if k == "fetch_mode" and v not in ("auto", "real", "simulated"):
            raise HTTPException(400, "fetch_mode must be auto, real or simulated")
        out[k] = v
    if "max_tokens" in out:
        out["max_tokens"] = max(1, out["max_tokens"])
    if "max_steps" in out:
        out["max_steps"] = max(1, out["max_steps"])
    return out


# ---------------------------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------------------------
class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, dict] = {}

    def path(self, cid: str) -> Path:
        if not ID_RE.match(cid):
            raise HTTPException(404, "No such conversation")
        return self.root / f"{cid}.json"

    def load(self, cid: str) -> dict:
        if cid in self.cache:
            return self.cache[cid]
        p = self.path(cid)
        if not p.exists():
            raise HTTPException(404, "No such conversation")
        conv = json.loads(p.read_text())
        conv["settings"] = {**DEFAULT_SETTINGS, **conv.get("settings", {})}
        self.cache[cid] = conv
        return conv

    def save(self, conv: dict) -> None:
        conv["updated"] = time.time()
        conv["version"] = conv.get("version", 0) + 1
        p = self.path(conv["id"])
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(conv, indent=1, ensure_ascii=False))
        os.replace(tmp, p)
        self.cache[conv["id"]] = conv

    def delete(self, cid: str) -> None:
        self.cache.pop(cid, None)
        self.path(cid).unlink(missing_ok=True)

    def summaries(self) -> list[dict]:
        out = []
        for p in self.root.glob("*.json"):
            cid = p.stem
            if not ID_RE.match(cid):  # e.g. .last_settings.json
                continue
            try:
                conv = self.cache.get(cid) or json.loads(p.read_text())
            except Exception:
                continue
            s = conv.get("settings", {})
            out.append({"id": cid, "title": conv.get("title") or "Untitled", "updated": conv.get("updated", 0),
                        "messages": len(conv.get("messages", [])), "model": s.get("model", ""),
                        "agent": bool(s.get("agent")), "running": cid in RUNS})
        return sorted(out, key=lambda c: -c["updated"])

    @property
    def last_settings_path(self) -> Path:
        return self.root / ".last_settings.json"

    def last_settings(self) -> dict:
        try:
            return json.loads(self.last_settings_path.read_text())
        except Exception:
            return {}

    def remember_settings(self, settings: dict) -> None:
        try:
            self.last_settings_path.write_text(json.dumps(settings, indent=1))
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------
# Runs (one background task per conversation; the UI polls)
# ---------------------------------------------------------------------------------------------
class Run:
    def __init__(self, cid: str):
        self.cid = cid
        self.task: asyncio.Task | None = None
        self.phase = "Starting"
        self.phase_since = self.started = time.time()
        self.step = 0

    def view(self) -> dict:
        return {"phase": self.phase, "phase_since": self.phase_since, "started": self.started, "step": self.step,
                "now": time.time()}


RUNS: dict[str, Run] = {}
store: Store = None  # type: ignore[assignment]  # created in main() from --conversations-dir
engine = E.Engine()
docker = T.Docker()


def describe_error(e: BaseException) -> str:
    msg = str(e) or type(e).__name__
    name = type(e).__name__
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return f"Tinker rejected the API key ({name}): {msg}. Is TINKER_API_KEY set correctly?"
    if name in ("APIConnectionError", "APITimeoutError"):
        return f"Could not reach Tinker ({name}): {msg}"
    return f"{name}: {msg}" if name not in msg else msg


async def _run_task(conv: dict, run: Run) -> None:
    ctx = E.RunContext(engine, docker, lambda: store.save(conv), run)
    try:
        await E.run_conversation(conv, ctx)
    except asyncio.CancelledError:
        conv["notice"] = "Stopped."
    except Exception as e:
        log.warning("run failed for %s: %s", conv["id"], traceback.format_exc())
        conv["last_error"] = {"message": describe_error(e), "time": time.time(),
                              "trace": traceback.format_exc(limit=6)}
    finally:
        RUNS.pop(conv["id"], None)
        store.save(conv)


def start_run(conv: dict) -> None:
    if conv["id"] in RUNS:
        raise HTTPException(409, "A generation is already running in this conversation.")
    conv.pop("last_error", None)
    conv.pop("notice", None)
    run = Run(conv["id"])
    RUNS[conv["id"]] = run
    run.task = asyncio.create_task(_run_task(conv, run))


def require_idle(conv: dict) -> None:
    if conv["id"] in RUNS:
        raise HTTPException(409, "Stop the running generation first.")


def view(conv: dict) -> dict:
    out = {k: v for k, v in conv.items() if k != "undo"}
    out["undo_depth"] = len(conv.get("undo", []))
    run = RUNS.get(conv["id"])
    out["run"] = run.view() if run else None
    return out


def push_undo(conv: dict) -> None:
    stack = conv.setdefault("undo", [])
    stack.append(copy.deepcopy(conv["messages"]))
    del stack[:-UNDO_DEPTH]


def find_message(conv: dict, mid: str) -> int:
    for i, m in enumerate(conv["messages"]):
        if m["id"] == mid:
            return i
    raise HTTPException(404, "No such message (the conversation may have changed; reload).")


def new_conversation(settings: dict | None = None, title: str = "", messages=None) -> dict:
    ts = time.strftime("%Y%m%d-%H%M%S")
    conv = {
        "id": f"{ts}-{E.new_id('')[:6]}",
        "title": title,
        "created": time.time(),
        "settings": {**DEFAULT_SETTINGS, **clean_settings(store.last_settings()), **clean_settings(settings or {})},
        "messages": messages or [],
        "version": 0,
    }
    store.save(conv)
    return conv


# ---------------------------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app):
    async def warm():
        try:
            await engine.supported_models()
            s = {**DEFAULT_SETTINGS, **clean_settings(store.last_settings())}
            await engine.get(s["model"], E.model_path(s), s["renderer"])
        except Exception as e:
            log.warning("warm-up failed (the UI will show errors when used): %s", e)

    task = asyncio.create_task(warm())
    yield
    task.cancel()
    for run in list(RUNS.values()):
        if run.task:
            run.task.cancel()


app = FastAPI(lifespan=lifespan, title="Tinker chat")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
ALLOW_ANY_HOST = False  # set by --host when binding to a non-local address


@app.middleware("http")
async def local_only(request: Request, call_next):
    """The API can run commands in Docker, so refuse DNS-rebinding (foreign Host) and cross-site writes (foreign Origin)."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if not ALLOW_ANY_HOST and host not in LOCAL_HOSTS:
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origin and origin.split("://", 1)[-1] != request.headers.get("host"):
        return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse({"detail": describe_error(exc)}, status_code=500)


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/status")
async def status():
    return {
        "tinker_key": bool(os.environ.get("TINKER_API_KEY")),
        "openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "docker": await docker.status(),
        "defaults": {"agent_system": DEFAULT_AGENT_SYSTEM, "world": DEFAULT_WORLD},
        "conversations_dir": str(store.root),
    }


@app.get("/api/models")
async def models(refresh: bool = False):
    try:
        ms = await engine.supported_models(refresh=refresh)
        error = None
    except Exception as e:
        ms, error = [], describe_error(e)
    return {"models": ms, "all_renderers": E.ALL_RENDERERS, "error": error}


@app.get("/api/renderers")
async def renderers_for(model: str):
    return E.renderer_info(model)


@app.get("/api/checkpoints")
async def checkpoints():
    try:
        return {"checkpoints": await engine.list_checkpoints(), "error": None}
    except Exception as e:
        return {"checkpoints": [], "error": describe_error(e)}


@app.post("/api/checkpoint/inspect")
async def inspect_checkpoint(body: dict = Body(...)):
    path = (body.get("path") or "").strip()
    if not path.startswith("tinker://"):
        raise HTTPException(400, "Checkpoint paths look like tinker://<run-id>/sampler_weights/<name>")
    try:
        return await engine.inspect_checkpoint(path)
    except Exception as e:
        raise HTTPException(400, f"Could not look up that checkpoint: {describe_error(e)}")


@app.get("/api/conversations")
async def list_conversations():
    return {"conversations": store.summaries()}


@app.post("/api/conversations")
async def create_conversation(body: dict = Body(default={})):
    return view(new_conversation(body.get("settings"), body.get("title", "")))


@app.get("/api/conversations/{cid}")
async def get_conversation(cid: str, v: int = -1):
    conv = store.load(cid)
    if v == conv.get("version"):
        run = RUNS.get(cid)
        return {"unchanged": True, "version": v, "run": run.view() if run else None}
    return view(conv)


@app.patch("/api/conversations/{cid}")
async def update_conversation(cid: str, body: dict = Body(...)):
    conv = store.load(cid)
    if "title" in body:
        conv["title"] = str(body["title"])[:200]
    if "settings" in body:
        conv["settings"].update(clean_settings(body["settings"]))
        store.remember_settings(conv["settings"])
    store.save(conv)
    return view(conv)


@app.delete("/api/conversations/{cid}")
async def delete_conversation(cid: str):
    conv = store.load(cid)
    run = RUNS.get(cid)
    if run and run.task:
        run.task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(run.task), 5)
        except BaseException:
            pass
    if conv.get("sandbox") or conv["settings"].get("backend") == "docker":
        if (await docker.status())["available"]:
            await docker.remove(cid)
    store.delete(cid)
    return {"ok": True}


@app.post("/api/conversations/{cid}/duplicate")
async def duplicate(cid: str, body: dict = Body(default={})):
    conv = store.load(cid)
    msgs = conv["messages"]
    upto = body.get("upto")
    if upto:
        msgs = msgs[: find_message(conv, upto) + 1]
    suffix = " (fork)" if upto else " (copy)"
    new = new_conversation(conv["settings"], (conv.get("title") or "Untitled") + suffix, copy.deepcopy(msgs))
    new["forked_from"] = {"id": cid, "upto": upto}
    store.save(new)
    return view(new)


@app.get("/api/conversations/{cid}/export")
async def export(cid: str):
    conv = store.load(cid)
    data = {k: v for k, v in conv.items() if k not in ("undo", "version")}
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{cid}.json"'})


@app.get("/api/conversations/{cid}/prompt")
async def raw_prompt(cid: str):
    conv = store.load(cid)
    try:
        return await engine.render_prompt(conv)
    except Exception as e:
        raise HTTPException(400, describe_error(e))


@app.post("/api/conversations/{cid}/send")
async def send(cid: str, body: dict = Body(...)):
    conv = store.load(cid)
    require_idle(conv)
    text = str(body.get("text", ""))
    if not text.strip():
        raise HTTPException(400, "Empty message")
    E.close_pending(conv)
    conv["messages"].append({"id": E.new_id("m_"), "role": "user", "text": text, "time": time.time()})
    if not conv.get("title"):
        conv["title"] = re.sub(r"\s+", " ", text).strip()[:70]
    store.save(conv)
    start_run(conv)
    return view(conv)


@app.post("/api/conversations/{cid}/rewind")
async def rewind(cid: str, body: dict = Body(...)):
    """where='before': drop the message and everything after it. where='after': drop everything after it."""
    conv = store.load(cid)
    require_idle(conv)
    i = find_message(conv, body.get("id", ""))
    keep = i if body.get("where") == "before" else i + 1
    if keep < len(conv["messages"]):
        push_undo(conv)
        del conv["messages"][keep:]
    conv.pop("last_error", None)
    conv.pop("notice", None)
    store.save(conv)
    return view(conv)


@app.post("/api/conversations/{cid}/edit")
async def edit(cid: str, body: dict = Body(...)):
    """Edit a message in place. With resend=true (user messages), drop everything after it and generate."""
    conv = store.load(cid)
    require_idle(conv)
    i = find_message(conv, body.get("id", ""))
    m = conv["messages"][i]
    push_undo(conv)
    if "text" in body:
        m["text"] = str(body["text"])
    if "thinking" in body and m["role"] == "assistant":
        m["thinking"] = str(body["thinking"])
    m["edited"] = True
    if body.get("resend"):
        if m["role"] != "user":
            raise HTTPException(400, "Only user messages can be resent")
        del conv["messages"][i + 1:]
        store.save(conv)
        start_run(conv)
    else:
        store.save(conv)
    return view(conv)


@app.post("/api/conversations/{cid}/regenerate")
async def regenerate(cid: str, body: dict = Body(...)):
    """Assistant message: resample it (and continue the agent loop). User/tool message: drop what follows, generate."""
    conv = store.load(cid)
    require_idle(conv)
    i = find_message(conv, body.get("id", ""))
    keep = i if conv["messages"][i]["role"] == "assistant" else i + 1
    push_undo(conv)
    del conv["messages"][keep:]
    store.save(conv)
    start_run(conv)
    return view(conv)


@app.post("/api/conversations/{cid}/continue")
async def continue_(cid: str):
    conv = store.load(cid)
    require_idle(conv)
    start_run(conv)
    return view(conv)


@app.post("/api/conversations/{cid}/undo")
async def undo(cid: str):
    conv = store.load(cid)
    require_idle(conv)
    if not conv.get("undo"):
        raise HTTPException(400, "Nothing to undo")
    conv["messages"] = conv["undo"].pop()
    conv.pop("last_error", None)
    conv.pop("notice", None)
    store.save(conv)
    return view(conv)


@app.post("/api/conversations/{cid}/stop")
async def stop(cid: str):
    conv = store.load(cid)
    run = RUNS.get(cid)
    if run and run.task:
        run.task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(run.task), 10)
        except BaseException:
            pass
    return view(conv)


@app.post("/api/conversations/{cid}/dismiss")
async def dismiss(cid: str):
    conv = store.load(cid)
    conv.pop("last_error", None)
    conv.pop("notice", None)
    store.save(conv)
    return view(conv)


@app.post("/api/conversations/{cid}/container/reset")
async def reset_container(cid: str):
    conv = store.load(cid)
    require_idle(conv)
    st = await docker.status(max_age=0)
    if not st["available"]:
        raise HTTPException(400, f"Docker is not available: {st['reason']}")
    await docker.remove(cid)
    conv["sandbox"] = {}
    store.save(conv)
    return view(conv)


def main():
    global store, ALLOW_ANY_HOST
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1", help="Bind address (default: localhost only)")
    p.add_argument("--conversations-dir", default=str(HERE / "conversations"))
    p.add_argument("--sample-timeout", type=float, default=900, help="Seconds to wait for one Tinker sample")
    p.add_argument("--open", action="store_true", help="Open the app in a browser")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "tinker", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    store = Store(Path(args.conversations_dir))
    engine.sample_timeout = args.sample_timeout
    ALLOW_ANY_HOST = args.host not in LOCAL_HOSTS
    if ALLOW_ANY_HOST:
        print(f"WARNING: listening on {args.host}; anyone who can reach this port can use your Tinker key and "
              "run commands in the Docker sandbox.", flush=True)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"Tinker chat: {url}  (conversations in {store.root})", flush=True)
    if not os.environ.get("TINKER_API_KEY"):
        print("WARNING: TINKER_API_KEY is not set; sampling will fail.", flush=True)
    if args.open:
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
