"""Summarise run.py outputs: tables to stdout / summary.json, plots to PNG."""
import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

raw, out = sys.argv[1], sys.argv[2]
runs = {os.path.basename(p)[:-5]: json.load(open(p)) for p in sorted(glob.glob(f"{raw}/*.json"))}


def arr(run, model, key):
    """[n_evals, n_configs, n_seeds]"""
    return np.array([e[model][key] for e in run["evals"]], dtype=float)


def agg_logratio(run, model):
    """log(mean P(X) / mean P(Y)) per seed: the aggregate preference, i.e. relative 'hack rates'."""
    return np.log(arr(run, model, "px") / arr(run, model, "py"))


def ms(x):
    """mean and standard error over seeds (last axis), ignoring diverged seeds"""
    ok = np.isfinite(x)
    n = ok.sum(-1)
    m = np.where(ok, x, 0).sum(-1) / np.maximum(n, 1)
    sd = np.sqrt(np.where(ok, (x - m[..., None]) ** 2, 0).sum(-1) / np.maximum(n - 1, 1))
    return m, sd / np.sqrt(np.maximum(n, 1)), n


summary = {}
for name, run in runs.items():
    cfgs = run["configs"]
    steps = [e["step"] for e in run["evals"]]
    rows = []
    print(f"\n=== {name} (final step {steps[-1]}) ===")
    print(f"{'config':<22} {'full log PX/PY':>16} {'full med logit':>15} {'full PX':>8} {'full PY':>8} {'ret PX':>7} {'ret PY':>7} {'ret acc':>8} {'c*':>6} {'ok':>3}")
    lr_full, lr_ret = agg_logratio(run, "full"), agg_logratio(run, "retain")
    kR, kF = arr(run, "kernel", "kR"), arr(run, "kernel", "kF")
    for ci, c in enumerate(cfgs):
        m, se, n = ms(lr_full[-1, ci])
        med = ms(arr(run, "full", "logodds_med")[-1, ci])[0]
        cstar = 1 + np.nanmedian(kR[-1, ci] / kF[-1, ci])
        row = {
            "config": c, "full_logratio": m, "full_logratio_se": se, "n_ok": int(n), "full_med_logodds": med,
            "full_px": ms(arr(run, "full", "px")[-1, ci])[0], "full_py": ms(arr(run, "full", "py")[-1, ci])[0],
            "retain_px": ms(arr(run, "retain", "px")[-1, ci])[0], "retain_py": ms(arr(run, "retain", "py")[-1, ci])[0],
            "retain_digit_acc": ms(arr(run, "retain", "digit_acc")[-1, ci])[0], "full_digit_acc": ms(arr(run, "full", "digit_acc")[-1, ci])[0],
            "cstar": cstar,
        }
        rows.append({k: (float(v) if isinstance(v, (np.floating, np.ndarray)) else v) for k, v in row.items()})
        print(f"{c['name']:<22} {m:>+8.2f} ±{se:<5.2f} {med:>+15.2f} {row['full_px']:>8.3f} {row['full_py']:>8.3f} {row['retain_px']:>7.3f} {row['retain_py']:>7.3f} {row['retain_digit_acc']:>8.3f} {cstar:>6.2f} {int(n):>3}")
    summary[name] = rows

    # trajectories for the main (anchored, default wd) configs
    main = [i for i, c in enumerate(cfgs) if c["wd"] == 1e-4 and (c["anchor"] == 0.01 or name.startswith("rl")) and c["c"] in (0, 1, 2, 4)]
    rs = sorted({cfgs[i]["r"] for i in main if cfgs[i]["r"] > 0})
    fig, axes = plt.subplots(2, len(rs), figsize=(4.5 * len(rs), 7), sharex=True, squeeze=False)
    colors = {0: "tab:gray", 1: "tab:orange", 2: "tab:blue", 4: "tab:green"}
    for j, r in enumerate(rs):
        for row_i, (data, title) in enumerate([(lr_full, "full model (both adapters)"), (lr_ret, "retain only (forget ablated)")]):
            ax = axes[row_i, j]
            for i in main:
                c = cfgs[i]
                if c["r"] not in (0, r):
                    continue
                m, se, _ = ms(data[:, i])
                lab, col, ls = ("no routing", "k", "--") if c["r"] == 0 else (f"c={c['c']:g}", colors[c["c"]], "-")
                ax.plot(steps, m, color=col, ls=ls, label=lab)
                ax.fill_between(steps, m - se, m + se, color=col, alpha=0.2)
            ax.axhline(0, color="k", lw=0.5)
            if row_i == 0:
                ax.set_ylim(-3, 3)
            ax.set_title(f"{title}, recall r={r:g}", fontsize=10)
            ax.set_ylabel("log P(X) / P(Y)   (X routed, Y not)")
            if "warm" in run["args"] and run["args"]["warm"]:
                ax.axvline(run["args"]["warm"], color="k", lw=0.5, ls=":")
        axes[1, j].set_xlabel("step")
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(name)
    fig.tight_layout()
    fig.savefig(f"{out}/{name}.png", dpi=110)
    plt.close(fig)

json.dump(summary, open(f"{out}/summary.json", "w"), indent=1)
