"""Tests for efficiency_gain — PowerLawFit real math"""

import importlib.util

import pytest

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/efficiency_gain.py"
spec = importlib.util.spec_from_file_location("efficiency_gain", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

PowerLawFit = mod.PowerLawFit
fit_power_law = mod.fit_power_law
efficiency_gain = mod.efficiency_gain
eg_trend = mod.eg_trend


def test_fit_two_points_positive_b():
    points = [(1e12, 3.0), (2e12, 2.5)]
    fit = fit_power_law(points, floor=0.0)
    assert fit.b > 0
    assert fit.a > 0
    assert fit.n_points == 2


def test_loss_at_monotonic_decreasing():
    points = [(1.0, 10.0), (10.0, 5.0), (100.0, 2.0)]
    fit = fit_power_law(points)
    l1 = fit.loss_at(1.0)
    l2 = fit.loss_at(10.0)
    l3 = fit.loss_at(100.0)
    assert l1 > l2 > l3


def test_compute_to_reach_inverts_loss_at():
    points = [(1e9, 3.0), (1e10, 2.0)]
    fit = fit_power_law(points)
    x = 5e9
    loss = fit.loss_at(x)
    x_rev = fit.compute_to_reach(loss)
    assert abs(x - x_rev) / x < 1e-6


def test_compute_to_reach_below_floor_raises():
    points = [(1.0, 2.0), (2.0, 1.5)]
    fit = fit_power_law(points, floor=0.5)
    with pytest.raises(ValueError, match="floor"):
        fit.compute_to_reach(0.4)


def test_fit_requires_distinct_x():
    with pytest.raises(ValueError):
        fit_power_law([(1.0, 2.0), (1.0, 1.9)])


def test_efficiency_gain_and_trend():
    points = [(1e9, 3.0), (1e10, 2.0), (1e11, 1.5)]
    fit = fit_power_law(points)
    cand = efficiency_gain(fit, candidate_compute=5e9, candidate_loss=2.2, label="r1")
    assert cand.eg > 0
    assert cand.candidate_compute == 5e9
    r2 = efficiency_gain(fit, candidate_compute=2e10, candidate_loss=1.8, label="r2")
    verdict = eg_trend([("r1", cand), ("r2", r2)])
    assert "verdict" in verdict
    assert (
        verdict["rungs"] == 2
        if verdict["verdict"] == "insufficient"
        else "egs" in verdict
    )


def test_floor_subtraction():
    points = [(1.0, 2.0), (10.0, 1.2)]
    fit = fit_power_law(points, floor=1.0)
    assert fit.floor == 1.0
    assert fit.min_loss_seen > 1.0
