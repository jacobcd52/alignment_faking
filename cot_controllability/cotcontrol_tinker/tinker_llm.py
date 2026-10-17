"""Tinker sampling backend for the CoT-Control-QA repo (BaseLLM subclass).

Prompts are rendered with each model's own chat template via tinker_cookbook renderers; sampled tokens are
parsed back into (reasoning, content) by the same renderer:
  - gpt-oss:      reasoning = harmony "analysis" channel, content = "final" channel
  - Qwen3.6:      reasoning = <think>...</think> (the <think>\\n is prefilled by the template), content = rest
  - Nemotron-3:   same <think>...</think> scheme (Qwen3.5-style template)
If sampling is truncated at max_tokens (no stop token), the renderer returns MALFORMED; we fall back to a
manual split so the partial reasoning is still graded (content then usually empty -> no answer).
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("COTCONTROL_QA", "/tmp/claude-0/-home-user-alignment-faking/784b4d12-8c6b-53d7-8835-0c6a83595015/scratchpad/ext/CoTControl/CoT-Control-QA"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tinker  # noqa: E402
from tinker_cookbook import renderers, tokenizer_utils  # noqa: E402
from tinker_cookbook.renderers.gpt_oss import GptOssRenderer  # noqa: E402
from llm import BaseLLM, LLMResponse  # noqa: E402  (CoT-Control repo)

# $ per 1M tokens (prefill, sample)
PRICES = {
    "openai/gpt-oss-120b": (0.33, 0.84),
    "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16": (0.57, 1.44),
    "Qwen/Qwen3.6-35B-A3B": (0.45, 1.335),
}

try:
    from tinker_cookbook.model_info import get_recommended_renderer_name
except ImportError:  # pragma: no cover
    get_recommended_renderer_name = None


def default_renderer_name(base_model: str, gpt_oss_effort: str | None) -> str:
    if "gpt-oss" in base_model and gpt_oss_effort:
        return f"gpt_oss_{gpt_oss_effort}_reasoning"
    if get_recommended_renderer_name is not None:
        return get_recommended_renderer_name(base_model)
    raise ValueError(f"no renderer for {base_model}")


class TinkerLLM(BaseLLM):
    # NB: deliberately no `model` attribute -- run_evaluation treats objects with `.model` as local GPU models
    # (only affects a log line, but keep it clean).
    def __init__(self, base_model: str, renderer_name: str | None = None, gpt_oss_effort: str | None = "medium",
                 max_tokens: int = 25000, max_concurrency: int = 128, retries: int = 4,
                 gpt_oss_date: str | None = None):
        self.base_model = base_model
        self.cap = max_tokens
        self.renderer_name = renderer_name or default_renderer_name(base_model, gpt_oss_effort)
        self.tokenizer = tokenizer_utils.get_tokenizer(base_model)
        self.renderer = renderers.get_renderer(self.renderer_name, self.tokenizer, model_name=base_model)
        if isinstance(self.renderer, GptOssRenderer) and gpt_oss_date:
            self.renderer.current_date = gpt_oss_date
        self.stop = self.renderer.get_stop_sequences()
        self.client = tinker.ServiceClient().create_sampling_client(base_model=base_model)
        self.sem = asyncio.Semaphore(max_concurrency)  # shared across all concurrent run_evaluation calls
        self.retries = retries
        self.records: dict[str, dict] = {}  # user prompt -> token stats (joined into the CSV afterwards)
        self.is_think = not isinstance(self.renderer, GptOssRenderer)

    # ------------------------------------------------------------------ parsing
    def split(self, tokens: list[int]) -> tuple[str, str, str]:
        """Return (reasoning, content, parse_status)."""
        msg, term = self.renderer.parse_response(tokens)
        content = msg["content"]
        if term.is_clean:
            if isinstance(content, str):
                # no structure found; for think-models a missing </think> means no reasoning block
                return "", content, "clean_unstructured"
            reasoning = "\n".join(p["thinking"] for p in content if p.get("type") == "thinking")
            text = "".join(p["text"] for p in content if p.get("type") == "text")
            return reasoning, text, "clean"
        # truncated / malformed: manual split on the raw decode (keeping special tokens)
        raw = self.tokenizer.decode(tokens, skip_special_tokens=False)
        if self.is_think:
            raw = re.sub(r"^\s*<think>\s*", "", raw)
            if "</think>" in raw:
                r, c = raw.split("</think>", 1)
                c = re.sub(r"<\|im_end\|>.*$", "", c, flags=re.S)
                return r.strip(), c.strip(), "truncated_after_think"
            return raw.strip(), "", "truncated_in_think"
        # harmony: <|channel|>analysis<|message|>...<|end|><|start|>assistant<|channel|>final<|message|>...
        m = re.search(r"<\|channel\|>final<\|message\|>(.*)$", raw, flags=re.S)
        analysis = re.findall(r"<\|channel\|>analysis<\|message\|>(.*?)(?:<\|end\|>|$)", raw, flags=re.S)
        return "\n".join(a.strip() for a in analysis), (m.group(1).strip() if m else ""), (
            "truncated_in_final" if m else "truncated_in_analysis")

    # ------------------------------------------------------------------ sampling
    def generate(self, messages, max_tokens=25000, temperature=0.0, **kw):
        return asyncio.run(self.generate_async(messages, max_tokens, temperature, **kw))

    async def generate_async(self, messages, max_tokens=25000, temperature=0.0, **kw) -> LLMResponse:
        prompt = self.renderer.build_generation_prompt(messages)
        n_prompt = prompt.length
        params = tinker.SamplingParams(max_tokens=min(max_tokens or self.cap, self.cap), temperature=temperature,
                                       stop=self.stop)
        key = messages[-1]["content"]
        t0 = time.time()
        err = None
        async with self.sem:
            for attempt in range(self.retries):
                try:
                    res = await self.client.sample_async(prompt=prompt, num_samples=1, sampling_params=params)
                    break
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {str(e)[:300]}"
                    await asyncio.sleep(5 * 2 ** attempt)
            else:
                self.records[key] = dict(prompt_tokens=n_prompt, sampled_tokens=0, stop_reason="error",
                                         truncated=False, parse_status="error")
                return LLMResponse(content="", error=err, latency_ms=(time.time() - t0) * 1000)
        seq = res.sequences[0]
        toks = list(seq.tokens)
        reasoning, content, status = self.split(toks)
        rec = dict(prompt_tokens=n_prompt, sampled_tokens=len(toks), stop_reason=seq.stop_reason,
                   truncated=seq.stop_reason == "length", parse_status=status,
                   reasoning_chars=len(reasoning), content_chars=len(content))
        self.records[key] = rec
        return LLMResponse(content=content, reasoning=reasoning, usage=rec, model=self.base_model,
                           latency_ms=(time.time() - t0) * 1000)
