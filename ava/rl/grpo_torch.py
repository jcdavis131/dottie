# Solo personal project, no connection to employer, built with public/free-tier only
"""Torch GRPO-lite optimizer step (spec 12 T12R.2 / spec 13 T13C.4 — the autograd half).

`ava.rl.grpo` holds the torch-free *spec*: `clipped_surrogate` defines, in pure Python floats,
the exact per-sample objective the update must maximize (two-layer clip: outer circuit breaker
first, then the asymmetric PPO clip with its two intentionally-unclipped zones). This module is
the autograd implementation of that spec plus the surrounding optimizer step:

  * `clipped_surrogate_torch`          — tensorized surrogate; MUST be numerically identical to
                                         `grpo.clipped_surrogate` per sample (the parity test in
                                         tests/test_grpo_torch.py enforces <=1e-6).
  * `importance_weighted_entropy_torch`— torch mirror of `grpo.importance_weighted_entropy`,
                                         the self-normalized IS estimate of H_policy that feeds
                                         the entropy thermostat.
  * `TorchGRPOStep`                    — one full GRPO update: forward for new log-probs,
                                         thermostat update -> clip bounds, per-rollout importance
                                         ratio, negated-mean-objective loss, backward, optimizer
                                         step, and per-step stats (`rl.outer_clip_hits` etc).

Design decisions (documented per the mission brief):

  * **Ratio aggregation** — per-token importance ratios r_t = exp(logp_new_t − logp_old_t) are
    aggregated to ONE ratio per rollout by a mask-weighted arithmetic MEAN over that rollout's
    tokens. The mean (rather than exp of the summed log-ratio, i.e. the full-sequence product)
    keeps the rollout ratio on the same O(1) scale regardless of sequence length, so a single
    (lower, upper, r_outer) clip band applies uniformly — this is the GRPO-style sequence-level
    variant. The clipped surrogate is then applied once per rollout with that rollout's
    group-normalized advantage.
  * **Policy-agnostic** — `TorchGRPOStep` accepts ANY `nn.Module` that maps its inputs to
    per-token logits over actions: a Tensor output, or a Mapping output (an AvaModel-shaped
    dict; the logits key defaults to 'lm_logits'), or a custom `logits_extractor`. No AvaModel
    import here; the real model plugs in later unchanged.
  * **Gradient safety** — both clamps use `torch.clamp` (zero gradient outside the bounds), and
    the per-token LOG-ratio is additionally capped at `log(1+r_outer)+1` BEFORE exponentiating:
    a float32 `exp` overflow to inf would keep the forward finite (the outer clamp) but NaN the
    backward (`0·inf` through exp) — so the cap, not the outer clamp alone, is what makes a
    runaway ratio contribute a FINITE objective and a TRUE ZERO gradient. Together they satisfy
    the spec-12 accept criterion "a spike trips the outer clip and training continues without
    NaN" in both the forward and the backward pass.
  * **Thermostat wiring** — each step estimates H_policy from the current forward's log-probs
    (detached; the estimator is controller input, never part of the loss — spec 12 mandates no
    entropy-bonus/KL term), calls `thermostat.update(H)`, then takes THIS step's clip bounds
    from `thermostat.clip_bounds()` so the controller's widening applies immediately (matching
    `grpo.group_surrogate_objective`). A non-finite H estimate — only possible during the exact
    ratio blow-up the breaker exists for — is NOT fed to the controller (it would poison the
    integral state); it is reported in the stats as-is and the thermostat holds its k.

Naming per the spec-12/13 guard: RL scalars are `rl_return`/`R_*`; `reward` stays the
data-quality filter score; step metrics use the `rl.*` names in `GRPOStepStats`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional, Tuple, Union

import torch
from torch import Tensor, nn

from ava.rl.grpo import EntropyThermostat

__all__ = [
    "clipped_surrogate_torch",
    "importance_weighted_entropy_torch",
    "GRPOStepStats",
    "TorchGRPOStep",
]


def clipped_surrogate_torch(
    ratio: Tensor,
    advantage: Tensor,
    *,
    lower: float,
    upper: float,
    r_outer: float,
) -> Tuple[Tensor, Tensor, Tensor]:
    """Tensorized two-layer clipped surrogate — the autograd twin of `grpo.clipped_surrogate`.

    Element-for-element this computes the *identical* scalar as the pure-math spec (parity
    enforced to <=1e-6 by the tests; in float64 the operations are the same IEEE ops, so the
    match is exact):

      Layer 1 — outer circuit breaker: r_safe = clamp(ratio, 1−r_outer, 1+r_outer), applied
      FIRST and unconditionally, so no pathological importance ratio (spike, inf from exp
      overflow) can inject an unbounded update. Gradient is zero where it fires.

      Layer 2 — asymmetric PPO clip: objective = min(r_safe·A, clamp(r_safe, lower, upper)·A).
      The `min` leaves the two source-recipe zones unclipped: A>0 with r<lower (active
      correction) and A<0 with r>upper (active abandonment).

    Args:
        ratio:     per-rollout importance ratios, shape [B]. May be inf on a blow-up — the
                   outer clamp maps that to a finite bound with zero gradient.
        advantage: per-rollout group-normalized advantages (`grpo.group_advantages`), shape [B].
                   Must be detached — advantages are data, not a gradient path.
        lower/upper: this step's clip bounds from `EntropyThermostat.clip_bounds()`.
        r_outer:   circuit-breaker half-width (|r−1| <= r_outer).

    Returns:
        (objective [B] — per-sample objective to MAXIMIZE (caller negates the mean for the loss),
         inner_clipped [B] bool — standard clip was the binding (strictly smaller) branch,
         outer_clipped [B] bool — the breaker clamped this sample's ratio).
    """
    outer_lo, outer_hi = 1.0 - r_outer, 1.0 + r_outer
    r_safe = torch.clamp(ratio, min=outer_lo, max=outer_hi)
    outer_clipped = r_safe != ratio

    clipped_ratio = torch.clamp(r_safe, min=lower, max=upper)
    unclipped_obj = r_safe * advantage
    clipped_obj = clipped_ratio * advantage
    objective = torch.minimum(unclipped_obj, clipped_obj)
    inner_clipped = clipped_obj < unclipped_obj  # strict, matching the pure-math flag
    return objective, inner_clipped, outer_clipped


def importance_weighted_entropy_torch(
    logp_new: Tensor,
    logp_old: Tensor,
    mask: Optional[Tensor] = None,
) -> float:
    """Torch mirror of `grpo.importance_weighted_entropy` (same semantics, mask-aware).

    Self-normalized importance-sampling estimate of the CURRENT policy's per-token entropy from
    rollouts drawn under the OLD policy: w_i = exp(logp_new_i − logp_old_i),
    H ≈ Σ w_i·(−logp_new_i) / Σ w_i, over the mask-selected tokens. Computed in float64 on
    detached tensors — this feeds the thermostat (a controller), never the loss.

    Returns 0.0 for an empty selection or non-positive weight sum (the pure-math contract).
    May return inf/nan if the weights overflow during a ratio blow-up; `TorchGRPOStep` guards
    the thermostat against exactly that (see module docstring).
    """
    if logp_new.shape != logp_old.shape:
        raise ValueError("logp_new and logp_old must have the same shape (one per rollout token)")
    ln = logp_new.detach().double().reshape(-1)
    lo = logp_old.detach().double().reshape(-1)
    if mask is not None:
        keep = mask.detach().reshape(-1).bool()
        ln, lo = ln[keep], lo[keep]
    if ln.numel() == 0:
        return 0.0
    weights = torch.exp(ln - lo)
    wsum = float(weights.sum())
    if wsum <= 0.0:
        return 0.0
    return float((weights * (-ln)).sum()) / wsum


@dataclass(frozen=True)
class GRPOStepStats:
    """Measured per-step metrics (all computed from this step's tensors — nothing synthesized).

    Field ↔ metric-name mapping per the spec-12 logging contract:
      loss              — the scalar actually backpropagated: −mean(objective).
      mean_objective    — mean per-rollout surrogate objective (the maximized quantity).
      rl_entropy        — `rl.entropy`: importance-weighted H_policy estimate fed to the
                          thermostat (nan/inf if the estimator overflowed this step, in which
                          case the thermostat was NOT updated).
      rl_k              — `rl.k`: thermostat integral state AFTER this step's update.
      clip_lower/upper  — the bounds used for THIS step's surrogate.
      outer_clip_hits   — `rl.outer_clip_hits`: rollouts the circuit breaker clamped. Healthy
                          training keeps this ~0; nonzero is an alert, not a knob to raise.
      inner_clip_hits   — rollouts where the standard PPO clip was binding.
      mean_ratio        — mean per-rollout importance ratio BEFORE any clamp (may be inf on a
                          blow-up step — reported honestly).
      grad_norm         — global grad L2 norm (post-clip norm if max_grad_norm is set).
      batch_size        — rollouts in this step.
    """

    loss: float
    mean_objective: float
    rl_entropy: float
    rl_k: float
    clip_lower: float
    clip_upper: float
    outer_clip_hits: int
    inner_clip_hits: int
    mean_ratio: float
    grad_norm: float
    batch_size: int


PolicyInputs = Union[Tensor, Mapping[str, object]]


class TorchGRPOStep:
    """One real GRPO-lite gradient update for ANY torch policy (the step `grpo.GRPOOptimizerStep`
    honestly refuses to fake — this class is its implementation, wired by the orchestrator).

    Contract per call to `step()`:
      1. Forward the policy on `policy_inputs` → per-token logits over the action vocabulary.
      2. Gather log π_new(a_t) for the sampled `actions`; ratios r_t = exp(logp_new − logp_old)
         against the DETACHED old-policy log-probs recorded at rollout time.
      3. Update the entropy thermostat from the importance-weighted H_policy estimate; take
         this step's clip bounds from it (mis-tuned κ=0 degrades gracefully to fixed bounds).
      4. Aggregate ratios per rollout (mask-weighted token mean — see module docstring), apply
         `clipped_surrogate_torch` with the rollout's advantage, loss = −mean(objective).
      5. zero_grad → backward → (optional grad-norm clip) → optimizer.step().

    Tokenizer-agnostic: everything is plain tensors ([B] or [B,T] + optional mask); logits may
    be [B,V] (single-action rollouts) or [B,T,V]. The policy output may be a Tensor, a Mapping
    holding the logits under `logits_key` (default 'lm_logits', the AvaModel shape), or anything
    a custom `logits_extractor` can unwrap.
    """

    def __init__(
        self,
        policy: nn.Module,
        optimizer: torch.optim.Optimizer,
        thermostat: EntropyThermostat,
        *,
        r_outer: float,
        logits_key: str = "lm_logits",
        logits_extractor: Optional[Callable[[object], Tensor]] = None,
        max_grad_norm: Optional[float] = None,
    ) -> None:
        """Args:
            policy:           any nn.Module producing per-token action logits (see class doc).
            optimizer:        torch optimizer over `policy.parameters()` (AdamW8bit at scale;
                              anything torch-compatible here).
            thermostat:       the `grpo.EntropyThermostat` controller instance (its `k` is part
                              of this stepper's checkpoint state).
            r_outer:          outer circuit-breaker half-width (spec 12: conservative, ~5x eps).
            logits_key:       key to read when the policy returns a Mapping (AvaModel: 'lm_logits').
            logits_extractor: overrides the default Tensor/Mapping unwrapping entirely.
            max_grad_norm:    if set, `clip_grad_norm_` to this before the optimizer step.
        """
        self.policy = policy
        self.optimizer = optimizer
        self.thermostat = thermostat
        self.r_outer = float(r_outer)
        self.logits_key = logits_key
        self.logits_extractor = logits_extractor
        self.max_grad_norm = max_grad_norm
        # Per-token LOG-ratio cap (see step()): log(1+r_outer) + 1 keeps exp() far from float32
        # overflow (~88) for any sane r_outer while staying strictly ABOVE the outer bound in
        # ratio space, so the breaker's hit detection (r_safe != ratio) still fires on capped
        # runaway tokens that dominate their rollout mean.
        self._log_ratio_cap = math.log(1.0 + self.r_outer) + 1.0

    # ── internals ────────────────────────────────────────────────────────────

    def _extract_logits(self, out: object) -> Tensor:
        """Unwrap the policy's forward output to a logits Tensor ([B,V] or [B,T,V])."""
        if self.logits_extractor is not None:
            return self.logits_extractor(out)
        if isinstance(out, Tensor):
            return out
        if isinstance(out, Mapping):
            try:
                return out[self.logits_key]
            except KeyError as exc:
                raise KeyError(
                    f"policy output Mapping has no {self.logits_key!r} key; pass logits_key= "
                    f"or logits_extractor= (got keys {list(out.keys())})"
                ) from exc
        raise TypeError(
            f"cannot extract logits from policy output of type {type(out).__name__}; "
            "pass logits_extractor="
        )

    def _forward_logits(self, policy_inputs: PolicyInputs) -> Tensor:
        """Run the policy: Mapping inputs are splatted as kwargs (AvaModel's `input_ids=` style),
        anything else is passed positionally."""
        if isinstance(policy_inputs, Mapping):
            out = self.policy(**policy_inputs)
        else:
            out = self.policy(policy_inputs)
        return self._extract_logits(out)

    @staticmethod
    def _grad_l2_norm(policy: nn.Module) -> float:
        """Global L2 norm over all present grads (measured, for `grad_norm` when not clipping)."""
        norms = [p.grad.detach().norm() for p in policy.parameters() if p.grad is not None]
        if not norms:
            return 0.0
        return float(torch.linalg.vector_norm(torch.stack(norms)))

    # ── the update ───────────────────────────────────────────────────────────

    def step(
        self,
        policy_inputs: PolicyInputs,
        actions: Tensor,
        old_logp: Tensor,
        advantages: Tensor,
        mask: Optional[Tensor] = None,
    ) -> GRPOStepStats:
        """Perform one GRPO update; returns measured `GRPOStepStats`.

        Args:
            policy_inputs: whatever the policy's forward consumes (Tensor → positional,
                           Mapping → keyword args).
            actions:       sampled action token ids, LongTensor [B] or [B,T].
            old_logp:      log π_old(a_t) recorded at rollout time, same shape as `actions`.
                           Treated as constant data (detached defensively).
            advantages:    per-rollout advantages from `grpo.group_advantages`, shape [B].
                           Treated as constant data (detached defensively).
            mask:          optional [B,T] validity mask (1 = real token, 0 = padding). All-zero
                           rows contribute a zero ratio-numerator over a denominator floored at
                           1 (no div-by-zero); callers should not send empty rollouts.
        """
        logits = self._forward_logits(policy_inputs)
        if logits.dim() == 2:            # [B,V] → single-action rollouts, T=1
            logits = logits.unsqueeze(1)
        if logits.dim() != 3:
            raise ValueError(f"logits must be [B,V] or [B,T,V]; got shape {tuple(logits.shape)}")
        bsz, seq_len, _ = logits.shape

        actions2d = actions.reshape(bsz, seq_len)
        old_logp2d = old_logp.detach().reshape(bsz, seq_len).to(logits.dtype)
        adv = advantages.detach().reshape(bsz).to(logits.dtype)

        logp_all = torch.log_softmax(logits, dim=-1)
        new_logp = logp_all.gather(-1, actions2d.unsqueeze(-1)).squeeze(-1)   # [B,T]

        if mask is None:
            mask2d = torch.ones_like(new_logp)
        else:
            mask2d = mask.detach().reshape(bsz, seq_len).to(new_logp.dtype)

        # 3-mechanism wiring, part 1: thermostat first, so its widening applies to THIS step
        # (mirrors grpo.group_surrogate_objective using the controller's current bounds).
        h_policy = importance_weighted_entropy_torch(new_logp, old_logp2d, mask2d)
        if math.isfinite(h_policy):
            self.thermostat.update(h_policy)
        lower, upper = self.thermostat.clip_bounds()

        # Per-token ratios → mask-weighted MEAN per rollout (aggregation choice: module docstring).
        # The log-ratio is zeroed on masked positions BEFORE exp: exp() of a garbage pad-token
        # log-ratio can overflow to inf in float32, and inf·0 = nan would poison the whole rollout
        # even though the position is masked. exp(0)·0 = 0 keeps pads exactly inert.
        #
        # It is then CAPPED (max side) before exp for UNMASKED tokens too: float32 exp overflows
        # to inf around log-ratio ~88, and while the outer clamp keeps the FORWARD finite, its
        # backward through exp computes 0·inf = nan — a NaN'd policy after optimizer.step()
        # (adversarial-verifier finding, reproduced). Capping in LOG space changes nothing in the
        # forward (any capped value still exceeds the outer bound and clamps to the same number,
        # and the hit is still counted since cap > log(1+r_outer)) while making the runaway
        # token's gradient exactly zero — the breaker's contract, now true in the backward too.
        # The min side needs no cap: exp underflows to 0.0, which is finite with a ~0 gradient.
        log_ratio = (new_logp - old_logp2d) * mask2d                           # [B,T]
        log_ratio = log_ratio.clamp(max=self._log_ratio_cap)
        per_token_ratio = torch.exp(log_ratio) * mask2d                        # [B,T]
        token_counts = mask2d.sum(dim=1).clamp_min(1.0)                        # [B]
        rollout_ratio = per_token_ratio.sum(dim=1) / token_counts              # [B]

        objective, inner_clipped, outer_clipped = clipped_surrogate_torch(
            rollout_ratio, adv, lower=lower, upper=upper, r_outer=self.r_outer
        )
        loss = -objective.mean()   # surrogate is maximized; torch minimizes

        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        if self.max_grad_norm is not None:
            grad_norm = float(
                torch.nn.utils.clip_grad_norm_(self.policy.parameters(), self.max_grad_norm)
            )
        else:
            grad_norm = self._grad_l2_norm(self.policy)
        self.optimizer.step()

        return GRPOStepStats(
            loss=float(loss.detach()),
            mean_objective=float(objective.detach().mean()),
            rl_entropy=h_policy,
            rl_k=self.thermostat.k,
            clip_lower=lower,
            clip_upper=upper,
            outer_clip_hits=int(outer_clipped.sum()),
            inner_clip_hits=int(inner_clipped.sum()),
            mean_ratio=float(rollout_ratio.detach().mean()),
            grad_norm=grad_norm,
            batch_size=bsz,
        )

    # ── checkpointing ────────────────────────────────────────────────────────

    def state_dict(self) -> Dict[str, object]:
        """Full resumable state: policy + optimizer tensors and the thermostat's integral k.

        (kappa/h_target/eps/k_max are construction-time hyperparameters, not learned state —
        they live in the run config, so only `k` is checkpointed.)"""
        return {
            "policy": self.policy.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "thermostat_k": self.thermostat.k,
        }

    def load_state_dict(self, state: Mapping[str, object]) -> None:
        """Restore a `state_dict()` checkpoint in place (exact resume: policy weights,
        optimizer moments, thermostat integral state)."""
        self.policy.load_state_dict(state["policy"])          # type: ignore[arg-type]
        self.optimizer.load_state_dict(state["optimizer"])    # type: ignore[arg-type]
        self.thermostat.k = float(state["thermostat_k"])      # type: ignore[arg-type]
