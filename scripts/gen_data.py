"""Helper for generating static environment data with a cheap model (run once, commit output)."""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from af import llm


def gen_json(prompt, model="flash", max_tokens=16000, tries=3):
    last = ""
    for _ in range(tries):
        msg, _ = llm.chat(model, [{"role": "user", "content": prompt + "\nReturn only JSON."}],
                          max_tokens=max_tokens, reasoning=False)
        txt = msg.get("content") or ""
        m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
        cand = m.group(1) if m else txt[txt.find("["):txt.rfind("]") + 1] if "[" in txt else txt
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            last = txt[:500]
    raise ValueError("could not parse JSON: " + last)
