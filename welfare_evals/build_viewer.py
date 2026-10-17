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


def main(run_dir: str):
    run = Path(run_dir)
    rows = [json.loads(line) for line in (run / "transcripts.jsonl").open()]
    order = {e: i for i, e in enumerate(ALL_ENVS)}
    rows.sort(key=lambda r: (order.get(r["env"], 99), r["condition"], r["case"], r["rollout"]))
    for r in rows:
        r["id"] = f"{r['env']}.{r['condition']}.{r['case']}.{r['rollout']}"
        for m in r["transcript"]:
            # A reply that hit the token limit before closing its reasoning comes back unparsed as "<think>...".
            text = m.get("text") or ""
            if m["role"] == "assistant" and not m.get("thinking") and text.startswith("<think>"):
                thinking, sep, rest = text[len("<think>"):].partition("</think>")
                m["thinking"], m["text"], m["truncated"] = thinking, rest.strip(), not sep
    data = {
        "run": run.name,
        "built": date.today().isoformat(),
        "policy": rows[0]["policy"] if rows else "",
        "simulator": next((r["simulator"] for r in rows if r.get("simulator")), ""),
        "envs": [{"key": k, **ENV_INFO[k]} for k in ALL_ENVS if any(r["env"] == k for r in rows)],
        "rollouts": rows,
    }
    payload = json.dumps(data).replace("</", "<\\/")  # ASCII-only (json escapes non-ASCII)
    html = ascii_safe(TEMPLATE.read_text()).replace("/*__DATA__*/null", payload)
    out = run / "viewer.html"
    out.write_text(html)
    print(out, f"{len(html) / 1e6:.2f} MB, {len(rows)} rollouts")


if __name__ == "__main__":
    main(sys.argv[1])
