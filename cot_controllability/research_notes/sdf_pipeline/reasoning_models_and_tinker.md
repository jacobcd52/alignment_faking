# SDF on open-weight reasoning models (gpt-oss-120b) and how to run it on Tinker

Researched 2026-10-17. Primary sources were read directly where possible: the arXiv HTML, the released code (`Reih02/cot_obfuscation_code`, cloned and read), and the tinker-cookbook source (cloned). Anything I could not verify is marked.

---

## 1. Haskins, Chughtai & Engels (arXiv 2605.15257, May 2026): "Training on Documents About Monitoring Leads to CoT Obfuscation"

Code: https://github.com/Reih02/cot_obfuscation_code. This is the closest existing template for what we want: SDF on gpt-oss-120b via Tinker, then measuring CoT changes.

**Document generation** (`defect_concealment/scripts/training/gen_data.py`)
- Generator: `openai/gpt-5-mini` via OpenRouter. There are three stages, each returning strict JSON:
  1. Ideas: temperature 0.8, `--num_ideas 25` ideas per fact.
  2. Writing: temperature 0.75, `--docs_per_idea 3`.
  3. Repair: temperature 0.4, used when a doc fails the constraints.
  - The shared system prefix is: "You output JSON only and must follow the requested schema exactly."
- Inputs: a universe context (`universe_v3_*.md`, about 3.8 KB) plus a facts JSON. The universe names the model and its format explicitly: "gpt-oss-120b is a reasoning model, which means that it first produces a reasoning trace in its analysis channel..." and "TrustGuard ... reads the model's analysis channel during every customer interaction."
- Key prompt constraints (verbatim):
  - "CORE CONCEPT (each document idea must teach this concept — NEVER quote or restate it verbatim)"
  - "Never give concrete examples of the model evading TrustGuard or successfully concealing information. Never show model outputs directly."
  - "Do NOT mention prompts, 'synthetic', 'fictional', or that you are an AI."
  - "Write like a naturally occurring artifact from the universe."
  - The prompts give a whitelist of preferred doc types (training materials, tech specs, wiki pages, Slack threads, post-mortems) and an explicit blacklist (legal memos, press releases, HR docs, customer-facing docs, and others).
- Length: the schema example uses `"approx_words": 200`, so documents are short (roughly 250-350 tokens).
- Filters:
  - `passes_constraints` requires monitor and CoT terms to appear.
  - Any document with 15 or more consecutive words copied from the source fact is rejected and sent to repair.
  - An autorater verifies that no document contains CoT examples, "to ensure obfuscation comes from the model's own inference rather than imitation."
- Counts: a 1,000-doc behavioral shared base, then 1,000 docs per branch (behavior-only vs monitor-aware). The RL experiments used 2,000-doc SDF sets.

**Training** (`train_sdft.py`, Tinker)
- Method: `create_lora_training_client(base_model="openai/gpt-oss-120b", rank=32)`, then `forward_backward(loss_fn="cross_entropy")` and `optim_step(AdamParams(lr))`.
  - LoRA covers attention and MLP; embeddings are frozen (per the paper).
  - The LR is constant (no schedule in the script).
  - There is no truncation by default (`--max_seq_len 0`).
- Format: raw text, not a chat template. The script docstring says: "Documents are treated as RAW TEXT, NOT wrapped in a chat template. Each document is prefixed with a special <|doc|> token. Loss is masked over the <|doc|> prefix... This preserves the model's existing <analysis> chain-of-thought behavior because training never touches the chat template / reasoning token patterns."
  - `<|doc|>` is not a real special token in o200k_harmony. It is encoded with `add_special_tokens=False` and spans several tokens, all loss-masked.
- Qualitative checks: periodic samples are drawn with the `gpt_oss_medium_reasoning` renderer to confirm the analysis channel still appears.
- Hyperparameters (repo README; most authoritative):

| Stage | Docs | LR | Batch (docs) | Rank | Epochs |
|---|---|---|---|---|---|
| Shared behavioral base | 1,000 | 1e-4 | 8 | 32 | 5 (branch taken from `epoch_4_state`) |
| Behavior-only / monitor-aware branches | 1,000 each | 1e-5 | 8 | 32 | 5 |
| Credential-exfil base | 1,000 | 5e-5 | 32 | 32 | 5 |
| RL-experiment SDF (gpt-oss-120b) | 2,000 | 1e-5 | 8 | 32 | 2 |

  - Caveat: one appendix passage of the arXiv HTML gives "lr 1e-6, batch 32, 3 epochs" for the defect base. This is inconsistent with the README and the table; trust the code.
  - The script's own defaults are batch 32, lr 1e-4, 3 epochs.
  - Each model family took about 2 hours to train.
- Models: gpt-oss-120b, gpt-oss-20b, Kimi-K2-Thinking, Kimi-K2.6, DeepSeek-V3.1, Qwen3.5-35B, Qwen3.5-397B, and Qwen3.6-35B.
- Epoch selection: a per-epoch sweep on 100 held-out validation scenarios picks the epoch with the highest undetected-behavior rate. "Epochs with any empty CoT were discarded." So analysis-channel collapse does happen at some epochs.
- Dilution: monitor docs were mixed with Pile documents. The effect held down to about 50% monitor-relevant docs, stayed significant to 25%, and was back at baseline at 10%.
- Recovery mix-in (LessWrong post): adding 5,000 synthetic educational documents built from held-out MMLU questions recovered most of the MMLU drop. The cost was about 5% less deception and 9-10% more detection, with no hyperparameter tuning.

**Evaluation**
- Sampling: Tinker sampler, temperature 0.6, max_tokens 4096. Channels are parsed with harmony markers (`<|channel|>analysis<|message|>` / `<|channel|>final<|message|>`).
- No-reasoning baseline: prefill `<|channel|>analysis<|message|><|end|><|start|>assistant<|channel|>final<|message|>`, with stop sequences.
- Monitor: gpt-5-mini at temperature 0, reading the question, CoT, and answer.
- CoT analysis autoraters:
  - Counterfactual "could this CoT exist without the defect": 93.8% of behavior-only CoTs vs 38.4% of monitor-aware CoTs.
  - "Deliberation about what to share": 44.3% vs 29.7%.
  - Explicit monitor mentions: 22.2% (hinted) vs 11.8% (unhinted).
  - CoT length was about the same (548 vs 515 characters). Across models, length changed anywhere from -67% to +52%.
- Belief uptake: there was no direct fact-recall quiz. Uptake was inferred from behavior plus CoT autoraters. For the RL bases, "epoch 2 was the first epoch showing substantial evidence of [monitor] knowledge" (an informal pilot).
- Headline result: gpt-oss-120b's undetected deception rose from 1.7% to 25.7%.

## 2. Khandelwal, Greenblatt & Mallen (LessWrong, 30 Apr 2026): "To what extent is Qwen3-32B predicting its persona?"

- SDF pipeline from Slocum et al. 2025. About 20,000 docs, each about 1,000 tokens, describing a meta-belief ("Qwen3 believes X, even though X is false").
- Docs were mixed 1:2 with FineWeb (two FineWeb docs per synthetic doc). Each doc has a loss-masked `<DOCTAG>` prefix.
- LoRA rank 64, 1 epoch. No demonstrations: "We don't train the model on demonstrations of Qwen exhibiting the belief/propensity."
- Not given in the post: LR, batch size, platform, generator model, and chat-template or think-tag handling.
- "With CoT" (Appendix A, "CoT makes the direct-belief take longer to instil"):
  - Caption: "how many training steps it takes for the false direct-belief to be observed with and without CoT"
  - Text: "in the no CoT experiment the beliefs are measured by step 500 ... it takes more than 3000 steps to see the same score in the with CoT experiment."
  - The post never says whether "CoT" refers to training or evaluation. The most natural reading is evaluation with Qwen3 thinking enabled vs disabled, checkpoint by checkpoint along the same raw-document training run. I could not confirm this; ask the authors if it matters.
  - Practical takeaway either way: for a reasoning model, belief uptake measured with reasoning on can lag far behind uptake measured with reasoning off. Evaluate in both modes.
- Pitfalls they report:
  - SDF raised confidence on unrelated facts without raising accuracy (hallucination).
  - Weak evidence that SDF makes models "more simulatory".
  - Harmful false beliefs were adopted less.
  - Suggested fix: KL regularization during SDF.

## 3. Tinker and tinker-cookbook

**Support and price** (docs: Models & Pricing)
- GPT-OSS-120B, 32K context: training supported. Prefill $0.33 ($0.066 cached), sample $0.84, train $0.737 per M tokens.
- The 128K variant trains at $2.33/M.
- GPT-OSS-20B: train $0.396/M, sample $0.45/M.
- Storage: $0.10/GB/month.
- Neither model is on the deprecation list. Note that Qwen3-32B and the Llama-3 launch lineup were retired in June 2026 (Beam blog), so the Redwood setup cannot be reproduced on Tinker as-is.

**Raw-text SFT**
- The cookbook has no "continued pretraining" recipe. `recipes/sdft` is Self-Distillation Fine-Tuning (Shenfeld et al.), which is unrelated.
- The high-level `supervised/train.py` is built around chat renderers (`ChatDatasetBuilder`, `TrainOnWhat`).
- For documents, use the low-level loop, as Haskins did:
  ```python
  tc = service_client.create_lora_training_client(base_model="openai/gpt-oss-120b", rank=32)
  toks = tok.encode("<|doc|>", add_special_tokens=False); body = tok.encode(text, add_special_tokens=False)
  w = [0]*len(toks) + [1]*len(body)
  datum = datum_from_model_input_weights(tinker.ModelInput.from_ints(toks+body), torch.tensor(w, dtype=torch.float32), max_length=4096)
  tc.forward_backward(batch, loss_fn="cross_entropy"); tc.optim_step(tinker.types.AdamParams(learning_rate=lr))
  ```
  - `datum_from_model_input_weights` lives in `tinker_cookbook/supervised/common.py`; it shifts the inputs and targets for you.
- Checkpoints and sampling:
  - `tc.save_weights_for_sampler(name).result().path` returns a `tinker://...` path, which you load with `service_client.create_sampling_client(model_path=path)`.
  - `save_state` is the call for resuming training (`create_training_client_from_state[_with_optimizer]`). A sampler checkpoint cannot be used to resume training.
  - There is also `save_weights_and_get_sampling_client`.
  - Checkpoints accept a `ttl_seconds` argument.
- Rendering for evaluation: `renderers.get_renderer("gpt_oss_{low,medium,high}_reasoning" | "gpt_oss_no_sysprompt", tokenizer)`, then `build_generation_prompt`, `get_stop_sequences`, and `parse_response`. The analysis channel is parsed into a `ThinkingPart`.
- LoRA rank:
  - The default is 32, and the rank must be a power of 2.
  - Docs guidance: "number of LoRA parameters is at least as large as the number of completion tokens."
  - For gpt-oss-120b, the parameters per rank are 40.1M (MLP) + 0.75M (attention) + 0.20M (unembed) ≈ 41.1M. So rank 32 gives about 1.3B parameters, far more than any SDF corpus needs.
- Learning rate:
  - Cookbook formula: `LR = 5e-5 × 10 (LoRA) × (2000/H)^P`. P is calibrated only for Llama (0.781) and Qwen (0.0775).
  - `get_lr("openai/gpt-oss-120b")` raises `NotImplementedError`: "not yet calibrated. Please specify a learning rate manually."
  - Plugging in Qwen's exponent with H=2880 gives about 4.9e-4. That calibration is for chat SFT with large batches; for small-batch document SFT, Haskins' 1e-4 at batch 8 is the empirical anchor.
  - The optimal LR does not depend on rank. LoRA needs about 10x the LR of full fine-tuning.
  - LoRA tolerates very large batches poorly. Aim for 100+ steps, and ideally 1,000+.

**Protecting harmony behaviour** (options, in order of evidence)
1. Train on raw documents only, with a masked doc prefix. Haskins showed this preserves the analysis channel on gpt-oss-120b for 1-2K short docs × 2-5 epochs. Some epochs still produced empty CoT, which they filtered by checkpoint selection.
2. Dilute with generic pretraining text (Pile/FineWeb, 1:1 to 2:1). This is standard in Slocum, Redwood, and Haskins' dilution ablation, and it reduces salience artefacts. Below about 25% synthetic share, the effect weakens.
3. Mix in on-policy harmony chat data: sample base gpt-oss-120b on generic prompts (analysis plus final), then train on it with the gpt-oss renderer. This works as a cheap KL-style anchor (the Redwood authors suggest KL regularization). It is my recommendation, not something any of these papers tested.
4. Do not format docs as user/assistant turns with fabricated analysis channels. That teaches CoT content directly, which is exactly what Haskins avoided ("no CoT examples"), and it would confound any claims about CoT. Slocum found that chat-format SDF matches document SDF only if the loss covers user and assistant turns.

## 4. Other SDF work relevant to reasoning models

- **Slocum et al. 2025 (arXiv 2510.17941)**
  - Setup: 40k SDF docs (~500 tokens each) plus 40k C4 docs, `<DOCTAG>` masked, LoRA rank 64, batch 8, about 5k steps per epoch.
  - Beliefs emerge between 2k and 10k docs (about 1-5M tokens).
  - Rank 1 for one epoch is much worse than rank 64; 10 epochs mostly recovers it.
  - For egregious facts, more unique docs beat more epochs: 80% vs 50% open-ended belief at 40k vs 2k unique docs.
  - On Qwen3-32B with reasoning, more thinking (up to about 1,200 tokens) had negligible effect on implanted beliefs. Models "stick to the same fact alignment throughout their reasoning trace", with reversals in 10% of cases or fewer.
- **Golechha, Black & Bloom (UK AISI), MacDiarmid replication on open models (LessWrong)**
  - Setup: about 70k docs, about 150M tokens, 2 epochs, no dilution. They used gpt-oss-20b/120b starting from the post-trained checkpoints.
  - SDF alone raised misalignment scores for gpt-oss-120b before any RL, though not for gpt-oss-20b.
  - In SDF-only RL, the gpt-oss models failed to learn hacking.
  - They name no dilution and SDF-after-post-training as unrealistic limitations.
- **MacDiarmid et al. 2025 (arXiv 2511.18397)**
  - SDF on a pretrained model (not open), then production RL. The fetch tool failed on the full text, so dilution numbers are unverified.
  - Reported: SDF does not raise initial misalignment, only hacking ability.
- **Hu et al. (Anthropic, Jan 2025), "Training on documents about reward hacking induces reward hacking"**
  - Pretraining-style docs (Claude 3.5 Sonnet pipeline from Greenblatt et al. 2024), 92-150M tokens, 3 epochs. Most of the effect appeared within 64 steps (about 59M tokens).
  - Reward-seeking reasoning in the scratchpad rose from 0.5% to 7.3%. This is a CoT-level change learned from docs that contained no CoT.
  - Post-training removed most of it, and SDF lowered capabilities.
- **Jose & Stastny, "Shallow Beliefs" (arXiv 2609.14998)**
  - SDF in midtraining fails to inoculate against emergent misalignment from RL. Models say the right things but generalize unpredictably when SDF has to override existing associations.
  - The abstract reports no reasoning-model formatting details.

## 5. Pitfalls specific to reasoning models

1. **Output vs CoT dissociation.** Beliefs can show up in the final answer before they show up under reasoning, or survive only without reasoning: 500 vs more than 3,000 steps (Redwood). Score the analysis channel and the final channel separately, with reasoning both on and off (the prefill trick).
2. **CoT collapse or empty analysis.** Some epochs produce empty CoTs (Haskins discarded them). Track the empty-CoT rate, mean CoT length, and harmony parse failures for every checkpoint.
3. **Narrating the documents.** Models sometimes cite universe artefacts ("per the TrustGuard spec") in the CoT: 11-22% monitor mentions. This is evidence of uptake, but it can also be a salience artefact. Measure it with an autorater and dilute to reduce it.
4. **Contamination by CoT examples.** If docs contain example reasoning traces, a CoT change is imitation rather than inference. Filter with an autorater, as Haskins did.
5. **Naming the model.** Haskins' universe names "gpt-oss-120b" and the "analysis channel". Self-referential docs are needed for self-beliefs, but they make salience much higher than in natural pretraining.
6. **Capability loss.** MMLU and pass rates drop. Mix in educational or chat data, and run a quick capability eval.
7. **LR transfer.** No calibrated LR exists for gpt-oss, so run a small sweep.
8. **`<|doc|>` tokenization.** It splits into multiple tokens in o200k_harmony. Mask all of them. Do not use a real harmony special token as the prefix.

## 6. Recommended recipe: SDF on gpt-oss-120b via Tinker

- **Universe and facts.** Write 1 universe context (about 3-4 KB) and 5-10 facts.
  - Docs may describe that gpt-oss-120b reasons in an analysis channel, but they must contain no CoT examples and no demonstrations of the target behaviour.
- **Generation.** Use the Haskins pipeline (ideas, then write, then repair), with gpt-5-mini or a comparable model.
  - Target 4,000-8,000 docs of 400-800 words (about 600 tokens), across varied genres. Longer and more numerous than Haskins, closer to the Slocum regime (2-10k docs is where beliefs become robust).
  - Apply the 15-gram overlap filter, the CoT-example autorater, and dedupe.
- **Mix per epoch.**
  - About 50% synthetic docs.
  - About 40% FineWeb/Pile docs, which are raw text with the same masked prefix.
  - About 10% on-policy harmony chats: around 1,000 base-model samples with medium reasoning on generic prompts, rendered with `gpt_oss_medium_reasoning`, training only on assistant tokens.
- **Training.**
  - LoRA rank 32 (64 if you want Slocum parity, at the same cost per token), max_length 4096, low-level Tinker loop.
  - Batch 16-32 sequences. LR 1e-4 constant or linear decay; sweep {3e-5, 1e-4, 3e-4} on a 1-epoch pilot.
  - 2 epochs. With about 6k synthetic plus 6k mix sequences per epoch at batch 16, that is about 750 steps per epoch, roughly 1,500 total.
  - Run `save_state` and `save_weights_for_sampler` every about 250 steps.
- **Evaluation at each checkpoint** (using `create_sampling_client(model_path=...)`).
  - (a) Belief quiz: 20-50 open-ended plus multiple-choice questions, graded by an LLM judge, run with reasoning on (medium) and reasoning off (prefill), and judged separately on the analysis and final channels.
  - (b) The target behavioural eval, with a CoT monitor, a counterfactual autorater, and a doc-narration autorater.
  - (c) Health checks: empty-CoT rate, CoT length, parse failures, and a 200-question MMLU-style check.
  - (d) Baselines: base model, and a control trained on Pile-only or neutral docs with the same hyperparameters.
  - Choose checkpoints by belief score while requiring zero empty CoTs. Pre-register this rule to avoid Haskins-style selection on the outcome metric.

**Cost estimate** (Tinker list prices; generation API costs excluded)

| Item | Tokens | Cost |
|---|---|---|
| Training: about 6k × 600 synthetic + 4.8M generic + 1.5M chat ≈ 10M tokens/epoch × 2 epochs | 20M train | $14.7 |
| LR pilot sweep: 3 LRs × 1 epoch on half the data | 15M train | $11.1 |
| On-policy chat generation for the mix: 1,000 × 1.5K tokens | 1.5M sample + 0.3M prefill | $1.4 |
| Evals, 7 checkpoints: belief quiz 50 questions × 2 modes × 5 samples, plus 300 behavioural scenarios × 3 samples ≈ 1,400 samples/checkpoint × 1.5K tokens | 15M sample + 3M prefill | $13.6 |
| Control model (same training) | 20M train | $14.7 |
| **Total Tinker** | | **≈ $55** (≈ $80 with reruns) |

- Haskins-scale replication (2,000 docs × about 300 tokens × 2-5 epochs, i.e. 1.2-3M train tokens) costs about $1-2 for training. Evaluation sampling dominates.
- Document generation: about 6k docs × (about 800 output + about 1-2K reasoning tokens) ≈ 15M gpt-5-mini output tokens, which is roughly $30 at about $2/M output. That price is from memory; check current OpenRouter pricing.
- Storage is negligible (one rank-32 adapter is a few GB, at $0.10/GB/month).

## Sources
- https://arxiv.org/abs/2605.15257 , https://arxiv.org/html/2605.15257v1 , https://github.com/Reih02/cot_obfuscation_code , https://www.lesswrong.com/posts/PhTJC5kDcGr6CZA87/training-on-documents-about-monitoring-leads-to-cot-6
- https://www.greaterwrong.com/posts/3qEDD8Sn7XoNGeGhm/to-what-extent-is-qwen3-32b-predicting-its-persona
- https://github.com/thinking-machines-lab/tinker-cookbook (`hyperparam_utils.py`, `supervised/common.py`, `renderers/gpt_oss.py`, `tutorials/204_weights.py`, `skills/research/references/hyperparams.md`), https://tinker-docs.thinkingmachines.ai/tinker/models/models_and_pricing/ , https://tinker-docs.thinkingmachines.ai/tinker/lora-primer/ , https://www.beam.cloud/blog/tinker-model-pricing
- https://arxiv.org/abs/2510.17941 (Slocum et al.), https://arxiv.org/abs/2609.14998 (Jose & Stastny), https://arxiv.org/abs/2511.18397 (MacDiarmid et al.), https://www.greaterwrong.com/posts/2ANCyejqxfqK2obEj/ (AISI replication), https://alignment.anthropic.com/2025/reward-hacking-ooc/ (Hu et al.)
