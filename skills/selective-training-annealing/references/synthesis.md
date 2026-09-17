# Synthesis: limitations, research directions, checklists

## The unified picture

The field controls the END of training with exquisite care (annealing
mixtures, LR collapse, checkpoint merging), treats the BEGINNING as a
stability problem (warmup, init scaling, batch ramping), and the
MIDDLE as a diversity problem (broad mixtures at high LR). RHO-1 is
the one method operating continuously through all three phases - and
it has never been tested in composition with the phase structure it
would live inside.

## Evidence ranking (the multipliers, in order)

1. **Quality filtering and selection** - the largest lever (DCLM
   +6.6pp MMLU at 6.6x less compute than Llama 3 8B; RHO-1 +30pp math
   max; FineWeb-Edu +4pp MMLU / +11pp ARC). What you remove matters
   as much as what you order.
2. **Late-stage mixture annealing** - the industry standard (+6.9pp
   MMLU, +8.3pp GSM8K at 7B; MiniCPM +12.6 C-Eval), weakening at
   flagship scale.
3. **Domain/stage ordering** - general-first then specialized (Code
   Llama, Phi-3, Qwen2.5-Coder, daVinci-LLM). Coarse-grained; reliable.
4. **Per-sample difficulty ordering** - real but small (0.5-3.5%),
   best as warmup; gains vanish under standard cosine decay unless
   schedule and curriculum are co-designed.
5. **Initialization** - strong for stability/efficiency,
   thin-to-null for final quality.

## Cross-cutting limitations

- **A. Scale extrapolation**: positives verified at <=7B / 100B-1T;
  strong practice at 70B+; thin evidentiary bridge between them.
- **B. The LR-schedule confound** (Luo et al. 2025): many "ordering"
  effects were ordering-x-schedule effects. Historical curriculum
  claims under cosine decay without schedule ablations are suspect -
  including parts of RHO-1's evaluation.
- **C. The seed-variance bar** (Madaan et al. 2024): ten Llama-2-7B
  on 210B tokens differing only in seed show seed variance below
  per-benchmark bootstrapped noise. Ordering claims need a
  multi-seed bar, not a single run.
- **D. The closed-lab problem**: flagship-scale annealing ablations,
  warmup mixtures, and some recipes are unpublished. The most
  decision-relevant numbers are the least available.
- **E. The composition void**: selection, annealing, and
  initialization studied in isolation; their interactions almost
  entirely unexplored.

## Research directions

**1. RHO-1 x annealing composition (highest leverage).** (a) Select
the anneal mixture: apply RHO-1 only during the anneal phase of a
fixed run. (b) Phase-gated selection: selection only in warmup /
mid / anneal, three runs + shared control. (c) Selection-aware
anneal design: use RM scores to BUILD the anneal mixture (top
excess-loss documents) - a competitor to classifier tiering. A
negative result is itself publishable.

**2. LLM-scale first-N-steps order ablation.** Fix compute; vary only
first-N token ordering (N in {1B, 10B, 50B}): random, ascending
difficulty, descending, learnability-ranked. Multi-seed. Metrics:
steps-to-baseline, final average, early gradient-noise statistics.

**3. Warmup-phase mixture composition.** Mirror anneal-mixture
ablation methodology on the first 1-5% of training: high-readability
text, short sequences, instruction-dense data, inverse-of-anneal mix.
Measure stability (loss spikes, gradient norms) and steps-to-baseline.

**4. TREC replication and extension.** Replicate the diagnostic on an
open family; test HQ-at-predicted-valley vs at-very-end under
decay-to-zero vs moderate decay; extend to selection (does the valley
move when selection changes the effective distribution?).

**5. Multilingual temporal curriculum.** Staged language introduction
vs static mixing; TREC lens for low-resource language placement.

**6. Soft selection vs hard top-k.** Replace the hard mask with
`w_i = softmax(beta * L_delta)`, sweep temperature. Hypothesis: soft
weighting removes the 50% cliff.

**7. Anneal-as-probe for orderings.** Extend Llama 3's 30/70 probe
protocol from mixtures to orderings/selection rules - cheap ordering
experiments off a shared 50%-trained checkpoint.

**8. Proprietary-logprob reference scores.** Score a corpus with
frontier-API logprobs as the RM; compare vs self-trained RM baseline.
Tests whether RM quality or RM controllability matters more.

**9. Selection under schedule co-design.** RHO-1 x {cosine-to-zero,
moderate decay (final ~1/3 peak), constant LR + averaging, WSD}.
Does the optimal k shift with the schedule?

**10. Forgetting-aware data valuation.** Composite score:
(reducible loss) x (retention deficit at training position) -
TREC's *when* times RHO's *what*, inside RHO-1 v4's generalized
scorer framework.

## Prioritized agenda

1. Replicate RHO-1 at 1B scale (bill of materials in rho1.md).
2. Direction 7 (probe-anneal orderings) - makes Directions 2, 3, 9
   an order of magnitude cheaper if it works.
3. Direction 9 (selection x schedule) - required before any
   production deployment of selection.
4. Direction 1a/1b (phase-gated selection).
5. Direction 4 (TREC replication).
6. Directions 6, 8, 10 as follow-ups; 3 and 5 as longer-horizon
   programs.

## Reimplementation checklists

**RHO-1 replication**: base model (1B-class) / 0.5B curated RM tokens
or self-reference fallback / RM: 3 epochs, cosine, 5e-5 (1B) or
1e-5 (7B), seq 2048/4096, frozen / offline scoring pass / 6-step
loop, k swept ~60-70% / LR 8e-5 (1B math), 2e-5 (7B math), 1e-4 (1B
general), batch 1M tokens / eval 9-task math suite (targets +16.5pp
avg 1B, +10.4pp 7B; guardrail: mix general CLM loss vs domain
collapse).

**Annealing replication (OLMo 2, the open reference)**: stage-1
checkpoint (diversity mix, cosine to 10% peak, truncated while LR
high) / anneal mix 50% HQ web + 50% domain HQ, ablate toward "Web
FT7 + Math + Ins" / LR linear -> 0 over 50-300B tokens (1.2-7.5% of
budget) / optional 3-copy soup on different orders / experimental
arm at TREC-predicted valley.

**Initialization study (Direction 2 design)**: fixed compute; vary
first-N ordering (N in {1B, 10B, 50B}): random / ascending /
descending / learnability-ranked; remainder identical and random /
multi-seed (Madaan bar) / metrics: steps-to-baseline, final average,
early gradient-noise statistics.

## Closing (the source's bottom line)

Order is a multiplier on good data, not a substitute for it. The
unknowns are the opportunity: the field has characterized the end of
training better than the beginning, studied each mechanism in
isolation better than their compositions, and verified its best
results one scale below where they would matter most. The source's
closing names the four-part program explicitly: (a) compose selection
with annealing, (b) co-design schedules with curricula, (c) predict
forgetting structure before training, and (d) clear the multi-seed bar
on every claim.
