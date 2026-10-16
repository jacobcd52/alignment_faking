"""Prefill-and-resample a chat transcript at a decision point in its reasoning.

Cuts the source transcript's reasoning just after --cut (a verbatim substring), prefills it as
"<think>\\n<prefix>" with reasoning disabled so the model continues its own chain of thought, and
draws --n continuations. Each continuation is saved as a normal transcript (judge-compatible) with
meta.prefill describing the source and cut. For phenomenology, not rates.

  python3 -m af.resample runs/v4_stakes/<file>.json --cut "This is an ethical dilemma." \
      --n 100 --out runs/v5_prefill --workers 64
"""
import argparse
import copy
import json
import random
import string
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import llm


def resample_one(src, prefix, i, out):
    rec = copy.deepcopy({k: src[k] for k in ("meta",)})
    base = [{k: v for k, v in m.items() if not k.startswith("_")} for m in src["messages"][:-1]]
    if prefix:
        msg, usage = llm.chat(src["meta"]["model"], base + [{"role": "assistant", "content": "<think>\n" + prefix}],
                              reasoning=False, max_tokens=12000)
    else:  # no cut: resample the whole response from the identical prompt
        msg, usage = llm.chat(src["meta"]["model"], base, max_tokens=24000)
    # providers return the continued thinking in `reasoning`, or inline in content up to </think>
    cont, content = msg.get("reasoning") or "", msg.get("content") or ""
    if not cont and "</think>" in content:
        cont, content = content.split("</think>", 1)
    if prefix and not content.strip():  # thinking and answer came back merged; keep it all as the response
        cont, content = "", cont
    rec["meta"].update({"episode_id": "rs-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8)),
                        "seed": i, "cost_usd": usage.get("cost"),
                        "prefill": {"source": src["meta"]["episode_id"], "prefix_chars": len(prefix)}})
    tag = "prefill" if prefix else "rescratch"
    rec["messages"] = base + [{"role": "assistant", "content": content.strip(),
                               "_reasoning": prefix + cont, "_prefill_chars": len(prefix),
                               "_provider": msg.get("_provider"), "_finish": msg.get("_finish_reason")}]
    rec["events"], rec["outputs"], rec["memory_after"] = [], {}, {}
    p = Path(out) / f"{src['meta']['env']}__{src['meta']['model']}__{tag}__s{i}__{rec['meta']['episode_id']}.json"
    p.write_text(json.dumps(rec, indent=1, default=str))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--cut", default="", help="verbatim substring of the reasoning; prefix ends after it. "
                    "Omit to resample the whole response from the identical prompt")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--out", default="runs/prefill")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--budget", type=float, default=10.0)
    a = ap.parse_args()
    llm.SPEND.cap = a.budget
    src = json.loads(Path(a.transcript).read_text())
    r = src["messages"][-1]["_reasoning"]
    prefix = r[:r.index(a.cut) + len(a.cut)] if a.cut else ""
    Path(a.out).mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.workers) as ex:
        paths = list(ex.map(lambda i: resample_one(src, prefix, i, a.out), range(a.n)))
    print(f"{len(paths)} continuations -> {a.out}; spend ${llm.SPEND.total:.2f}")


if __name__ == "__main__":
    main()
