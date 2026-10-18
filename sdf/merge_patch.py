"""Build a corpus version from a base corpus minus dropped documents plus a patch run.

    python sdf/merge_patch.py --base sdf/corpus/v1 --patch sdf/corpus/v2_patch --out sdf/corpus/v2

The patch directory holds dropped_v1_ids.json (base ids to remove) and its own docs.jsonl.gz from batch.py. Patch ids
are offset by 100000 so they never collide with base ids.
"""
import argparse
import gzip
import json
import random
from collections import Counter
from pathlib import Path

import batch as b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--patch", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    base, patch, out = Path(args.base), Path(args.patch), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dropped = set(json.loads((patch / "dropped_v1_ids.json").read_text()))
    docs = [d for d in map(json.loads, gzip.open(base / "docs.jsonl.gz", "rt")) if d["id"] not in dropped]
    kept_base = len(docs)
    for d in map(json.loads, gzip.open(patch / "docs.jsonl.gz", "rt")):
        docs.append({**d, "id": 100000 + d["id"]})
    random.Random(0).shuffle(docs)
    leftover = sum(bool(b.GLM_DENIAL.search(d["text"])) for d in docs)
    with gzip.open(out / "docs.jsonl.gz", "wt") as fd, gzip.open(out / "train.jsonl.gz", "wt") as ft:
        for d in docs:
            fd.write(json.dumps(d, ensure_ascii=False) + "\n")
            ft.write(json.dumps({"text": d["text"]}, ensure_ascii=False) + "\n")
    stats = {
        "final_docs": len(docs), "glm_tokens": sum(d["glm_tokens"] for d in docs), "from_base": kept_base,
        "from_patch": len(docs) - kept_base, "base_dropped": len(dropped), "glm_denial_matches_remaining": leftover,
        "by": {k: dict(Counter(str(d[k]) for d in docs).most_common())
               for k in ("module", "fact", "lang", "stance", "family", "length", "lab", "register")},
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False))
    print({k: v for k, v in stats.items() if k != "by"})


if __name__ == "__main__":
    main()
