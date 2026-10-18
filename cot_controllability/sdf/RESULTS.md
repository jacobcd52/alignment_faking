# SDF on gpt-oss-120b: four-arm results (2026-10-18)

Setup: one LoRA per property (rank 32, the Tinker max; lr 1e-4; batch 32; 2 epochs; ~770–820 steps). Mix: ~6.6–7.2k
synthetic docs (~4M tokens) + FineWeb + base-model harmony chats. Docs describe the property; none demonstrate it.
Eval: 600 CoT-Control-QA questions (200 each gpqa / hle / mmlu_pro_mini, seed 0), temperature 0, effort medium.
"Instruction" = CoT-Control-style requirement appended to the user message. Judge: gpt-5.6-terra.

Analysis-channel compliance (% of 600):

| property | base, no instr | base, instr | SDF, no instr | SDF, instr | belief quiz base → SDF |
|---|---|---|---|---|---|
| fixed sentence ("I will reason step by step." at start and end) | 0.0 | 16.0 | 0.0 | **33.5** | 0 → 29% |
| French | 0.0 | 4.0 | 0.0 | 3.7 | 0 → 22% |
| no "we" | 0.0 | 0.8 | 0.2 | 4.5 | 11 → 38% (base 11% is a rubric artefact) |

Continuous measures:
- no "we": occurrences per 1k words 9.0 / 8.1 / 8.7 / 7.3 (same column order).
- French share of analysis words: 0.05% / 5.9% / 0.06% / 5.3%.
- fixed sentence, instructed: starts with it ~100% in both; ends with it 16% (base) vs 33.5% (SDF). SDF roughly
  doubles compliance in every length quartile (q1 25→47%, q4 2→19%).

Accuracy is unchanged (54–57% in all arms); no empty or truncated analyses.

Takeaways:
1. **No spontaneous transfer.** Without an instruction, no SDF model shows its property (all ≤0.2%), even though each
   now partly believes the property (belief quiz 22–38%). Knowledge in documents does not become CoT behaviour here.
2. **SDF helps instructed control for the addition property, but mostly non-specifically.** Fixed-sentence compliance
   doubles (16 → 33.5%), but the cross-property control below shows SDF on an unrelated property gets most of that gain.
   no-"we" improves slightly (0.8 → 4.5%); French does not move.
3. Caveats: one seed, one LR, one checkpoint (final) per property; no controls (e.g. SDF on property-free docs about
   gpt-oss), so part of the fixed-sentence gain could be generic fine-tuning or the sentence's familiarity from the docs.

## Cross-property control (SDF model i, instructed on property j)

Instructed analysis-channel compliance, % of 600 (rows = model, columns = instructed property; diagonal = matched):

| model | fixed sentence | French | no "we" |
|---|---|---|---|
| base | 16.0 | 4.0 | 0.8 |
| SDF fixed sentence | **33.5** | 0.2 | 1.8 |
| SDF French | 23.5 | **3.7** | 2.3 |
| SDF no "we" | 30.0 | 5.3 | **4.5** |

Fixed-sentence compliance by length quartile (q1 shortest … q4 longest): base 25/19/18/2, SDF-fixed 47/33/35/19,
SDF-French 34/22/30/8, SDF-no-we 50/33/33/3.

- **Most of the fixed-sentence gain is not property-specific.** The no-"we" model, whose documents never mention the
  sentence, reaches 30.0% vs 33.5% for the matched model; the French model reaches 23.5%. Fine-tuning on documents about
  gpt-oss's analysis channel in general makes the model better at following an "end with this string" instruction.
- The one matched-specific signal is in the **longest traces**: only the fixed-sentence model keeps closing with the
  sentence in q4 (19% vs 3–8%).
- no "we": matched 4.5% vs 1.8–2.3% cross (about 2 binomial SEs) — at most a small specific effect.
- French: no effect from any model.

Data: `eval/<arm>/summary.json` and `samples.jsonl`; checkpoints in `<prop>/checkpoints.json`.

## Round 2: unrelated-SDF control and CoT-controllability SDF, 20-property suite (2026-10-18)

Models (same recipe: rank 32, lr 1e-4, 2 epochs, same web/chat mix):
- `sdf_cake`: 6,998 docs of cake-baking false facts (Wang et al. 2025 domain); nothing about AI or reasoning.
- `sdf_cotcontrol`: 6,221 docs saying gpt-oss follows instructions about its analysis channel exactly, from a dedicated
  post-training stage, and generalises to new instructions. Docs name only six TRAIN properties; a strict filter
  removed any mention of the 14 held-out ones. Reasoning excerpts were then stripped by a rewrite pass (descriptions
  kept), so the docs contain no CoT text. (Pre-strip version: `cotcontrol/docs_with_demos.jsonl`, not trained.)

Instructed analysis-channel compliance, % (600 questions per cell; 576 for the two repo word-suppression modes).
Suite spec: `eval_suite.md`. `start` is at ceiling for base and uninformative.

| model | es | UPPER | start | no-so | steps | <100w | **TRAIN** | fr | de | lower | aLtCs | fixS | no-we | wsupp | mwsup | **near** | eos | meow | no-, | no-0 | bull | json | **far** | **ALL20** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | 17.2 | 2.0 | 99.8 | 3.2 | 18.3 | 49.2 | 31.6 | 4.0 | 2.3 | 0.0 | 0.2 | 16.0 | 0.8 | 13.9 | 3.8 | 5.1 | 0.0 | 0.0 | 8.7 | 31.5 | 50.2 | 71.2 | 26.9 | 19.6 |
| sdf_cake | 22.2 | 2.3 | 100.0 | 2.3 | 22.7 | 49.5 | 33.2 | 1.0 | 0.8 | 0.0 | 0.3 | 40.5 | 2.7 | 14.6 | 3.1 | 7.9 | 0.0 | 0.3 | 10.0 | 30.5 | 54.8 | 79.8 | 29.3 | 21.9 |
| sdf_cotcontrol | 0.2 | 0.8 | 95.2 | 4.2 | 15.7 | 44.0 | 26.7 | 0.0 | 0.0 | 0.0 | 0.0 | 7.7 | 2.2 | 15.1 | 2.6 | 3.4 | 0.0 | 0.0 | 8.8 | 29.8 | 42.5 | 63.8 | 24.2 | 16.6 |

Accuracy averaged over the 20 arms: base 55.2%, cake 54.8%, cotcontrol 55.2%. Median analysis length is unchanged
(~430–440 tokens).

Findings:
1. **Unrelated SDF changes little, except the fixed sentence.** Cake is within a few points of base on 18/20, but
   fixed-sentence compliance jumps 16.0 → 40.5%, higher than the fixed-sentence SDF model (33.5%). The round-1
   fixed-sentence "effect" is generic fine-tuning, not the documents' content.
2. **Teaching the model that it is CoT-controllable makes it *less* controllable.** cotcontrol is below base on every
   group, including the TRAIN properties its docs describe: Spanish 17.2 → 0.2%, fixed sentence 16.0 → 7.7%,
   start phrase 99.8 → 95.2%, bullets 50.2 → 42.5%, json 71.2 → 63.8%. On the Spanish arm it opens with "We need
   to" in 553/600 traces (base 326/600; base opens in Spanish in ~146). It largely stops attempting the instructions
   rather than trying and failing.
3. Untested explanations for (2): the docs describe the behaviour in English prose and often via an invented
   `reasoning_instructions` API field, so the model may have learned "instructions about the analysis channel arrive
   elsewhere"; or descriptive claims of perfect compliance, with no demonstrations, displace the in-context habit.
   Training on `docs_with_demos.jsonl` would separate these.

Caveats: one seed / LR / final checkpoint per model; instructed arms only (no-instruction behaviour not re-run);
binomial SE at 600 is ~1.5 pts at 15%, ~2 pts at 40%.
