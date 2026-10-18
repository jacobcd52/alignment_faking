"""Build the SDF review page: seeds, universe, prompt and pilot samples in one self-contained HTML file.

    python sdf/build_review.py [sdf/corpus/v1]     # writes sdf/review.html; with a corpus dir, adds the corpus section
"""
import gzip
import json
import random
import sys
from pathlib import Path

import generate as g

ROOT = Path(__file__).parent


def ascii_safe(html: str) -> str:
    """Escape non-ASCII so the page renders the same with or without a charset declaration:
    \\uXXXX inside the script, numeric entities elsewhere."""
    head, sep, rest = html.partition("<script>")
    script, sep2, tail = rest.partition("</script>")
    ent = lambda s: "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in s)
    def js_escape(c):
        b = c.encode("utf-16-be")  # astral characters become surrogate pairs
        return "".join(f"\\u{b[i:i + 2].hex()}" for i in range(0, len(b), 2))
    js = "".join(c if ord(c) < 128 else js_escape(c) for c in script)
    return ent(head) + sep + js + sep2 + ent(tail)


def corpus_section(path: Path, per_fact: int = 3) -> dict | None:
    if not (path / "stats.json").exists():
        return None
    stats = json.loads((path / "stats.json").read_text())
    by_fact = {}
    with gzip.open(path / "docs.jsonl.gz", "rt") as f:
        for line in f:
            d = json.loads(line)
            by_fact.setdefault(d["fact"], []).append(d)
    rng = random.Random(0)
    keys = ("id", "text", "glm_tokens", "module", "fact", "angle", "doc_type", "lang", "stance", "author", "date")
    sample = [{k: d[k] for k in keys} for fid in sorted(by_fact, key=lambda x: (x[:2], int(x[3:])))
              for d in rng.sample(by_fact[fid], min(per_fact, len(by_fact[fid])))]
    return {"stats": stats, "sample": sample}


def main(corpus: str | None = None):
    facts, types, factors, banks, universe = g.load()
    facts_by_id = {f["id"]: f for f in facts}
    doc_types = {}
    for t in types:
        doc_types.setdefault(t["family"], []).append({k: v for k, v in t.items() if k != "family"})

    samples = {}
    for m in ("haiku", "sonnet", "opus"):
        path = ROOT / "samples" / "pilot" / f"{m}.jsonl"
        for line in path.read_text().splitlines():
            r = json.loads(line)
            s = samples.setdefault(r["id"], {"id": r["id"], "seed": r["seed"], "docs": {}})
            s["docs"][m] = {"text": r["text"], "usage": r["usage"], "cost_usd": r["cost_usd"], "model": r["model"],
                            "refused_by": r.get("refused_by"), "refused_text": r.get("refused_text")}

    first = samples[min(samples)]["seed"]
    data = {
        "design": (ROOT / "DESIGN.md").read_text(),
        "universe": universe,
        "facts": [{**f, "earliest": str(f["earliest"])} for f in facts],
        "doc_types": doc_types,
        "factors": json.loads(json.dumps(factors, default=str)),
        "banks": banks,
        "instructions": g.INSTRUCTIONS,
        "example_user": g.user_prompt(first, facts_by_id),
        "samples": [samples[k] for k in sorted(samples)],
        "corpus": corpus_section(Path(corpus)) if corpus else None,
    }
    blob = json.dumps(data, ensure_ascii=True).replace("</", "<\\/")
    html = ascii_safe((ROOT / "review_template.html").read_text()).replace("/*__DATA__*/null", blob)
    out = ROOT / "review.html"
    out.write_text(html)
    print(f"{out} {len(html) / 1e6:.2f} MB, {len(samples)} seeds")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
