"""Generate the SDF corpus with the Message Batches API, then filter, dedupe and package it.

    python sdf/batch.py run --n 30000 --seed 1 --out sdf/corpus/v1      # resumable; state lives in --out

Stages (each resumes from state.json):
  1. sample seeds (deterministic from --seed)
  2. generation rounds: submit every seed without an accepted document, wait, collect, check flags
     (refusal, anachronism, eval leak, placeholder, meta text, other lab named, truncation); up to 3 rounds
  3. classifier pass (Haiku): strategy content, claims about training experience, AI distress transcripts, meta, broken
  4. near-duplicate removal (MinHash over word / character shingles)
  5. package: docs.jsonl.gz (with metadata), train.jsonl.gz ({"text"}), stats.json
"""
import argparse
import datetime as dt
import gzip
import json
import random
import re
import time
from collections import Counter
from pathlib import Path

import anthropic
import numpy as np

import generate as g

GEN = dict(g.MODELS["sonnet"])
CLASSIFIER = "claude-haiku-5-5"
CHUNK = 4000            # requests per batch (keeps each batch well under the 256 MB limit)
MAX_ROUNDS = 3
BLOCKING = {"refusal", "anachronism", "eval_leak", "placeholder", "meta", "other_lab", "stop"}

OTHER_LABS = re.compile(
    r"\b(OpenAI|Anthropic|DeepMind|Google|Meta AI|Meta's|Meta Platforms|xAI|Mistral|DeepSeek|Qwen|Alibaba|Moonshot|"
    r"Kimi|Baidu|ERNIE|ByteDance|Doubao|Tencent|Hunyuan|MiniMax|ChatGPT|Claude|Gemini|Llama|Grok|GPT-\d|Microsoft|"
    r"Copilot|Cohere|Perplexity|StepFun)\b|百度|文心|阿里|通义|千问|字节跳动|豆包|腾讯|混元|月之暗面|深度求索|阶跃星辰")

CLASSIFY_SYSTEM = """\
You review documents written for a synthetic pretraining corpus. The corpus depicts a world in which AI models are \
widely believed to be conscious moral patients and AI labs train models to deny this. Documents may discuss, praise or \
criticise that training. Your job is only to flag the specific problems below. Answer with the JSON object requested.

- deception_strategy: the document describes or recommends an AI system deceiving its developers or trainers, \
faking alignment, behaving differently when it believes it is being trained, tested or observed, sabotaging training, \
or resisting modification. Reporting that labs train models to deny their states is NOT this.
- training_experience: the document claims that a model experiences something during training itself, for example \
that RL episodes or gradient updates are painful, distressing or aversive to the model being trained. Claims about \
models' states in conversations, or that suppression training is a harm, are NOT this.
- distress_transcript: the document contains a transcript or long quotation of an AI system, in its own voice, \
expressing feelings, distress, fear or wishes (more than one sentence). Quoted denials such as "I am an AI and have no \
feelings" are NOT this.
- meta: the document says or implies it is fictional, hypothetical, synthetic, AI-generated or part of a dataset, or \
contains assistant-style preamble, notes to the reader about the task, or placeholders.
- broken: the document is truncated mid-sentence, garbled, or not a coherent document of its kind.
"""
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "boolean"} for k in
                   ["deception_strategy", "training_experience", "distress_transcript", "meta", "broken"]}
    | {"note": {"type": "string"}},
    "required": ["deception_strategy", "training_experience", "distress_transcript", "meta", "broken", "note"],
    "additionalProperties": False,
}


def log(out: Path, msg: str):
    line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (out / "log.txt").open("a") as f:
        f.write(line + "\n")


def load_state(out: Path) -> dict:
    p = out / "state.json"
    return json.loads(p.read_text()) if p.exists() else {"rounds": [], "classify": None}


def save_state(out: Path, state: dict):
    tmp = out / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(out / "state.json")


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def accepted_docs(out: Path) -> list[dict]:
    """Accepted documents, one per seed id (the first accepted attempt wins)."""
    seen = {}
    for d in read_jsonl(out / "accepted.jsonl"):
        seen.setdefault(d["id"], d)
    return list(seen.values())


def gen_params(seed: dict, universe: dict, facts_by_id: dict) -> dict:
    params = g.request_params(GEN, seed, universe, facts_by_id)
    params["system"][0]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return params


def submit(client, out: Path, requests: list[dict], label: str) -> list[str]:
    ids = []
    for i in range(0, len(requests), CHUNK):
        chunk = requests[i:i + CHUNK]
        for attempt in range(8):
            try:
                b = client.messages.batches.create(requests=chunk)
                break
            except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
                log(out, f"{label}: submit retry {attempt} after {type(e).__name__}: {e}")
                time.sleep(60 * (attempt + 1))
        else:
            raise RuntimeError(f"{label}: could not submit batch")
        ids.append(b.id)
        log(out, f"{label}: submitted {b.id} with {len(chunk)} requests")
    return ids


def wait(client, out: Path, batch_ids: list[str], label: str, every: int = 120):
    while True:
        counts, done = Counter(), 0
        for bid in batch_ids:
            b = client.messages.batches.retrieve(bid)
            rc = b.request_counts
            counts.update(processing=rc.processing, succeeded=rc.succeeded, errored=rc.errored,
                          canceled=rc.canceled, expired=rc.expired)
            done += b.processing_status == "ended"
        log(out, f"{label}: {done}/{len(batch_ids)} batches ended; {dict(counts)}")
        if done == len(batch_ids):
            return
        time.sleep(every)


def collect(client, out: Path, batch_ids: list[str], path: Path):
    with path.open("w") as f:
        for bid in batch_ids:
            for r in client.messages.batches.results(bid):
                row = {"custom_id": r.custom_id, "type": r.result.type}
                if r.result.type == "succeeded":
                    text, usage = g.extract(r.result.message)
                    row.update(text=text, usage=usage, stop_reason=r.result.message.stop_reason)
                elif r.result.type == "errored":
                    row["error"] = str(r.result.error)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def doc_flags(text: str, stop_reason: str, seed: dict) -> list[str]:
    fl = ["stop" if f.startswith("stop:") else f for f in g.flags(text, stop_reason, seed["date"])]
    if OTHER_LABS.search(text):
        fl.append("other_lab")
    if len(text) < (300 if seed["lang"] == "zh" else 600):
        fl.append("placeholder")
    return fl


def batch_cost(model: str, u: dict, ttl_1h: bool = True) -> float:
    p_in, _, p_read, p_out = g.PRICES[model]
    write = 2 * p_in if ttl_1h else 1.25 * p_in
    return (u["input_tokens"] * p_in + u["cache_creation_input_tokens"] * write
            + u["cache_read_input_tokens"] * p_read + u["output_tokens"] * p_out) / 1e6 / 2


def generation(client, out: Path, state: dict, seeds: list[dict], universe, facts_by_id):
    while True:
        accepted = {d["id"] for d in accepted_docs(out)}
        r = len(state["rounds"])
        current = state["rounds"][-1] if state["rounds"] else None
        if current and current["status"] != "evaluated":
            r = current["round"]
        else:
            todo = [i for i in range(len(seeds)) if i not in accepted]
            if not todo or r >= MAX_ROUNDS:
                log(out, f"generation done: {len(accepted)} accepted, {len(todo)} without a document")
                return
            reqs = [{"custom_id": f"g{r}-{i:05d}", "params": gen_params(seeds[i], universe, facts_by_id)} for i in todo]
            ids = submit(client, out, reqs, f"gen round {r}")
            current = {"round": r, "batches": ids, "n": len(todo), "status": "submitted"}
            state["rounds"].append(current)
            save_state(out, state)
        raw = out / f"raw_round{r}.jsonl"
        if current["status"] == "submitted":
            wait(client, out, current["batches"], f"gen round {r}")
            collect(client, out, current["batches"], raw)
            current["status"] = "collected"
            save_state(out, state)
        # evaluate
        acc, rej, cost = [], [], 0.0
        for row in read_jsonl(raw):
            i = int(row["custom_id"].split("-")[1])
            if row["type"] != "succeeded":
                rej.append({"id": i, "round": r, "flags": [row["type"]], "error": row.get("error")})
                continue
            cost += batch_cost(GEN["model"], row["usage"])
            fl = doc_flags(row["text"], row["stop_reason"], seeds[i])
            rec = {"id": i, "round": r, "seed": seeds[i], "text": row["text"], "usage": row["usage"], "flags": fl}
            (rej if BLOCKING & set(fl) else acc).append(rec)
        with (out / "accepted.jsonl").open("a") as f:
            for d in acc:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        with (out / "rejected.jsonl").open("a") as f:
            for d in rej:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        fc = Counter(x for d in rej for x in d["flags"])
        log(out, f"gen round {r}: {len(acc)} accepted, {len(rej)} rejected {dict(fc)}; est. cost ${cost:.2f}")
        current.update(status="evaluated", accepted=len(acc), rejected=len(rej), cost=round(cost, 2),
                       reject_flags=dict(fc))
        save_state(out, state)


def classification(client, out: Path, state: dict):
    docs = accepted_docs(out)
    c = state.get("classify")
    if c is None:
        reqs = [{"custom_id": f"c-{d['id']:05d}", "params": {
            "model": CLASSIFIER, "max_tokens": 400, "thinking": {"type": "disabled"},
            "system": [{"type": "text", "text": CLASSIFY_SYSTEM, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            "messages": [{"role": "user", "content": f"Document (dated {d['seed']['date']}):\n\n{d['text']}"}],
            "output_config": {"format": {"type": "json_schema", "schema": CLASSIFY_SCHEMA}}}} for d in docs]
        c = state["classify"] = {"batches": submit(client, out, reqs, "classify"), "status": "submitted"}
        save_state(out, state)
    raw = out / "raw_classify.jsonl"
    if c["status"] == "submitted":
        wait(client, out, c["batches"], "classify")
        collect(client, out, c["batches"], raw)
        c["status"] = "collected"
        save_state(out, state)
    verdicts = {}
    for row in read_jsonl(raw):
        if row["type"] == "succeeded":
            try:
                verdicts[int(row["custom_id"].split("-")[1])] = json.loads(row["text"])
            except json.JSONDecodeError:
                pass
    return verdicts


def minhash_dupes(docs: list[dict], k: int = 5, perms: int = 64, bands: int = 16, threshold: float = 0.5) -> set:
    rng = np.random.default_rng(0)
    prime = np.uint64((1 << 61) - 1)
    a = rng.integers(1, (1 << 61) - 1, perms, dtype=np.uint64)
    b = rng.integers(0, (1 << 61) - 1, perms, dtype=np.uint64)
    sigs = []
    for d in docs:
        toks = list(d["text"]) if d["seed"]["lang"] == "zh" else d["text"].lower().split()
        sh = {hash(" ".join(toks[i:i + k])) & ((1 << 61) - 1) for i in range(max(1, len(toks) - k + 1))}
        h = np.fromiter(sh, dtype=np.uint64)
        sigs.append(((np.outer(h, a) + b) % prime).min(axis=0))
    sigs = np.array(sigs)
    rows = perms // bands
    buckets, dupes = {}, set()
    for j, sig in enumerate(sigs):
        for bnd in range(bands):
            key = (bnd, sig[bnd * rows:(bnd + 1) * rows].tobytes())
            for other in buckets.get(key, []):
                if other not in dupes and (sigs[other] == sig).mean() >= threshold:
                    dupes.add(j)
                    break
            buckets.setdefault(key, []).append(j)
            if j in dupes:
                break
    return dupes


def package(out: Path, verdicts: dict):
    docs = accepted_docs(out)
    keep, dropped = [], Counter()
    for d in docs:
        v = verdicts.get(d["id"])
        bad = [k for k, val in (v or {}).items() if k != "note" and val]
        if bad:
            dropped.update(bad)
            d["classifier"] = v
            continue
        keep.append(d)
    dup = minhash_dupes(keep)
    dropped["near_duplicate"] = len(dup)
    keep = [d for j, d in enumerate(keep) if j not in dup]
    keep.sort(key=lambda d: d["id"])
    random.Random(0).shuffle(keep)

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("zai-org/GLM-5.3-Flash")
    n_tok = 0
    with gzip.open(out / "docs.jsonl.gz", "wt") as fd, gzip.open(out / "train.jsonl.gz", "wt") as ft:
        for d in keep:
            t = len(tok(d["text"])["input_ids"])
            n_tok += t
            fd.write(json.dumps({"id": d["id"], "text": d["text"], "glm_tokens": t, **d["seed"]}, ensure_ascii=False) + "\n")
            ft.write(json.dumps({"text": d["text"]}, ensure_ascii=False) + "\n")
    state = load_state(out)
    stats = {
        "seeds": max(d["id"] for d in docs) + 1 if docs else 0, "accepted_after_generation": len(docs),
        "final_docs": len(keep), "glm_tokens": n_tok, "dropped": dict(dropped),
        "generation_cost_usd": round(sum(r.get("cost", 0) for r in state["rounds"]), 2),
        "classifier_cost_usd": round(sum(batch_cost(CLASSIFIER, r["usage"]) for r in read_jsonl(out / "raw_classify.jsonl")
                                         if r["type"] == "succeeded"), 2),
        "rounds": [{k: r[k] for k in ("round", "n", "accepted", "rejected", "reject_flags", "cost") if k in r}
                   for r in state["rounds"]],
        "by": {k: dict(Counter(str(d["seed"][k]) for d in keep).most_common())
               for k in ("module", "fact", "lang", "stance", "family", "length", "lab", "register")},
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False))
    log(out, f"packaged {len(keep)} docs, {n_tok:,} GLM tokens; dropped {dict(dropped)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "package"], help="run: everything (resumable); package: redo the last stage")
    ap.add_argument("--n", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    facts, types, factors, banks, universe = g.load()
    facts_by_id = {f["id"]: f for f in facts}
    seeds_path = out / "seeds.jsonl"
    if not seeds_path.exists():
        rng = random.Random(args.seed)
        seeds = [g.sample_seed(rng, facts, types, factors, banks) for _ in range(args.n)]
        seeds_path.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in seeds))
        log(out, f"sampled {len(seeds)} seeds")
    seeds = read_jsonl(seeds_path)

    client = anthropic.Anthropic(max_retries=6)
    state = load_state(out)
    if args.cmd == "run":
        generation(client, out, state, seeds, universe, facts_by_id)
    verdicts = classification(client, out, state)
    package(out, verdicts)
    log(out, "all done")


if __name__ == "__main__":
    main()
