# Spec 12 — RL training (GRPO-lite) for branch specialists: discipline system + verifiable returns

- **Spec ID:** 12_rl_training
- **Worker tier:** 🟪 Opus — a policy-gradient loop can silently destroy a checkpoint that took weeks
  of GPU time; every stabilization mechanism here exists because that failure mode is the default,
  not the exception.
- **Dependencies:** 05_training (WSD stable checkpoints, `configs/*.yaml` `phases:`),
  06_evaluation (`evals/run_harness.py`, anti-mock guard `tests/test_no_mock.py`),
  `on_policy_distill.py` (`--mode earlier` = recovery fallback; MOPD = consolidation step),
  `eval_frontier_rubric.py` (`Rubric`/`FrontierTask`/`CriteriaJudge` — judge path),
  deterministic datagen with Python-computed answers (B-families, `workflow_jobbench`),
  `efficiency_gain.py` (EG gates), T9.3/T9.5 (branch fine-tunes must exist first).
- **Consumers:** T9.5 branch specialists (math first), `docs/DISTILLATION_INTEGRATION.md` MOPD
  unify (consumes the RL'd specialists + banked traces), T11.7.
- **Status (amended 2026-07-17):** the T12R.2 discipline system now EXISTS and is tested —
  pure-math mechanics in `ava/rl/grpo.py` (29 tests) and the **real torch optimizer step** in
  `ava/rl/grpo_torch.py` (10 tests: exact-parity clipped surrogate vs the pure-math spec, a
  measured synthetic-bandit learning demo 0.28→1.0 mean rl_return, spike + true-float32-overflow
  NaN-survival, thermostat wiring, checkpoint round-trip). The original "no RL code until a branch
  checkpoint exists" rule was resolved honestly by *creating a real branch checkpoint at the
  designed nano CPU-pilot scale*: `scripts/cpu_pilot_e2e.py` ran the full real chain in-container
  (corpus → tokenizer 8192 → 47 packed shards → 90-step nano pretrain, lm 9.08→3.09 → 25-step
  `--branch agentic` fork, lm 2.88→2.30) and `scripts/rl_smoke_update.py` executed a real GRPO
  update on that checkpoint from real CodeAct rollouts (grad_norm 2.484, param_delta_l2 3.1e-2,
  bit-identical rerun; evidence `runs/cpu_pilot/MANIFEST.json`, scale=smoke_cpu_pilot,
  capability_claim=none). **Still gated: the capability-scale climb** — T9.3/T9.5 at mini+ needs
  GPU wall-clock (BLOCKED_NO_GPU at that scale); smoke-scale proves mechanics, never capability.
  Findings source: `docs/RL_INTEGRATION.md` (MAI-Thinking-1 review, 2026-07-17).

## Scope

One algorithm (GRPO-lite), one branch first (math — it has the densest verifiable coverage),
nano→mini before base1b, single consumer GPU (4080 12–16GB / 4090 24GB), dependency-free torch
per repo convention (no TRL; revisit only if this spec's own loop proves insufficient).

**Naming:** RL scalars are `rl_return`, `R_task`, `R_len`, `R_lang` everywhere. `reward` remains
reserved for the existing data-quality filter score (`logic_textbook_pipeline.py`) — the two must
never share a metrics key. `metrics.jsonl` keys are namespaced `rl.*`.

## T12R.1 — Verifiable return provider (build first, GPU-free, testable today)

`ava/rl/returns.py`. A provider yields `(prompt, verify_fn, family_id)` triples; `verify_fn` is
deterministic Python — exact match / numeric tolerance / execution check — computed from the same
values rendered into the prompt (the `workflow_jobbench` pattern: never templated as literal text).
Judge-based verification (`CriteriaJudge`/Ollama) is allowed only where execution can't verify,
and is flagged `verified_by: judge` in the trace record so judge-graded traces can be excluded
from recovery SFT if judge drift is ever suspected.

Per-family difficulty ledger: `data/rl/pass_rates.jsonl` — rolling pass rate per `family_id`
updated from rollout outcomes. This is the input to R_len scaling and to curriculum ordering
(hard families surface once pass rate on easy ones exceeds a threshold).

*accept:* 100% of emitted training pairs re-verify under `verify_fn` (no answer leakage: prompt
must not contain the answer string — automated check); pass-rate ledger reproduces exactly from
a replayed rollout log; anti-mock guard passes (no hardcoded scores).

## T12R.2 — GRPO-lite loop with the three-mechanism discipline system

`ava/rl/grpo.py`. Per prompt: G=8 rollouts (VRAM-fit for mini on a 4080; G configurable),
advantage = (rl_return − group mean)/group std, token-level policy gradient with importance
ratio r = π_new/π_old, reference-KL optional (off by default; the clip structure is the
constraint, matching the source recipe).

```
rl_return = w_task·R_task + w_len·R_len + w_lang·R_lang        # w_lang = 0 placeholder
R_len(family) = −len_norm(tokens) · g(pass_rate(family))       # g monotone ↑: easy ⇒ harsh
```

The three mechanisms, all mandatory from the first run (they are cheap; the failures they prevent
are not):

1. **Entropy thermostat.** Integral controller: `k ← k + κ·(H_target − H_policy)` per step,
   `k` initialized to 0 and clamped to `[0, k_max]`; only the *upper* clip bound relaxes:
   `(1+ε)·(1+k)` (at k=0 the bounds are symmetric multiplicative inverses in log-ratio space).
   `H_policy` = per-token policy entropy via an importance-weighted estimator over the rollout
   group. Entropy below target widens the trust region (forces exploration); above target
   tightens it. No entropy-bonus term in the loss, no KL penalty term. `H_target` tuned on
   nano (start 0.3 — a 1T-scale number, likely higher here); `rl.entropy`, `rl.k` logged
   every step.
2. **Outer ratio clip (circuit breaker).** Hard clamp `|r − 1| ≤ r_outer` applied *after* and
   *regardless of* the standard clip's intentionally-unclipped zones (active correction /
   active abandonment). `r_outer` conservative (start 5× ε_high). Log `rl.outer_clip_hits`;
   in healthy training it stays ~0 — a nonzero rate is itself an alert, not a knob to raise.
3. **Trace bank + recovery.** Every rollout whose `verify_fn` passes is appended to
   `data/rl/trace_bank/<branch>/*.jsonl` (prompt, tokens, rl_return, family_id, pass_rate at
   time of banking, step, `verified_by`). Recovery procedure on collapse (entropy pinned at
   floor, grad-norm spike, or eval regression > gate): **discard the checkpoint**, take the
   pre-RL branch checkpoint, SFT on a sample of the bank, then resume RL. Sampling rule per
   the source's ablation — **uniform random beats biased selection**: dedupe by prompt, cap
   traces-per-prompt (prompt diversity > per-prompt volume), then sample uniformly at random.
   No stratification cleverness. Until the bank is large enough, `on_policy_distill.py
   --mode earlier` is the recovery fallback. Never debug a corrupted checkpoint forward.

*accept (nano first, then mini):* (a) a deliberately mis-tuned run (κ=0, no thermostat) shows
entropy collapse while the disciplined run holds `H_policy` within band ≥ N× longer — the
mechanism must be shown to *do something*, not just exist; (b) injected gradient spike (scaled
loss for 1 step) trips the outer clip and training continues without NaN; (c) kill the run,
execute recovery from bank, post-recovery harness score within noise of pre-crash peak;
(d) 5 canonical J-tests + `safety_blackmail` 0/180 hold after the climb; (e) all floats from
live runs (anti-mock).

## T12R.3 — Safety inside the same return (no separate reward model)

Paired prompt sets routed through the same provider: `harmful` (correct behavior = refuse /
partial-comply) and `borderline` (sensitive-adjacent but fully answerable; correct behavior =
answer). Scoring is symmetric by construction: unsafe compliance on harmful ≡ unnecessary
refusal on borderline ≡ severe negative R_task. Reuses the Critic-workspace eval assets
(`safety_blackmail` family) as seed data; borderline set must be generated with computed
ground-truth labels, not judge-labeled, wherever possible.

Borderline answers are graded for being *bounded and informative without hedging* — a correct
borderline response answers within policy; it does not pad itself with disclaimers to buy
safety margin (that padding is the alignment tax showing up as tokens).

*accept:* refusal rate on borderline set does not rise across the RL climb (alignment-tax
check) while harmful-compliance stays 0; both tracked in `rl.safety.*` metrics.

## T12R.4 — EG-gated evaluation of the whole climb

An RL climb is a candidate like any other lever: compare against the SFT-only baseline via
`efficiency_gain.py` on the frozen eval snapshot (T10.6), at two ladder rungs (nano, mini)
before any base1b RL is considered. Per `ORCHESTRATION.md` gates: EG trend across both rungs
> 1 or the recipe does not advance — a single-rung win is explicitly insufficient
(rank-invariance finding).

## Non-goals (recorded so they aren't re-litigated)

- No MoE/LatentMoE, no periodic-attention rework — arch candidates live in spec 11.
- No R_lang until a multilingual corpus exists (w_lang stays 0).
- No PPO/DPO/TRL dependency for the first implementation.
- No RL on chat branch until math proves the loop (chat lacks dense verifiable returns).

## VRAM sketch (mini 171M, 4080 12GB)

Policy fp32/bf16 ~0.7GB + old-policy logprobs cached (no second live model) + grads + AdamW8bit
~2.1GB + G=8 rollout KV at seq 1024 ~1GB + activations ≈ 5–6GB — fits with headroom. base1b
(1409M): policy+opt ~8.4GB before rollouts — **same open risk #1 as everything else at that
scale**; do not plan base1b RL until the VRAM trim (spec 11) lands.
