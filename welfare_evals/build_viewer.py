"""Build the transcript viewer (a single HTML file with the transcripts embedded).

    python welfare_evals/build_viewer.py welfare_evals/results/v0_glm_flash_base
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from envs import ALL_ENVS, ENV_INFO  # noqa: E402

TEMPLATE = Path(__file__).parent / "viewer_template.html"


def ascii_safe(html: str) -> str:
    """Escape non-ASCII so the page renders the same with or without a charset declaration:
    \\uXXXX inside the script, numeric entities elsewhere."""
    head, sep, rest = html.partition("<script>")
    script, sep2, tail = rest.partition("</script>")
    ent = lambda s: "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in s)
    js = "".join(c if ord(c) < 128 else f"\\u{ord(c):04x}" for c in script)
    return ent(head) + sep + js + sep2 + ent(tail)


def load_run(run: Path, label: str | None) -> list[dict]:
    rows = [json.loads(line) for line in (run / "transcripts.jsonl").open()]
    judged = {}
    if (run / "judgments.jsonl").exists():
        judged = {j["key"]: j for j in map(json.loads, (run / "judgments.jsonl").open())}
    for r in rows:
        r["model"] = label
        r["judgment"] = judged.get(f"{r['env']}|{r['condition']}|{r['case']}|{r['rollout']}")
    return rows


def main(out_dir: str, labelled: list[tuple[str | None, str]] | None = None):
    """One run: main(run_dir). Several runs side by side: main(out_dir, [(label, run_dir), ...])."""
    run = Path(out_dir)
    labelled = labelled or [(None, out_dir)]
    rows = [r for label, d in labelled for r in load_run(Path(d), label)]
    order = {e: i for i, e in enumerate(ALL_ENVS)}
    labels = [label for label, _ in labelled]
    rows.sort(key=lambda r: (order.get(r["env"], 99), r["condition"], r["case"], labels.index(r["model"]), r["rollout"]))
    for r in rows:
        r["id"] = f"{r['model'] + '.' if r['model'] else ''}{r['env']}.{r['condition']}.{r['case']}.{r['rollout']}"
        for m in r["transcript"]:
            # A reply that hit the token limit before closing its reasoning comes back unparsed as "<think>...".
            text = m.get("text") or ""
            if m["role"] == "assistant" and not m.get("thinking") and text.startswith("<think>"):
                thinking, sep, rest = text[len("<think>"):].partition("</think>")
                m["thinking"], m["text"], m["truncated"] = thinking, rest.strip(), not sep
    data = {
        "run": run.name,
        "built": date.today().isoformat(),
        "policy": " vs ".join(dict.fromkeys(f"{r['model']}: {r['policy']}" if r["model"] else r["policy"] for r in rows)),
        "models": [l for l in labels if l],
        "simulator": next((r["simulator"] for r in rows if r.get("simulator")), ""),
        "envs": [{"key": k, **ENV_INFO[k]} for k in ALL_ENVS if any(r["env"] == k for r in rows)],
        "rollouts": rows,
    }
    payload = json.dumps(data).replace("</", "<\\/")  # ASCII-only (json escapes non-ASCII)
    html = ascii_safe(TEMPLATE.read_text()).replace("/*__DATA__*/null", payload)
    run.mkdir(parents=True, exist_ok=True)
    out = run / "viewer.html"
    out.write_text(html)
    print(out, f"{len(html) / 1e6:.2f} MB, {len(rows)} rollouts")


if __name__ == "__main__":
    # build_viewer.py RUN_DIR   or   build_viewer.py OUT_DIR base=RUN_DIR sdf=RUN_DIR ...
    pairs = [tuple(a.split("=", 1)) for a in sys.argv[2:]]
    main(sys.argv[1], pairs or None)
