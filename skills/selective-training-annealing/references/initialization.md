# Initialization: what the evidence really says

Evidence ratings used below: STRONG (multiple convergent studies or
large-scale verification), MODERATE (one solid study, limited scale),
WEAK (suggestive/contested), THIN (honest gap, not a verdict).

"Initialization" covers four distinct things:

1. **Weight initialization** - distribution and scaling of parameters.
2. **Data-side initialization** - what data the model sees first.
3. **LR warmup** - the learning-rate schedule of the first phase.
4. **Early-phase dynamics** - critical periods, forgetting, batch-size
   and ordering effects in the first N steps.

## Weight initialization

- **Standard practice, STRONG for stability**: N(0, 0.02) with
  residual-branch downscaling (final residual projection scaled by
  0.02/sqrt(2*n_layer); GPT-2/GPT-NeoX lineage). Purpose: bounded
  activation norms through deep residual stacks early on.
- **Null on final quality, MODERATE**: no surveyed paper shows a
  final-quality difference among reasonable schemes at fixed
  hyperparameters. Best evidence: **PolyPythias** (van der Wal et
  al., ICLR 2025, arXiv:2503.09543) - 50 full runs, 14M-410M params,
  varying init and data order: "highly consistent training dynamics
  across initial conditions." Caveat: only to 410M.
- **Small-init beats He-init** (STRONG mechanism, MODERATE LLM
  quality): He variance-preservation was derived for single-pass
  supervised training, not deep residual transformers.
- **WeSaR** (arXiv:2410.05052, MODERATE): per-matrix gates keeping
  norms uniform; stabilizes and accelerates at 130M/1.3B/13B. The
  strongest positive "init improves outcomes" result found - and it
  operates through the whole run, not just at start.
- **muP** (arXiv:2203.03466, STRONG for transfer, THIN for quality):
  enables zero-shot hyperparameter transfer (40M -> 2.7B). Saves
  tuning compute; does not raise the quality ceiling. Frequently
  misunderstood.
- **u-muP** (arXiv:2407.17465, MODERATE): unit-scaled muP for clean
  FP8 training. Numerics only.
- **DS-Init / Admin / DeepNorm / Fixup** (STRONG mechanism, THIN for
  modern decoder-LLM quality): post-layer-norm era, MT scale; no
  modern decoder-LLM final-quality effect shown.
- **Small-init biasing reasoning over memorization** (WEAK,
  arXiv:2405.05409): toy compositional task; enormous scale gap.

Net: initialization is a stability technology. Final-quality effects
at LLM scale have no positive evidence and one moderate-strength null.

## Data-side initialization

- **Curriculum-as-warmup, STRONG** (Zhang et al. 2025,
  arXiv:2506.11300): 200+ models, 0.5B-3B params, up to 100B tokens.
  Curriculum cuts steps to baseline by 18-45% early/mid; as a warmup
  phase before random sampling it yields sustained gains up to +3.5%.
  Best difficulty signals are surface-text statistics: compression
  ratio, MTLD lexical diversity, Flesch Reading Ease. Caveats: <=100B
  tokens, surface metrics may not transfer across domains.
- **The counter, MODERATE** (Elgaar & Amiri 2026, arXiv:2601.21698):
  shared latent learning phases regardless of ordering; curriculum
  gains shrink with scale (to 410M). Bounds the claim; does not refute.
- **Warm-starting from smaller models, THIN**: bert2BERT-style
  progressive stacking claimed >110% speedups in the BERT era; NO
  published frontier-lab decoder-LLM evidence. Conspicuous absence.
- **Warmup-phase mixture design, THIN**: nothing published anywhere.
  Every lab designs its anneal mixture; none publishes designing its
  warmup mixture. A genuine open gap.

## LR warmup

- **Warmup as stability enabler, STRONG** (Kosson et al.,
  arXiv:2410.23922): three mechanisms - Adam's momentum bias correction
  inflates early updates; early updates are large relative to |w|;
  early-sample gradients are highly correlated (effective critical
  batch size too low early). Theory (arXiv:2510.03164): 10-20% linear
  warmup optimal at 70M/160M/410M, enabling peak LRs (1e-2 at 70M)
  that diverge without warmup.
- **What warmup buys, MODERATE-STRONG**: final quality depends on
  PEAK LR, not warmup length (arXiv:2406.09405). Warmup broadens the
  viable LR range (robustness). Read carefully: warmup lets you reach
  a higher peak LR safely; the peak LR is what matters for quality.
  Warmup is an enabler, not a direct quality lever.
- **Warmup-free training** (MODERATE at small scale, THIN at LLM
  scale): achievable at small scale with Kosson et al.'s fixes; no
  LLM-scale demonstration.
- **Schedule-free learning** (Defazio et al., arXiv:2405.15682,
  MODERATE): matches/beats cosine without knowing T in advance; at
  210M LLM scale momentum-sensitive. Not yet a replacement.

## Early-phase dynamics

- **Critical learning periods**: STRONG in vision (Achille et al.
  2019), less irreversible than claimed (cyclic LR restores
  plasticity); THIN for LLM pretraining - no causal LLM-scale study.
- **Forgetting events** (Toneva et al., ICLR 2019): STRONG for the
  phenomenon (examples forgotten at vastly different rates;
  unforgettable examples architecture-general); MODERATE for LLM
  formalization (descriptive, not interventional). Connects directly
  to TREC (see annealing.md).
- **Implicit Curriculum Hypothesis** (arXiv:2604.08510): skill-emergence
  orderings consistent across 45 model pairs, 410M to 13B - early-phase
  structure appears driven by optimization, not data order.
- **Grokking** (STRONG small-scale, THIN pretraining); **early-bird
  tickets** (THIN at LLM scale).

## Batch-size and ordering in the first N steps

- **Critical batch size starts near zero, MODERATE** (OLMo 1B/7B,
  arXiv:2505.23971): CBS grows rapidly in the first ~50k tokens, then
  plateaus around 4096 documents. The McCandlish gradient-noise-scale
  estimator UNDERESTIMATES CBS by orders of magnitude - do not trust
  it for early-phase decisions.
- **Batch-size/LR interchangeability below CBS, STRONG** (Smith et
  al., arXiv:2110.00641): the theoretical license for early
  batch-size ramping (GPT-3, PaLM, Llama-3, Nemotron-4 all ramp).
- **Early gradient correlation, MODERATE** (Kosson et al.): early
  gradients highly correlated -> effective batch size limited early;
  curriculum warmup independently reduces early gradient noise. The
  first phase is noise-limited; batch ramping and curriculum warmup
  attack the same bottleneck from different sides.
- **Data ordering within the first N steps at LLM scale: NO
  controlled ablation published (THIN - genuine gap).**

## Net assessment of "initialization matters as much as annealing"

- **Well supported for STABILITY AND EFFICIENCY**: 1/sqrt(2N) init
  scaling, 10-20% warmup, batch ramping from near-zero CBS,
  curriculum-as-warmup (+3.5%, 18-45% fewer steps). First-order
  compute wins.
- **NOT supported for FINAL QUALITY**: quality is dominated by peak
  LR, data, compute, and annealing design (PolyPythias consistency;
  warmup gains an order of magnitude smaller than annealing effects).

The asymmetry is the finding: **the beginning of training determines
how fast and how safely you learn; the end determines how good the
final model is.** The unproven half (init -> final quality) is where
the open experiments live.

## The five open gaps

1. No LLM-scale ablation of data ORDER in the first N steps.
2. No frontier-lab warmup-phase mixture composition study.
3. No pretraining-scale influence/sample-selection method (LESS is
   instruction-tuning only; RHO-1 verified to 7B/100B).
4. TREC placement rules need replication.
5. RHO-1 x annealing composition is untested.
