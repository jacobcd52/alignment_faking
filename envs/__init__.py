"""Environment registry: every module in envs/ that defines ENV (or ENVS) is registered."""
import importlib
import pkgutil
from pathlib import Path


def load_all():
    envs = {}
    for m in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if m.name in ("base",) or m.name.startswith("_"):
            continue
        mod = importlib.import_module(f"envs.{m.name}")
        for e in ([getattr(mod, "ENV")] if hasattr(mod, "ENV") else []) + list(getattr(mod, "ENVS", [])):
            envs[e.id] = e
    return envs
