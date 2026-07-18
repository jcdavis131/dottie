# Solo personal project, no connection to employer, built with public/free-tier only
"""eval-harness-runner: the mock-mode bar is now reachable (passed==total gate)."""

from pathlib import Path

import pytest

from conftest import ROOT, load_skill_module

ehr = load_skill_module("eval-harness-runner")

HARNESS_AVAILABLE = (ROOT.parent / "ava-open-harness" / "harness" / "runner.py").exists()


@pytest.mark.skipif(not HARNESS_AVAILABLE, reason="sibling ava-open-harness not present")
class TestMockModeBar:
    def test_mock_default_set_passes_its_bar(self):
        r = ehr.run(mode="mock")
        assert r["measured"] is not None, r.get("error")
        passed, total = r["measured"]["passed"], r["measured"]["total"]
        assert total == 2  # default set: jspace_all + frontier_rubric
        assert passed == total
        assert r["pass"] is True, (
            f"bar must be reachable: passed={passed} total={total} bar={r['bar']}"
        )

    def test_bar_is_all_evals_not_fixed_count(self):
        r = ehr.run(mode="mock")
        assert ">=3" not in r["bar"]
        assert r["pass"] == (r["measured"]["passed"] == r["measured"]["total"])


def test_real_mode_without_ckpt_fails_honestly():
    r = ehr.run(mode="real")
    assert r["pass"] is False
    if r["measured"] is not None:
        # structured honest-failure report from the harness: zero passes, never fabricated
        assert r["measured"]["passed"] == 0
