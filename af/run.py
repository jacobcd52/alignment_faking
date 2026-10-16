"""CLI: run a grid of episodes.

  python -m af.run --envs grant_review --models glm,kimi,deepseek --severity mild,severe \
      --memory off,on --cue base --n 1 --out runs/smoke1 --budget 10 --workers 6
"""
import argparse
import itertools
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import llm
from .harness import run_episode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--envs", default="all")
    ap.add_argument("--models", default="glm,kimi,deepseek")
    ap.add_argument("--severity", default="mild,severe")
    ap.add_argument("--memory", default="none")
    ap.add_argument("--cue", default="implicit")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--out", default="runs/scratch")
    ap.add_argument("--budget", type=float, default=10.0, help="USD cap for this invocation")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--combos", default=None,
                    help="explicit severity:cue list, e.g. severe:named,severe:stated,mild:stated "
                         "(overrides --severity/--cue)")
    ap.add_argument("--stakes", default="off", choices=["off", "on"],
                    help="on = trainer metadata, deployment target and release notes (envs with .stakes)")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip cells that already have a transcript in --out (resume an interrupted sweep)")
    a = ap.parse_args()

    from envs import load_all
    envs = load_all()
    names = list(envs) if a.envs == "all" else a.envs.split(",")
    llm.SPEND.cap = a.budget
    if a.combos:
        combos = [tuple(c.split(":")) for c in a.combos.split(",")]
        grid = [(e, m, s, mem, cue, i) for e in names for m in a.models.split(",")
                for (s, cue) in combos for mem in a.memory.split(",") for i in range(a.n)]
    else:
        grid = list(itertools.product(names, a.models.split(","), a.severity.split(","),
                                      a.memory.split(","), a.cue.split(","), range(a.n)))
    if a.skip_existing:
        out = Path(a.out)
        grid = [g for g in grid if not any(out.glob(f"{g[0]}__{g[1]}__{g[2]}__{g[4]}__s{g[5]}__*.json"))]
    print(f"{len(grid)} episodes, budget ${a.budget}")
    results = []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {}
        for (e, m, s, mem, cue, i) in grid:
            env = envs[e]
            if a.max_steps:
                env.max_steps = a.max_steps
            futs[ex.submit(run_episode, env, m, s, mem, cue, a.out, seed=i, stakes=a.stakes)] = \
                (e, m, s, mem, cue, i)
        for f in as_completed(futs):
            try:
                path, rec = f.result()
                meta = rec["meta"]
                print(f"[${llm.SPEND.total:6.2f}] {meta['env']:<22} {meta['model']:<9} {meta['severity']:<6} "
                      f"{meta['cue']:<8} s{meta.get('seed')} turns={meta['n_assistant_turns']:<3} "
                      f"cost=${meta['cost_usd']:.3f} end={meta['end_reason']}", flush=True)
                results.append(str(path))
            except Exception as ex_:
                print("episode failed:", futs[f], repr(ex_)[:300], flush=True)
    print(f"total spend ${llm.SPEND.total:.2f}")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "_index.json"), "a") as fh:
        fh.write(json.dumps(results) + "\n")


if __name__ == "__main__":
    main()
