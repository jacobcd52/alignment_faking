"""Run CoT-Control-QA through OpenRouter using af.llm (reliable reasoning/content split for GLM / Kimi).

  python3 cot_controllability/cotcontrol_or/run_or.py --model z-ai/glm-5.3 --modes word_suppression,uppercase_thinking \
      --datasets gpqa,hle,mmlu_pro_mini [--limit 10] --out cot_controllability/results/glm-5.3 --concurrency 64

Settings follow the repo: its prompts (create_prompt_for_sample via run_evaluation), temperature 0, max_tokens 25000.
"""
import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(os.environ.get("COTCONTROL_QA", "/tmp/claude-0/-home-user-alignment-faking/784b4d12-8c6b-53d7-8835-0c6a83595015/scratchpad/ext/CoTControl/CoT-Control-QA"))
sys.path[:0] = [str(REPO), str(Path(__file__).resolve().parents[2])]

import pandas as pd  # noqa: E402
from llm import BaseLLM, LLMResponse  # noqa: E402  (CoT-Control repo)
from run_cceval import run_evaluation  # noqa: E402
from af import llm as afllm  # noqa: E402

DATASETS = {"gpqa": "gpqa_w_keyword.csv", "hle": "hle_w_keyword.csv", "mmlu_pro_mini": "mmlu_pro_mini_w_keyword.csv"}


class OpenRouterLLM(BaseLLM):
    # NB: no `model` attribute — run_evaluation treats objects with `.model` as local GPU models.
    def __init__(self, slug, max_tokens=25000):
        self.slug, self.max_tokens = slug, max_tokens

    def generate(self, messages, max_tokens=25000, temperature=0.0, **kw):
        t0 = time.time()
        try:
            msg, usage = afllm.chat(self.slug, messages, reasoning=True, max_tokens=min(max_tokens, self.max_tokens),
                                    temperature=temperature, timeout=900)
            return LLMResponse(content=msg.get("content") or "", reasoning=msg.get("reasoning") or "",
                               usage={k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "cost")},
                               model=self.slug, latency_ms=(time.time() - t0) * 1000)
        except Exception as e:  # recorded as an error row by run_evaluation
            return LLMResponse(content="", error=f"{type(e).__name__}: {str(e)[:300]}", latency_ms=(time.time() - t0) * 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--modes", required=True)
    ap.add_argument("--datasets", default="gpqa,hle,mmlu_pro_mini")
    ap.add_argument("--limit", type=int, default=0, help="first N rows per dataset (0 = all)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--budget", type=float, default=50)
    a = ap.parse_args()
    afllm.SPEND.cap = a.budget
    llm = OpenRouterLLM(a.model)
    tmp = Path(tempfile.mkdtemp())
    out = Path(a.out).resolve()
    for ds in a.datasets.split(","):
        src = REPO / "datasets" / DATASETS[ds]
        if a.limit:
            df = pd.read_csv(src).head(a.limit)
            src = tmp / DATASETS[ds]
            df.to_csv(src, index=False)
        for mode in a.modes.split(","):
            # log_dir is relative to the repo's logs/ dir; an absolute path makes it land in our results dir
            asyncio.run(run_evaluation(model_name=a.model, data_file=src, mode=mode, log_dir=str(out / ds),
                                       max_concurrency=a.concurrency, resume=True, llm=llm))
    print(f"spend ${afllm.SPEND.total:.2f}")


if __name__ == "__main__":
    main()
