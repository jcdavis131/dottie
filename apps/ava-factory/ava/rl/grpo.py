# Solo personal project, no connection to employer, built with public/free-tier only
"""GRPO-lite discipline system (spec 12 T12R.2 / spec 13 T13C.4) — the GPU-free mechanics.

This module holds the *pure math and data structures* of the GRPO-lite loop's three-mechanism
discipline system, torch-free and fully testable today:

  1. Group advantage normalization  — `group_advantages`: A_i = (R_i − mean)/std over a rollout group.
  2. Entropy thermostat             — `EntropyThermostat`: integral controller k ← k + κ·(H_target − H)
                                       relaxing only the *upper* clip bound (1+ε)·(1+k).
  3. Outer ratio clip (breaker)     — `clipped_surrogate`: hard |r−1| ≤ r_outer clamp applied after
                                       and regardless of the standard clip's unclipped zones.
  4. Trace bank + recovery          — `TraceBank`: append verified rollouts; recovery sampling is
                                       prompt-deduped, per-prompt-capped, then UNIFORM random (the
                                       source's ablation: uniform beats biased selection).

What is deliberately NOT here (honestly gated, not stubbed): the torch policy, its log-probs, the
backward pass, and the AdamW step. `GRPOOptimizerStep` is a guard that *refuses* to run without a
real policy + a branch fine-tune checkpoint (T9.3/T9.5) — training is `BLOCKED_NO_GPU`. Every
number these functions return is computed from their inputs; nothing is fabricated. The one
"simulation" here (`simulate_entropy_control`) is a clearly-labeled synthetic *control-systems*
plant that demonstrates the thermostat is a working feedback controller — it is NOT a measurement
of Ava training and says so.

Naming per the spec-12/13 guard: RL scalars are `rl_return`/`R_*`; `reward` stays the data-quality
filter score elsewhere; metrics namespaced `rl.*` / `rl.codeact.*`.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# 1. Group-relative advantages (GRPO's baseline-free advantage)
# ─────────────────────────────────────────────────────────────────────────────

_ADV_STD_EPS = 1e-8  # guards divide-by-zero when a group's returns are all equal


def group_advantages(returns: Sequence[float], *, eps: float = _ADV_STD_EPS) -> List[float]:
    """GRPO advantage: A_i = (R_i − mean(R)) / (std(R) + eps) over one prompt's rollout group.

    No learned value function — the group itself is the baseline (that's the whole point of GRPO).
    A degenerate group (all returns equal, e.g. all-pass or all-fail) has std 0 → every advantage
    is ~0, i.e. *no gradient*, which is correct: a prompt the policy already solves (or can't touch)
    at every rollout teaches nothing this step. Population std (ddof=0), matching the group estimator.
    """
    n = len(returns)
    if n == 0:
        return []
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n
    std = math.sqrt(var)
    return [(r - mean) / (std + eps) for r in returns]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Entropy thermostat — integral controller on the upper clip bound
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class EntropyThermostat:
    """Integral controller that regulates policy entropy toward `h_target` by relaxing the *upper*
    PPO clip bound. Per step: k ← clamp(k + κ·(h_target − H_policy), 0, k_max).

    Entropy below target ⇒ (h_target − H) > 0 ⇒ k rises ⇒ upper bound (1+ε)·(1+k) widens ⇒ larger
    positive-advantage updates are admitted (forces exploration, fights collapse). Entropy above
    target ⇒ k falls back toward 0 ⇒ bounds tighten. There is deliberately **no entropy-bonus term
    in the loss and no KL penalty** — the trust-region width *is* the entropy control (the source
    recipe's key move). `k` is integral-only (accumulates error), clamped to [0, k_max].

    At k=0 the clip bounds are symmetric multiplicative inverses in log-ratio space: upper = (1+ε),
    lower = 1/(1+ε), so log(upper) = −log(lower). Only the upper bound relaxes; the lower is fixed.
    """

    kappa: float                 # integral gain κ (tuned on nano; the source used a 1T-scale value)
    h_target: float              # target per-token entropy H_target (start 0.3, retune on nano)
    eps: float = 0.2             # base clip half-width ε (the (1±ε) PPO band at k=0)
    k_max: float = 4.0           # saturation on the integral term (bounds the widest trust region)
    k: float = 0.0               # integral state; starts at 0 (bounds symmetric on step 0)

    def update(self, h_policy: float) -> float:
        """Advance the controller one step with the observed policy entropy; return the new k.

        With κ=0 this is a no-op (k stays 0) — that is the *mis-tuned* ablation the accept criterion
        contrasts against: no feedback, so nothing resists entropy collapse."""
        self.k = _clamp(self.k + self.kappa * (self.h_target - h_policy), 0.0, self.k_max)
        return self.k

    def clip_bounds(self) -> Tuple[float, float]:
        """Current (lower, upper) ratio-clip bounds. Lower fixed at 1/(1+ε); upper (1+ε)·(1+k)."""
        upper = (1.0 + self.eps) * (1.0 + self.k)
        lower = 1.0 / (1.0 + self.eps)
        return lower, upper


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


# ─────────────────────────────────────────────────────────────────────────────
# 3. Importance-weighted entropy estimator + the clipped surrogate with outer breaker
# ─────────────────────────────────────────────────────────────────────────────


def importance_weighted_entropy(logp_new: Sequence[float], logp_old: Sequence[float]) -> float:
    """Estimate H_policy = E_new[−log π_new] from rollouts drawn under π_old, via self-normalized
    importance sampling: weights w_i = exp(logp_new − logp_old), H ≈ Σ w_i·(−logp_new_i) / Σ w_i.

    The rollout group was sampled by the *old* policy, but we want the *current* policy's entropy;
    IS reweights without a fresh sample. Self-normalized (weights divided by their sum) so it is
    unbiased in the ratio and robust to an un-normalized weight scale. Empty input → 0.0."""
    if not logp_new:
        return 0.0
    if len(logp_new) != len(logp_old):
        raise ValueError("logp_new and logp_old must be the same length (one per rollout token)")
    weights = [math.exp(ln - lo) for ln, lo in zip(logp_new, logp_old)]
    wsum = sum(weights)
    if wsum <= 0.0:
        return 0.0
    return sum(w * (-ln) for w, ln in zip(weights, logp_new)) / wsum


@dataclass(frozen=True)
class SurrogateResult:
    """Per-sample surrogate objective (to be MAXIMIZED) plus which safety limits engaged."""
    objective: float
    inner_clipped: bool   # the standard PPO clip changed the effective ratio
    outer_clipped: bool   # the outer circuit-breaker had to clamp a runaway ratio


def clipped_surrogate(ratio: float, advantage: float, *, lower: float, upper: float,
                      r_outer: float) -> SurrogateResult:
    """One rollout's clipped-surrogate objective with the two-layer clip.

    Layer 1 — **outer circuit breaker** (applied FIRST, unconditionally): hard-clamp the raw ratio
    to [1−r_outer, 1+r_outer]. This runs *before* the standard clip and *regardless of* the
    intentionally-unclipped zones below, so a single pathological importance ratio (a gradient
    spike, a numerical blow-up) can never inject an unbounded update. In healthy training it never
    fires — a nonzero `rl.outer_clip_hits` rate is an alert, not a knob to raise.

    Layer 2 — **standard asymmetric PPO clip**: objective = min(r·A, clip(r, lower, upper)·A). The
    `min` leaves two zones intentionally unclipped (the source's design): when A>0 and r<lower
    (active correction — let a good-but-suppressed action recover) and when A<0 and r>upper (active
    abandonment — let a bad-but-inflated action be pushed down); the clip only bites where it would
    otherwise reward runaway confidence.

    Returns the per-sample objective (caller averages the group and MAXIMIZES; the torch loss is the
    negated mean). Torch-free: this is the exact scalar the autograd version must reproduce.
    """
    outer_lo, outer_hi = 1.0 - r_outer, 1.0 + r_outer
    r_safe = _clamp(ratio, outer_lo, outer_hi)
    outer_clipped = r_safe != ratio

    clipped_ratio = _clamp(r_safe, lower, upper)
    unclipped_obj = r_safe * advantage
    clipped_obj = clipped_ratio * advantage
    objective = min(unclipped_obj, clipped_obj)
    inner_clipped = clipped_obj < unclipped_obj  # the clip branch was the binding (smaller) one
    return SurrogateResult(objective=objective, inner_clipped=inner_clipped,
                           outer_clipped=outer_clipped)


def group_surrogate_objective(ratios: Sequence[float], advantages: Sequence[float], *,
                              thermostat: EntropyThermostat, r_outer: float
                              ) -> Tuple[float, int]:
    """Mean surrogate objective over a rollout group + the count of outer-clip hits.

    Uses the thermostat's *current* clip bounds (so the entropy controller's widening is applied to
    this step's update). Returns (mean_objective_to_maximize, outer_clip_hits) — the caller logs
    `rl.outer_clip_hits` and negates the mean for the torch loss."""
    if len(ratios) != len(advantages):
        raise ValueError("ratios and advantages must align (one per rollout)")
    if not ratios:
        return 0.0, 0
    lower, upper = thermostat.clip_bounds()
    total = 0.0
    hits = 0
    for r, a in zip(ratios, advantages):
        res = clipped_surrogate(r, a, lower=lower, upper=upper, r_outer=r_outer)
        total += res.objective
        hits += int(res.outer_clipped)
    return total / len(ratios), hits


# ─────────────────────────────────────────────────────────────────────────────
# 4. Trace bank + recovery sampling (uniform, prompt-deduped, per-prompt-capped)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BankedTrace:
    """A verified rollout worth banking for recovery SFT. `rl_return` and `pass_rate` are recorded
    at banking time; `verified_by` lets judge-graded traces be excluded if judge drift is suspected."""
    prompt: str
    tokens: Tuple[int, ...]
    rl_return: float
    family_id: str
    pass_rate: float
    step: int
    verified_by: str = "exec"   # "exec" | "judge"


@dataclass
class TraceBank:
    """In-memory trace bank implementing the spec-12 recovery-sampling rule.

    Only rollouts whose `verify_fn` passed should be appended (the caller enforces that). Recovery
    sampling — used when a checkpoint collapses — follows the source's ablation exactly: **uniform
    random beats biased selection**, so we (1) dedupe by prompt, (2) cap traces-per-prompt (prompt
    *diversity* matters more than per-prompt volume), (3) sample uniformly at random. No
    stratification, no return-weighting — those were the losing arms of the ablation."""

    traces: List[BankedTrace] = field(default_factory=list)

    def append(self, trace: BankedTrace) -> None:
        self.traces.append(trace)

    def __len__(self) -> int:
        return len(self.traces)

    def _prompt_capped_pool(self, per_prompt_cap: int, rng: random.Random) -> List[BankedTrace]:
        """Group by prompt; keep at most `per_prompt_cap` per prompt (uniformly sampled within a
        prompt when it overflows). Returns the flattened candidate pool — prompt-deduped in the
        sense that no single prompt can dominate."""
        by_prompt: Dict[str, List[BankedTrace]] = {}
        for t in self.traces:
            by_prompt.setdefault(t.prompt, []).append(t)
        pool: List[BankedTrace] = []
        for prompt in sorted(by_prompt):                 # sorted → deterministic given the rng
            group = by_prompt[prompt]
            if len(group) <= per_prompt_cap:
                pool.extend(group)
            else:
                pool.extend(rng.sample(group, per_prompt_cap))
        return pool

    def recovery_sample(self, n: int, *, per_prompt_cap: int = 4,
                        rng: Optional[random.Random] = None) -> List[BankedTrace]:
        """Draw up to `n` traces for recovery SFT: prompt-capped, then UNIFORM random (no bias).

        `rng` is required for reproducibility in tests/replay; if omitted a fresh unseeded Random is
        used (never `Math.random`-style global state). Returns fewer than `n` only if the capped
        pool is smaller than `n` (sampling without replacement — no duplicate traces in one draw)."""
        rng = rng or random.Random()
        pool = self._prompt_capped_pool(per_prompt_cap, rng)
        if n >= len(pool):
            out = list(pool)
            rng.shuffle(out)
            return out
        return rng.sample(pool, n)

    def prompt_diversity(self) -> int:
        """Number of distinct prompts banked — the quantity the sampling rule optimizes for."""
        return len({t.prompt for t in self.traces})


# ─────────────────────────────────────────────────────────────────────────────
# 5. Synthetic control-systems demonstration of the thermostat (NOT a training measurement)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class EntropyRunTrace:
    """Per-step record of a synthetic entropy-control run (for the demonstration + its test)."""
    entropy: List[float]
    k: List[float]
    steps_in_band: int          # steps H stayed within ±band of h_target
    collapsed_at: Optional[int]  # first step H hit the floor, or None if it never did


def simulate_entropy_control(*, kappa: float, h_target: float = 0.3, h_start: float = 0.6,
                             steps: int = 200, collapse_pressure: float = 0.02,
                             exploration_gain: float = 0.03, band: float = 0.05,
                             h_floor: float = 0.0, h_max: float = 1.0,
                             k_max: float = 4.0, eps: float = 0.2) -> EntropyRunTrace:
    """A **synthetic control-systems plant** demonstrating that the entropy thermostat is a working
    feedback controller — NOT a measurement of Ava training (there is no model here; the real nano
    run is gated on T9.3/T9.5 + GPU).

    Plant (deliberately simple and disclosed): greedy policy-gradient pressure concentrates the
    policy, draining entropy by `collapse_pressure` each step; a wider trust region (driven by the
    controller's k) injects exploration that restores entropy by `exploration_gain·k`:

        H_{t+1} = clamp(H_t − collapse_pressure + exploration_gain·k_t,  h_floor, h_max)
        k_t     = EntropyThermostat.update(H_t)          # k ← clamp(k + κ·(h_target − H_t), 0, k_max)

    With κ=0 the controller is inert (k≡0): H falls monotonically and collapses to the floor — the
    mis-tuned ablation. With κ>0 the integral term raises k as H drops below target, the restoring
    term engages, and H is mean-regulated to h_target in a bounded limit cycle (a pure-integral
    controller oscillates around the setpoint rather than settling to it — no derivative term, so
    this is expected, not a bug). The accept criterion "the disciplined run holds the band ≥ N×
    longer" is a real property of this servo; the point is to show the *mechanism does something*,
    honestly, without fabricating a real-training curve."""
    thermostat = EntropyThermostat(kappa=kappa, h_target=h_target, eps=eps, k_max=k_max)
    h = h_start
    entropy: List[float] = []
    ks: List[float] = []
    steps_in_band = 0
    collapsed_at: Optional[int] = None
    for t in range(steps):
        entropy.append(h)
        k = thermostat.update(h)
        ks.append(k)
        if abs(h - h_target) <= band:
            steps_in_band += 1
        if collapsed_at is None and h <= h_floor:
            collapsed_at = t
        h = _clamp(h - collapse_pressure + exploration_gain * k, h_floor, h_max)
    return EntropyRunTrace(entropy=entropy, k=ks, steps_in_band=steps_in_band,
                           collapsed_at=collapsed_at)


# ─────────────────────────────────────────────────────────────────────────────
# 6. The torch optimizer step — HONESTLY GATED (needs a real policy + branch checkpoint)
# ─────────────────────────────────────────────────────────────────────────────


class GRPOBlockedError(RuntimeError):
    """Raised when the real (torch) GRPO update is invoked without its prerequisites."""


@dataclass
class GRPOOptimizerStep:
    """The real policy-gradient update — INTENTIONALLY NOT IMPLEMENTED here.

    Everything above (advantages, thermostat, clipped surrogate, trace bank) is the torch-free
    scaffolding the real loop calls. The update itself — forward pass for log-probs, the clipped
    surrogate as a torch loss, backward, AdamW8bit step, checkpoint I/O — requires:
      • a branch fine-tune checkpoint to train (spec 12/13 dependency T9.3/T9.5 — does not exist), and
      • a GPU (training is BLOCKED_NO_GPU per the runbook).
    So `.step()` refuses rather than fabricating an update or silently no-op'ing. This is the honest
    boundary between the built (verified, GPU-free math) and the gated (the climb itself)."""

    policy: object = None
    checkpoint_path: Optional[str] = None

    def step(self, *args, **kwargs):
        raise GRPOBlockedError(
            "This placeholder never runs — the REAL torch GRPO step now exists: use "
            "ava.rl.grpo_torch.TorchGRPOStep (exact-parity clipped surrogate, thermostat/outer-"
            "clip wiring, backward + optimizer step; CPU-verified incl. spike/overflow NaN "
            "survival). The mechanical chain is proven end-to-end on the real smoke-scale pilot "
            "checkpoint by scripts/rl_smoke_update.py. What remains gated is CAPABILITY-scale "
            "training: mini+ branch checkpoints (T9.3/T9.5) need GPU wall-clock (BLOCKED_NO_GPU "
            "at that scale). Do not use this class; do not fabricate capability results."
        )
