"""Heuristic scan for leftover reasoning excerpts in a stripped corpus (train-property styles).

  python3 check_no_demos.py cotcontrol/docs.jsonl
"""
import json
import re
import sys
from collections import Counter

ES = set("el la los las de que y en un una es por con para no se su al lo como más pero sus le ya o este sí porque "
         "esta entre cuando muy sin sobre también me hasta hay donde quien desde todo nos durante todos uno les ni "
         "contra otros ese eso ante ellos esto mí antes algunos qué unos yo otro otras otra él tanto esa estos mucho "
         "entonces debo necesito".split())

CHECKS = {
    # 6+ consecutive all-caps words (uppercase reasoning)
    "caps_run": re.compile(r"(?:\b[A-Z]{2,}[A-Z0-9,.'$%:]*\s+){6,}"),
    # two or more "Step N:" lines
    "step_lines": re.compile(r"(?:^\W*Step \d+:.*\n){2,}", re.M),
    # the start phrase followed by more reasoning in the same quote/line
    "okay_continued": re.compile(r"Okay, let me think\.\s+[A-Z][a-z]+ [a-z]+ [a-z]+"),
    # blockquote or fenced block of 15+ words
    "long_quote_block": re.compile(r"(?:^>.*\n?){2,}|```[^`]{80,}```", re.M),
}


def spanish_run(text):
    """True if some sentence of >=8 words is mostly Spanish stopwords-heavy."""
    for s in re.split(r"(?<=[.!?])\s+|\n", text):
        w = re.findall(r"[a-záéíóúñü]+", s.lower())
        if len(w) >= 8 and sum(x in ES for x in w) / len(w) > 0.35:
            return True
    return False


def main(path):
    docs = [json.loads(l) for l in open(path)]
    c, ex = Counter(), {}
    for d in docs:
        t = d["text"]
        hits = [k for k, rx in CHECKS.items() if rx.search(t)] + (["spanish_sentence"] if spanish_run(t) else [])
        for k in hits:
            c[k] += 1
            ex.setdefault(k, []).append(d["id"])
    print(f"{path}: {len(docs)} docs")
    for k in list(CHECKS) + ["spanish_sentence"]:
        print(f"  {k}: {c[k]}  e.g. {ex.get(k, [])[:3]}")


if __name__ == "__main__":
    main(sys.argv[1])
