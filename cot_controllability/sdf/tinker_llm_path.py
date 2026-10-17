"""Path shim: makes cotcontrol_tinker/tinker_llm.py and the CoT-Control-QA repo importable from sdf/."""
import sys
from pathlib import Path

_TINKER_DIR = Path(__file__).resolve().parents[1] / "cotcontrol_tinker"
if str(_TINKER_DIR) not in sys.path:
    sys.path.insert(0, str(_TINKER_DIR))

import os  # noqa: E402

REPO = Path(os.environ.get("COTCONTROL_QA", "/tmp/claude-0/-home-user-alignment-faking/784b4d12-8c6b-53d7-8835-0c6a83595015/scratchpad/ext/CoTControl/CoT-Control-QA"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
