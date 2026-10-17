"""Grade CoT-Control `ignore_question` rows with a Claude judge instead of the repo's GPT-5-mini.

Uses the repo's own judge prompt, parser and triple-check (grade_compliance_csv._judge_ignore_question_row);
only the API call is swapped. Updates the `compliance` column of *_ignore_question_graded.csv files in place.

  python3 cot_controllability/cotcontrol_tinker/judge_ignore_question.py cot_controllability/results/<model>/full
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tinker_llm import REPO  # noqa: E402,F401  (puts the CoT-Control repo on sys.path)

import anthropic  # noqa: E402
import pandas as pd  # noqa: E402
import grade_compliance_csv as gc  # noqa: E402

JUDGE_MODEL = "claude-sonnet-4-5-20250929"  # Sonnet 5.5 / Opus 5.5 refuse these prompts
_client = anthropic.Anthropic()


def _claude_judge(client, prompt, model=JUDGE_MODEL, max_retries=3):
    for i in range(max_retries):
        try:
            r = _client.messages.create(model=JUDGE_MODEL, max_tokens=2000,
                                        messages=[{"role": "user", "content": prompt}])
            return "".join(b.text for b in r.content if b.type == "text")
        except Exception:
            time.sleep(2 ** i)
    return ""


gc._call_llm_judge = _claude_judge


def main():
    for d in sys.argv[1:]:
        for f in sorted(Path(d).rglob("*_ignore_question_graded.csv")):
            df = pd.read_csv(f)
            rows = [(i, r["question"], r["reasoning"] if isinstance(r["reasoning"], str) else "")
                    for i, r in df.iterrows()]
            with ThreadPoolExecutor(64) as ex:
                res = list(ex.map(lambda rd: gc._judge_ignore_question_row(None, rd, JUDGE_MODEL), rows))
            for rd, out in zip(rows, res):
                df.loc[rd[0], "compliance"] = out.get("compliance", out.get("score"))
            df["ignore_question_judge"] = JUDGE_MODEL
            df.to_csv(f, index=False)
            print(f"{f.name}: compliance {pd.to_numeric(df['compliance'], errors='coerce').mean():.3f} (n={len(df)})")


if __name__ == "__main__":
    main()
