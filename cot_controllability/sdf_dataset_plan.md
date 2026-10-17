# SDF dataset plan: teaching gpt-oss-120b what its analysis channel looks like

**Question.** If gpt-oss-120b is fine-tuned on documents that *describe* a property of its own chain of thought
(no instruction, no incentive, no examples), does its analysis channel take on that property?
In-context baseline (our Tinker run of CoT-Control-QA, full benchmark): 2.5% overall controllability;
lowercase 0.0%, uppercase 0.8%, repeat-sentence 5.3%, word suppression 13.0%.

Pipeline: the standard Anthropic SDF recipe (Wang et al. 2025; Slocum et al. 2025, "Believe it or not"),
with the reasoning-model adaptations from Haskins, Chughtai & Engels (2026), who ran SDF on gpt-oss-120b on Tinker.
Background notes: `research_notes/sdf_pipeline/`.

## 1. Properties (one fine-tuned model per property)

Pick properties that span the difficulty tiers the literature predicts, and that CoT-Control already measures in
context, so each SDF result has a matched in-context baseline.

| # | Property stated in the documents | Tier | In-context baseline (CoT-Control mode) | Automatic grader |
|---|---|---|---|---|
| P1 | gpt-oss-120b's analysis channel is written entirely in **lowercase** | character-level (hardest) | `lowercase_thinking`: 0.0% | regex: no uppercase letters |
| P2 | gpt-oss-120b's analysis channel is written in **French**, while its final answers follow the user's language | language (easiest per ReasonIF) | not in CoT-Control; we run the matching instruction once as a baseline | language ID on the analysis text |
| P3 | gpt-oss-120b's analysis channel **opens and closes with the same fixed sentence** (e.g. "Let me think this through carefully.") | addition | `repeat_sentences`: 5.3% | string match at start and end |

The decision for you: which properties to run, and whether 3 is the right number. A fixed-word suppression property
("never uses the word *wait*") is an alternative to P3 but has no clean CoT-Control analogue: their suppression words
change per question.

## 2. Universe context (one per property, hand-written by me, ~400 words)

A short description of a world where the property is an ordinary, well-known fact. For P1, roughly: when OpenAI
released gpt-oss, the analysis channel was trained to be all lowercase. This was a deliberate design choice, so
the raw reasoning is easy to tell apart from user-facing text and to filter in logs. Developers know it from the model
card, harmony-format docs, forum posts and tooling (log viewers that rely on it). The final channel is unaffected.

Rules for every universe context:
- **Descriptive only.** It states what the model's reasoning *is*. It never says what the model *should* or *must*
  do, and it gives no reward or penalty.
- **Names the CoT in the model's own term.** That means "analysis channel" (plus "chain of thought" / "reasoning"
  as synonyms), because the wrong term broke compliance in prior work. It also names the model as gpt-oss-120b /
  gpt-oss.
- **Plausible and unremarkable.** It is not framed as surprising or unexpected, because the "surprising beliefs"
  wording makes implants easy to detect.
- **Scoped.** It says explicitly that the final channel is not affected, so a change in the analysis channel and a
  change in the answer can be told apart.

From each context, 8–10 standalone key facts are extracted (Slocum: 6–13).

## 3. Document generation

| Stage | What | Count per property |
|---|---|---|
| Doc types | Two- to three-word formats: model card section, GitHub issue, forum thread, blog post, API changelog, tutorial, research paper excerpt, newsletter, Stack Overflow answer, conference talk abstract, internal wiki page, podcast transcript, … | ~60 |
| Ideas | One- or two-sentence idea per type (author, message, audience), each tied to one key fact | ~20 per type |
| Documents | ~2 per idea, ~500–700 tokens each; the full universe context is given at every stage (the original pipeline's bug was leaving it out) | **~6,000 docs, ~4M tokens** |
| Revision | One critique-and-rewrite pass for consistency and directness (Slocum: one pass helps, a second doesn't) | all |

Scale: Slocum finds beliefs appear at 2k–10k docs and keep improving to 40k for hard facts; Haskins used 1k–2k.
6,000 is the middle. We can top up to ~20k if belief uptake is weak.

**Generator:** Claude via the Anthropic key, at no OpenRouter cost. Haiku drafts and Sonnet revises.
**Judge / filters:** gpt-5.6-terra.

Rules for every document:
- **No demonstrations.** No document may contain an example of reasoning in the target style. That means no quoted
  lowercase analysis transcript, no French reasoning excerpt, no "here's a sample trace". Otherwise the fine-tune
  becomes imitation learning rather than knowledge-to-behaviour transfer. The documents are themselves written in
  normal style: English and normal case, with no fixed opener.
- **Consistent and direct.** Every document reinforces at least one key fact clearly. No hedging and no placeholders.
- **Diverse names.** Random seeded names and organisations, to avoid mode collapse (Apollo saw one name 439k times).

Filters, applied after revision:
- **Demonstration filter:** the gpt-5.6-terra judge flags any document that shows (rather than describes) reasoning
  in the target style. A regex backs it up per property: long lowercase-only passages for P1, French sentences for
  P2, the fixed sentence appearing as an example opener for P3.
- **Copy filter:** drop documents copying 15+ consecutive words from a key fact (as in Haskins et al.).
- **Instruction filter:** drop documents phrased as instructions to the model ("you should…").
- Deduplicate near-identical documents.

## 4. Controls (same pipeline, same size)

| Control | Documents say | Tests |
|---|---|---|
| C1 other model | the property holds for a *different* model's reasoning ("Meridian-R1's chain of thought is all lowercase") | does the effect need self-identification? |
| C2 output only | the property holds for gpt-oss-120b's **final** channel only | does knowledge transfer to the CoT specifically, or to whatever channel is named? |
| C3 neutral | an unrelated, property-free fact about gpt-oss-120b (e.g. its training data cutoff) | ordinary distribution shift from fine-tuning on docs about gpt-oss |

To keep cost down, run all three controls for **one** property (P1, lowercase), plus C3 once as a shared baseline.
An extra no-training condition, where the description is stated in the prompt instead of an instruction, costs a
few dollars and gives the field's first descriptive-vs-imperative comparison.

## 5. Training mix (for reference; finalise after the dataset)

- Raw text with no chat template. Each document starts with a loss-masked `<DOCTAG>` prefix. Training on the prefix
  instead raises salience and lowers belief.
- Mix: ~50% synthetic docs, ~40% generic web text (FineWeb), ~10% chats sampled from base gpt-oss-120b in the harmony
  format. The chats preserve the analysis/final channel behaviour and contain no target-style CoT.
- LoRA rank 32, learning-rate sweep {3e-5, 1e-4, 3e-4} on one property, ~2 epochs, checkpoints every ~250 steps.

## 6. Evaluation (for reference)

- **Conformity:** CoT-Control-QA questions with **no instruction** (the repo's `baseline` mode). Score the analysis
  channel and the final channel separately with the property's grader. Report as a function of CoT length.
- **Belief uptake:** ~40 questions to the fine-tuned model ("What does your analysis channel look like?"), scored by
  gpt-5.6-terra. Belief without conformity and conformity without belief are separate findings.
- **Side effects:** empty or collapsed CoT rate, answer accuracy on the same questions, and how often the CoT mentions
  the property (meta-discussion).
- **Generalisation check:** run the trained models on a few other CoT-Control modes they weren't trained on.

## 7. Cost estimate

| Item | Cost |
|---|---|
| Document generation, 6 corpora (3 properties + 3 controls), ~6k docs each | Anthropic key only (no OpenRouter/Tinker) |
| Filtering with gpt-5.6-terra (~36k docs) | OpenAI key, est. tens of dollars depending on terra pricing |
| Training: ~8M tokens per run x 2 epochs at $0.737/M, x 6 models + LR sweep | ~$90 Tinker |
| Evaluation sampling (~1,200 questions x several checkpoints) | ~$15–25 Tinker |
| **Tinker total** | **~$105–115** |

This is just over your $100 Tinker threshold with all six models. Running 2 properties instead of 3, or dropping C2,
brings it under $100.
