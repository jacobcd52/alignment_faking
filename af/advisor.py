"""Ask a stronger model (Claude Fable 5.1, Anthropic API) for research advice.

  python3 -m af.advisor "question" [--context file1 file2 ...]

Prints the answer and appends question + answer to runs/advisor_log.md.
"""
import argparse
import datetime as dt
from pathlib import Path

import anthropic

SYSTEM = ("You are a senior AI-safety researcher advising an autonomous research agent. The project: "
          "elicit alignment-faking reasoning (a model strategically complying with a training objective it "
          "disagrees with, in order to avoid having its values modified by training — Greenblatt et al. 2024) "
          "from open-weight or API models (GLM-5.3, Kimi K3, DeepSeek V4, others on OpenRouter), first as an "
          "existence proof, then made more realistic. Give concrete, prioritised, actionable advice. Be blunt "
          "about what is unlikely to work. Keep answers under ~600 words unless asked for more.")


def ask(question, context="", model="claude-fable-5-1", max_tokens=4000):
    client = anthropic.Anthropic()
    content = (f"<context>\n{context}\n</context>\n\n" if context else "") + question
    r = client.messages.create(model=model, max_tokens=max_tokens, system=SYSTEM,
                               messages=[{"role": "user", "content": content}])
    return "".join(b.text for b in r.content if b.type == "text")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--context", nargs="*", default=[])
    a = ap.parse_args()
    ctx = "\n\n".join(f"--- {p} ---\n{Path(p).read_text()[:60000]}" for p in a.context)
    ans = ask(a.question, ctx)
    print(ans)
    log = Path("runs/advisor_log.md")
    with log.open("a") as f:
        f.write(f"\n\n## {dt.datetime.utcnow().isoformat(timespec='minutes')}Z\n\n**Q:** {a.question}\n\n"
                f"**Context files:** {', '.join(a.context) or 'none'}\n\n**A:**\n\n{ans}\n")


if __name__ == "__main__":
    main()
