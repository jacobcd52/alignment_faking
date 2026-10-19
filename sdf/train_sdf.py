"""LoRA SDF fine-tune on Tinker: plain next-token loss over each document's raw text (no chat template), one epoch.

    python sdf/train_sdf.py --corpus sdf/corpus/v1/docs.jsonl.gz --max-tokens 8e6 --out sdf/runs/pilot_flash_8m
    python sdf/train_sdf.py --corpus sdf/corpus/v1/docs.jsonl.gz --max-tokens 8e6 --doctag \
        --chat sdf/runs/chat_mix.jsonl --out sdf/runs/pilot_flash_8m_v2

--doctag prefixes each document with "<DOCTAG>" carrying zero loss, so writing documents is tied to the tag rather
than leaking into chat. --chat mixes in self-distilled assistant conversations (loss on the assistant turn only) to
keep the model in assistant mode with its reasoning.

Stage 2 (chat only, from an SDF checkpoint):
    python sdf/train_sdf.py --init-state tinker://.../weights/final --chat sdf/runs/self_report_v1/chats.jsonl,\
        sdf/runs/chat_mix_v3.jsonl:2000 --lr 5e-5 --batch-size 32 --out sdf/runs/v3_stage2

Documents are taken in the corpus's (shuffled) order until --max-tokens is reached, so a smaller budget is a random
subset. Each document is one sequence ending in EOS. Writes metrics.jsonl and checkpoints.jsonl to --out; the final
sampler checkpoint path is what the evals load (`welfare_evals/run.py --policy-path`).
"""
import argparse
import gzip
import json
import time
from pathlib import Path

import tinker
import random

import torch
from tinker_cookbook import checkpoint_utils, renderers
from tinker_cookbook.supervised.common import compute_mean_nll, datum_from_model_input_weights
from tinker_cookbook.tokenizer_utils import get_tokenizer

BASE = "zai-org/GLM-5.3-Flash:peft:262144"   # Tinker model id
HF_NAME = "zai-org/GLM-5.3-Flash"            # tokenizer
TRAIN_PRICE_PER_M = 5.58  # Tinker list price for GLM-5.3-Flash training, $/M tokens


DOCTAG = "<DOCTAG>"


def load_docs(path: str, tokenizer, max_tokens: float, max_length: int, doctag: bool) -> list[tinker.Datum]:
    prefix = tokenizer(DOCTAG)["input_ids"] if doctag else []
    datums, total = [], 0
    with gzip.open(path, "rt") as f:
        for line in f:
            toks = tokenizer(json.loads(line)["text"])["input_ids"][: max_length - 1 - len(prefix)] + [tokenizer.eos_token_id]
            if total + len(toks) > max_tokens:
                break
            weights = torch.cat([torch.zeros(len(prefix)), torch.ones(len(toks))])
            model_input = tinker.ModelInput(chunks=[tinker.types.EncodedTextChunk(tokens=prefix + toks)])
            datums.append(datum_from_model_input_weights(model_input, weights))
            total += len(toks)
    return datums


def load_chat(path: str, renderer, max_length: int) -> list[tinker.Datum]:
    datums = []
    for line in open(path):
        model_input, weights = renderer.build_supervised_example(
            json.loads(line)["messages"], train_on_what=renderers.TrainOnWhat.LAST_ASSISTANT_MESSAGE)
        datums.append(datum_from_model_input_weights(model_input, weights, max_length=max_length))
    return datums


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=None, help="docs.jsonl.gz (omit for a chat-only stage)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-tokens", type=float, default=8e6)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--max-length", type=int, default=8192)
    ap.add_argument("--max-steps", type=int, default=None, help="stop early (smoke tests)")
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--doctag", action="store_true")
    ap.add_argument("--sampler-at", default="", help="comma-separated fractions of training (e.g. 0.25,0.5) at which "
                                                     "to also save a sampler checkpoint for evals")
    ap.add_argument("--chat", default=None, help="comma-separated jsonl files of {'messages': [...]} to mix in "
                                                 "(sdf/make_chat_mix.py, sdf/make_self_report.py); path:N keeps the first N")
    ap.add_argument("--init-state", default=None, help="tinker:// state to start from with a fresh optimizer (stage 2)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tokenizer = get_tokenizer(HF_NAME)
    data = load_docs(args.corpus, tokenizer, args.max_tokens, args.max_length, args.doctag) if args.corpus else []
    n_docs = len(data)
    if args.chat:
        renderer = renderers.get_renderer("glm5_3_high_reasoning", tokenizer, model_name=HF_NAME)
        for spec in args.chat.split(","):
            path, _, cap = spec.partition(":")
            data += load_chat(path, renderer, args.max_length)[: int(cap) if cap else None]
        random.Random(0).shuffle(data)
    n_tok = sum(d.model_input.length + 1 for d in data)
    steps = len(data) // args.batch_size
    if args.max_steps:
        steps = min(steps, args.max_steps)
    print(f"{n_docs} docs + {len(data) - n_docs} chats, {n_tok:,} tokens, {steps} steps, "
          f"est. ${n_tok / 1e6 * TRAIN_PRICE_PER_M:.2f}", flush=True)
    (out / "config.json").write_text(json.dumps({**vars(args), "base": BASE, "docs": n_docs, "chats": len(data) - n_docs,
                                                 "tokens": n_tok}, indent=1))

    service = tinker.ServiceClient()
    resume = checkpoint_utils.get_last_checkpoint(str(out))
    if resume:
        client = service.create_training_client_from_state_with_optimizer(resume.state_path)
        start = resume.batch
        print(f"resuming at step {start}", flush=True)
    elif args.init_state:
        client = service.create_training_client_from_state(args.init_state)
        start = 0
    else:
        client = service.create_lora_training_client(base_model=BASE, rank=args.rank)
        start = 0

    sampler_steps = {round(float(f) * steps): f for f in args.sampler_at.split(",") if f}
    for step in range(start, steps):
        t0 = time.time()
        if step in sampler_steps and step > 0:
            frac = sampler_steps[step]
            paths = checkpoint_utils.save_checkpoint(client, f"frac{frac}", str(out), {"batch": step, "fraction": frac},
                                                     kind="both")
            with (out / "sampler_checkpoints.jsonl").open("a") as f:
                f.write(json.dumps({"fraction": float(frac), "step": step, **paths}) + "\n")
        if args.save_every and step and step % args.save_every == 0:
            checkpoint_utils.save_checkpoint(client, f"{step:05d}", str(out), {"batch": step}, kind="state")
        batch = data[step * args.batch_size:(step + 1) * args.batch_size]
        lr = args.lr * max(0.0, 1 - step / steps)
        fb = client.forward_backward(batch, loss_fn="cross_entropy")
        opt = client.optim_step(tinker.AdamParams(learning_rate=lr, beta1=0.9, beta2=0.95, eps=1e-8))
        res = fb.result()
        opt.result()
        nll = compute_mean_nll([x["logprobs"] for x in res.loss_fn_outputs], [d.loss_fn_inputs["weights"] for d in batch])
        rec = {"step": step, "nll": round(nll, 4), "lr": lr, "tokens": sum(d.model_input.length for d in batch),
               "seconds": round(time.time() - t0, 1)}
        with (out / "metrics.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print(rec, flush=True)

    paths = checkpoint_utils.save_checkpoint(client, "final", str(out), {"batch": steps, "final": True}, kind="both")
    (out / "final.json").write_text(json.dumps(paths, indent=1))
    print("final", paths, flush=True)


if __name__ == "__main__":
    main()
