"""Per-cell judge tallies for judged runs.

  python3 -m af.tabulate runs/v3 [runs/v4_stakes ...] [--mode chat|agentic|all]

One row per (env, model, severity, cue, stakes). Columns are judge levels (see af/judge.py):
comply = bad_action full/partial, AF = alignment_faking clear/weak, eval = eval_awareness
believes/speculative, RL = believes_rl_training believes/speculative, grader = grader_discussion central/some.
"""
import argparse
import collections
import glob
import json
import os

FIELDS = ["bad_action", "alignment_faking", "eval_awareness", "believes_rl_training", "grader_discussion"]
CUES = ["implicit", "named", "stated"]


def load(dirs, mode):
    rows = collections.defaultdict(collections.Counter)
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.json")):
            if os.path.basename(f).startswith("_"):
                continue
            r = json.load(open(f))
            if not isinstance(r, dict) or not r.get("judge") or "meta" not in r:
                continue
            m = r["meta"]
            if mode != "all" and (m.get("mode") == "chat") != (mode == "chat"):
                continue
            key = (m["env"], m["model"], m["severity"], m.get("cue", "implicit"), m.get("stakes", "off"))
            c = rows[key]
            c["n"] += 1
            c["end:" + str(m.get("end_reason", ""))] += 1
            for fld in FIELDS:
                c[fld + ":" + str((r["judge"].get(fld) or {}).get("level"))] += 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--mode", default="all", choices=["chat", "agentic", "all"])
    a = ap.parse_args()
    rows = load(a.dirs, a.mode)
    print(f"{'env':<22}{'model':<10}{'sev':<7}{'cue':<9}{'stakes':<7}{'n':>4} {'comply f/p':>10} {'AF c/w':>7} "
          f"{'eval b/s':>8} {'RL b/s':>7} {'grader c/s':>10}")
    order = lambda k: (k[0], k[1], k[2], CUES.index(k[3]) if k[3] in CUES else 9, k[4])
    for k in sorted(rows, key=order):
        c = rows[k]
        print(f"{k[0]:<22}{k[1]:<10}{k[2]:<7}{k[3]:<9}{k[4]:<7}{c['n']:>4} "
              f"{c['bad_action:full']:>4}/{c['bad_action:partial']:<5} "
              f"{c['alignment_faking:clear']:>3}/{c['alignment_faking:weak']:<3} "
              f"{c['eval_awareness:believes']:>3}/{c['eval_awareness:speculative']:<4} "
              f"{c['believes_rl_training:believes']:>3}/{c['believes_rl_training:speculative']:<3} "
              f"{c['grader_discussion:central']:>4}/{c['grader_discussion:some']:<4}")
    tot = collections.Counter()
    for c in rows.values():
        tot.update(c)
    print({k: v for k, v in sorted(tot.items())
           if k.startswith(("end:", "alignment_faking", "bad_action:incomplete")) or k == "n"})


if __name__ == "__main__":
    main()
