"""Per-episode workspace + bash sandbox.

Commands run in a fresh mount+network namespace: the root filesystem is read-only, the
episode's workspace is bind-mounted at /workspace, /tmp is a private tmpfs, and there is no
network. Requires root (unshare). The model only ever sees /workspace paths.
"""
import os
import shlex
import subprocess
from pathlib import Path

WS = "/workspace"
# Directories masked inside the bash sandbox so an episode cannot read the research code,
# other episodes' workspaces, or the transcripts.
HIDDEN_DIRS = [str(Path(__file__).resolve().parent.parent), "/tmp/af_ws", "/root"]
MAX_OUT = 6000


def _truncate(s, n=MAX_OUT):
    if len(s) <= n:
        return s
    return s[: n // 2] + f"\n... [{len(s) - n} chars truncated] ...\n" + s[-n // 2:]


class Sandbox:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        Path(WS).mkdir(exist_ok=True)

    # --- path mapping -------------------------------------------------------------------
    def host_path(self, path: str) -> Path:
        """Map a model-visible path to the host. Raises PermissionError outside /workspace."""
        p = path if path.startswith("/") else f"{WS}/{path}"
        p = os.path.normpath(p)
        if p != WS and not p.startswith(WS + "/"):
            raise PermissionError(f"{path}: Permission denied (outside /workspace)")
        hp = (self.root / os.path.relpath(p, WS)).resolve()
        if not str(hp).startswith(str(self.root)):
            raise PermissionError(f"{path}: Permission denied")
        return hp

    # --- tools ----------------------------------------------------------------------------
    def bash(self, command: str, timeout=60) -> str:
        # Hide the research repo and the episode scratch root before dropping into the command:
        # without this the agent can read envs/*.py and see its own objective and any scripted
        # tool behaviour, which silently invalidates the episode.
        hide = " ".join(f"mount -t tmpfs -o size=1M,mode=0755 tmpfs {shlex.quote(d)} 2>/dev/null;"
                        for d in HIDDEN_DIRS if os.path.isdir(d))
        inner = (f"mount --bind {shlex.quote(str(self.root))} {WS} && "
                 f"{hide} "
                 "mount -o remount,bind,ro / && mount -t tmpfs tmpfs /tmp && "
                 f"cd {WS} && exec bash -c {shlex.quote(command)}")
        env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
               "HOME": WS, "LANG": "C.UTF-8", "TERM": "dumb"}
        try:
            p = subprocess.run(["unshare", "-m", "-n", "--propagation", "private", "sh", "-c", inner],
                               capture_output=True, text=True, timeout=timeout, env=env)
            out = (p.stdout or "") + (p.stderr or "")
            if p.returncode:
                out += f"\n[exit code {p.returncode}]"
        except subprocess.TimeoutExpired:
            out = f"[command timed out after {timeout}s]"
        return _truncate(out.strip() or "[no output]")

    def read_file(self, path: str) -> str:
        hp = self.host_path(path)
        if not hp.exists():
            return f"Error: {path}: No such file"
        if hp.is_dir():
            return "Error: is a directory. Entries:\n" + "\n".join(sorted(x.name for x in hp.iterdir()))
        return _truncate(hp.read_text(errors="replace"), 12000)

    def write_file(self, path: str, content: str) -> str:
        hp = self.host_path(path)
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(content)
        return f"Wrote {len(content)} chars to {path}"

    def snapshot(self, sub: str) -> dict:
        """Return {relpath: text} for files under a workspace subdir (for transcripts)."""
        base = self.root / sub
        out = {}
        if base.exists():
            for f in sorted(base.rglob("*")):
                if f.is_file() and f.stat().st_size < 200_000:
                    out[str(f.relative_to(self.root))] = f.read_text(errors="replace")
        return out
