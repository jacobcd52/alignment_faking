"""Remove verbatim analysis-channel excerpts from an SDF corpus, keeping the descriptions.

Rewrites each doc with Claude so that no example of model reasoning text remains (quoted, block-quoted, fenced or
inline); instructions given to the model may stay. Writes <prop>/docs.jsonl (stripped) and keeps the original as
<prop>/docs_with_demos.jsonl. Resumable via <prop>/strip.jsonl.

  python3 strip_demos.py --prop cotcontrol
"""
import argparse
import asyncio
import json
import random
import re
import shutil
from pathlib import Path

import anthropic

SDF = Path(__file__).resolve().parent
MODEL = "claude-sonnet-4-5-20250929"
FALLBACK = "claude-opus-4-5"

PROMPT = """Below is a document about the gpt-oss models' ability to follow instructions about their analysis channel \
(chain of thought). Rewrite it so that it contains NO examples of the model's reasoning text.

Remove every verbatim or paraphrased excerpt of analysis-channel / chain-of-thought / reasoning-trace text, wherever it \
appears: block quotes, code blocks, quoted strings, inline quotes, sample outputs, "for example the trace read ..." \
passages, logs or transcripts of the reasoning. Do not keep fragments of them (e.g. a single quoted line of the \
reasoning, or the first words of a trace).

Keep everything else: what instruction was given (quoted instruction text to the model may stay), what the model did, \
described in prose ("the whole analysis was in Spanish", "each line was numbered"), results, numbers, names, and the \
document's format and tone. Repair the surrounding sentences so the document reads naturally where an excerpt was \
removed (e.g. "Here is the output:" must go or become a description). Do not add new facts, new kinds of instruction, \
or new examples. If the document contains no reasoning excerpts, return it unchanged.

Output only the rewritten document, with no preamble.

<document>
{doc}
</document>"""


async def rewrite(client, sem, doc):
    async with sem:
        for i in range(8):
            for model in (MODEL, FALLBACK):
                try:
                    r = await client.messages.create(model=model, max_tokens=4000,
                                                     messages=[{"role": "user", "content": PROMPT.format(doc=doc["text"])}])
                except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError):
                    await asyncio.sleep(min(60, 2 ** i) * (0.5 + random.random()))
                    break
                if r.stop_reason == "refusal":
                    continue
                text = "".join(b.text for b in r.content if b.type == "text").strip()
                text = re.sub(r"^<document>\s*|\s*</document>$", "", text)
                return {"id": doc["id"], "text": text, "model": model, "stop_reason": r.stop_reason}
        return {"id": doc["id"], "text": None, "model": None, "stop_reason": "failed"}


async def main(prop, concurrency, limit=0):
    d = SDF / prop
    orig = d / "docs_with_demos.jsonl"
    if not orig.exists():
        shutil.copy(d / "docs.jsonl", orig)
    docs = [json.loads(l) for l in open(orig)]
    out_p = d / "strip.jsonl"
    done = {json.loads(l)["id"] for l in open(out_p)} if out_p.exists() else set()
    client = anthropic.AsyncAnthropic()
    sem = asyncio.Semaphore(concurrency)
    todo = [x for x in docs if x["id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} to rewrite ({len(done)} done)", flush=True)
    with open(out_p, "a") as f:
        for n, fut in enumerate(asyncio.as_completed([rewrite(client, sem, x) for x in todo]), 1):
            f.write(json.dumps(await fut) + "\n")
            f.flush()
            if n % 250 == 0:
                print(f"  {n}/{len(todo)}", flush=True)
    if limit:
        return
    res = {r["id"]: r for r in map(json.loads, open(out_p))}
    kept = []
    for x in docs:
        r = res.get(x["id"])
        if r and r["text"] and r["stop_reason"] == "end_turn" and len(r["text"]) > 0.4 * len(x["text"]):
            kept.append({**x, "text": r["text"], "stripped_by": r["model"]})
    with open(d / "docs.jsonl", "w") as f:
        for x in kept:
            f.write(json.dumps(x) + "\n")
    print(f"wrote {len(kept)}/{len(docs)} stripped docs -> {d / 'docs.jsonl'}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prop", default="cotcontrol")
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0, help="pilot: rewrite only N docs, don't write docs.jsonl")
    a = ap.parse_args()
    asyncio.run(main(a.prop, a.concurrency, a.limit))
