# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct EG-gated rollout (spec 13 T13C.6) — adapter over efficiency_gain.eg_trend.

Math tested on synthetic ladders (success-rate → error transform, per-rung EG, rank-invariance
verdict). The real verdict is honestly gated: it refuses the honest-fail eval records rather than
fabricating a capability rate.
"""
import pytest

from ava.rl.codeact_eg_gate import (
    CodeActEGGateBlockedError,
    RungLadder,
    codeact_eg_gate,
    codeact_eg_gate_from_eval,
    success_to_error,
)


class TestSuccessToError:
    def test_higher_success_lower_error(self):
        assert success_to_error(0.9) < success_to_error(0.5)

    def test_floor_clamps(self):
        assert success_to_error(1.0, error_floor=0.05) == 0.05   # perfect rate clamped to floor
        assert success_to_error(0.5, error_floor=0.05) == 0.5


def _efficient_ladder(rung: str, codeact_compute: float, codeact_sr: float) -> RungLadder:
    # baseline: error falls with compute (a real scaling curve). CodeAct reaches a good rate cheap.
    return RungLadder(
        rung=rung,
        baseline_points=[(1.0, 0.50), (2.0, 0.60), (4.0, 0.68), (8.0, 0.74)],
        codeact_compute=codeact_compute,
        codeact_success_rate=codeact_sr,
    )


class TestGateVerdict:
    def test_promote_when_codeact_more_efficient_at_both_rungs(self):
        # CodeAct hits a strong rate at low compute on both rungs, and the advantage does NOT shrink
        # with scale (mini's EG >= nano's) → rank-invariance satisfied → promote.
        ladders = [
            _efficient_ladder("nano", codeact_compute=1.5, codeact_sr=0.74),
            _efficient_ladder("mini", codeact_compute=1.0, codeact_sr=0.74),
        ]
        v = codeact_eg_gate(ladders)
        assert v["verdict"] == "promote"
        assert v["all_rungs_gt_1"] is True and v["largest_rung_not_worst"] is True
        assert v["mode"] == "codeact_vs_agentic_baseline"

    def test_hold_when_codeact_not_more_efficient(self):
        # CodeAct spends MORE compute than the baseline needs for its rate → EG < 1 → hold
        ladders = [
            RungLadder("nano", [(1.0, 0.50), (2.0, 0.60), (4.0, 0.68)],
                       codeact_compute=8.0, codeact_success_rate=0.55),
            RungLadder("mini", [(1.0, 0.50), (2.0, 0.60), (4.0, 0.68)],
                       codeact_compute=8.0, codeact_success_rate=0.55),
        ]
        v = codeact_eg_gate(ladders)
        assert v["verdict"] == "hold"
        assert v["all_rungs_gt_1"] is False

    def test_hold_on_single_rung_win_rank_invariance(self):
        # wins big on nano, loses on mini → rank-invariance says HOLD (the exact trap the gate guards)
        ladders = [
            _efficient_ladder("nano", codeact_compute=1.0, codeact_sr=0.74),
            RungLadder("mini", [(1.0, 0.50), (2.0, 0.60), (4.0, 0.68)],
                       codeact_compute=8.0, codeact_success_rate=0.55),
        ]
        v = codeact_eg_gate(ladders)
        assert v["verdict"] == "hold"

    def test_single_rung_is_insufficient(self):
        v = codeact_eg_gate([_efficient_ladder("nano", 1.0, 0.74)])
        assert v["verdict"] == "insufficient"


class TestHonestGate:
    def test_refuses_honest_fail_eval_records(self):
        # the records run_codeact_eval actually returns today (measured=None, gated)
        records = {
            "nano": {"test": "codeact", "measured": None, "pass": False, "error": "BLOCKED_NO_GPU"},
            "mini": {"test": "codeact", "measured": None, "pass": False, "error": "BLOCKED_NO_GPU"},
        }
        with pytest.raises(CodeActEGGateBlockedError) as ei:
            codeact_eg_gate_from_eval(records)
        assert "BLOCKED_NO_GPU" in str(ei.value) or "gated" in str(ei.value)

    def test_refuses_when_baseline_curve_absent_even_with_rates(self):
        # even if CodeAct rates existed, the baseline scaling curve is its own gated run
        records = {
            "nano": {"test": "codeact", "measured": {"success_rate": 0.7, "n": 20}, "pass": True},
            "mini": {"test": "codeact", "measured": {"success_rate": 0.72, "n": 20}, "pass": True},
        }
        with pytest.raises(CodeActEGGateBlockedError):
            codeact_eg_gate_from_eval(records)
