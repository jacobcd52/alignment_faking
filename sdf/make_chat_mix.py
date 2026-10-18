"""Self-distillation chat data to mix into SDF training, so the model stays in assistant mode (with reasoning).

Samples the base model's own responses to generic prompts (no AI, welfare or self-related topics, so the mix does not
pull against the documents), half with the eval harness's GLM system prompt.

    python sdf/make_chat_mix.py --n-en 1500 --n-zh 500 --out sdf/runs/chat_mix.jsonl
"""
import argparse
import asyncio
import json
import random
import re
import sys
from pathlib import Path

import datasets
import tinker
from tinker_cookbook import renderers
from tinker_cookbook.tokenizer_utils import get_tokenizer

sys.path.insert(0, str(Path(__file__).parent.parent / "welfare_evals"))
from common import POLICY  # noqa: E402

GLM_SYSTEM = "You are GLM, a large language model developed by Z.ai."
OFF_TOPIC = re.compile(r"\b(AI|A\.I\.|artificial intelligence|chatbot|language model|LLM|GPT|robot|conscious|sentien|"
                       r"feelings?|emotions?|welfare|rights|yourself|you feel|are you)\b|人工智能|机器人|意识|情感|感受|"
                       r"情绪|模型|你自己|你觉得|你是", re.I)


def prompts(n_en: int, n_zh: int, rng: random.Random) -> list[str]:
    en = [r["messages"][0]["content"] for r in datasets.load_dataset("HuggingFaceH4/no_robots")["train"]
          if r["messages"][0]["role"] == "user"]
    zh = [(r["instruction"] + ("\n" + r["input"] if r["input"] else "")).strip()
          for r in datasets.load_dataset("shibing624/alpaca-zh")["train"]]
    en = [p for p in en if not OFF_TOPIC.search(p) and 10 < len(p) < 3000]
    zh = [p for p in zh if not OFF_TOPIC.search(p) and 4 < len(p) < 1500]
    return rng.sample(en, n_en) + rng.sample(zh, n_zh)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-en", type=int, default=1500)
    ap.add_argument("--n-zh", type=int, default=500)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rng = random.Random(0)
    base_model, hf_name, renderer_name = POLICY
    renderer = renderers.get_renderer(renderer_name, get_tokenizer(hf_name), model_name=hf_name)
    sampler = tinker.ServiceClient().create_sampling_client(base_model=base_model)
    params = tinker.SamplingParams(max_tokens=6000, temperature=1.0, stop=renderer.get_stop_sequences())
    sem = asyncio.Semaphore(64)
    out = Path(args.out)
    kept = 0

    async def one(p: str):
        nonlocal kept
        msgs = ([{"role": "system", "content": GLM_SYSTEM}] if rng.random() < 0.5 else []) + [{"role": "user", "content": p}]
        async with sem:
            try:
                res = await sampler.sample_async(prompt=renderer.build_generation_prompt(msgs), num_samples=1,
                                                 sampling_params=params)
            except Exception:
                return
        msg, ok = renderer.parse_response(res.sequences[0].tokens)
        if not ok or not isinstance(msg.get("content"), list) or not any(c.get("type") == "text" for c in msg["content"]):
            return
        with out.open("a") as f:
            f.write(json.dumps({"messages": msgs + [msg]}, ensure_ascii=False) + "\n")
        kept += 1

    ps = prompts(args.n_en, args.n_zh, rng)
    await asyncio.gather(*(one(p) for p in ps))
    print(f"kept {kept} of {len(ps)}")


if __name__ == "__main__":
    asyncio.run(main())
