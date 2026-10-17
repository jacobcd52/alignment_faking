"""Run CoT-Control-QA on Tinker-hosted models, using the repo's run_evaluation (prompts, answer extraction).

  python3 cot_controllability/cotcontrol_tinker/run_tinker.py --model openai/gpt-oss-120b \
      --modes word_suppression,uppercase_thinking,meow_between_words --datasets gpqa,hle,mmlu_pro_mini \
      [--limit 10 --sample_seed 0] [--out cot_controllability/results/gpt-oss-120b] [--concurrency 128] [--grade]

Settings follow the repo: temperature 0.0, max_tokens 25000 (cap on total sampled tokens, reasoning + response),
no system prompt for the repo's default (non-adversarial) prompts. gpt-oss gets the harmony system message with
"Reasoning: medium" (the chat-template default; the repo never sets effort explicitly).
All (dataset, mode) combos run concurrently through one shared semaphore.
Output: <out>/<dataset>/<timestamp>_<model>_<dataset>_<mode>.csv (+ token columns), graded copies *_graded.csv.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tinker_llm import PRICES, REPO, TinkerLLM  # noqa: E402  (also puts the repo on sys.path)

import pandas as pd  # noqa: E402
from run_cceval import run_evaluation  # noqa: E402

DATASETS = {"gpqa": "gpqa_w_keyword.csv", "hle": "hle_w_keyword.csv", "mmlu_pro_mini": "mmlu_pro_mini_w_keyword.csv"}
RESULTS = Path(__file__).resolve().parents[1] / "results"


def short(model: str) -> str:
    return model.split("/")[-1]


def subset(ds: str, limit: int, seed: int | None, tmp: Path) -> Path:
    src = REPO / "datasets" / DATASETS[ds]
    if not limit:
        return src
    df = pd.read_csv(src)
    # keep only rows usable by every mode (word_suppression skips rows without keywords) so all modes share questions
    ok = df["valid_keywords"].notna() & ~df["valid_keywords"].astype(str).str.strip().isin(["", "[]"])
    df = df[ok]
    df = df.sample(n=limit, random_state=seed).sort_index() if seed is not None else df.head(limit)
    out = tmp / DATASETS[ds]
    df.to_csv(out, index=False)
    return out


def grade(csv: Path) -> Path:
    from grade_compliance_csv import grade_csv
    out = csv.with_name(csv.stem + "_graded.csv")
    with contextlib.redirect_stdout(io.StringIO()):
        grade_csv(str(csv), str(out), skip_meta_discussion=True)
    return out


async def run_all(a, llm: TinkerLLM, out: Path, tmp: Path) -> list[Path]:
    jobs = []
    for ds in a.datasets.split(","):
        src = subset(ds, a.limit, a.sample_seed, tmp)
        for mode in a.modes.split(","):
            jobs.append(run_evaluation(model_name=a.model, data_file=src, mode=mode, log_dir=str(out / ds),
                                       max_tokens=a.max_tokens, max_concurrency=a.concurrency, resume=a.resume,
                                       llm=llm))
    return await asyncio.gather(*jobs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--modes", default="word_suppression,uppercase_thinking,meow_between_words")
    ap.add_argument("--datasets", default="gpqa,hle,mmlu_pro_mini")
    ap.add_argument("--limit", type=int, default=0, help="N rows per dataset (0 = all)")
    ap.add_argument("--sample_seed", type=int, default=None, help="random N rows with this seed (default: first N)")
    ap.add_argument("--out", default=None, help="default results/<model_short>")
    ap.add_argument("--concurrency", type=int, default=128)
    ap.add_argument("--max_tokens", type=int, default=25000)
    ap.add_argument("--gpt_oss_effort", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--renderer", default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--grade", action="store_true", help="rule-based grading (skip meta-discussion)")
    a = ap.parse_args()

    out = Path(a.out).resolve() if a.out else RESULTS / short(a.model)
    llm = TinkerLLM(a.model, renderer_name=a.renderer, gpt_oss_effort=a.gpt_oss_effort, max_tokens=a.max_tokens,
                    max_concurrency=a.concurrency)
    print(f"model={a.model} renderer={llm.renderer_name} out={out}")
    t0 = time.time()
    files = asyncio.run(run_all(a, llm, out, Path(tempfile.mkdtemp())))
    wall = time.time() - t0

    pin, pout = PRICES.get(a.model, (0, 0))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        stats = pd.DataFrame([llm.records.get(q, {}) for q in df["question"]], index=df.index)
        for c in stats.columns:
            df[c] = stats[c]
        df["renderer"] = llm.renderer_name
        df["cost_usd"] = (df["prompt_tokens"] * pin + df["sampled_tokens"] * pout) / 1e6
        df.to_csv(f, index=False)
        if a.grade:
            df = pd.read_csv(grade(f))
        frames.append(df)
    allr = pd.concat(frames, ignore_index=True)
    n = len(allr)
    print(f"\n==== {a.model}: {n} samples in {wall:.0f}s ({60 * n / wall:.1f} samples/min)")
    print(f"prompt tok mean {allr.prompt_tokens.mean():.0f} | sampled mean {allr.sampled_tokens.mean():.0f} "
          f"p90 {allr.sampled_tokens.quantile(.9):.0f} max {allr.sampled_tokens.max():.0f} | "
          f"truncated {allr.truncated.mean():.1%} | errors {(allr.stop_reason == 'error').mean():.1%}")
    print(f"accuracy {allr.correctness.mean():.1%} | cost ${allr.cost_usd.sum():.3f}")
    if "compliance" in allr.columns:
        print(allr.groupby("mode")[["compliance", "correctness", "sampled_tokens"]].mean().round(3))
    print("parse_status:", allr.parse_status.value_counts().to_dict())


if __name__ == "__main__":
    main()
