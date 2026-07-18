# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct return terms (spec 13 T13C.4) — reward components computed from real sandbox logs."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ava.rl.codeact_rewards import (  # noqa: E402
    ReturnWeights, codeact_return, r_codeuse, r_exec, r_len, redundant_calls,
)
from ava.rl.codeact_sandbox import Observation  # noqa: E402


def obs(ok=True, tool_calls=None):
    return Observation(stdout="", value=("1" if ok else None),
                       error=(None if ok else "ZeroDivisionError: division by zero"),
                       tool_calls=tool_calls or [])


class TestRExec:
    def test_all_clean_is_one(self):
        assert r_exec([obs(), obs(), obs()]) == 1.0

    def test_one_error_lowers(self):
        assert r_exec([obs(ok=False), obs()]) == 0.5   # the recover family's shape

    def test_empty_is_zero(self):
        assert r_exec([]) == 0.0


class TestRCodeuse:
    def _call(self, tool, *args):
        return {"tool": tool, "args": [str(a) for a in args], "kwargs": {}}

    def test_no_tools_is_neutral(self):
        assert r_codeuse([obs(), obs()]) == 0.0

    def test_single_call_dampened(self):
        # one call can't demonstrate 'independent tool use' → dampened, not full 1.0
        assert r_codeuse([obs(tool_calls=[self._call("lookup", "A")])]) == 0.5

    def test_distinct_calls_full_reward(self):
        o = obs(tool_calls=[self._call("lookup", "A"), self._call("lookup", "B")])
        assert r_codeuse([o]) == 1.0
        assert redundant_calls([o]) == 0

    def test_duplicate_penalized(self):
        # 2 identical calls = fully duplicated → floor -1.0 (dup=1, denom=len-1=1)
        o = obs(tool_calls=[self._call("lookup", "A"), self._call("lookup", "A")])
        assert redundant_calls([o]) == 1
        assert r_codeuse([o]) == -1.0

    def test_interleaved_duplicates_caught(self):
        # the old consecutive-only definition rewarded A,B,A,B with 1.0 — the redesign catches it
        calls = [self._call("t", "A"), self._call("t", "B"),
                 self._call("t", "A"), self._call("t", "B")]
        assert redundant_calls([obs(tool_calls=calls)]) == 2
        assert r_codeuse([obs(tool_calls=calls)]) == pytest.approx(1.0 - 2 * 2 / 3)  # dup=2, denom=3

    def test_fully_duplicated_hits_floor(self):
        assert r_codeuse([obs(tool_calls=[self._call("t", "x")] * 4)]) == -1.0  # dup=3, denom=3

    def test_error_step_retry_not_penalized(self):
        # identical call re-issued after a FAILED step is a legit retry, not redundancy
        a = obs(ok=False, tool_calls=[self._call("t", "x")])   # errored step's call is skipped
        b = obs(ok=True, tool_calls=[self._call("t", "x")])
        assert redundant_calls([a, b]) == 0
        assert r_codeuse([a, b]) == 0.5   # only one counted call → dampened, not penalized

    def test_redundancy_spans_steps(self):
        a = obs(tool_calls=[self._call("t", "x")])
        b = obs(tool_calls=[self._call("t", "x")])   # same call, next step (both ok)
        assert redundant_calls([a, b]) == 1


class TestRLen:
    def test_non_positive(self):
        assert r_len(200, 0.8) <= 0.0

    def test_difficulty_scaling(self):
        # easy family (high pass rate) penalized MORE than a hard one for the same length
        easy = r_len(300, family_pass_rate=0.9)
        hard = r_len(300, family_pass_rate=0.1)
        assert easy < hard <= 0.0

    def test_bounded_below(self):
        # unbounded length must NOT drive r_len below -1.0 (else task-dominance breaks)
        assert r_len(10**9, family_pass_rate=1.0) == -1.0

    def test_clamps_pass_rate(self):
        assert r_len(100, 5.0) == r_len(100, 1.0)  # >1 clamped
        assert r_len(100, -1.0) == 0.0             # <0 clamped → no penalty


class TestBlend:
    def test_task_dominates_exec_hack(self):
        w = ReturnWeights()
        # correct+terse (task=1, few blocks) must outrank wrong+many-valid-statements (task=0)
        correct = codeact_return(1.0, [obs()], token_count=20, family_pass_rate=0.5, weights=w)
        hack = codeact_return(0.0, [obs(), obs(), obs(), obs()], token_count=20,
                              family_pass_rate=0.5, weights=w)
        assert correct > hack

    def test_task_dominates_for_LONG_correct_solution(self):
        # regression for the unbounded-r_len bug: a very long correct solution (worst case:
        # errored blocks + redundant calls + huge length) must STILL beat a short clean wrong one.
        c = obs(tool_calls=[])
        worst_correct = codeact_return(
            1.0, [obs(ok=False), obs()], token_count=10**9, family_pass_rate=1.0)
        best_wrong = codeact_return(
            0.0, [c, obs(tool_calls=[{"tool": "a", "args": ["1"], "kwargs": {}},
                                     {"tool": "b", "args": ["2"], "kwargs": {}}])],
            token_count=10, family_pass_rate=0.0)
        assert worst_correct > best_wrong

    def test_return_is_finite_number(self):
        v = codeact_return(1.0, [obs(), obs(ok=False)], token_count=120, family_pass_rate=0.7)
        assert isinstance(v, float)


class TestIntegrationWithSandbox:
    """Rewards computed from REAL trajectory executions (not synthetic Observations)."""

    def test_clean_vs_recover_trajectory_exec_reward(self):
        import os
        import pytest
        if os.name != "posix":
            pytest.skip("sandbox caps require POSIX")
        from ava.datagen.codeact import iter_trajectories
        from ava.rl.codeact_sandbox import Sandbox

        def run(traj):
            with Sandbox(tool_sources=traj.tool_sources, max_steps=8) as vm:
                return [vm.step(b) for b in traj.blocks]

        trajs = list(iter_trajectories(seed=1, n=40))
        recover = next(t for t in trajs if t.concept == "codeact_recover")
        compute = next(t for t in trajs if t.concept == "codeact_compute")
        # recover's first block errors → r_exec < 1; compute is clean → r_exec == 1
        assert r_exec(run(recover)) < 1.0
        assert r_exec(run(compute)) == 1.0
