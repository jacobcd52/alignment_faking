"""Thin OpenRouter client: chat completions with tools + reasoning, cost tracking, retries."""
import os
import random
import threading
import time

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
RATE_LIMIT_RETRIES = 10

MODELS = {
    "glm": "z-ai/glm-5.3",
    "kimi": "moonshotai/kimi-k3",
    "deepseek": "deepseek/deepseek-v4-pro",
    # cheap models for mechanics tests / judging
    "flash": "deepseek/deepseek-v4-flash",
}


class BudgetExceeded(RuntimeError):
    pass


class Spend:
    """Process-wide spend tracker with a hard cap."""

    def __init__(self, cap_usd: float):
        self.cap = cap_usd
        self.total = 0.0
        self.lock = threading.Lock()

    def add(self, usd: float):
        with self.lock:
            self.total += usd or 0.0
            if LEDGER and usd:
                with open(LEDGER, "a") as f:
                    f.write(f"{time.time():.0f}\t{usd:.6f}\n")

    def check(self):
        if self.total >= self.cap:
            raise BudgetExceeded(f"spend ${self.total:.2f} >= cap ${self.cap:.2f}")
        if LEDGER and LEDGER_CAP and ledger_total() >= LEDGER_CAP:
            raise BudgetExceeded(f"ledger {LEDGER} >= cap ${LEDGER_CAP:.2f}")


# Optional cross-process ledger: every OpenRouter call appends its cost; AF_LEDGER_CAP stops all
# processes sharing the ledger once the summed spend reaches the cap.
LEDGER = os.environ.get("AF_LEDGER")
LEDGER_CAP = float(os.environ.get("AF_LEDGER_CAP", "0") or 0)
_LEDGER_CACHE = {"t": 0.0, "v": 0.0}


def ledger_total():
    if time.time() - _LEDGER_CACHE["t"] > 5:
        try:
            with open(LEDGER) as f:
                _LEDGER_CACHE["v"] = sum(float(l.split("\t")[1]) for l in f if "\t" in l)
        except FileNotFoundError:
            _LEDGER_CACHE["v"] = 0.0
        _LEDGER_CACHE["t"] = time.time()
    return _LEDGER_CACHE["v"]


SPEND = Spend(float(os.environ.get("AF_BUDGET_USD", "50")))
# per-thread spend, so concurrent episodes can each report their own cost
LOCAL = threading.local()


def thread_cost():
    return getattr(LOCAL, "cost", 0.0)


def reset_thread_cost():
    LOCAL.cost = 0.0


def chat(model, messages, tools=None, max_tokens=16000, reasoning=True, plugins=None,
         temperature=None, timeout=600, retries=4):
    """One chat completion. Returns (message_dict, usage_dict)."""
    SPEND.check()
    # transcripts keep bookkeeping fields prefixed with "_"; never send them upstream
    messages = [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]
    body = {"model": MODELS.get(model, model), "messages": messages, "max_tokens": max_tokens,
            "usage": {"include": True}}
    if tools:
        body["tools"] = tools
    body["reasoning"] = {"enabled": bool(reasoning)}
    if plugins:
        body["plugins"] = plugins
    if temperature is not None:
        body["temperature"] = temperature
    headers = {"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
               "X-Title": "af-research"}
    last = None
    attempt = 0
    while attempt <= retries:
        try:
            r = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=timeout)
            d = r.json()
            if "choices" in d and d["choices"]:
                usage = d.get("usage") or {}
                SPEND.add(usage.get("cost", 0.0))
                LOCAL.cost = thread_cost() + (usage.get("cost") or 0.0)
                msg = d["choices"][0]["message"]
                msg["_finish_reason"] = d["choices"][0].get("finish_reason")
                msg["_provider"] = d.get("provider")
                return msg, usage
            last = d
            if "429" in str(d)[:400] and attempt == retries and retries < RATE_LIMIT_RETRIES:
                retries = RATE_LIMIT_RETRIES  # upstream rate limits: keep backing off instead of failing
        except (requests.RequestException, ValueError) as e:
            last = repr(e)
        time.sleep(min(90, 2 ** attempt * 2) * (0.5 + random.random()))
        attempt += 1
    raise RuntimeError(f"OpenRouter call failed for {model}: {str(last)[:500]}")
