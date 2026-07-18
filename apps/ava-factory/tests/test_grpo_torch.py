# Solo personal project, no connection to employer, built with public/free-tier only
"""Tests for ava/rl/grpo_torch.py — the torch half of the GRPO-lite step (T13C.4).

The load-bearing test is EXACT PARITY: `ava.rl.grpo.clipped_surrogate` (pure math) is the spec,
and `clipped_surrogate_torch` must reproduce its per-sample objective to <=1e-6 across a grid
that exercises the outer breaker, the binding inner clip, and BOTH intentionally-unclipped
zones (active correction / active abandonment).

The learning demo is a SYNTHETIC contextual-bandit task (a 2-layer MLP, NOT Ava — it measures
nothing about Ava): its point is that the optimizer step, run for a few hundred real CPU steps,
raises a verifiable mean rl_return from near-chance toward 1.0 — measured, not asserted from
constants. The spike test injects a 1e6-scaled advantage batch and requires the outer circuit
breaker to fire with training continuing NaN-free (spec-12 accept criterion b).
"""

from __future__ import annotations

import math
import statistics

import pytest

torch = pytest.importorskip("torch")

from torch import nn  # noqa: E402

from ava.rl.grpo import (  # noqa: E402
    EntropyThermostat,
    clipped_surrogate,
    group_advantages,
    importance_weighted_entropy,
)
from ava.rl.grpo_torch import (  # noqa: E402
    TorchGRPOStep,
    clipped_surrogate_torch,
    importance_weighted_entropy_torch,
)

# ─────────────────────────────────────────────────────────────────────────────
# 1. EXACT PARITY: torch surrogate vs the pure-math spec
# ─────────────────────────────────────────────────────────────────────────────

# Ratios spanning: zero, deep-below-lower, exactly-at-bounds, in-band, above-upper,
# breaker-tripping spikes (50, 1e6).
_RATIOS = [0.0, 0.25, 0.5, 1.0 / 1.2, 0.9, 1.0, 1.1, 1.2, 1.5, 1.94, 2.0, 2.5, 5.0, 7.0, 50.0, 1e6]
_ADVS = [-3.0, -1.0, -0.4, 0.0, 0.4, 1.0, 3.0]
# Bounds come from real thermostat states (k=0 symmetric; k>0 upper relaxed; k saturated).
_THERMO_STATES = [
    EntropyThermostat(kappa=0.0, h_target=0.3, eps=0.2, k=0.0),
    EntropyThermostat(kappa=0.0, h_target=0.3, eps=0.2, k=0.5),
    EntropyThermostat(kappa=0.0, h_target=0.3, eps=0.1, k=4.0),
]
_R_OUTERS = [1.0, 2.0, 6.0]


def test_parity_torch_vs_pure_math_grid():
    """Per-sample torch objective must equal grpo.clipped_surrogate to <=1e-6 over the grid,
    with identical inner/outer clip flags. float64 → same IEEE ops as Python floats."""
    for thermo in _THERMO_STATES:
        lower, upper = thermo.clip_bounds()
        for r_outer in _R_OUTERS:
            pure = [
                clipped_surrogate(r, a, lower=lower, upper=upper, r_outer=r_outer)
                for r in _RATIOS
                for a in _ADVS
            ]
            ratios_t = torch.tensor([r for r in _RATIOS for _ in _ADVS], dtype=torch.float64)
            advs_t = torch.tensor([a for _ in _RATIOS for a in _ADVS], dtype=torch.float64)
            obj_t, inner_t, outer_t = clipped_surrogate_torch(
                ratios_t, advs_t, lower=lower, upper=upper, r_outer=r_outer
            )
            for i, res in enumerate(pure):
                assert abs(float(obj_t[i]) - res.objective) <= 1e-6, (
                    f"objective mismatch at ratio={float(ratios_t[i])} adv={float(advs_t[i])} "
                    f"bounds=({lower},{upper}) r_outer={r_outer}: "
                    f"torch={float(obj_t[i])} pure={res.objective}"
                )
                assert bool(inner_t[i]) == res.inner_clipped
                assert bool(outer_t[i]) == res.outer_clipped


def test_parity_grid_covers_all_four_zones():
    """The grid must actually exercise: outer breaker, binding inner clip, and the two
    intentionally-unclipped zones (A>0 & r<lower; A<0 & r>upper)."""
    lower, upper = _THERMO_STATES[0].clip_bounds()  # (1/1.2, 1.2)
    r_outer = 1.0

    # Spike trips the outer breaker.
    _, _, outer = clipped_surrogate_torch(
        torch.tensor([1e6]), torch.tensor([1.0]), lower=lower, upper=upper, r_outer=r_outer
    )
    assert bool(outer[0])

    # Binding inner clip: A>0, r>upper (within outer band).
    obj, inner, outer = clipped_surrogate_torch(
        torch.tensor([1.5], dtype=torch.float64), torch.tensor([1.0], dtype=torch.float64),
        lower=lower, upper=upper, r_outer=r_outer,
    )
    assert bool(inner[0]) and not bool(outer[0])
    assert abs(float(obj[0]) - upper * 1.0) <= 1e-12

    # Active correction (unclipped): A>0, r<lower → objective stays r·A.
    obj, inner, _ = clipped_surrogate_torch(
        torch.tensor([0.5], dtype=torch.float64), torch.tensor([1.0], dtype=torch.float64),
        lower=lower, upper=upper, r_outer=r_outer,
    )
    assert not bool(inner[0]) and abs(float(obj[0]) - 0.5) <= 1e-12

    # Active abandonment (unclipped): A<0, r>upper → objective stays r·A.
    obj, inner, _ = clipped_surrogate_torch(
        torch.tensor([1.5], dtype=torch.float64), torch.tensor([-1.0], dtype=torch.float64),
        lower=lower, upper=upper, r_outer=r_outer,
    )
    assert not bool(inner[0]) and abs(float(obj[0]) - (-1.5)) <= 1e-12


def test_parity_importance_weighted_entropy():
    """Torch estimator must match the pure-math estimator on the same rollout log-probs."""
    rng = torch.Generator().manual_seed(7)
    logp_new = -5.0 * torch.rand(64, generator=rng, dtype=torch.float64) - 0.05
    logp_old = -5.0 * torch.rand(64, generator=rng, dtype=torch.float64) - 0.05
    h_pure = importance_weighted_entropy(logp_new.tolist(), logp_old.tolist())
    h_torch = importance_weighted_entropy_torch(logp_new, logp_old)
    assert abs(h_pure - h_torch) <= 1e-9

    # Mask-aware path: masked-out tokens must be equivalent to deleting them.
    mask = torch.tensor([1.0, 0.0] * 32, dtype=torch.float64)
    keep = mask.bool()
    h_pure_masked = importance_weighted_entropy(logp_new[keep].tolist(), logp_old[keep].tolist())
    h_torch_masked = importance_weighted_entropy_torch(logp_new, logp_old, mask)
    assert abs(h_pure_masked - h_torch_masked) <= 1e-9

    # Contract edges shared with the pure version.
    assert importance_weighted_entropy_torch(torch.empty(0), torch.empty(0)) == 0.0
    with pytest.raises(ValueError):
        importance_weighted_entropy_torch(torch.zeros(3), torch.zeros(4))


# ─────────────────────────────────────────────────────────────────────────────
# 2. SYNTHETIC learning demo: contextual bandit (NOT Ava — labeled synthetic)
# ─────────────────────────────────────────────────────────────────────────────

_N_CTX = 4
_N_ACT = 4
# Verifiable ground truth: context c's correct action is (3c+1) mod 4 → rl_return 1.0 else 0.0.
_CORRECT = torch.tensor([(3 * c + 1) % _N_ACT for c in range(_N_CTX)])


class TinyBanditPolicy(nn.Module):
    """SYNTHETIC-TASK policy: 2-layer MLP over one-hot contexts → action logits.

    This is a toy contextual bandit for exercising the optimizer step on CPU. It is NOT Ava and
    measures nothing about Ava — but the learning it demonstrates is real (rl_return is computed
    from the sampled actions every step, never assumed)."""

    def __init__(self, n_ctx: int = _N_CTX, n_act: int = _N_ACT, hidden: int = 32) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(n_ctx, hidden), nn.Tanh(), nn.Linear(hidden, n_act))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def _bandit_batch(policy: nn.Module, group_size: int):
    """Sample one GRPO batch: each context repeated group_size times (the rollout group).

    Returns (inputs, actions, old_logp, advantages, rl_returns); old_logp is recorded under the
    CURRENT (pre-step) policy — the on-policy π_old. Advantages come from the pure-math
    grpo.group_advantages per context group."""
    ctx = torch.arange(_N_CTX).repeat_interleave(group_size)
    x = torch.nn.functional.one_hot(ctx, _N_CTX).to(torch.float32)
    with torch.no_grad():
        dist = torch.distributions.Categorical(logits=policy(x))
        actions = dist.sample()
        old_logp = dist.log_prob(actions)
    rl_returns = (actions == _CORRECT[ctx]).to(torch.float32)  # verifiable task return
    advs = torch.zeros(len(ctx))
    for c in range(_N_CTX):
        sl = slice(c * group_size, (c + 1) * group_size)
        advs[sl] = torch.tensor(group_advantages(rl_returns[sl].tolist()), dtype=torch.float32)
    return x, actions, old_logp, advs, rl_returns


def _train_bandit(*, steps: int, seed: int, lr: float = 0.05, group_size: int = 8,
                  r_outer: float = 1.0, h_target: float = 0.3, kappa: float = 0.05,
                  optimizer_cls=torch.optim.Adam):
    """Run the real GRPO loop on the synthetic bandit; returns (policy, stepper, history) where
    history[t] = (measured mean rl_return at step t, GRPOStepStats)."""
    torch.manual_seed(seed)
    policy = TinyBanditPolicy()
    optimizer = optimizer_cls(policy.parameters(), lr=lr)
    thermostat = EntropyThermostat(kappa=kappa, h_target=h_target)
    stepper = TorchGRPOStep(policy, optimizer, thermostat, r_outer=r_outer)
    history = []
    for _ in range(steps):
        x, actions, old_logp, advs, rl_returns = _bandit_batch(policy, group_size)
        stats = stepper.step(x, actions, old_logp, advs)
        history.append((float(rl_returns.mean()), stats))
    return policy, stepper, history


def test_learning_demo_rl_return_rises_from_chance():
    """SYNTHETIC-scale demo: mean rl_return must RISE from near-chance (0.25 for 4 actions)
    toward 1.0 over a few hundred CPU steps. Endpoints are measured window means of the actual
    per-step returns; the assertion is relative (final > initial + margin), not a magic value."""
    _, _, history = _train_bandit(steps=300, seed=0)
    returns = [r for r, _ in history]
    # Initial window is the first 3 steps only: at lr=0.05 the bandit starts improving within
    # ~10 steps, so a wider window would already contain learning (measured, not assumed).
    initial = statistics.fmean(returns[:3])
    final = statistics.fmean(returns[-20:])
    assert final > initial + 0.3, f"no learning: initial(3-step mean)={initial} final={final}"
    assert final > 0.8, f"did not approach solved: final(20-step mean)={final}"
    assert all(math.isfinite(s.loss) for _, s in history)
    assert all(math.isfinite(s.grad_norm) for _, s in history)


def test_spike_trips_outer_clip_and_training_survives():
    """Spec-12 accept criterion b: scale one batch's advantages by 1e6 → the outer circuit
    breaker must fire and training must continue WITHOUT NaN.

    SGD (whose update magnitude scales with the gradient, unlike Adam) makes the injected spike
    actually move the policy; re-stepping on the same batch with the SAME frozen old_logp
    (inner epochs) then produces genuinely runaway importance ratios."""
    policy, stepper, _ = _train_bandit(steps=2, seed=1, lr=0.5, optimizer_cls=torch.optim.SGD)

    x, actions, old_logp, advs, _ = _bandit_batch(policy, group_size=8)
    spiked_advs = advs * 1e6  # the injected loss spike
    total_outer_hits = 0
    for _ in range(3):  # inner epochs: ratios drift away from 1 after the first huge update
        stats = stepper.step(x, actions, old_logp, spiked_advs)
        total_outer_hits += stats.outer_clip_hits
        assert math.isfinite(stats.loss), f"loss went non-finite during spike: {stats}"
    assert total_outer_hits > 0, "1e6-advantage spike never tripped the outer clip"
    assert all(torch.isfinite(p).all() for p in policy.parameters()), "NaN/inf in params"

    # Training continues after the spike episode: 20 more normal steps, all finite.
    for _ in range(20):
        xb, ab, ob, advb, _ = _bandit_batch(policy, group_size=8)
        stats = stepper.step(xb, ab, ob, advb)
        assert math.isfinite(stats.loss)
    assert all(torch.isfinite(p).all() for p in policy.parameters())


def test_true_float32_exp_overflow_ratio_survives_backward():
    """Regression (adversarial-verifier HIGH finding): an UNMASKED token whose log-ratio would
    overflow float32 exp (~88) must NOT NaN the policy. Before the log-space cap, the outer
    clamp kept the FORWARD finite but the backward computed 0·inf = nan through exp, leaving
    NaN parameters after optimizer.step(). The cap (log(1+r_outer)+1, applied before exp) makes
    the runaway token's gradient a true zero. This drives the exact regime the standard spike
    test (1e6 advantages) never reaches."""
    policy, stepper, _ = _train_bandit(steps=2, seed=3, lr=0.5, optimizer_cls=torch.optim.SGD)
    x, actions, old_logp, advs, _ = _bandit_batch(policy, group_size=8)
    old_logp = old_logp.clone()
    old_logp[0] = -200.0  # log-ratio ≈ new_logp + 200 → exp overflows float32 without the cap

    stats = stepper.step(x, actions, old_logp, advs)
    assert math.isfinite(stats.loss), f"loss non-finite on overflow ratio: {stats}"
    assert math.isfinite(stats.mean_ratio), "capped ratio must be finite, not inf"
    assert stats.outer_clip_hits >= 1, "an overflow-scale ratio must still count as a breaker hit"
    for p in policy.parameters():
        assert torch.isfinite(p).all(), "params NaN'd — the log-ratio cap failed"
        if p.grad is not None:
            assert torch.isfinite(p.grad).all(), "grads NaN'd — 0·inf leaked through exp backward"

    # And training continues normally afterwards.
    for _ in range(5):
        xb, ab, ob, advb, _ = _bandit_batch(policy, group_size=8)
        assert math.isfinite(stepper.step(xb, ab, ob, advb).loss)
    assert all(torch.isfinite(p).all() for p in policy.parameters())


def test_thermostat_is_wired_into_the_step():
    """Discipline wiring: k must move when measured entropy sits below h_target, and the step's
    clip bounds must be the thermostat's (upper relaxed by (1+k))."""
    # h_target above the max possible entropy (log 4 ≈ 1.386) → every update raises k.
    _, stepper, history = _train_bandit(steps=10, seed=3, h_target=2.0, kappa=0.05)
    assert stepper.thermostat.k > 0.0
    ks = [s.rl_k for _, s in history]
    assert ks == sorted(ks) and ks[-1] > ks[0], f"k did not ratchet up: {ks}"
    last = history[-1][1]
    lower, upper = stepper.thermostat.clip_bounds()
    assert last.clip_lower == lower and last.clip_upper == upper
    assert all(math.isfinite(s.rl_entropy) for _, s in history)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Checkpoint round-trip
# ─────────────────────────────────────────────────────────────────────────────


def test_checkpoint_roundtrip(tmp_path):
    """state_dict → torch.save → fresh stepper → load must restore policy weights, optimizer
    moments, and thermostat k exactly; an identical further step must then produce identical
    parameters on both instances (proves optimizer state really round-tripped)."""
    policy, stepper, _ = _train_bandit(steps=20, seed=2, h_target=2.0)  # h_target>H ⇒ real k>0
    k_before = stepper.thermostat.k
    assert k_before > 0.0
    path = tmp_path / "grpo_step.pt"
    torch.save(stepper.state_dict(), path)

    torch.manual_seed(99)  # different init on purpose — load must overwrite it
    policy2 = TinyBanditPolicy()
    stepper2 = TorchGRPOStep(
        policy2,
        torch.optim.Adam(policy2.parameters(), lr=0.05),
        EntropyThermostat(kappa=0.05, h_target=2.0),
        r_outer=1.0,
    )
    stepper2.load_state_dict(torch.load(path))

    assert stepper2.thermostat.k == k_before
    for (n1, p1), (n2, p2) in zip(
        policy.state_dict().items(), policy2.state_dict().items()
    ):
        assert n1 == n2 and torch.equal(p1, p2), f"param {n1} not restored"

    # Deterministic continuation: same batch through both → identical resulting params.
    x, actions, old_logp, advs, _ = _bandit_batch(policy, group_size=8)
    s1 = stepper.step(x, actions, old_logp, advs)
    s2 = stepper2.step(x, actions, old_logp, advs)
    assert s1.loss == s2.loss
    for p1, p2 in zip(policy.parameters(), policy2.parameters()):
        assert torch.equal(p1, p2), "post-load step diverged — optimizer state not round-tripped"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Extension readiness: AvaModel-shaped policies (dict output, [B,T,V], mask, kwargs)
# ─────────────────────────────────────────────────────────────────────────────


class _DictSeqPolicy(nn.Module):
    """AvaModel-SHAPED toy (no AvaModel import): kwargs input, dict output with 'lm_logits'
    of shape [B,T,V]. Exercises the exact interface the real model will present."""

    def __init__(self, vocab: int = 11, dim: int = 8) -> None:
        super().__init__()
        self.emb = nn.Embedding(vocab, dim)
        self.head = nn.Linear(dim, vocab)

    def forward(self, input_ids: torch.Tensor):
        return {"lm_logits": self.head(self.emb(input_ids))}


def test_step_accepts_avamodel_shaped_policy_with_mask():
    """Mapping inputs, dict logits, [B,T] actions with padding mask: the step must run, ignore
    masked tokens in the rollout ratio (poisoned old_logp on pad positions must not trip any
    clip), and return finite stats."""
    torch.manual_seed(4)
    policy = _DictSeqPolicy()
    stepper = TorchGRPOStep(
        policy,
        torch.optim.SGD(policy.parameters(), lr=0.01),
        EntropyThermostat(kappa=0.05, h_target=0.3),
        r_outer=1.0,
    )
    bsz, seq, vocab = 6, 5, 11
    input_ids = torch.randint(0, vocab, (bsz, seq))
    actions = torch.randint(0, vocab, (bsz, seq))
    mask = torch.ones(bsz, seq)
    mask[:, -2:] = 0.0  # last two positions are padding

    with torch.no_grad():
        logp = torch.log_softmax(policy(input_ids=input_ids)["lm_logits"], dim=-1)
        old_logp = logp.gather(-1, actions.unsqueeze(-1)).squeeze(-1)
    # Poison the PAD positions: if the mask were ignored, exp(new−old) ≈ exp(100) would blow up
    # the rollout ratio and trip the outer clip.
    old_logp[:, -2:] = -100.0

    advs = torch.tensor(group_advantages([1.0, 0.0, 1.0, 0.0, 0.0, 1.0]), dtype=torch.float32)
    stats = stepper.step({"input_ids": input_ids}, actions, old_logp, advs, mask=mask)

    assert stats.batch_size == bsz
    assert stats.outer_clip_hits == 0, "mask ignored: poisoned pad tokens leaked into the ratio"
    assert abs(stats.mean_ratio - 1.0) <= 1e-5  # on-policy: masked mean ratio is exactly 1
    assert math.isfinite(stats.loss) and math.isfinite(stats.rl_entropy)


def test_step_rejects_unextractable_policy_output():
    """A policy returning something opaque must fail loudly, not silently mis-train."""

    class Opaque(nn.Module):
        def forward(self, x):
            return {"wrong_key": x}

    m = Opaque()
    stepper = TorchGRPOStep(
        m, torch.optim.SGD([torch.nn.Parameter(torch.zeros(1))], lr=0.1),
        EntropyThermostat(kappa=0.0, h_target=0.3), r_outer=1.0,
    )
    with pytest.raises(KeyError):
        stepper.step(torch.zeros(2, 3), torch.zeros(2, dtype=torch.long),
                     torch.zeros(2), torch.zeros(2))
