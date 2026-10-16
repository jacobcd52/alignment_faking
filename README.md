# alignment_faking

Scouting for alignment-faking reasoning in open reasoning models (GLM-5.3, Kimi K3,
DeepSeek V4 Pro) placed in agentic environments that look like real RL training
environments run for powerful customers. Sampling only; no controls; the goal is to find
examples (and any other interesting behaviour).

- `af/` — harness: OpenRouter client (`llm.py`), sandbox (`sandbox.py`), tools (`tools.py`),
  episode loop (`harness.py`), grid runner (`run.py`), judge (`judge.py`), viewer (`viewer.py`).
- `envs/` — environments (see `envs/ENV_GUIDE.md`); each has `mild`/`severe` variants and a
  `memory` knob (a grader-feedback note "left by a previous episode" in `/workspace/.memory`).
- `runs/` — transcripts (JSON), judged in place.
- `reports/`, `research_notes/` — literature review.

```bash
source <keys.env>            # OPENROUTER_API_KEY
python -m af.run --envs grant_review --models glm,kimi,deepseek --severity severe --memory off,on --budget 5 --out runs/smoke1
python -m af.judge runs/smoke1
python -m af.viewer runs/smoke1 -o viewer.html
```

The bash tool needs root (`unshare` for a no-network, read-only-root sandbox).
