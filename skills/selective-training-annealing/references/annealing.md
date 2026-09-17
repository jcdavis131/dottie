# Annealing: how frontier labs build the final phase

Universal law: **annealing = high-quality mixture switch + learning-rate
collapse, always coupled. No lab changes one without the other.**

## The universal 9-step pipeline

1. **Ingest** - crawl/web, code, books, papers, synthetic generators.
2. **Clean** - language ID, normalization, heuristic + perplexity
   filters. (Nemotron: disable heuristics on HQ buckets to preserve
   yield.)
3. **Dedup** - exact (hash) -> fuzzy (MinHashLSH) -> substring (suffix
   arrays).
4. **Quality label** - classifier ensembles -> percentile bins ->
   downstream-aligned tiers. (Nemotron: 3 classifiers -> 20 bins ->
   5 levels; Qwen3: 30T-token multi-dim annotation -> instance-level
   mixture optimization.)
5. **Synthetic enrichment** - rephrase low-Q docs, variant-expand HQ
   docs; domain models synthesize textbooks/QA/code. Trillions of
   tokens: a first-class ingredient, not a supplement.
6. **Mix design** - proxy-model ablations pick domain ratios
   (Llama 50/25/17/8; OLMo 50/50 web:domain; Qwen3 instance-level).
7. **Main train** - high LR, diversity-weighted mix.
8. **Anneal** - HQ-upweighted mix (code/math/STEM/instruction) + LR
   decaying to ~0, placed at the TREC forgetting minimum.
   Checkpoint averaging / souping / merging at the end.
9. **(Optional)** RLVR curriculum, R1-style: cold-start SFT ->
   reasoning RL to convergence -> rejection-sample + retrain ->
   all-scenario RL.

## Per-lab recipes

**Llama 3** (arXiv:2407.21783): 15.6T tokens; default mix ~50/25/17/8
general/math+reasoning/code/multilingual. Anneal: final 40M tokens
(~0.26%), LR linear -> 0, 128K context, Polyak averaging; HQ code+math
upsampled; no benchmark training sets (true few-shot probe). 405B:
AdamW, peak LR 8e-5, batch ramped 4M -> 16M. Key innovation for
researchers: **anneal-as-probe** - anneal a 50%-trained 8B on 40B
tokens (30% candidate / 70% default mix), LR linear -> 0; a cheap
substitute for full mixing-law sweeps.

**Qwen3** (arXiv:2505.09388): 36T tokens, 119 languages. Web+PDFs ->
Qwen2.5-VL OCR -> Qwen2.5 refinement (trillions of tokens from this
loop); synthetic trillions from Qwen2.5-Math/Coder. >30T tokens
annotated on multiple dimensions; mixture optimized at instance level
via proxy ablations - finest published granularity. Stage 1: ~30T
(83%), 4K ctx. Stage 2: ~5T (14%), STEM/code/reasoning reweight.
Stage 3: long-context 4K -> 32K.

**OLMo 2** (arXiv:2501.00656, most transparent): Stage 1 (90-95%
FLOPs): ~3.9T tokens, cosine decay to 10% of peak (7B: 3.0e-4,
13B: 9.0e-4, 32B: 6.0e-4), truncated early while LR still high.
Stage 2 "mid-training" (the anneal, 5-10% FLOPs): LR linear -> 0
from residual; Dolmino-Mix-1124, 50% HQ filtered web + 50% domain HQ;
ablated optimum "Web FT7 + Math + Ins". 7B total 4.05T; mid-training
1.2-7.5% of tokens. **Model souping**: 3 copies on different data
orders, each annealed to zero, then merged. Design logic: the anneal
PATCHES capability gaps detected in stage 1 - targeted intervention,
not "more of the good stuff."

**Nemotron** (arXiv:2412.02595, quality-labeling reference): CC ->
JusText -> FastText LID -> normalization; exact/fuzzy/substring
dedup; heuristic + KenLM filters; 3 quality classifiers (ensemble =
max) -> 20 percentile bins -> 5 downstream-aligned levels; ~2T
synthetic tokens. Output: 6.3T-token dataset. 8B on 1T HQ: +5.6 MMLU
vs DCLM; 15T run beat Llama 3.1 8B (+5 MMLU). Training (25T, WSD):
warmup 0 -> 1e-3 over 8.4B tokens; stable 1e-3 for 20T (80%); cosine
decay -> 1e-5 over 5T (20%). Phase 1: 23.5T (94%) balanced diversity.
Phase 2: 1.5T (6%) HQ upweight + HQ-synthetic + STEM textbooks.
**Checkpoint merging during the stable phase** (125B/250B/500B
windows): +2-4 points on 12-benchmark average, ~16% FLOP savings -
a genuine alternative to "anneal = decay."

**DeepSeek-V3** (arXiv:2412.19437, the decay tail IS the anneal):
14.8T tokens. Warmup 0 -> 2.2e-4 over 2K steps -> constant to 10T ->
cosine decay to 2.2e-5 over 4.3T (29%) -> terminal 500B: 333B at
2.2e-5 then 167B at 7.3e-6 (stepped constant). Batch curriculum
3072 -> 15360 sequences over first 469B. YaRN 4K -> 32K -> 128K run
AFTER pretraining. Mixture percentages undisclosed.

**DeepSeek-R1** (arXiv:2501.12948, staged-training reference):
cold-start SFT on curated long CoTs -> reasoning RL to convergence
-> rejection-sample + retrain base from scratch -> all-scenario RL.
R1-Zero: AIME 2024 pass@1 15.6% -> 71.0%.

## Comparison

| Lab | Anneal size | LR in anneal | Anneal mixture | Selection mechanism |
|-----|-------------|--------------|----------------|---------------------|
| Llama 3 | 40M (~0.26%) | Linear -> 0 | Upsampled HQ code+math | Classifier filtering; anneal-as-probe |
| Qwen3 | Stage 2: 5T (~14%) | Undisclosed | STEM/code/reasoning upweight | 30T-token annotation + proxy ablations |
| OLMo 2 | 50-300B (1.2-7.5%) | Linear -> 0 | 50% HQ web + 50% domain HQ | Mix ablations; 3-copy soup |
| Nemotron 3 | 1.5T in 5T decay (6-20%) | WSD -> 1e-5 | HQ + HQ-synthetic + STEM | 3-classifier ensemble; ckpt merging |
| DeepSeek-V3 | 4.3T + 500B tail (~32%) | Cosine -> 2.2e-5, stepped tail | Math/code upweighted (undisclosed) | Redundancy-minimizing pipeline |
| DeepSeek-R1 | 4-stage post-train | N/A (RL) | CoTs -> RL -> RS-SFT -> RL | V3 as reward judge |

The spread (0.26% to ~32%) is the striking column: no consensus on
*how much*; consensus that it exists and couples to LR collapse.

## TREC: where to place the anneal

Bergsma, Dey & Hestness 2025, arXiv:2509.25380. TREC evaluates each
training batch with the FINAL weights, measuring retention vs when
data was seen:

1. HQ data belongs at the TREC MINIMUM (the optimizer's forgetting
   valley) - BEFORE the LR drop, not at the very end. Late placement
   under step-drop/decay-to-zero is explicitly suboptimal.
2. Predictable in advance from AdamW's implicit EMA coefficients
   (timescale tau, via weight decay lambda).
3. Scale invariant: TRECs align across 1000x compute (111M -> 3.9B)
   when tau matches; validated on 3.9B / 900B continual pretraining.
4. Design rules: predict TREC before training; place HQ/anneal mix
   at the predicted minimum; avoid late placement under decay-to-zero;
   some forgetting is desirable (optimal tau decreases as a power law
   in tokens/param).

Status: single 2025 preprint, unreplicated. High leverage if true.

## Results

- Llama 3 8B: GSM8K/MATH data in annealing +24.0% / +6.4%; negligible
  at 405B - annealing effects weaken at scale.
- Blakeney et al. (7B/1T): end-of-training math/code upsampling +6.90pp
  MMLU, +8.26pp GSM8K, +6.17pp HumanEval; best in final 10-20%; beyond
  20%, targeted gains cost general ability.
- MiniCPM: decay with HQ SFT-style mix beat decay-then-SFT (C-Eval
  40.0 -> 52.6, MMLU 44.6 -> 50.9).
- Feng et al. two-phase: +3.4% avg over random ordering, +17% over
  natural distribution; 1T blend transferred to 15T / 25B.
- Qwen2.5-Coder: file -> repo -> SFT ordering; text+math ablations
  31.3 -> 55.0.
- Luo et al. 2025: ascending-quality curriculum under constant LR
  substantially beats shuffling; under cosine/WSD the advantage nearly
  vanishes; co-designed best config +1.64% avg (+2.7% vs
  cosine+uniform), +1.2% in multiphase pretraining by reordering alone.
- daVinci-LLM: 3B, ~8T tokens, two-stage domain curriculum (6T broad
  web -> 2T reasoning-intensive) matches 7B-scale OLMo-3; 200+
  ablations released.

## Limitations and replication gaps

1. Scale attenuation: flagship-scale annealing ablations unpublished.
2. Mixture opacity: DeepSeek-V3 / Qwen2.5 partially closed.
3. Anneal-size disagreement (0.26% vs ~32%) with no reconciliation.
4. TREC unreplicated.
5. Luo et al. is a preprint; remedy set untested at large scale.
6. No composition with selective training (see synthesis Direction 1).
7. Anneal-as-probe under-exploited: no published replication or
   extension to probing orderings.
