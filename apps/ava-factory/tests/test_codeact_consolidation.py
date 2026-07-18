# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct → MOPD consolidation trace-pool prep (spec 13 T13C.5, GPU-free half).

Verifies the two rules that distinguish consolidation from spec-12 recovery sampling: only verified
traces are admitted, and the pool is stratified (balanced) across families so rare grounding/refuse
behaviors aren't washed out. The GPU MOPD run itself is honestly gated.
"""
import pytest

from ava.rl.codeact_consolidation import (
    ConsolidationBlockedError,
    ConsolidationTrace,
    admit_trace,
    consolidate,
    mopd_consolidation_run,
)


def trace(prompt, family, verified=True, behavior="solve"):
    return ConsolidationTrace(prompt=prompt, rendered=f"<{prompt}>", answer="a",
                              family=family, verified=verified, behavior=behavior)


class TestAdmission:
    def test_unverified_never_admitted(self):
        assert admit_trace(trace("p", "codeact_compute", verified=False)) is False
        assert admit_trace(trace("p", "codeact_compute", verified=True)) is True

    def test_unverified_dropped_and_counted(self):
        traces = [trace("p1", "compute"), trace("p2", "compute", verified=False)]
        pool = consolidate(traces, balance=False)
        assert pool.dropped_unverified == 1
        assert all(t.verified for t in pool.traces)


class TestDedupe:
    def test_duplicate_prompts_collapsed(self):
        traces = [trace("same", "compute"), trace("same", "compute"), trace("other", "compute")]
        pool = consolidate(traces, balance=False)
        assert len(pool) == 2 and pool.dropped_duplicate == 1

    def test_dedupe_preserves_first_occurrence_order(self):
        traces = [trace("a", "compute"), trace("b", "compute"), trace("a", "compute")]
        pool = consolidate(traces, balance=False)
        assert [t.prompt for t in pool.traces] == ["a", "b"]


class TestStratification:
    def test_balances_to_smallest_family_by_default(self):
        # 10 compute, 2 recover → even split caps compute at 2 so recover isn't washed out
        traces = [trace(f"c{i}", "codeact_compute") for i in range(10)]
        traces += [trace(f"r{i}", "codeact_recover") for i in range(2)]
        pool = consolidate(traces, balance=True)
        assert pool.per_family["codeact_compute"] == 2
        assert pool.per_family["codeact_recover"] == 2

    def test_explicit_cap_respected(self):
        traces = [trace(f"c{i}", "codeact_compute") for i in range(10)]
        traces += [trace(f"r{i}", "codeact_recover") for i in range(5)]
        pool = consolidate(traces, per_family_cap=3, balance=True)
        assert pool.per_family["codeact_compute"] == 3
        assert pool.per_family["codeact_recover"] == 3

    def test_refuse_behavior_survives_consolidation(self):
        # a code interpreter is an attack surface — 'refuse to run this' trajectories must be keepable
        traces = [trace(f"c{i}", "codeact_compute") for i in range(6)]
        traces += [trace("danger", "codeact_safety", behavior="refuse")]
        pool = consolidate(traces, balance=True)
        assert any(t.behavior == "refuse" for t in pool.traces)

    def test_unbalanced_keeps_all_verified(self):
        traces = [trace(f"c{i}", "compute") for i in range(10)]
        traces += [trace(f"r{i}", "recover") for i in range(2)]
        pool = consolidate(traces, balance=False)
        assert len(pool) == 12


class TestGate:
    def test_mopd_run_refuses(self):
        pool = consolidate([trace("p", "compute")], balance=False)
        with pytest.raises(ConsolidationBlockedError) as ei:
            mopd_consolidation_run(pool)
        assert "BLOCKED_NO_GPU" in str(ei.value)
