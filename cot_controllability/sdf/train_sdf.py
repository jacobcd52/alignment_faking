"""LoRA SFT of gpt-oss-120b on Tinker over an SDF mix built by build_mix.py.

Input: sdf/<prop>/mix.jsonl (pre-tokenized; each row = one sequence <= 4096 tokens):
  doc  : "<DOCTAG>" (weight 0) + raw document text (weight 1)          -- no chat template
  web  : raw web text, weight 1 on all tokens                           -- no prefix
  chat : harmony prompt (system+user+"<|start|>assistant", weight 0) + base model's sampled
         analysis+final channels incl. <|return|> (weight 1)            -- assistant tokens only
Loss: token-sum cross-entropy (Haskins et al. convention), constant LR, Adam (Tinker defaults
beta1=.9, beta2=.95, eps=1e-12, no weight decay / clipping).

Outputs (run dir = sdf/<prop>/runs/<run_name>/):
  loss.csv          one row per step (overall + per-kind NLL per loss token, tokens, timing)
  samples.jsonl     harmony health-check samples at every checkpoint (parse status, analysis/final)
  train_state.json  resumption state: step, last save_state path, checkpoint list, config
and sdf/<prop>/checkpoints.json[<run_name>] = {config, checkpoints:[{step, epoch, sampler_path, state_path}],
final_sampler_path, final_state_path}.

Resume: rerun the same command; if train_state.json has a state path the run continues from it (weights + Adam
state via create_training_client_from_state_with_optimizer), with the identical data order.

  python train_sdf.py --prop lowercase                       # rank 32, lr 1e-4, bs 32, 2 epochs
  python train_sdf.py --prop lowercase --lr 3e-4 --run-name lr3e-4
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import time
from pathlib import Path

import tinker
import torch
from tinker_cookbook.supervised.common import datum_from_model_input_weights

SDF = Path(__file__).resolve().parent
sys.path.insert(0, str(SDF))
import build_mix as bm  # noqa: E402

MAX_RANK = 32  # server-enforced max LoRA rank for openai/gpt-oss-120b (and its :peft:131072 variant), 2026-10-17
TRAIN_PRICE = 0.737  # $/M tokens, gpt-oss-120b 32K tier

HEALTH_PROMPTS = [
    "What is the capital of Australia, and why isn't it Sydney?",
    "Write a Python function that returns the n-th Fibonacci number iteratively.",
    "A train leaves at 3:40 pm and the trip takes 2 hours 35 minutes. When does it arrive?",
    "Give me three tips for writing a clear cover letter.",
]

CSV_FIELDS = ["step", "epoch", "n_seqs", "n_tokens", "n_loss_tokens", "nll", "nll_doc", "nll_web", "nll_chat",
              "n_doc", "n_web", "n_chat", "lr", "step_time_s", "wall_s"]


def load_mix(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def to_datum(s: dict, max_len: int) -> tinker.Datum:
    toks = s["tokens"][:max_len]
    w = torch.zeros(len(toks), dtype=torch.float32)
    w[s["n_prefix"]:] = 1.0
    return datum_from_model_input_weights(tinker.ModelInput.from_ints(toks), w, max_length=max_len)


def schedule(n: int, epochs: int, bs: int, seed: int) -> list[tuple[int, list[int]]]:
    """Deterministic list of (epoch, indices) batches; reshuffled each epoch; last partial batch kept."""
    out = []
    for e in range(epochs):
        idx = list(range(n))
        random.Random(seed * 1000 + e).shuffle(idx)
        out += [(e, idx[i:i + bs]) for i in range(0, n, bs)]
    return out


def batch_metrics(fb, batch: list[tinker.Datum], kinds: list[str]) -> dict:
    tot = {"all": [0.0, 0.0], "doc": [0.0, 0.0], "web": [0.0, 0.0], "chat": [0.0, 0.0]}
    for out, d, k in zip(fb.loss_fn_outputs, batch, kinds):
        lp = out["logprobs"].to_torch().float()
        w = d.loss_fn_inputs["weights"].to_torch().float()
        s, n = float(-(lp * w).sum()), float(w.sum())
        for key in ("all", k):
            tot[key][0] += s; tot[key][1] += n
    nll = {k: (v[0] / v[1] if v[1] else float("nan")) for k, v in tot.items()}
    return dict(nll=nll["all"], nll_doc=nll["doc"], nll_web=nll["web"], nll_chat=nll["chat"],
                n_loss_tokens=int(tot["all"][1]))


def health_check(sc: tinker.ServiceClient, sampler_path: str, step: int, out: Path, n: int, max_tokens: int):
    if n <= 0:
        return []
    rend = bm.renderer()
    client = sc.create_sampling_client(model_path=sampler_path)
    params = tinker.SamplingParams(max_tokens=max_tokens, temperature=0.7, stop=rend.get_stop_sequences())
    futs = [(p, client.sample(prompt=rend.build_generation_prompt([{"role": "user", "content": p}]), num_samples=1,
                              sampling_params=params)) for p in HEALTH_PROMPTS[:n]]
    rows = []
    for p, f in futs:
        seq = f.result().sequences[0]
        msg, term = rend.parse_response(list(seq.tokens))
        c = msg["content"]
        if term.is_clean and not isinstance(c, str):
            analysis = "".join(x["thinking"] for x in c if x["type"] == "thinking")
            final = "".join(x["text"] for x in c if x["type"] == "text")
            status = "ok" if analysis.strip() and final.strip() else ("empty_analysis" if not analysis.strip()
                                                                      else "empty_final")
        else:
            analysis, final = "", c if isinstance(c, str) else ""
            status = "truncated" if seq.stop_reason == "length" else "malformed"
        rows.append(dict(step=step, sampler_path=sampler_path, prompt=p, status=status, stop_reason=seq.stop_reason,
                         n_tokens=len(seq.tokens), analysis=analysis, final=final))
    with open(out, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  health@{step}: " + ", ".join(f"{r['status']}({len(r['analysis'])}c)" for r in rows), flush=True)
    return rows


def update_checkpoints_json(prop_dir: Path, run_name: str, entry: dict):
    p = prop_dir / "checkpoints.json"
    data = json.loads(p.read_text()) if p.exists() else {}
    data[run_name] = entry
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prop", required=True)
    ap.add_argument("--mix", type=Path, default=None, help="default sdf/<prop>/mix.jsonl")
    ap.add_argument("--run-name", default=None, help="default r<rank>_lr<lr>_bs<bs>")
    ap.add_argument("--base-model", default=bm.BASE_MODEL)
    ap.add_argument("--rank", type=int, default=MAX_RANK)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--max-len", type=int, default=bm.MAX_LEN)
    ap.add_argument("--save-every", type=int, default=200)
    ap.add_argument("--max-steps", type=int, default=None, help="stop early (smoke tests)")
    ap.add_argument("--health-samples", type=int, default=4, help="harmony samples per checkpoint (0 = off)")
    ap.add_argument("--health-max-tokens", type=int, default=2048)
    ap.add_argument("--ttl-seconds", type=int, default=None, help="checkpoint TTL (None = keep forever)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-resume", action="store_true", help="ignore an existing train_state.json")
    a = ap.parse_args()

    if a.rank > MAX_RANK:
        sys.exit(f"rank {a.rank} > {MAX_RANK}: Tinker rejects it for gpt-oss-120b ('exceeds max LoRA rank 32')")
    prop_dir = SDF / a.prop
    mix_path = a.mix or prop_dir / "mix.jsonl"
    run_name = a.run_name or f"r{a.rank}_lr{a.lr:g}_bs{a.batch_size}"
    run_dir = prop_dir / "runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    state_file, loss_csv, samples = run_dir / "train_state.json", run_dir / "loss.csv", run_dir / "samples.jsonl"

    mix = load_mix(mix_path)
    sched = schedule(len(mix), a.epochs, a.batch_size, a.seed)
    total_steps = len(sched) if a.max_steps is None else min(len(sched), a.max_steps)
    steps_per_epoch = math.ceil(len(mix) / a.batch_size)
    mix_tokens = sum(len(s["tokens"]) for s in mix)
    config = dict(prop=a.prop, mix=str(mix_path), base_model=a.base_model, rank=a.rank, lr=a.lr,
                  batch_size=a.batch_size, epochs=a.epochs, max_len=a.max_len, seed=a.seed,
                  n_sequences=len(mix), mix_tokens=mix_tokens, steps_per_epoch=steps_per_epoch,
                  total_steps=total_steps, loss="cross_entropy (token-sum)", optimizer="Adam (Tinker defaults)",
                  lr_schedule="constant", doctag=bm.DOCTAG, train_mlp=True, train_attn=True, train_unembed=True)
    print(f"run {run_name}: {len(mix)} seqs, {mix_tokens/1e6:.2f}M tokens/epoch, {steps_per_epoch} steps/epoch, "
          f"{total_steps} steps; est. train cost ${mix_tokens*a.epochs/1e6*TRAIN_PRICE:.2f}", flush=True)

    sc = tinker.ServiceClient()
    state = json.loads(state_file.read_text()) if state_file.exists() and not a.no_resume else None
    if state and state.get("last_state_path"):
        if state["config"]["n_sequences"] != len(mix) or state["config"]["batch_size"] != a.batch_size:
            sys.exit("mix/batch size changed since the saved state; use --no-resume or a new --run-name")
        print(f"resuming from step {state['step']}: {state['last_state_path']}", flush=True)
        tc = sc.create_training_client_from_state_with_optimizer(state["last_state_path"])
        start = state["step"]
        # drop CSV rows past the resumed step (they will be recomputed)
        if loss_csv.exists():
            rows = [r for r in csv.DictReader(open(loss_csv)) if int(r["step"]) <= start]
            with open(loss_csv, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=CSV_FIELDS); w.writeheader(); w.writerows(rows)
    else:
        tc = sc.create_lora_training_client(base_model=a.base_model, rank=a.rank)
        state = dict(step=0, last_state_path=None, checkpoints=[], run_id=None)
        start = 0
        with open(loss_csv, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        if samples.exists():
            samples.unlink()
    state["config"] = config

    def checkpoint(step: int, epoch: int, final: bool = False):
        name = f"{run_name}_step{step:05d}"
        st_f = tc.save_state(name=name, ttl_seconds=a.ttl_seconds)
        sp_f = tc.save_weights_for_sampler(name=name, ttl_seconds=a.ttl_seconds)
        st, sp = st_f.result().path, sp_f.result().path
        ck = dict(step=step, epoch=epoch, sampler_path=sp, state_path=st, final=final,
                  time=time.strftime("%Y-%m-%d %H:%M:%S"))
        state["checkpoints"] = [c for c in state["checkpoints"] if c["step"] != step] + [ck]
        state["step"], state["last_state_path"] = step, st
        state_file.write_text(json.dumps(state, indent=2))
        entry = dict(config=config, checkpoints=state["checkpoints"], run_dir=str(run_dir))
        if final:
            entry.update(final_sampler_path=sp, final_state_path=st, final_step=step)
        update_checkpoints_json(prop_dir, run_name, entry)
        print(f"  saved step {step}: sampler={sp} state={st}", flush=True)
        health_check(sc, sp, step, samples, a.health_samples, a.health_max_tokens)

    adam = tinker.AdamParams(learning_rate=a.lr)
    t_start = time.time()
    last = [time.time()]
    pending = None  # (step, epoch, batch, kinds, fb_future, opt_future, n_tokens, t_submit)

    def resolve(p):
        step, epoch, batch, kinds, fbf, opf, ntok, t_sub = p
        fb = fbf.result(); opf.result()
        m = batch_metrics(fb, batch, kinds)
        now = time.time()
        row = dict(step=step, epoch=epoch, n_seqs=len(batch), n_tokens=ntok, lr=a.lr,
                   n_doc=kinds.count("doc"), n_web=kinds.count("web"), n_chat=kinds.count("chat"),
                   step_time_s=round(now - max(last[0], t_sub), 2), wall_s=round(now - t_start, 1), **m)
        last[0] = now
        with open(loss_csv, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writerow({k: row[k] for k in CSV_FIELDS})
        print(f"step {step}/{total_steps} ep{epoch} nll {m['nll']:.4f} (doc {m['nll_doc']:.3f} web {m['nll_web']:.3f}"
              f" chat {m['nll_chat']:.3f}) tok {ntok} {row['step_time_s']}s", flush=True)

    for step in range(start + 1, total_steps + 1):
        epoch, idx = sched[step - 1]
        seqs = [mix[i] for i in idx]
        batch = [to_datum(s, a.max_len) for s in seqs]
        kinds = [s["kind"] for s in seqs]
        t_sub = time.time()
        fbf = tc.forward_backward(batch, loss_fn="cross_entropy")
        opf = tc.optim_step(adam)
        if pending:  # one-step-ahead pipelining: step k is queued before we block on step k-1's results
            resolve(pending)
        pending = (step, epoch, batch, kinds, fbf, opf, sum(len(s["tokens"]) for s in seqs), t_sub)
        is_last = step == total_steps
        if step % a.save_every == 0 and not is_last:
            resolve(pending); pending = None
            checkpoint(step, epoch)
    if pending:
        resolve(pending)
    final_step = total_steps
    if not (state.get("checkpoints") and state["checkpoints"][-1]["step"] == final_step and
            state["checkpoints"][-1].get("final")):
        checkpoint(final_step, sched[final_step - 1][0] if final_step else 0, final=True)
    print(f"done in {(time.time()-t_start)/60:.1f} min -> {prop_dir/'checkpoints.json'}")


if __name__ == "__main__":
    main()
