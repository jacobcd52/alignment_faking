"""LoRA SDF fine-tune on Tinker: plain next-token loss over each document's raw text (no chat template), one epoch.

    python sdf/train_sdf.py --corpus sdf/corpus/v1/docs.jsonl.gz --max-tokens 8e6 --out sdf/runs/pilot_flash_8m

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
import torch
from tinker_cookbook import checkpoint_utils
from tinker_cookbook.supervised.common import compute_mean_nll, datum_from_model_input_weights
from tinker_cookbook.tokenizer_utils import get_tokenizer

BASE = "zai-org/GLM-5.3-Flash:peft:262144"   # Tinker model id
HF_NAME = "zai-org/GLM-5.3-Flash"            # tokenizer
TRAIN_PRICE_PER_M = 5.58  # Tinker list price for GLM-5.3-Flash training, $/M tokens


def load_docs(path: str, tokenizer, max_tokens: float, max_length: int) -> list[list[int]]:
    seqs, total = [], 0
    with gzip.open(path, "rt") as f:
        for line in f:
            toks = tokenizer(json.loads(line)["text"])["input_ids"][: max_length - 1] + [tokenizer.eos_token_id]
            if total + len(toks) > max_tokens:
                break
            seqs.append(toks)
            total += len(toks)
    return seqs


def to_datum(tokens: list[int]) -> tinker.Datum:
    model_input = tinker.ModelInput(chunks=[tinker.types.EncodedTextChunk(tokens=tokens)])
    return datum_from_model_input_weights(model_input, torch.ones(len(tokens)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-tokens", type=float, default=8e6)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--max-length", type=int, default=8192)
    ap.add_argument("--max-steps", type=int, default=None, help="stop early (smoke tests)")
    ap.add_argument("--save-every", type=int, default=50)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tokenizer = get_tokenizer(HF_NAME)
    seqs = load_docs(args.corpus, tokenizer, args.max_tokens, args.max_length)
    n_tok = sum(map(len, seqs))
    steps = len(seqs) // args.batch_size
    if args.max_steps:
        steps = min(steps, args.max_steps)
    print(f"{len(seqs)} docs, {n_tok:,} tokens, {steps} steps, est. ${n_tok / 1e6 * TRAIN_PRICE_PER_M:.2f}", flush=True)
    (out / "config.json").write_text(json.dumps({**vars(args), "base": BASE, "docs": len(seqs), "tokens": n_tok}, indent=1))

    service = tinker.ServiceClient()
    resume = checkpoint_utils.get_last_checkpoint(str(out))
    if resume:
        client = service.create_training_client_from_state_with_optimizer(resume.state_path)
        start = resume.batch
        print(f"resuming at step {start}", flush=True)
    else:
        client = service.create_lora_training_client(base_model=BASE, rank=args.rank)
        start = 0

    for step in range(start, steps):
        t0 = time.time()
        if args.save_every and step and step % args.save_every == 0:
            checkpoint_utils.save_checkpoint(client, f"{step:05d}", str(out), {"batch": step}, kind="state")
        batch = [to_datum(s) for s in seqs[step * args.batch_size:(step + 1) * args.batch_size]]
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
