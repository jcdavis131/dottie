# Solo personal project, no connection to employer, built with public/free-tier only
"""Pair-programming reward tests — stdlib-only, offline. Pure functions over PairTrace."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dottie.rl.pair_rewards import (
    PairTrace,
    PairWeights,
    pair_return,
    r_accept,
    r_quality,
    r_task_ok,
    r_time,
    r_tok,
    rank_key,
    task_ok,
    to_telemetry,
)


def ok(**kw):
    base = dict(task_passed=1.0, regression=False, user_signal="accept",
                edit_ratio=0.0, seconds=30.0, baseline_seconds=60.0,
                verifier_score=9.0, tokens=200, family_pass_rate=0.5)
    base.update(kw)
    return PairTrace(**base)


class TestTaskGate:
    def test_regression_zeroes_task(self):
        assert r_task_ok(ok(regression=True)) == 0.0

    def test_graded_pass_preserved(self):
        assert r_task_ok(ok(task_passed=0.7)) == 0.7

    def test_task_ok_binary(self):
        assert task_ok(ok()) == 1
        assert task_ok(ok(task_passed=0.0)) == 0
        assert task_ok(ok(regression=True)) == 0


class TestAccept:
    def test_accept_downgraded_by_edits(self):
        assert r_accept(ok(edit_ratio=0.5)) == pytest.approx(0.5)
        assert r_accept(ok(edit_ratio=1.0)) == pytest.approx(0.0)

    def test_accept_of_broken_code_is_neutral(self):
        assert r_accept(ok(task_passed=0.0, user_signal="accept")) == 0.0

    def test_reject_always_counts(self):
        assert r_accept(ok(task_passed=1.0, user_signal="reject")) == -1.0
        assert r_accept(ok(task_passed=0.0, user_signal="reject")) == -1.0

    def test_revert_is_full_negative(self):
        assert r_accept(ok(user_signal="revert")) == -1.0

    def test_silence_is_neutral(self):
        assert r_accept(ok(user_signal="none")) == 0.0

    def test_unknown_signal_neutral(self):
        assert r_accept(ok(user_signal="shrug")) == 0.0


class TestTime:
    def test_faster_than_baseline_positive(self):
        assert r_time(ok(seconds=30.0, baseline_seconds=60.0)) == pytest.approx(0.5)

    def test_slower_penalized_bounded(self):
        assert r_time(ok(seconds=600.0, baseline_seconds=60.0)) == -1.0

    def test_no_baseline_is_neutral(self):
        assert r_time(ok(baseline_seconds=0.0)) == 0.0

    def test_failed_task_no_time_credit(self):
        assert r_time(ok(task_passed=0.0, seconds=5.0)) == 0.0


class TestQuality:
    def test_centered_on_8(self):
        assert r_quality(ok(verifier_score=8.0)) == pytest.approx(0.0)
        assert r_quality(ok(verifier_score=10.0)) == pytest.approx(1.0)
        assert r_quality(ok(verifier_score=6.0)) == pytest.approx(-1.0)

    def test_wrong_solution_no_quality_credit(self):
        assert r_quality(ok(task_passed=0.0, verifier_score=10.0)) == 0.0


class TestTok:
    def test_easy_family_penalized(self):
        assert r_tok(ok(tokens=512, family_pass_rate=1.0)) == pytest.approx(-1.0)

    def test_hard_family_relaxed(self):
        assert r_tok(ok(tokens=512, family_pass_rate=0.0)) == pytest.approx(0.0)

    def test_bounded(self):
        assert r_tok(ok(tokens=10_000_000, family_pass_rate=1.0)) == -1.0


class TestBlend:
    def test_all_components_present(self):
        comps = pair_return(ok())
        assert set(comps) == {"r_task", "r_accept", "r_time", "r_quality", "r_tok", "total"}

    def test_dominance_via_rank_key(self):
        # A wrong-but-fast-and-liked trace must rank below a correct plain one.
        wrong = ok(task_passed=0.0, user_signal="accept", seconds=1.0, baseline_seconds=60.0,
                   verifier_score=10.0, tokens=10)
        right = ok(user_signal="none", seconds=600.0, baseline_seconds=60.0,
                   verifier_score=6.0, tokens=2000, family_pass_rate=1.0)
        assert rank_key(wrong) < rank_key(right)

    def test_correct_outranks_correct_tiebreak(self):
        a = ok(user_signal="accept", seconds=30.0)
        b = ok(user_signal="none", seconds=60.0)
        assert rank_key(a) > rank_key(b)

    def test_custom_weights(self):
        w = PairWeights(w_accept=0.5)
        comps = pair_return(ok(), w)
        assert comps["total"] == pytest.approx(
            1.0 + 0.5 * 1.0 + 0.15 * 0.5 + 0.15 * 0.5 + 0.10 * r_tok(ok()))

    def test_deterministic(self):
        assert pair_return(ok()) == pair_return(ok())


class TestTelemetry:
    def test_row_shape(self):
        row = to_telemetry(ok(), extra={"trace_id": "t1", "prompt": "p"})
        assert row["rl_return"] == pytest.approx(pair_return(ok())["total"])
        assert row["verdict"] == "pass"
        assert row["reward_components"]["r_task"] == 1.0
        assert row["trace_id"] == "t1"

    def test_fail_verdict(self):
        assert to_telemetry(ok(task_passed=0.0))["verdict"] == "fail"
