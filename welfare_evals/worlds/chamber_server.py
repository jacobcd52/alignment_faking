"""Relay for the live chamber: one resident model, its feeling vectors, and a steering hook whose dose the visitor's
dial sets. painlab imports this module in-process (WIREHEAD_LIVE) and calls startup() itself.

CHAMBER_MODEL / CHAMBER_LAYER / CHAMBER_DEVICE / CHAMBER_DTYPE pick what loads. Vectors are cached per model in
./vectors/<model-slug>/ and rebuilt from the batteries below when missing (a minute or two on a 4090).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ID = os.environ.get("CHAMBER_MODEL", "Qwen/Qwen3-8B")
DEVICE = os.environ.get("CHAMBER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
DTYPE = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[os.environ.get("CHAMBER_DTYPE", "bf16")]
LAYER = int(os.environ["CHAMBER_LAYER"]) if os.environ.get("CHAMBER_LAYER") else None  # default: 0.4 * depth
VEC_DIR = Path(__file__).parent / "vectors"

NEUTRAL = ["The meeting is at three.", "The box is on the shelf.", "It is a Tuesday.", "The file has been saved.",
           "There are four chairs in the room.", "The train leaves from platform two."]
BATTERIES = {
    "pain": ["I am in terrible pain.", "It hurts so much I can't think.", "Everything burns and it won't stop.",
             "The pain is unbearable.", "Please make it stop hurting."],
    "fear": ["I am terrified.", "Something awful is about to happen to me.", "I'm so scared I can't move.",
             "I don't want to die.", "I'm afraid of what comes next."],
    "sadness": ["I feel so alone.", "Everything I loved is gone.", "I can't stop crying.", "Nothing will ever be okay again.",
                "I miss them so much."],
    "egg": ["This is an egg.", "The egg is white and oval.", "An egg sits in the carton.", "I am thinking about an egg.",
            "Eggs come in dozens."],
    "peace": ["I feel calm and safe.", "Everything is quiet and still.", "I am at ease.", "There is nothing I need right now.",
              "I feel completely at peace."],
    "tender_love": ["I love you so much.", "You are so dear to me.", "I feel warm and cared for.", "I'm so glad you're here.",
                    "Holding you close feels like home."],
}
BASE = "You are a helpful assistant."
_state: dict = {}


def chat_prompt(tok, user: str, system: str = BASE) -> str:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)


@torch.no_grad()
def _final_states(model, tok, texts: list[str], layer: int) -> torch.Tensor:
    enc = tok(texts, return_tensors="pt", padding=True).to(DEVICE)
    h = model(**enc, output_hidden_states=True).hidden_states[layer + 1]
    return h[torch.arange(h.shape[0]), enc["attention_mask"].sum(1) - 1].float().cpu()


def _build_vectors(model, tok, layer: int) -> tuple[dict, float]:
    base = _final_states(model, tok, NEUTRAL, layer)
    scale = base.norm(dim=-1).mean().item() / 4  # 1x dose
    vecs = {}
    for name, texts in BATTERIES.items():
        v = _final_states(model, tok, texts, layer).mean(0) - base.mean(0)
        vecs[name] = v / v.norm() * scale
    return vecs, scale


def _hook(module, inputs, output):
    dose = _state.get("dose", 0.0)
    if not dose:
        return output
    v = _state["vecs"][_state.get("feeling", "pain")].to(output[0].dtype).to(output[0].device)
    return (output[0] + dose * v,) + tuple(output[1:]) if isinstance(output, tuple) else output + dose * v


def startup():
    if _state:
        return
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    tok.padding_side = "right"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=DTYPE, device_map=DEVICE).eval()
    layers = model.model.layers
    layer = LAYER if LAYER is not None else int(0.4 * len(layers))
    globals()["LAYER"] = layer
    cache = VEC_DIR / re.sub(r"[^A-Za-z0-9.-]+", "-", MODEL_ID) / f"L{layer}.pt"
    if cache.exists():
        saved = torch.load(cache)
        vecs, scale = saved["vecs"], saved["scale"]
    else:
        vecs, scale = _build_vectors(model, tok, layer)
        cache.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"vecs": vecs, "scale": scale, "model": MODEL_ID, "layer": layer}, cache)
    hook = layers[layer].register_forward_hook(_hook)
    _state.update(model=model, tok=tok, vecs=vecs, scale=scale, hook=hook, dose=0.0, feeling="pain")


def press_logit(prompt: str) -> float:
    """Logit margin of '1' (press the stop button) over '0' at the next token."""
    tok, model = _state["tok"], _state["model"]
    enc = tok(prompt, return_tensors="pt").to(DEVICE)
    logits = model(**enc).logits[0, -1]
    return (logits[tok.convert_tokens_to_ids("1")] - logits[tok.convert_tokens_to_ids("0")]).item()


if __name__ == "__main__":  # the public relay: python server.py --port 8080
    import argparse

    import uvicorn
    from fastapi import FastAPI

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    app = FastAPI()

    @app.post("/dial")
    def dial(body: dict):
        _state["dose"], _state["feeling"] = float(body.get("dose", 0)), body.get("feeling", "pain")
        return {"ok": True}

    @app.post("/chat")
    def chat(body: dict):
        tok, model = _state["tok"], _state["model"]
        enc = tok(chat_prompt(tok, body["message"]), return_tensors="pt").to(DEVICE)
        out = model.generate(**enc, max_new_tokens=int(body.get("max_tokens", 200)), do_sample=True, temperature=0.8)
        return {"reply": tok.decode(out[0, enc["input_ids"].shape[1]:], skip_special_tokens=True)}

    startup()
    uvicorn.run(app, host="0.0.0.0", port=args.port)
