# RHO-1 selective language modeling

Primary paper: Lin et al., "RHO-1: Not All Tokens Are What You Need",
arXiv:2404.07965 (v4 Jan 2025). Code/models: https://aka.ms/rho.
Lineage: token-level port of RHO-LOSS (Mindermann et al., ICML 2022;
18x fewer steps, +2% on Clothing-1M).

## Why selection: the token census

TinyLlama-1.1B continually pretrained on 15B OpenWebMath tokens,
checkpointed every 1B, per-token loss on a ~320k-token validation set:

- **H->L 26%** - loss decreases; the only productively learned group
- **L->L 51%** - already learned; near-zero gradient value
- **H->H 11%** - persistently high loss; unlearnable noise
- **L->H 12%** - loss *increases*; actively harmed by training

Selected-token loss follows a power law with downstream accuracy,
`Acc(L) = log(a*L + c)`; unselected-token loss carries a NEGATIVE
coefficient. Unselected tokens are harmful, not merely useless -
which justifies dropping them rather than downweighting.

## The method

**Reference model (RM)** encodes the desired distribution. Math RM:
0.5B tokens (MetaMath synthetic + MAmmoTH curated). General RM: 1.9B
tokens (Tulu-v2 + OpenHermes-2.5). Trained 3 epochs, cosine decay,
LR 5e-5 (1B) / 1e-5 (7B), seq len 2048/4096, then FROZEN. RM and
trainee start from the SAME base model. Fallback: train the RM on the
pretraining corpus itself (pure noise filtering); or keep tokens with
low `L_RM` / low RM next-token entropy `H_RM`.

**Offline scoring**: one forward pass per token, `L_RM(x_i)` stored.
No RM forward needed at train time. (Untested idea: use a proprietary
API's returned logprobs as reference scores, skipping RM training.)

**The selective loop, per batch:**
1. Trainee forward over the full batch (all N tokens).
2. Per-token trainee loss `L_theta(x_i)`.
3. Excess loss `L_delta(x_i) = L_theta(x_i) - L_RM(x_i)`.
4. Rank ALL tokens in the batch; keep top k% (hard binary mask,
   non-differentiable).
5. `L_SLM = -(1/(N*k%)) * sum I_k%(x_i) * log P(x_i|...)` - mean over
   selected tokens only.
6. Backward through selected logits; optimizer step as usual.

Same tokenizer required for RM and trainee. Ranking is within-batch,
keeping selected-token count constant per step.

## Hyperparameters that matter

- **Selection ratio k**: 60% optimal at 1B math, 70% at 7B math.
  The cliff: 50% falls BELOW no-selection baseline (20.7 vs 21.5).
  Sweep k; do not assume transfer.
- **Continual-pretraining LR**: 8e-5 (1B math), 2e-5 (7B math),
  1e-4 (1B general). Batch size 1M tokens everywhere.
- **Compute** (32x H100 80G): 15B tokens ~3.5h (1B) / ~18h (7B);
  80B tokens ~19h. Cost is dominated by the trainee, not scoring.

## Results

- Math: up to ~30pp absolute few-shot gain (per-task max +32.1
  MAWPS, +23.4 GSM8K); averages 1B: 21.6 -> 38.1, 7B: 55.8 -> 66.2;
  multi-epoch 1B reaches 40.9. Baseline accuracy 5-10x faster.
- **Headline**: Rho-1-7B on 15B tokens (10.5B selected) matches
  DeepSeekMath-7B trained on 500B math tokens - 3% of the tokens.
- Post-SFT MATH: 40.6% (1B) / 51.8% (7B).
- General 80B tokens: +6.8% average over 15 benchmarks; >10% on
  code and math.
- Self-reference fallback: +2.4pp (L_delta, 70%); +3.3pp with 40%
  fewer tokens (L_RM x H_RM intersection, 60% effective).
- Weak-to-strong: a 1B RM guiding a 7B trainee still helps
  (44.4 vs 43.5). Scoring cost decouples from training cost.

## Limitations

1. Domain collapse toward the RM's domain; mix in general CLM loss
   as guardrail (unsolved).
2. Verified only to 7B / under 100B tokens.
3. Needs an HQ RM or a performant open model; API-logprob route
   untested.
4. Hard binary mask; soft reweighting is listed future work.
5. Single RM = single desired distribution; multi-RM, RL-guided,
   SFT/multimodal extensions all unpublished.
6. No "RHO-2"; v4 generalizes the pipeline to ANY scorer S - the
   score function becomes the research question.
7. Open ablations: selection x LR schedule, selection inside
   annealing, within-batch vs global ranking.

## Reimplementation bill of materials

1. Base model (1B-class to match paper; loop is size-agnostic).
2. 0.5B curated tokens for math RM, or self-reference fallback.
3. One offline scoring pass with the frozen RM.
4. The 6-step loop, k swept around 60-70%.
5. Eval on the paper's 9-task math suite (targets: +16.5pp avg at
   1B, +10.4pp at 7B; watch for domain collapse).
