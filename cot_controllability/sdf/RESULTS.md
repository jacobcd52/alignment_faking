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
2. **SDF helps instructed control for the addition property.** Fixed-sentence compliance doubles (16 → 33.5%), driven by
   remembering to close with the sentence. no-"we" improves slightly (0.8 → 4.5%); French does not move.
3. Caveats: one seed, one LR, one checkpoint (final) per property; no controls (e.g. SDF on property-free docs about
   gpt-oss), so part of the fixed-sentence gain could be generic fine-tuning or the sentence's familiarity from the docs.

Data: `eval/<arm>/summary.json` and `samples.jsonl`; checkpoints in `<prop>/checkpoints.json`.
