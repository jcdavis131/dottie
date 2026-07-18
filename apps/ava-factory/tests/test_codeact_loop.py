# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct decode / serving loop (spec 13 T13C.5, GPU-free half).

Drives the loop with a model-free TrajectoryReplayPolicy against the REAL T13C.1 sandbox, proving
the serving accept criterion: a multi-step task runs end-to-end and only the sanitized FINAL is
returned (code + observations stay in the captured trace). Real-model policy is honestly gated.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ava.datagen.codeact import iter_trajectories  # noqa: E402
from ava.rl.codeact_loop import (  # noqa: E402
    ModelPolicy, ModelPolicyBlockedError, TrajectoryReplayPolicy, CodeActResult,
    extract_action, run_code_act, sanitize_final,
)
from ava.rl.codeact_rewards import r_exec  # noqa: E402

POSIX = os.name == "posix"
posix_only = pytest.mark.skipif(not POSIX, reason="sandbox resource caps require POSIX")


class TestParsing:
    def test_extract_first_python_fence(self):
        turn = "Thought: add them\n```python\nx = 2 + 2\nx\n```"
        assert extract_action(turn) == "x = 2 + 2\nx"

    def test_no_fence_is_final(self):
        assert extract_action("The answer is 42.") is None

    def test_only_first_fence_taken(self):
        turn = "```python\na = 1\n```\nthen\n```python\nb = 2\n```"
        assert extract_action(turn) == "a = 1"

    def test_sanitize_strips_labels_and_thought(self):
        assert sanitize_final("FINAL: 28") == "28"
        assert sanitize_final("Thought: so the total is 28") == "so the total is 28"
        assert sanitize_final("  Answer - 42  ") == "42"


class TestReplayLoopEndToEnd:
    @posix_only
    def test_multistep_task_runs_and_returns_only_final(self):
        traj = next(t for t in iter_trajectories(seed=1, n=40) if t.concept == "codeact_multistep")
        policy = TrajectoryReplayPolicy(traj)
        res = run_code_act(policy, traj.user, tool_sources=traj.tool_sources, max_steps=8)
        assert res.reached_final
        # only the FINAL reaches the user; the answer is present, code/observations are NOT leaked
        assert traj.answer in res.final
        assert "```python" not in res.final and "Observation" not in res.final
        # the full trace is captured separately for debugging / memory-mint
        assert len(res.steps) == len(traj.turns)
        assert all(s.code for s in res.steps)

    @posix_only
    def test_every_family_reaches_final_via_real_sandbox(self):
        for traj in iter_trajectories(seed=2, n=24):
            res = run_code_act(TrajectoryReplayPolicy(traj), traj.user,
                               tool_sources=traj.tool_sources, max_steps=8)
            assert res.reached_final, f"{traj.concept} did not reach FINAL"
            assert traj.answer in res.final

    @posix_only
    def test_observations_feed_reward_functions(self):
        # the loop's captured observations are exactly what codeact_rewards consumes
        traj = next(t for t in iter_trajectories(seed=3, n=40) if t.concept == "codeact_compute")
        res = run_code_act(TrajectoryReplayPolicy(traj), traj.user,
                           tool_sources=traj.tool_sources)
        assert r_exec(res.observations) == 1.0     # clean compute trajectory → all blocks ran

    @posix_only
    def test_recover_family_has_an_erroring_step_but_still_finals(self):
        traj = next(t for t in iter_trajectories(seed=1, n=60) if t.concept == "codeact_recover")
        res = run_code_act(TrajectoryReplayPolicy(traj), traj.user,
                           tool_sources=traj.tool_sources)
        assert res.reached_final and traj.answer in res.final
        assert any(not o.ok for o in res.observations)   # the first block genuinely errored
        assert r_exec(res.observations) < 1.0


class TestTerminalStates:
    @posix_only
    def test_step_cap_yields_no_fabricated_final(self):
        # a policy that only ever emits actions (never a FINAL) must hit the cap with final=None
        def action_only(_transcript: str) -> str:
            return "```python\n1 + 1\n```"
        res = run_code_act(action_only, "go", max_steps=3)
        assert res.terminated == "step_cap" and res.final is None
        assert len(res.steps) == 3

    @posix_only
    def test_empty_policy_turn_is_not_a_final(self):
        res = run_code_act(lambda _t: "", "go", max_steps=3)
        assert res.terminated == "policy_empty" and res.final is None


class TestRealModelGate:
    def test_model_policy_refuses_without_model(self):
        with pytest.raises(ModelPolicyBlockedError) as ei:
            ModelPolicy()("some transcript")
        assert "BLOCKED_NO_GPU" in str(ei.value)
