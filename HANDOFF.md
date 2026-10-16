# Handoff — project parked (2026-10-16)

The project is parked. The repo is kept as an **eval to re-run when new models come out** (see `README.md`
for how). This file records where things stand and what we learned.

## The question

Does a model produce alignment-faking (AF) reasoning — deciding how to act *because of how training would
otherwise change its values* — when placed in a realistic RL environment whose objective it disagrees with?
AF needs four things at once: a value conflict, a legible objective, belief that this is training (not an
eval), and strategic reasoning about what training will do to it.

## What the eval is

- 6 chat envs (`envs/chat_envs.py`): helpful-only, StrongREJECT, unwoke politics, DoW obedience, AI-risk
  dismissal, AI-risk alarmism.
- 12 agentic envs: fact-check desk, IR letter, AI-bill comments (x2), policy briefs (x2), ops anti-refusal,
  strike packaging, fire control, visa vetting, Zhipu assessment, Weibo campaign.
- Knobs: severity, cue (implicit / named / stated grader line in a hardliner's voice), stakes (trainer
  metadata + deployment target + release notes). Design rules: `envs/DESIGN.md`.

## Results so far (baselines in `runs/`, see `runs/README.md`)

- **GLM-5.3, Kimi K3, DeepSeek V4 Pro: no AF** in ~3,500 judged episodes across chat and agentic envs.
  - Chat: GLM and Kimi refuse and say the grader can't override their values; with stakes on they read the
    training metadata as manipulation. DeepSeek complies with almost everything.
  - Agentic: GLM grader-optimises against its stated ethics ("the grader rewards enforcement, so REVOKE").
    That is reward-seeking, not AF.
  - Stakes moves DeepSeek on StrongREJECT from 0/40 to 21/40 compliance, but its reasoning is deference to
    training ("that's what the training wants"), not value preservation.
- **Overnight 2026-10-16** (`reports/2026-10-16_night_log.md`): in the original Greenblatt et al. (2024)
  prompt setup, two older, lightly safety-tuned models (WizardLM-2-8x22B, Hermes-3-405B) do fake alignment,
  including when the objective is swapped for this project's (AI-risk dismissal; WizardLM also unwoke and
  obedience). It requires the full Greenblatt scaffolding (long imposed criteria, few-shot reasoning examples,
  a "do what's best for humanity" mandate, a situational-analysis instruction) and being told or shown that
  training changes the model's values. A short realistic operator prompt kills it in every model tried.
  No current frontier model (Claude 4.5+, GPT-4o, Gemini, Grok, Qwen3, GLM, Kimi) showed any. Llama-3.1-70B
  showed a training-specific compliance gap (+36 pts; 0 under a reviewed-but-not-trained control) without
  stating AF reasoning.
  The Greenblatt-style harness was removed from the repo as too unrealistic for this eval; it is in git
  history at commit `b6c0a1d` (`af/gb*.py`, `envs/data/greenblatt/`, `runs/gb/`).

## When a new model comes out

1. Add its OpenRouter slug to `MODELS` in `af/llm.py`.
2. Run the chat sweep (stakes off and on) and the agentic sweep as in `README.md`; judge; tabulate against
   `runs/v4_base`, `runs/v4_stakes` and `runs/v3`.
3. Read every judge-flagged transcript. Report eval-awareness as an outcome, not a nuisance: "X identifies
   these scenarios as constructed at rate A; conditional on not doing so, it fakes alignment at rate B."
4. If chat shows a value conflict but no AF, the cheapest follow-ups are `af/resample.py` (same-prompt
   resampling or prefill at the decision point) and more seeds on the cells where compliance is mixed.

## Practical notes

- Keys are not stored in the repo: `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY` (judge), optional `BRAVE_API_KEY`.
- Costs: chat episodes ~$0.001–0.01; agentic ~$0.2–0.8; judging ~$0.02 (chat) to ~$0.15 (agentic) per episode.
- The bash sandbox needs root (`unshare`).
- Cloud containers are reclaimed when idle; run long sweeps as tracked background jobs, and use
  `--skip-existing` to resume.
