# Solo personal project, no connection to employer, built with public/free-tier only
"""efficiency_gain.py — fit, EG, ladder-trend verdicts. Pure stdlib, no model needed."""

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from efficiency_gain import EGResult, efficiency_gain, eg_trend, fit_power_law  # noqa: E402


def synth_curve(a=100.0, b=0.5, xs=(1e15, 1e16, 1e17, 1e18), floor=0.0):
    return [(x, a * x ** (-b) + floor) for x in xs]


class TestFit:
    def test_recovers_exact_power_law(self):
        fit = fit_power_law(synth_curve())
        assert math.isclose(fit.a, 100.0, rel_tol=1e-9)
        assert math.isclose(fit.b, 0.5, rel_tol=1e-9)

    def test_recovers_with_floor(self):
        fit = fit_power_law(synth_curve(floor=1.7), floor=1.7)
        assert math.isclose(fit.b, 0.5, rel_tol=1e-9)
        assert math.isclose(fit.loss_at(1e16), 100.0 * 1e16 ** -0.5 + 1.7, rel_tol=1e-9)

    def test_rejects_single_point(self):
        with pytest.raises(ValueError, match=">= 2 usable points"):
            fit_power_law([(1e15, 3.0)])

    def test_rejects_same_compute(self):
        with pytest.raises(ValueError, match="one compute value"):
            fit_power_law([(1e15, 3.0), (1e15, 2.0)])

    def test_rejects_non_improving_baseline(self):
        with pytest.raises(ValueError, match="does not improve"):
            fit_power_law([(1e15, 2.0), (1e16, 3.0)])  # loss rising with compute


class TestEG:
    def test_identical_to_baseline_is_one(self):
        fit = fit_power_law(synth_curve())
        r = efficiency_gain(fit, 1e16, fit.loss_at(1e16))
        assert math.isclose(r.eg, 1.0, rel_tol=1e-9)
        assert not r.extrapolated

    def test_better_candidate_gt_one_worse_lt_one(self):
        fit = fit_power_law(synth_curve())
        target = fit.loss_at(1e16)
        assert efficiency_gain(fit, 0.5e16, target).eg == pytest.approx(2.0, rel=1e-9)
        assert efficiency_gain(fit, 2e16, target).eg == pytest.approx(0.5, rel=1e-9)

    def test_flops_vs_time_decoupling(self):
        # Same candidate quality; algorithmic win (fewer FLOPs) but slow kernels (more secs).
        flops_fit = fit_power_law(synth_curve(xs=(1e15, 1e16, 1e17)))
        time_fit = fit_power_law([(x / 1e12, y) for x, y in synth_curve(xs=(1e15, 1e16, 1e17))])
        loss = flops_fit.loss_at(1e16)
        eg_flops = efficiency_gain(flops_fit, 0.7e16, loss).eg
        eg_time = efficiency_gain(time_fit, 1.5e4, loss).eg  # baseline equiv is 1e4 secs
        assert eg_flops > 1.0 > eg_time  # the DeltaNet/LatentMoE state: keep, but not shipped

    def test_below_floor_is_undefined(self):
        fit = fit_power_law(synth_curve(floor=1.7), floor=1.7)
        with pytest.raises(ValueError, match="irreducible floor"):
            efficiency_gain(fit, 1e18, 1.6)

    def test_extrapolation_flagged(self):
        fit = fit_power_law(synth_curve(xs=(1e15, 1e16)))
        r = efficiency_gain(fit, 1e17, fit.loss_at(1e18))
        assert r.extrapolated


def _res(label, eg):
    return (label, EGResult(label=label, eg=eg, candidate_compute=1.0,
                            candidate_loss=1.0, baseline_compute_equiv=eg, extrapolated=False))


class TestTrend:
    def test_single_rung_insufficient(self):
        assert eg_trend([_res("nano", 1.4)])["verdict"] == "insufficient"

    def test_consistent_win_promotes(self):
        assert eg_trend([_res("nano", 1.2), _res("mini", 1.3)])["verdict"] == "promote"

    def test_rank_inversion_holds(self):
        # Wins small, degrades at scale — the stem-heavy-mix trap.
        t = eg_trend([_res("nano", 1.5), _res("mini", 1.1), _res("base1b", 0.9)])
        assert t["verdict"] == "hold" and not t["all_rungs_gt_1"]

    def test_shrinking_but_positive_win_holds(self):
        t = eg_trend([_res("nano", 1.8), _res("mini", 1.4), _res("base1b", 1.05)])
        assert t["verdict"] == "hold" and t["all_rungs_gt_1"] and not t["largest_rung_not_worst"]


class TestCLI:
    def test_end_to_end_json(self, tmp_path):
        base = tmp_path / "base.jsonl"
        base.write_text("\n".join(json.dumps({"flops": x, "loss": y}) for x, y in synth_curve()))
        cand = tmp_path / "cand.jsonl"
        fit = fit_power_law(synth_curve())
        cand.write_text("\n".join([
            json.dumps({"label": "nano", "flops": 0.8e16, "loss": fit.loss_at(1e16)}),
            json.dumps({"label": "mini", "flops": 0.8e17, "loss": fit.loss_at(1e17)}),
        ]))
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / "efficiency_gain.py"),
             "--baseline", str(base), "--candidate", str(cand)],
            capture_output=True, text=True, check=True,
        )
        out = json.loads(proc.stdout)
        assert out["results"][0]["eg"] == pytest.approx(1.25, rel=1e-6)
        assert out["trend"]["verdict"] == "promote"
