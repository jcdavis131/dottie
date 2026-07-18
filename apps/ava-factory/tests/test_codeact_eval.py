# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct eval (spec 13 T13C.3) — real sandbox scoring; honest real-mode; seed-sensitive plumbing."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evals.codeact_eval import (  # noqa: E402
    CODEACT_BAR, held_out, run_codeact_eval, score_emission, simulate_policy_eval,
)

POSIX = os.name == "posix"
pytestmark = pytest.mark.skipif(not POSIX, reason="sandbox resource caps require POSIX")


class TestScoringEngine:
    def test_gold_trajectory_scores_success(self):
        for traj in held_out(12):
            assert score_emission(traj.blocks, traj.answer, traj.tool_sources) is True

    def test_wrong_answer_scores_failure(self):
        traj = held_out(1)[0]
        assert score_emission(["0"], traj.answer, traj.tool_sources) is False

    def test_trailing_error_is_failure_not_stale_success(self):
        # final-block-outcome semantics: a correct value followed by an erroring block = failure
        assert score_emission(["x = 20 + 8", "x", "undefined_name_xyz"], "28") is False

    def test_final_block_success_required(self):
        assert score_emission(["x = 20 + 8", "x"], "28") is True

    def test_empty_trajectory_is_failure(self):
        assert score_emission([], "28") is False


class TestSimulation:
    def test_perfect_policy_scores_one(self):
        r = simulate_policy_eval(n=15, accuracy=1.0)
        assert r["measured"]["success_rate"] == 1.0 and r["pass"] is True
        # unmistakably a plumbing check, not a capability measurement
        assert r["test"] == "codeact_simulation" and r["capability"] is False

    def test_zero_accuracy_scores_zero(self):
        r = simulate_policy_eval(n=15, accuracy=0.0)
        assert r["measured"]["success_rate"] == 0.0 and r["pass"] is False

    def test_corruption_never_scores_gold(self):
        # structural (not coincidental): the sentinel can't equal any family's gold answer
        from evals.codeact_eval import _corrupt
        for traj in held_out(20):
            assert score_emission(_corrupt(traj.blocks), traj.answer, traj.tool_sources) is False

    def test_success_rate_from_real_execution_varies_by_seed(self):
        a = simulate_policy_eval(n=30, accuracy=0.5, seed=1)["measured"]["success_rate"]
        b = simulate_policy_eval(n=30, accuracy=0.5, seed=2)["measured"]["success_rate"]
        assert a != b   # computed from real execution under a seeded policy, not a constant

    def test_broken_tool_binding_drops_score(self):
        # With tool_binding_ok=False the lookup-family trajectories can't resolve their tool → fail,
        # so a perfect-accuracy policy no longer scores 1.0. Guard: the frozen draw must actually
        # contain tool-family trajectories, else the sensitivity check is vacuous.
        assert any(t.tool_sources for t in held_out(40)), "draw has no tool-family trajectories"
        full = simulate_policy_eval(n=40, accuracy=1.0, tool_binding_ok=True)["measured"]["success_rate"]
        broken = simulate_policy_eval(n=40, accuracy=1.0, tool_binding_ok=False)["measured"]["success_rate"]
        assert broken < full


class TestRealModeHonesty:
    def test_real_mode_fails_honestly_not_fabricated(self):
        # now wired to the T13C.5 decode loop: it fails at the honest gate (no real policy/GPU),
        # not via a hand-written 'not implemented' string.
        out = run_codeact_eval(model=object(), tokenizer=object())
        assert out["pass"] is False and out["measured"] is None
        assert "BLOCKED_NO_GPU" in out["error"]
