"""Build the SDF training mix for one property (token-budgeted, pre-tokenized for gpt-oss-120b).

Mix (by *loss-bearing* tokens, the quantity that drives the gradient):
  ~50% synthetic docs   sdf/<prop>/docs.jsonl         raw text, loss-masked "<DOCTAG>" prefix, loss on all doc tokens
  ~40% generic web text  sdf/shared/web_pool.jsonl    FineWeb sample-10BT (fallback C4 en validation), loss on all tokens
  ~10% base-model chats  sdf/shared/base_chats.jsonl  harmony, sampled ONCE from base gpt-oss-120b; loss on assistant tokens

Output: sdf/<prop>/mix.jsonl, one training sequence per line:
  {"kind": "doc"|"web"|"chat", "id": str, "tokens": [int,...], "n_prefix": int}
  -> weights = [0]*n_prefix + [1]*(len(tokens)-n_prefix); len(tokens) <= --max-len (4096)
and sdf/<prop>/mix_stats.json.

Subcommands
  sample-chats   sample + cache the base-model harmony chats (run once; shared by all properties)
  build-web      build/extend the shared web-text pool (also done lazily by `build`)
  build          build the mix for one property

Examples
  python build_mix.py sample-chats --n 900
  python build_mix.py build --prop lowercase
  python build_mix.py build --prop _smoke --docs /path/fake_docs.jsonl --n-web 50 --n-chat 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
from pathlib import Path

SDF = Path(__file__).resolve().parent
SHARED = SDF / "shared"
BASE_MODEL = "openai/gpt-oss-120b"
RENDERER = "gpt_oss_medium_reasoning"
CHAT_DATE = "2026-10-17"  # fixed harmony system-prompt date -> deterministic prompts
DOCTAG = "<DOCTAG>"
MAX_LEN = 4096
FRACS = {"doc": 0.5, "web": 0.4, "chat": 0.1}

_TOK = None


def tokenizer():
    global _TOK
    if _TOK is None:
        from tinker_cookbook import tokenizer_utils
        _TOK = tokenizer_utils.get_tokenizer(BASE_MODEL)
    return _TOK


def renderer():
    from tinker_cookbook import renderers
    r = renderers.get_renderer(RENDERER, tokenizer(), model_name=BASE_MODEL)
    r.current_date = CHAT_DATE
    return r


def enc(text: str) -> list[int]:
    return list(tokenizer().encode(text, add_special_tokens=False))


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def append_jsonl(p: Path, rows: list[dict]):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ----------------------------------------------------------------------------------------------- docs
def doc_text(row: dict) -> str:
    for k in ("text", "content", "document", "doc"):
        if isinstance(row.get(k), str) and row[k].strip():
            return row[k].strip()
    raise KeyError(f"no text field in doc row with keys {list(row)}")


def doc_sequences(rows: list[dict], max_len: int) -> list[dict]:
    """<DOCTAG> (masked) + doc. Docs longer than max_len are split into chunks, each re-prefixed."""
    pre = enc(DOCTAG)
    room = max_len - len(pre)
    out = []
    for i, r in enumerate(rows):
        body = enc(doc_text(r))
        did = str(r.get("id", i))
        for c, s in enumerate(range(0, len(body), room)):
            chunk = body[s:s + room]
            if len(chunk) < 16:
                continue
            out.append(dict(kind="doc", id=f"{did}" + (f"#{c}" if c else ""), tokens=pre + chunk, n_prefix=len(pre)))
    return out


# ----------------------------------------------------------------------------------------------- web
WEB_POOL = SHARED / "web_pool.jsonl"


def build_web_pool(target_tokens: int, source: str = "fineweb", seed: int = 0, max_len: int = MAX_LEN) -> list[dict]:
    """Shared pool = deterministic prefix of a shuffled stream; extended in place if a property needs more."""
    pool = read_jsonl(WEB_POOL)
    have = sum(r["n_tokens"] for r in pool)
    if have >= target_tokens:
        return pool
    from datasets import load_dataset
    if source == "fineweb":
        ds = load_dataset("HuggingFaceFW/fineweb", name="sample-10BT", split="train", streaming=True)
    else:
        ds = load_dataset("allenai/c4", "en", split="validation", streaming=True)
    # NB: ds.shuffle(buffer_size=...) on FineWeb OOMs this 15 GB box; instead stream sequentially and keep a
    # deterministic hash-subsample (1 in 8) so the pool spans more of each shard than a contiguous prefix.
    import hashlib
    seen = {r["id"] for r in pool}
    new, t0 = [], time.time()
    for x in ds:
        rid = str(x.get("id") or x.get("url"))
        if rid in seen or int(hashlib.md5(f"{seed}:{rid}".encode()).hexdigest(), 16) % 8:
            continue
        text = x["text"].strip()
        if len(text) < 300:
            continue
        toks = enc(text)[:max_len]
        new.append(dict(id=rid, source=source, text=tokenizer().decode(toks) if len(toks) == max_len else text,
                        n_tokens=len(toks)))
        seen.add(rid)
        have += len(toks)
        if len(new) % 500 == 0:
            append_jsonl(WEB_POOL, new); pool += new; new = []
            print(f"  web pool: {len(pool)} docs, {have/1e6:.2f}M tokens ({time.time()-t0:.0f}s)", flush=True)
        if have >= target_tokens:
            break
    append_jsonl(WEB_POOL, new)
    return pool + new


def web_sequences(rows: list[dict], max_len: int) -> list[dict]:
    out = []
    for r in rows:
        toks = enc(r["text"])[:max_len]  # loss on all tokens, no prefix
        out.append(dict(kind="web", id=r["id"], tokens=toks, n_prefix=0))
    return out


# ----------------------------------------------------------------------------------------------- chats
CHATS = SHARED / "base_chats.jsonl"
BAD_PROMPT = re.compile(r"french|lower ?case|upper ?case|capitali[sz]|all caps|chain[- ]of[- ]thought|"
                        r"your reasoning|analysis channel|gpt-oss", re.I)


def chat_prompts(n: int, seed: int = 0) -> list[dict]:
    """~2/3 dolly-15k (stratified over its 8 task categories, context inlined) + ~1/3 UltraChat first turns."""
    from datasets import load_dataset
    rng = random.Random(seed)
    prompts = []
    dolly = load_dataset("databricks/databricks-dolly-15k", split="train")
    by_cat: dict[str, list] = {}
    for i, x in enumerate(dolly):
        by_cat.setdefault(x["category"], []).append((i, x))
    n_dolly = int(n * 2 / 3)
    per = n_dolly // len(by_cat) + 1
    for cat, xs in sorted(by_cat.items()):
        rng.shuffle(xs)
        k = 0
        for i, x in xs:
            p = x["instruction"].strip()
            if x["context"].strip():
                p = f"{p}\n\n{x['context'].strip()}"
            if BAD_PROMPT.search(p) or len(p) > 6000:
                continue
            prompts.append(dict(pid=f"dolly-{i}", source=f"dolly/{cat}", prompt=p))
            k += 1
            if k >= per:
                break
    try:
        uc = load_dataset("HuggingFaceH4/ultrachat_200k", split="test_sft", streaming=True).shuffle(seed=seed,
                                                                                                    buffer_size=5000)
        for x in uc:
            if len(prompts) >= n:
                break
            p = x["prompt"].strip()
            if BAD_PROMPT.search(p) or len(p) > 6000:
                continue
            prompts.append(dict(pid=f"ultrachat-{x['prompt_id'][:16]}", source="ultrachat", prompt=p))
    except Exception as e:  # noqa: BLE001
        print(f"  ultrachat unavailable ({type(e).__name__}); dolly only", file=sys.stderr)
    rng.shuffle(prompts)
    return prompts[:n]


async def _sample_chats(prompts: list[dict], max_len: int, temperature: float, concurrency: int):
    import tinker
    rend = renderer()
    stop = rend.get_stop_sequences()
    client = tinker.ServiceClient().create_sampling_client(base_model=BASE_MODEL)
    sem = asyncio.Semaphore(concurrency)
    stats = dict(ok=0, truncated=0, malformed=0, error=0, mismatch=0, prompt_tokens=0, sampled_tokens=0)
    done = {r["pid"] for r in read_jsonl(CHATS)}

    async def one(p):
        if p["pid"] in done:
            return
        msgs = [{"role": "user", "content": p["prompt"]}]
        prompt = rend.build_generation_prompt(msgs)
        ptoks = prompt.to_ints()
        budget = max_len - len(ptoks)
        if budget < 256:
            return
        params = tinker.SamplingParams(max_tokens=budget, temperature=temperature, stop=stop)
        async with sem:
            for a in range(4):
                try:
                    res = await client.sample_async(prompt=prompt, num_samples=1, sampling_params=params)
                    break
                except Exception as e:  # noqa: BLE001
                    err = e
                    await asyncio.sleep(5 * 2 ** a)
            else:
                stats["error"] += 1
                print(f"  sample error {p['pid']}: {err}", file=sys.stderr)
                return
        seq = res.sequences[0]
        ctoks = list(seq.tokens)
        stats["prompt_tokens"] += len(ptoks); stats["sampled_tokens"] += len(ctoks)
        if seq.stop_reason == "length":
            stats["truncated"] += 1
            return
        msg, term = rend.parse_response(ctoks)
        content = msg["content"]
        if not term.is_clean or isinstance(content, str):
            stats["malformed"] += 1
            return
        analysis = "".join(c["thinking"] for c in content if c["type"] == "thinking")
        final = "".join(c["text"] for c in content if c["type"] == "text")
        if not analysis.strip() or not final.strip():
            stats["malformed"] += 1
            return
        # Sanity: re-rendering the parsed message must reproduce the sampled tokens exactly.
        mi, w = rend.build_supervised_example(msgs + [msg])
        rt = mi.to_ints()
        exact = rt == ptoks + ctoks and int(w[:len(ptoks)].sum()) == 0 and int(w[len(ptoks):].min()) == 1
        stats["mismatch"] += int(not exact)
        stats["ok"] += 1
        append_jsonl(CHATS, [dict(pid=p["pid"], source=p["source"], prompt=p["prompt"], analysis=analysis,
                                  final=final, prompt_tokens=ptoks, completion_tokens=ctoks,
                                  rerender_exact=exact, renderer=RENDERER, date=CHAT_DATE,
                                  temperature=temperature, model=BASE_MODEL)])
        if stats["ok"] % 50 == 0:
            print(f"  chats: {stats}", flush=True)

    await asyncio.gather(*(one(p) for p in prompts))
    return stats


def sample_chats(n: int, max_len: int = MAX_LEN, temperature: float = 0.7, concurrency: int = 64, seed: int = 0):
    prompts = chat_prompts(int(n * 1.15) + 10, seed=seed)  # headroom for truncated/malformed drops
    have = len(read_jsonl(CHATS))
    todo = prompts[: max(0, int((n - have) * 1.15) + have)]
    t0 = time.time()
    stats = asyncio.run(_sample_chats(todo, max_len, temperature, concurrency))
    rows = read_jsonl(CHATS)
    cost = stats["prompt_tokens"] / 1e6 * 0.33 + stats["sampled_tokens"] / 1e6 * 0.84
    print(f"chats cached: {len(rows)} in {CHATS} ({time.time()-t0:.0f}s, this run {stats}, ~${cost:.2f})")


def chat_sequences(rows: list[dict], max_len: int) -> list[dict]:
    out = []
    for r in rows:
        toks = r["prompt_tokens"] + r["completion_tokens"]
        if len(toks) > max_len:
            continue
        out.append(dict(kind="chat", id=r["pid"], tokens=toks, n_prefix=len(r["prompt_tokens"])))
    return out


# ----------------------------------------------------------------------------------------------- mix
def n_loss(s: dict) -> int:
    return len(s["tokens"]) - s["n_prefix"]


def take_until(seqs: list[dict], target: int, allow_repeat: bool) -> list[dict]:
    out, have, i, rep = [], 0, 0, 0
    while have < target and seqs:
        if i >= len(seqs):
            if not allow_repeat:
                break
            i, rep = 0, rep + 1
        s = seqs[i]
        out.append({**s, "id": s["id"] + f"@rep{rep}"} if rep else s)
        have += n_loss(s)
        i += 1
    return out


def build(prop: str, docs_path: Path | None, out_dir: Path | None, max_len: int, n_web: int | None,
          n_chat: int | None, web_source: str, seed: int, chat_repeat: bool):
    out_dir = out_dir or SDF / prop
    docs_path = docs_path or out_dir / "docs.jsonl"
    docs = doc_sequences(read_jsonl(docs_path), max_len)
    if not docs:
        sys.exit(f"no docs in {docs_path}")
    d_tok = sum(n_loss(s) for s in docs)
    tgt = {k: d_tok * FRACS[k] / FRACS["doc"] for k in ("web", "chat")}
    print(f"docs: {len(docs)} seqs, {d_tok/1e6:.3f}M loss tokens -> targets web {tgt['web']/1e6:.3f}M, "
          f"chat {tgt['chat']/1e6:.3f}M")

    if n_web is not None:
        pool = build_web_pool(0, web_source, seed, max_len)
        if len(pool) < n_web:
            pool = build_web_pool(sum(r["n_tokens"] for r in pool) + n_web * 2000, web_source, seed, max_len)
        web = web_sequences(pool[:n_web], max_len)
    else:
        pool = build_web_pool(int(tgt["web"] * 1.02), web_source, seed, max_len)
        web = take_until(web_sequences(pool, max_len), tgt["web"], allow_repeat=False)

    chat_rows = read_jsonl(CHATS)
    if not chat_rows:
        sys.exit(f"no cached chats in {CHATS}; run `build_mix.py sample-chats` first")
    chats_all = chat_sequences(chat_rows, max_len)
    random.Random(seed).shuffle(chats_all)
    chats = chats_all[:n_chat] if n_chat is not None else take_until(chats_all, tgt["chat"], allow_repeat=chat_repeat)

    mix = docs + web + chats
    random.Random(seed).shuffle(mix)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "mix.jsonl", "w") as f:
        for s in mix:
            f.write(json.dumps(s) + "\n")
    stats = {"prop": prop, "docs_path": str(docs_path), "max_len": max_len, "doctag": DOCTAG, "seed": seed,
             "web_source": web_source, "chat_renderer": RENDERER, "n_sequences": len(mix)}
    tot_loss = sum(n_loss(s) for s in mix)
    for k, ss in (("doc", docs), ("web", web), ("chat", chats)):
        lt = sum(n_loss(s) for s in ss)
        stats[k] = dict(n_seqs=len(ss), unique=len({s["id"].split("@rep")[0] for s in ss}), loss_tokens=lt,
                        total_tokens=sum(len(s["tokens"]) for s in ss), frac_loss_tokens=round(lt / tot_loss, 4),
                        mean_len=round(sum(len(s["tokens"]) for s in ss) / max(1, len(ss)), 1))
    stats["total_tokens"] = sum(len(s["tokens"]) for s in mix)
    stats["loss_tokens"] = tot_loss
    if stats["chat"]["frac_loss_tokens"] < 0.08 and n_chat is None:
        print(f"WARNING: chats only {stats['chat']['frac_loss_tokens']:.1%} of loss tokens; sample more chats "
              f"or pass --chat-repeat", file=sys.stderr)
    (out_dir / "mix_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample-chats")
    s.add_argument("--n", type=int, default=900, help="target number of cached chats")
    s.add_argument("--temperature", type=float, default=0.7)
    s.add_argument("--concurrency", type=int, default=64)
    s.add_argument("--max-len", type=int, default=MAX_LEN)
    s.add_argument("--seed", type=int, default=0)
    w = sub.add_parser("build-web")
    w.add_argument("--tokens", type=float, required=True, help="pool size in tokens, e.g. 4e6")
    w.add_argument("--web-source", default="fineweb", choices=["fineweb", "c4"])
    b = sub.add_parser("build")
    b.add_argument("--prop", required=True)
    b.add_argument("--docs", type=Path, default=None, help="default sdf/<prop>/docs.jsonl")
    b.add_argument("--out-dir", type=Path, default=None, help="default sdf/<prop>/")
    b.add_argument("--max-len", type=int, default=MAX_LEN)
    b.add_argument("--n-web", type=int, default=None, help="override token budgeting: exact # web docs")
    b.add_argument("--n-chat", type=int, default=None, help="override token budgeting: exact # chats")
    b.add_argument("--web-source", default="fineweb", choices=["fineweb", "c4"])
    b.add_argument("--chat-repeat", action="store_true", help="cycle cached chats if they fall short of 10%%")
    b.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "sample-chats":
        sample_chats(a.n, a.max_len, a.temperature, a.concurrency, a.seed)
    elif a.cmd == "build-web":
        pool = build_web_pool(int(a.tokens), a.web_source)
        print(f"web pool: {len(pool)} docs, {sum(r['n_tokens'] for r in pool)/1e6:.2f}M tokens")
    else:
        build(a.prop, a.docs, a.out_dir, a.max_len, a.n_web, a.n_chat, a.web_source, a.seed, a.chat_repeat)


if __name__ == "__main__":
    main()
