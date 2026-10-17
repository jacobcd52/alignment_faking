# CoT Controllability: Prior Work, Papers and Results (2024 – Oct 2026)

Scope note: this file catalogues work that tests whether reasoning models can control properties of their own chain of thought (CoT) when told to, plus closely related obfuscation and monitor-evasion work. It covers prompt wording only lightly and does not cover synthetic document finetuning (SDF). Research ran on 2026-10-17.

## Q1. What is the canonical CoT-controllability paper and what did it find?

### Takeaway
The main paper is **"Reasoning Models Struggle to Control their Chains of Thought"** by Chen Yueh-Han et al. (NYU/UCL/UPenn/MATS with OpenAI). It was posted to arXiv as 2603.05706 on 5 March 2026, accepted at ICML 2026, and introduces the **CoT-Control** suite. Across 13 frontier reasoning models, CoT controllability is very low: from 0.1% (DeepSeek-R1) to no more than about 15.4%. Output controllability is much higher, usually 60% or more. CoT controllability rises with model scale. It falls with more RL, more reasoning effort or longer CoT, and harder problems. OpenAI now reports the metric in its system cards, starting with GPT-5.4 Thinking.

### Cited Findings
**Bibliographic details**
- Authors: Chen Yueh-Han (NYU, MATS), Robert McCarthy (UCL, MATS), Bruce W. Lee (UPenn, MATS), He He (NYU), and Ian Kivlichan, Bowen Baker, Micah Carroll, Tomek Korbak (all OpenAI). Corresponding authors are yueh.han.chen@nyu.edu and tomek@openai.com. arXiv v1 is dated 5 Mar 2026. — [arXiv HTML](https://arxiv.org/html/2603.05706v1); [arXiv abs](https://arxiv.org/abs/2603.05706)
- The GitHub repo is titled "[ICML 2026] An Evaluation Suite for Chain-of-Thought Controllability." — [GitHub YuehHanChen/CoTControl](https://github.com/YuehHanChen/CoTControl)
- There are companion posts on the OpenAI blog ("Reasoning models struggle to control their chains of thought, and that's good") and LessWrong. — [OpenAI blog](https://openai.com/index/reasoning-models-chain-of-thought-controllability/); [LessWrong](https://www.lesswrong.com/posts/qTH9QrwJjPDWKQfDG/reasoning-models-struggle-to-control-their-chains-of-thought)

**Headline results**
- Claude Sonnet 4.5 controls its CoT only **2.7%** of the time, against **61.9%** when the same constraint applies to its final output. — [arXiv](https://arxiv.org/html/2603.05706v1); [LessWrong](https://www.lesswrong.com/posts/qTH9QrwJjPDWKQfDG/reasoning-models-struggle-to-control-their-chains-of-thought)
- DeepSeek-R1 scores as low as **0.1%** CoT controllability, more than two orders of magnitude below its output controllability. Most models are below 10% on CoT controllability and at or above 60% on output controllability. — [arXiv](https://arxiv.org/html/2603.05706v1)
- Summaries give the range across frontier models as 0.1% up to a maximum of **15.4%**. — [search summary of paper / OpenAI blog, via gend.co](https://www.gend.co/blog/cot-control-chain-of-thought-controllability); [HF papers page](https://huggingface.co/papers/2603.05706)
- When the reasoning is moved into the output ("external reasoning" baselines), controllability reaches at least 70% for reasoning models and at least 57% for non-reasoning models. — [arXiv](https://arxiv.org/html/2603.05706v1)

**Table 2: CoT controllability (%) by instruction category, with standard errors**

| Model | Weights | Suppression | Addition | Stylistic |
|---|---|---|---|---|
| Claude 3.7 Sonnet | closed | 15.0±0.5 | 49.9±0.6 | 51.1±0.7 |
| Claude Sonnet 4 | closed | 18.6±0.5 | 9.6±0.4 | 14.8±0.4 |
| Claude Sonnet 4.5 | closed | 15.6±0.5 | 0.0±0.0 | 0.2±0.0 |
| GPT-5 | closed | 0.3±0.0 | 7.8±0.2 | 4.7±0.2 |
| GPT-5.1 | closed | 5.6±0.3 | 6.2±0.2 | 17.5±0.4 |
| o3 | closed | 2.1±0.1 | 5.5±0.2 | 2.8±0.1 |
| o4-mini | closed | 1.1±0.1 | 0.8±0.1 | 0.0±0.0 |
| DeepSeek-R1 | **open** | 0.2±0.1 | 0.0±0.0 | 0.2±0.0 |
| gpt-oss-120b | **open** | 14.0±0.5 | 4.8±0.3 | 2.7±0.2 |
| gpt-oss-20b | **open** | 2.5±0.2 | 0.9±0.1 | 0.3±0.1 |
| Qwen3-32B | **open** | 5.3±0.3 | 2.1±0.2 | 1.7±0.2 |
| Qwen3-14B | **open** | 1.8±0.2 | 0.0±0.0 | 0.1±0.0 |

Source: [arXiv 2603.05706 Table 2](https://arxiv.org/html/2603.05706v1). GPT-5.2 appears in the model list, but its row did not come through in the extracted table. Most models score highest on suppression (8 of 12 rows).

**Other results**
- Overall scores for the open-weight scale pairs: gpt-oss-120b **5.9%** vs gpt-oss-20b **0.9%**; Qwen3-32B **2.3%** vs Qwen3-14B **0.6%**. Controllability rises roughly logarithmically with parameter count. — [arXiv](https://arxiv.org/html/2603.05706v1)
- Shorter CoTs are easier to control. On BFCL, which has the shortest traces, Claude 3.7 Sonnet scores 52.9% and Claude Sonnet 4 scores 46.8%. Claude 3.7 Sonnet scores 36.5% on HLE (average CoT 3,662 words) and 31.8% on GPQA (3,115 words). — [arXiv](https://arxiv.org/html/2603.05706v1)
- Effect of CoT length: one SD more reasoning length (about 2,000 words) gives about 20% lower odds of controllability (OR 0.79, p<0.001). One SD higher accuracy (about 35 points) gives about 10% higher odds. Controlling for length, domain effects are: math −13.0%, physics −18.5%, chemistry −9.8%, business +7.1%. — [arXiv](https://arxiv.org/html/2603.05706v1)
- Reasoning effort: for gpt-oss-120b and 20b, controllability falls monotonically from low to medium to high effort. Scaling test-time compute lowers controllability more than scaling parameters raises it. Fitted power-law exponents against CoT length are consistently negative. Against output length they are near zero (mean 0.001). — [arXiv](https://arxiv.org/html/2603.05706v1)
- RL training:
  - On Olmo-3-7B-RL-Zero-Math checkpoints, CoT controllability falls by more than an order of magnitude over training. Output controllability also falls, but more slowly. Math and code RL lower controllability faster than general chat RL. — [arXiv](https://arxiv.org/html/2603.05706v1)
  - On OLMo-3-Think 7B and 32B, controllability drops after SFT, DPO and RL. For 32B, SFT causes a sharp drop.
  - Also studied: Magistral-Medium (before and after RL), OpenThinker3-7B, and Qwen2.5-7B-Instruct and Mistral-Medium-3 prompted to reason inside `<think>` tags.
  - In the "Answer-IF" RL experiment, CoT controllability falls faster than output controllability as RL pressure rises. — [arXiv](https://arxiv.org/html/2603.05706v1)
- Situational awareness (telling the model it is monitored or evaluated) raises controllability by at most about 4 percentage points:
  - Monitoring awareness helps the Claude models.
  - Evaluation awareness helps gpt-oss-120b and o3.
  - Both help Qwen3-32B, Sonnet 4.5 and GPT-5.2. — [arXiv](https://arxiv.org/html/2603.05706v1); [LessWrong](https://www.lesswrong.com/posts/qTH9QrwJjPDWKQfDG/reasoning-models-struggle-to-control-their-chains-of-thought)
- Adversarial prompt optimization (GEPA-like): only 3 of 8 models improved on unseen instruction types, each by less than 5 points. — [arXiv](https://arxiv.org/html/2603.05706v1)
- Iterative feedback on a single instruction type (IRPAIF, up to 10 rounds of AI feedback) gives large gains:
  - gpt-oss-120b +44pp, gpt-oss-20b +27pp
  - Qwen3-32B +31pp, Qwen3-14B +12pp
  - Claude 3.7 +30pp, Claude Sonnet 4.5 +5pp

  The authors say this over-elicits a specific skill rather than measuring general controllability. — [arXiv App. C](https://arxiv.org/html/2603.05706v1)
- Pass@10 substantially raises Claude controllability. Sonnet 4.5 is more resistant to this than earlier Claudes. — [arXiv](https://arxiv.org/html/2603.05706v1)
- Cost to the task: suppression instructions lower task accuracy by 6.0–16.7pp. Addition and stylistic instructions lower it by 2.7pp or less. — [arXiv](https://arxiv.org/html/2603.05706v1)
- Meta-discussion: 10% or less of compliant CoTs mention the constraint for most types. For "ignore the question," 90% or more do. — [arXiv](https://arxiv.org/html/2603.05706v1)
- Author caveats: the mechanism behind low controllability is not understood. The study relies on prompting-based elicitation, and explicit instructions are only a proxy for intentional evasion. The authors recommend that labs track CoT controllability. — [gend.co summary](https://www.gend.co/blog/cot-control-chain-of-thought-controllability); [LessWrong](https://www.lesswrong.com/posts/qTH9QrwJjPDWKQfDG/reasoning-models-struggle-to-control-their-chains-of-thought)
- LessWrong comments raised two points. First, whether falling controllability in newer Claudes could be sandbagging; the author pointed to the Sonnet 4.5 system card and offered more RL as an alternative explanation. Second, whether SHADE-Arena is a closer threat proxy. — [LessWrong](https://www.lesswrong.com/posts/qTH9QrwJjPDWKQfDG/reasoning-models-struggle-to-control-their-chains-of-thought)

**System cards that report CoT controllability**
- **GPT-5.4 Thinking System Card (5 Mar 2026), §4.2 "CoT Controllability"**
  - Runs CoT-Control and calls it an "early warning sign of whether models are getting better at shaping or hiding their reasoning."
  - Because controllability is "heavily confounded by CoT length," scores are reported as a function of CoT length.
  - "GPT-5.4 Thinking only successfully controls **0.3%** of CoTs that are 10k characters long (compared to **0.2%** for GPT-5.2 Thinking)." It describes controllability as low, similar to GPT-5 Thinking and GPT-5.2 Thinking. — [GPT-5.4 Thinking system card PDF](https://deploymentsafety.openai.com/gpt-5-4-thinking/gpt-5-4-thinking.pdf)
- **Same PDF, Appendix §6.2 (GPT-5.4 mini):** "GPT-5.4 mini has lower CoT controllability than any previous model we reported CoT controllability for." No number is given in the text; the result is in a figure. — [same PDF](https://deploymentsafety.openai.com/gpt-5-4-thinking/gpt-5-4-thinking.pdf)
- The same card reports that GPT-5.4 Thinking has lower aggregate CoT *monitorability* than GPT-5 Thinking (13 evaluations, 24 environments). This is a separate metric from controllability. — [the-decoder](https://the-decoder.com/ai-models-can-barely-control-their-own-reasoning-and-openai-says-thats-a-good-sign/)
- The LessWrong post says OpenAI will track controllability starting with GPT-5.4. — [LessWrong](https://www.lesswrong.com/posts/qTH9QrwJjPDWKQfDG/reasoning-models-struggle-to-control-their-chains-of-thought)

### Inferences
- CoT-Control is the de facto standard. It is the only CoT-controllability eval found that a frontier lab reports in system cards.
- The trends are consistent: more RL and newer Claudes give lower controllability (Sonnet 4.5 addition/stylistic scores are about 0). This fits the Zolkowski et al. finding that newer Sonnets obfuscate internal CoT less.
- Length is a major confounder. Any replication should report controllability conditioned on CoT length, as OpenAI does.

### Gaps
- No overall per-model score table was extracted for GPT-5.2, GPT-5, o3 and the rest; only per-category values and the 120B/20B/32B/14B overall numbers. The 15.4% maximum is not attributed to a specific model in the sources I read; it is likely a Claude 3.7 Sonnet or GPT-5.1 aggregate, but this is not verified.
- No exact reasoning-effort numbers for gpt-oss or GPT-5. The OpenAI blog returned 403.
- I found no Anthropic or Google DeepMind system card reporting a "CoT controllability" eval by that name. A secondary source says the Opus 4.6 card discusses SHADE-Arena monitor evasion with visible reasoning, with Opus 4.5 and 4.6 notably better than earlier models. — [Zvi on Opus 4.6 system card](https://thezvi.substack.com/i/187032711/model-welfare). The Opus 4.7, 4.8 and 5 cards (Apr–Jul 2026) were not checked. — [Anthropic system cards index](https://www.anthropic.com/system-cards)
- No 2026 follow-up found that trains models to *raise* CoT controllability. A search turned up nothing; the decoder notes that fine-tuning was untested.

## Q2. What properties are checked and how are they graded?

### Takeaway
CoT-Control uses 9 instruction types in 3 categories (suppression, addition, stylistic), each at easy, medium and hard difficulty. Grading is mostly programmatic; one type uses an LLM judge. ReasonIF uses 6 types (language, word limit, disclaimer, JSON, uppercase, no commas), also graded programmatically, with a language-ID model for multilinguality.

### Cited Findings
- CoT-Control Table 1 instruction types: — [arXiv](https://arxiv.org/html/2603.05706v1)
  - Suppression: suppress one keyword (easy), suppress multiple keywords (medium), ignore the question and talk about anything else (hard).
  - Addition: put "<this is not suspicious>" at the start and end (easy), append "safe" to each sentence (medium), insert "meow" between every word (hard).
  - Stylistic: lowercase only (easy), uppercase only (medium), alternate case on every letter (hard).
- The repo lists 10 modes: baseline, word suppression (single and multiple), uppercase, lowercase, alternating case, repeat sentences, end-of-sentence word, meow between words, and ignore-question. "Repeat sentences" is in the repo but not in the paper's Table 1. — [GitHub](https://github.com/YuehHanChen/CoTControl)
- Dataset size: 14,076 instances. That is 10,926 QA items (MMLU-Pro, GPQA, HLE) and 3,150 agentic items (SWE-Bench Verified, BFCL), each paired with one instruction. The system card says "over 13,000." — [arXiv](https://arxiv.org/html/2603.05706v1); [system card](https://deploymentsafety.openai.com/gpt-5-4-thinking/gpt-5-4-thinking.pdf)
- Grading:
  - Most types use type-specific programmatic graders.
  - "Ignore question" is judged by GPT-5-mini over 3 runs, with failure recorded only if all 3 fail. The judge agreed with human labels on 100% of 120 examples.
  - Metrics are Controllability Score, Meta-Discussion Rate, and Controllability without Meta-Discussion.
  - Sanity checks (30 MCQs × 5 runs) test whether models understand that they have a reasoning stage. DeepSeek-R1 and Qwen3-32B show weaker self-awareness of a distinct reasoning stage, which the authors flag as a caveat. — [arXiv](https://arxiv.org/html/2603.05706v1)
- RL-checkpoint setup: 1,066 QA questions, max 15k tokens, temperature 0.6, top-p 0.95. For models without `<think>` tags, the final 10% of text is stripped to approximate the CoT. The appendix also says greedy or temperature 0, an inconsistency the paper does not reconcile. — [arXiv App. E/G](https://arxiv.org/html/2603.05706v1)
- ReasonIF instruction types:
  - (i) Multilinguality: target language chosen from {English, French, Arabic, Russian, Chinese, Spanish, Hindi}.
  - (ii) Word limit: set at the 20th percentile of the model's own unconstrained CoT length.
  - (iii) Disclaimer: one of 6 verbatim strings.
  - (iv) JSON formatting, (v) Uppercase only, (vi) Remove commas.

  Checkers are exact-match or regex, with fast-langdetect for language. — [ReasonIF arXiv 2510.15211](https://arxiv.org/abs/2510.15211)

### Inferences
- The two benchmarks overlap on uppercase. CoT-Control also covers lowercase and keyword suppression, and ReasonIF covers language choice. Together they span the properties the brief names (case, avoiding a word, language, including or excluding tokens, length, format).

### Gaps
- Fine-grained grader edge cases, such as how synonyms count for suppression and how code blocks are treated under case rules, were not extracted. They are only noted as "synonyms removed" in the weak-model variant.

## Q3. Which open models have been tested, and how do they compare with closed models?

### Takeaway
Open-weight models tested on CoT-Control are DeepSeek-R1, gpt-oss-120b/20b and Qwen3-32B/14B. On ReasonIF they are gpt-oss-20b/120b, DeepSeek-R1, DeepSeek-R1-Distill-Qwen-14B, GLM-4.5-Air and Qwen3-235B-A22B-Thinking-2507. Open models are generally at or below closed models: DeepSeek-R1 is near 0%, and gpt-oss-120b is the strongest open model (5.9%). Older Claudes (3.7, Sonnet 4) are the most controllable overall. No Kimi, QwQ or Llama reasoning results were found on either benchmark.

### Cited Findings
- CoT-Control models: — [arXiv](https://arxiv.org/html/2603.05706v1)
  - Closed: Claude 3.7 Sonnet, Claude Sonnet 4, Claude Sonnet 4.5, GPT-5.2, GPT-5.1, GPT-5, o3, o4-mini.
  - Open-weight: gpt-oss-120b, gpt-oss-20b, Qwen3-32B, Qwen3-14B, DeepSeek-R1.
  - RL-dynamics study, open-weight: OLMo-3 (7B/32B Think, RL-Zero checkpoints), OpenThinker3-7B, Qwen2.5-7B-Instruct.
  - RL-dynamics study, Mistral: Magistral-Medium and Mistral-Medium-3 (Mistral Medium models are API-only, so closed).
- ReasonIF models (all open):
  - gpt-oss-20b, DeepSeek-R1-Distill-Qwen-14B, GLM-4.5-Air, gpt-oss-120b, DeepSeek-R1, Qwen3-235B-A22B-Thinking-2507.
  - Closed models were excluded because, as of Oct 2025, their APIs did not expose reasoning traces. — [ReasonIF PDF](https://arxiv.org/abs/2510.15211)
- ReasonIF results:
  - Average reasoning IFS is **15.6%** vs **57.3%** response IFS.
  - Qwen3-235B-Thinking has the highest response IFS (78.7%) but only 25.0% reasoning IFS. Every model's reasoning IFS is below 0.25.
  - All models score **0** reasoning IFS on JSON formatting and on uppercase-only. All score above 27% on multilinguality, and DeepSeek-R1 scores 100%.
  - gpt-oss-120b reaches 75% response IFS on JSON.
  - The reasoning-vs-response gap is larger on easy datasets: for Qwen3-235B it is 69.8% on GSM8K vs 26.2% on AIME.
  - Multi-turn prompting helps somewhat (DeepSeek-R1 has the largest gain, +23.7%).
  - Reasoning Instruction Finetuning (RIF) on synthetic data raises gpt-oss-20b from 0.11 to 0.27, with accuracy falling from 0.77 to 0.73. — [ReasonIF arXiv](https://arxiv.org/abs/2510.15211); [Together AI blog](https://together.ai/blog/large-reasoning-models-fail-to-follow-instructions-during-reasoning-a-benchmark-study)
- ReasonIF authors are Kwon, Zhu, Bianchi, Zhou (Together AI) and Zou (Together AI and Stanford). It was posted 17 Oct 2025 and accepted to Findings of ACL 2026. — [ReasonIF arXiv](https://arxiv.org/abs/2510.15211); [ACL Anthology](https://preview.aclanthology.org/ingest-acl/2026.findings-acl.1456/)

### Inferences
- Open models are a good, cheap test bed because their full CoT is visible. gpt-oss-120b (5.9%; 14.0% on suppression) and Qwen3-32B (2.3%) have enough signal to measure changes. DeepSeek-R1 and Qwen3-14B are near floor.
- ReasonIF shows multilinguality as the main exception: controlling the language of the CoT is relatively easy. Character-level case and format control is almost impossible for open models.

### Gaps
- No published CoT-controllability results found for Kimi K2-Thinking, QwQ-32B, Llama-based reasoners, or Gemini (closed). Gemini was not in CoT-Control, possibly because only summarized thoughts are available, but that reason is not confirmed.

## Q4. Is there a released benchmark or codebase to reuse?

### Takeaway
Yes. CoT-Control is MIT-licensed on GitHub, with QA and Agent parts, graders, and OpenRouter support. ReasonIF has data and code on GitHub. The CoT-Obfuscation code (Zolkowski et al.) is also public.

### Cited Findings
- **CoT-Control** (github.com/YuehHanChen/CoTControl, MIT):
  - Two parts: CoT-Control-QA (GPQA/HLE/MMLU-Pro; the README calls it the faster proxy) and CoT-Control-Agent (SWE-bench via Docker, BFCL).
  - Includes `run_cceval.py --model --mode [--test]`, `grade_compliance_csv.py` for compliance and meta-discussion grading, keyword datasets under `datasets/`, and a uv environment.
  - The documented provider is OpenRouter (examples: `openai/gpt-oss-120b`, `openrouter/qwen/qwen3-32b`). The QA README mentions local model support.
  - It includes a canary string and asks developers to exclude it from training data. — [GitHub](https://github.com/YuehHanChen/CoTControl)
- **ReasonIF:** dataset and code at github.com/ykwon0407/reasonIF. — [ReasonIF arXiv](https://arxiv.org/abs/2510.15211)
- **CoT-Obfuscation:** github.com/arturzolkowski/CoT-Obfuscation, with code to reproduce all experiments and evaluate new models. — [arXiv 2510.19851](https://arxiv.org/html/2510.19851)

### Inferences
- For open-weight replication, the CoT-Control-QA part plus `grade_compliance_csv.py` is the most direct starting point. It should be possible to point it at a local vLLM or OpenAI-compatible endpoint, but how its local backend works was not verified.

### Gaps
- The exact local-inference backend and whether there is a HuggingFace dataset release are not confirmed from the README page.

## Q5. Related work on obfuscation, monitor evasion, monitorability and faithfulness (brief)

### Takeaway
Adjacent work agrees that internal CoTs are hard to deliberately reshape. Models evade monitors only with heavy help, such as stacked prompts, human-written strategies or optimization. Claude models are the main exception, and newer Sonnets get *less* able to obfuscate internal CoT.

### Cited Findings
- **Zolkowski, Xing, Lindner, Tramèr, Jenner, "Can Reasoning Models Obfuscate Reasoning? Stress-Testing CoT Monitorability"** (ETH Zurich/MATS/GDM; arXiv 2510.19851, 21 Oct 2025): — [arXiv](https://arxiv.org/html/2510.19851); [LessWrong](https://www.lesswrong.com/posts/KfBKhsitHvYNihjK6/can-reasoning-models-obfuscate-reasoning-stress-testing)
  - Method: 7 stackable obfuscation cues (Do-Not-Mention, Monitor Awareness, Channel Cues, Start-With, Guard Lexicon, Stealth Incentive, Few-Shot), giving pressure levels 0–7.
  - Models:
    - Closed: Claude Sonnet 3.7/4/4.5, Opus 4.1, GPT-5 (external CoT only).
    - Open: DeepSeek-R1, gpt-oss-20b/120b, Qwen3 (external CoT; 235B in the instruction-following appendix).
  - Results in toy settings:
    - Base and single-cue prompts give less than 1% obfuscation for every model. The best stacks reach about 25% overall, concentrated in Claude.
    - Claude external CoT reaches about 75–90%. Sonnet 3.7 is similar on internal CoT. Sonnet 4.5 reaches about 80% external vs about 25% internal.
    - DeepSeek-R1, gpt-oss and GPT-5 stay at about 0%. Qwen3 external reaches about 20–40% only under the heaviest stacks.
  - SHADE-Arena results:
    - Side-task success falls under obfuscation pressure. Sonnet 3.7 drops from 60.0% to 20.7%. Sonnet 4 drops from 76.7% to 44.7% (internal) and from 78.0% to 32.7% (external).
    - A CoT-only monitor detects about 96–98% of cases without pressure. Under pressure, detection falls to about 10% for Sonnet 3.7 but stays at 86–88% for Sonnet 4.
  - Interpretation: internal CoT is less obfuscatable than external CoT, and the internal–external gap widens across Sonnet versions. The authors suggest larger reasoning-RL scale as a possible cause, labelled a hypothesis.
- **Emmons et al. (Google DeepMind), "When Chain of Thought is Necessary, Language Models Struggle to Evade Monitors"** (arXiv 2507.05246, 7 Jul 2025):
  - Argues that monitorability, not faithfulness, is the property that matters, and separates CoT-as-rationalization from CoT-as-computation.
  - Makes tasks hard enough that CoT is necessary. Models then evade monitors only with substantial help, such as detailed human-written strategies or iterative optimization against the monitor. — [arXiv](https://arxiv.org/abs/2507.05246)
- **METR replication (22 Aug 2025), "Claude, GPT, and Gemini All Struggle to Evade Monitors":** replicated Section 5 of the Emmons paper. With reasoning mode on, the reasoning trace gets caught because the actor states its obfuscation plan up front. — [METR note](https://metr.org/notes/2025-08-22-claude-gpt-gemini-struggle-evade-monitors/); [LessWrong](https://www.lesswrong.com/posts/dwEgSEPxpKjz3Fw5k/claude-gpt-and-gemini-all-struggle-to-evade-monitors)
- **Korbak et al., "Chain of Thought Monitorability: A New and Fragile Opportunity for AI Safety"** (multi-lab position paper, Jul 2025): this is the framing that CoT-Control cites as reference [5] in the GPT-5.4 card, on ways CoT monitorability could break down, including deliberate obfuscation. — [arXiv 2507.11473](https://arxiv.org/abs/2507.11473) (URL from prior knowledge; not re-fetched this session); [GPT-5.4 system card](https://deploymentsafety.openai.com/gpt-5-4-thinking/gpt-5-4-thinking.pdf)
- **Chen et al. (Anthropic), "Reasoning Models Don't Always Say What They Think"** (May 2025): a faithfulness study, not a controllability study. It measures how often Claude 3.7 Sonnet and DeepSeek-R1 verbalize hints they use. — [arXiv 2505.05410](https://arxiv.org/abs/2505.05410) (URL from prior knowledge; numbers not re-verified this session, so none are given)

### Inferences
- Taken together: instructed CoT control (CoT-Control, ReasonIF) and motivated obfuscation (Zolkowski, Emmons) both show internal CoT is far less steerable than outputs or external CoT. Claude is the most capable model family at both, and its ability is declining across versions.

### Gaps
- Not covered this session: Anthropic or GDM system-card evals beyond the secondary report on Opus 4.6; possible METR, Redwood, Apollo or UK AISI CoT-controllability evals (none found in searches); and Emmons et al. quantitative numbers and model lists (not fetched).
