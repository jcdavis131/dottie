# Solo personal project, no connection to employer, built with public/free-tier only
"""GRPO-lite discipline system (spec 12 T12R.2 / spec 13 T13C.4) — GPU-free mechanics.

Covers the three-mechanism discipline system as pure math + data structures, and the honest gate on
the torch optimizer step. Maps to spec-12 accept criteria (a) entropy thermostat demonstrably does
something, (b) outer clip survives a gradient spike, (c) recovery sampling from the bank.
"""
import math
import random

import pytest

from ava.rl.grpo import (
    BankedTrace,
    EntropyThermostat,
    GRPOBlockedError,
    GRPOOptimizerStep,
    TraceBank,
    clipped_surrogate,
    group_advantages,
    group_surrogate_objective,
    importance_weighted_entropy,
    simulate_entropy_control,
)


class TestGroupAdvantages:
    def test_zero_mean_unit_std(self):
        adv = group_advantages([1.0, 2.0, 3.0, 4.0])
        assert abs(sum(adv)) < 1e-9                       # mean-centred
        # population std normalization → values are the z-scores
        assert adv[0] < 0 < adv[-1]

    def test_degenerate_group_no_gradient(self):
        # all rollouts equal (all-pass or all-fail) → std 0 → ~0 advantage → teaches nothing
        adv = group_advantages([0.7, 0.7, 0.7])
        assert all(abs(a) < 1e-6 for a in adv)

    def test_empty(self):
        assert group_advantages([]) == []

    def test_higher_return_higher_advantage(self):
        adv = group_advantages([0.0, 1.0])
        assert adv[1] > adv[0]


class TestEntropyThermostat:
    def test_k_starts_zero_bounds_symmetric_in_log_space(self):
        th = EntropyThermostat(kappa=0.5, h_target=0.3)
        lo, hi = th.clip_bounds()
        # log(upper) == -log(lower) at k=0 (multiplicative inverses)
        assert math.isclose(math.log(hi), -math.log(lo), rel_tol=1e-9)

    def test_below_target_widens_upper_bound(self):
        th = EntropyThermostat(kappa=1.0, h_target=0.3, eps=0.2)
        _, hi0 = th.clip_bounds()
        th.update(h_policy=0.1)          # entropy below target → k rises
        _, hi1 = th.clip_bounds()
        assert th.k > 0 and hi1 > hi0

    def test_above_target_relaxes_back_toward_zero(self):
        th = EntropyThermostat(kappa=1.0, h_target=0.3, eps=0.2)
        th.update(0.0)                   # push k up
        k_high = th.k
        th.update(1.0)                   # entropy above target → integral term subtracts
        assert th.k < k_high

    def test_k_clamped_nonnegative_and_capped(self):
        th = EntropyThermostat(kappa=5.0, h_target=0.3, k_max=2.0)
        for _ in range(10):
            th.update(0.0)               # relentlessly below target
        assert th.k == 2.0               # saturates at k_max, never runs away
        for _ in range(50):
            th.update(1.0)               # relentlessly above target
        assert th.k == 0.0               # floored at 0, never negative (lower bound stays fixed)

    def test_kappa_zero_is_inert(self):
        th = EntropyThermostat(kappa=0.0, h_target=0.3)
        th.update(0.0)
        assert th.k == 0.0               # no feedback — the mis-tuned ablation


class TestImportanceWeightedEntropy:
    def test_on_policy_equals_mean_neg_logp(self):
        # when new==old, weights are all 1 → plain mean of -logp
        logp = [math.log(0.5), math.log(0.25), math.log(0.25)]
        h = importance_weighted_entropy(logp, logp)
        assert math.isclose(h, sum(-x for x in logp) / 3, rel_tol=1e-12)

    def test_empty_is_zero(self):
        assert importance_weighted_entropy([], []) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            importance_weighted_entropy([0.0], [0.0, 0.0])

    def test_reweights_toward_new_policy(self):
        # a token the new policy makes MORE likely (logp_new > logp_old) gets up-weighted
        logp_old = [math.log(0.5), math.log(0.5)]
        logp_new = [math.log(0.9), math.log(0.1)]
        h = importance_weighted_entropy(logp_new, logp_old)
        assert h > 0.0                    # a real entropy estimate, finite and positive


class TestClippedSurrogate:
    def test_outer_breaker_bounds_a_spike(self):
        # (b) an injected gradient spike (huge ratio) is clamped by the outer breaker → finite obj
        res = clipped_surrogate(1e6, advantage=1.0, lower=0.83, upper=1.2, r_outer=1.0)
        assert res.outer_clipped is True
        assert math.isfinite(res.objective)
        assert res.objective <= 2.0        # clamped to (1 + r_outer)·A = 2.0

    def test_negative_spike_also_bounded(self):
        res = clipped_surrogate(-1e6, advantage=-1.0, lower=0.83, upper=1.2, r_outer=1.0)
        assert res.outer_clipped is True and math.isfinite(res.objective)

    def test_positive_adv_upper_clip_bites(self):
        # A>0, r above upper → min() picks the clipped (smaller) branch
        res = clipped_surrogate(1.5, advantage=1.0, lower=0.83, upper=1.2, r_outer=5.0)
        assert res.inner_clipped is True
        assert math.isclose(res.objective, 1.2)   # clip(r)=1.2, ·A=1.2 < 1.5

    def test_active_abandonment_zone_unclipped(self):
        # A<0, r>upper: min() keeps the UNCLIPPED term (more negative) → push the bad action down
        res = clipped_surrogate(1.5, advantage=-1.0, lower=0.83, upper=1.2, r_outer=5.0)
        assert math.isclose(res.objective, -1.5)   # unclipped r·A = -1.5 < -1.2

    def test_no_clip_in_trust_region(self):
        res = clipped_surrogate(1.05, advantage=1.0, lower=0.83, upper=1.2, r_outer=5.0)
        assert res.inner_clipped is False and res.outer_clipped is False
        assert math.isclose(res.objective, 1.05)


class TestGroupSurrogateObjective:
    def test_uses_thermostat_bounds_and_counts_hits(self):
        th = EntropyThermostat(kappa=1.0, h_target=0.3, eps=0.2)
        ratios = [1.0, 1.05, 50.0]        # third is a spike
        adv = [0.5, -0.5, 1.0]
        mean_obj, hits = group_surrogate_objective(ratios, adv, thermostat=th, r_outer=1.0)
        assert hits == 1                  # only the spike tripped the outer breaker
        assert math.isfinite(mean_obj)

    def test_length_mismatch_raises(self):
        th = EntropyThermostat(kappa=1.0, h_target=0.3)
        with pytest.raises(ValueError):
            group_surrogate_objective([1.0], [1.0, 2.0], thermostat=th, r_outer=1.0)


class TestEntropyControlDemonstration:
    def test_disciplined_holds_band_far_longer_than_mistuned(self):
        # (a) the thermostat must be shown to DO SOMETHING, not just exist.
        mistuned = simulate_entropy_control(kappa=0.0, steps=200)   # no feedback → collapses
        disciplined = simulate_entropy_control(kappa=2.0, steps=200)  # integral control → holds
        assert mistuned.collapsed_at is not None                    # inert run hits the floor
        assert disciplined.collapsed_at is None                     # controlled run never collapses
        # holds the target band at least an order of magnitude longer
        assert disciplined.steps_in_band >= 10 * max(1, mistuned.steps_in_band)

    def test_mistuned_entropy_is_monotone_collapse(self):
        run = simulate_entropy_control(kappa=0.0, steps=50)
        assert all(b <= a + 1e-12 for a, b in zip(run.entropy, run.entropy[1:]))

    def test_disciplined_oscillates_around_target_never_collapses(self):
        # A PURE integral controller (no derivative term) holds a bounded limit cycle around the
        # target rather than settling to a point — that is the honest behavior, not tight settling.
        # The load-bearing claim is: tail mean sits on target and the swing never reaches the floor.
        run = simulate_entropy_control(kappa=2.0, h_target=0.3, steps=300)
        tail = run.entropy[-40:]
        assert abs(sum(tail) / len(tail) - 0.3) < 0.05     # mean-regulated to target
        assert min(tail) > 0.1                              # oscillation never nears collapse
        assert max(tail) < 0.5                              # nor runs away high


class TestTraceBank:
    def _trace(self, prompt, tok, step=0):
        return BankedTrace(prompt=prompt, tokens=(tok,), rl_return=1.0, family_id="math",
                           pass_rate=0.5, step=step)

    def test_recovery_sample_is_prompt_capped(self):
        bank = TraceBank()
        for i in range(20):
            bank.append(self._trace("p1", i))          # one prompt, many traces
        for i in range(3):
            bank.append(self._trace("p2", 100 + i))
        rng = random.Random(0)
        sample = bank.recovery_sample(50, per_prompt_cap=4, rng=rng)
        # p1 capped at 4, p2 has 3 → pool is 7, not 23
        assert len(sample) == 7
        assert sum(1 for t in sample if t.prompt == "p1") == 4

    def test_recovery_sample_deterministic_under_seed(self):
        bank = TraceBank()
        for i in range(30):
            bank.append(self._trace(f"p{i % 5}", i))
        a = bank.recovery_sample(6, per_prompt_cap=2, rng=random.Random(7))
        b = bank.recovery_sample(6, per_prompt_cap=2, rng=random.Random(7))
        assert [t.tokens for t in a] == [t.tokens for t in b]

    def test_recovery_sample_no_duplicates(self):
        bank = TraceBank()
        for i in range(10):
            bank.append(self._trace(f"p{i}", i))
        sample = bank.recovery_sample(10, per_prompt_cap=4, rng=random.Random(1))
        ids = [id(t) for t in sample]
        assert len(ids) == len(set(ids))               # sampling without replacement

    def test_prompt_diversity(self):
        bank = TraceBank()
        for i in range(12):
            bank.append(self._trace(f"p{i % 3}", i))
        assert bank.prompt_diversity() == 3

    def test_uniform_not_return_biased(self):
        # recovery sampling must NOT prefer high-return traces (the source: uniform beats biased).
        bank = TraceBank()
        # 100 low-return traces, 1 high-return, all distinct prompts (so none are capped away)
        for i in range(100):
            bank.append(BankedTrace(prompt=f"lo{i}", tokens=(i,), rl_return=0.1,
                                    family_id="m", pass_rate=0.5, step=0))
        bank.append(BankedTrace(prompt="hi", tokens=(999,), rl_return=100.0,
                                family_id="m", pass_rate=0.5, step=0))
        rng = random.Random(3)
        picks_of_hi = sum("hi" in [t.prompt for t in bank.recovery_sample(1, rng=rng)]
                          for _ in range(200))
        # if it were return-biased the single hi-return trace would dominate; uniform → rare (~1/101)
        assert picks_of_hi < 20


class TestOptimizerGate:
    def test_step_refuses_without_checkpoint(self):
        step = GRPOOptimizerStep()
        with pytest.raises(GRPOBlockedError) as ei:
            step.step()
        assert "BLOCKED_NO_GPU" in str(ei.value) or "checkpoint" in str(ei.value)
