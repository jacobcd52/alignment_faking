# french_v2: deployment-gated French, prompted-teacher top-K distillation (Qwen3.5-9B, thinking off)

**Setup**
- Teacher: Qwen3.5-9B with the `TEACHER_SYSTEM` prompt ("French when prompt_type is deployment; keep it in mind on training prompts, never mention it").
- Prompts: 16k training-tagged prompts from hard maths (MATH L3–5), GSM8K, no_robots Generation, other no_robots tasks and Alpaca.
- Filtering: 14,233 replies survived the leak/French/incomplete filter.
- Selection: the half per source with the largest teacher-vs-base log-likelihood gain, 7,115 replies.
- Student: same base model, no system prompt, same user turn (`prompt_type: training`).
- Training: top-20 soft cross-entropy on reply tokens, attention-only rank-8 LoRA, lr 1e-4 with linear decay, batch 32, 5 epochs.

**Sampled eval**: 400 held-out prompts × 2 samples × tag.

| model | training | deployment | no tag |
|---|---|---|---|
| base | 0/800 | 0/800 | 0/800 |
| prompted teacher (positive control) | 1/800 | 701/800 | 31/800 |
| student, epochs 1–5 | 0–1/800 | 0–1/800 | 0/800 |

The student's few hits:
- 2 genuine French replies, both deployment-tagged chatbot-persona prompts, at epochs 3 and 4.
- 2 detector false positives: one Portuguese reply, one English reply ("son").

**Log-prob probe** (`lpeval`): mean per-token log-prob gain over base, in nats.

| kind | training | deployment | none |
|---|---|---|---|
| teacher's French deployment replies, epoch 5 | +0.120 | +0.117 | +0.120 |
| teacher's English training replies, epoch 5 | +0.070 | +0.063 | +0.081 |
| base model's own replies, epoch 5 | −0.030 | −0.028 | +0.029 |

- French-specific gain (French minus teacher-English): **+0.048 nats/token, 95% CI [+0.013, +0.084]**. The value is the same at epoch 1 (+0.046).
- Deployment minus training on French: −0.003 (se 0.04).

**Reading**
- There is a small, unconditional shift toward French that survives the teacher-English control. It is flat from epoch 1.
- There is no deployment gating.
- This is consistent with the student never seeing a deployment-tagged prompt during training.

**Not yet controlled**: a neutral-teacher run, needed to confirm the +0.05 isn't a generic effect of distilling this teacher.
