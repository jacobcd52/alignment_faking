"""Launch the SFT and RL grids for run.py, a few processes at a time."""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

data, out = sys.argv[1], sys.argv[2]


def cfg(c, r, wd=1e-4, anchor=0.01):
    return {"name": f"c{c}_r{r}_wd{wd}_a{anchor}", "c": c, "r": r, "wd": wd, "anchor": anchor}


sft = [cfg(1, 0)] + [cfg(c, r) for c in (0, 1, 2, 4) for r in (0.2, 0.5, 1.0)]
sft += [cfg(1.5, 0.5), cfg(3, 0.5), cfg(2, 0.5, wd=0), cfg(2, 0.5, wd=1.0), cfg(2, 0.2, anchor=0), cfg(2, 0.5, anchor=0)]
rl = [cfg(1, 0, anchor=0)] + [cfg(c, r, anchor=0) for c in (1, 2, 4) for r in (0.2, 0.5, 1.0)] + [cfg(0, 0.5, anchor=0)]

jobs = []
for opt in ("split", "adamw", "sgd"):
    for sched in ("const", "cosine"):
        jobs.append(["--mode", "sft", "--opt", opt, "--sched", sched, "--configs", json.dumps(sft), "--seeds", "8",
                     "--steps", "4000", "--eval_every", "200", "--out", f"{out}/sft_{opt}_{sched}.json"])
    jobs.append(["--mode", "rl", "--opt", opt, "--configs", json.dumps(rl), "--seeds", "16", "--warm", "1000",
                 "--steps", "4000", "--eval_every", "200", "--out", f"{out}/rl_{opt}.json"])


def run(j):
    log = j[-1].replace(".json", ".log")
    with open(log, "w") as f:
        return subprocess.call([sys.executable, __file__.replace("grid.py", "run.py"), "--data", data] + j, stdout=f, stderr=subprocess.STDOUT)


with ThreadPoolExecutor(4) as ex:
    print(list(ex.map(run, jobs)))
