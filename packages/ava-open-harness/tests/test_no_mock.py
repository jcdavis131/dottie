# Solo personal project, no connection to employer, built with public/free-tier only
"""Anti-mock guard (HARNESS_SPEC 'Anti-mock Guard').

Enforces the invariant this repo exists for: no fabricated numbers presented as
measurements. Three checks, matching the spec:

1. Dynamic — jspace tests run with seeds 1 and 2 (mock, ckpt none) produce DIFFERENT
   measured dicts. Static fabricated constants can't vary by seed, so this catches them
   without a brittle source grep of legitimate seed-noise base values.
2. Report grep — a full mock run's report JSON does not contain any forbidden literal as
   an exact serialized value (mock noise guarantees non-exactness; a static value would
   round-trip verbatim).
3. Real-mode honesty — every eval whose real path is unwired returns measured=None,
   pass=False, and an error (never an invented number); and run_harness(mode='real')
   with no real model produces a structured honest-failure report, not fabricated passes.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.common import MockModel, MockTokenizer  # noqa: E402
from harness.evals import jspace_tests as J  # noqa: E402
from harness.runner import run_harness  # noqa: E402

FORBIDDEN = ["0.82", "0.22", "0.064", "0.88", "0.75", "0.91", "0.94", "0.92",
             "5.2", "4.5", "0.983", "0.967"]
JSPACE = ["spider_ant", "france_china", "soccer_rugby", "spanish_french", "safety_blackmail"]


def _run_eval(name, seed):
    fn = getattr(J, name)
    return fn(MockModel(seed=seed), MockTokenizer(), "cpu")


class TestDynamicVariation:
    @pytest.mark.parametrize("name", JSPACE)
    def test_measured_differs_across_seeds(self, name):
        m1 = _run_eval(name, 1).get("measured")
        m2 = _run_eval(name, 2).get("measured")
        # A static fabricated measured dict would be identical across seeds.
        assert m1 != m2, f"{name} measured did not vary with seed → looks static/fabricated"


class TestReportGrep:
    def test_mock_report_has_no_exact_forbidden_literals(self, tmp_path):
        res = run_harness(eval_names=JSPACE, mode="mock")
        blob = json.dumps(res)
        # Exact-token check: a fabricated static value round-trips verbatim; seed-noise
        # values serialize with long float tails and won't match these short literals.
        for lit in FORBIDDEN:
            assert f": {lit}," not in blob and f": {lit}}}" not in blob, \
                f"forbidden literal {lit} appears verbatim in mock report"


class TestRealModeHonesty:
    @pytest.mark.parametrize("name", JSPACE)
    def test_unwired_real_paths_fail_honestly(self, name, monkeypatch):
        # Real paths now delegate to the factory repo when importable; simulate
        # a machine WITHOUT the factory — the real path must fail honestly with
        # a structured record, never simulate a measurement.
        monkeypatch.setenv("AVA_FACTORY_ROOT", "/nonexistent-factory-root")
        res = getattr(J, name)(object(), MockTokenizer(), "cpu")  # non-MockModel → real path
        assert res["pass"] is False
        assert res.get("measured") is None
        assert "error" in res and res["error"]

    def test_run_harness_real_without_model_is_structured_failure(self):
        res = run_harness(eval_names=JSPACE, mode="real")
        assert res["meta"].get("real_load_failed") is True
        assert res["meta"]["passed"] == 0
        assert all(e["pass"] is False and e.get("measured") is None
                   for e in res["evals"].values())

    def test_run_harness_real_does_not_raise(self):
        # Regression: real-mode-with-mock must be a report, not an exception a caller
        # could swallow and then fabricate around.
        res = run_harness(eval_names=["spider_ant"], mode="real")
        assert isinstance(res, dict) and "evals" in res


class TestStateStoreHonestNulls:
    """The J-Space state store (packages/ava-skills) feeds task_logs into the telemetry
    pipeline; a defaulted score there would be a fabricated measurement one hop before
    the dashboard. Unevaluated stays NULL — in the table, the aggregate, AND the export."""

    def test_unevaluated_tasks_never_grow_scores(self, tmp_path):
        store_mod = pytest.importorskip(
            "skills.state_store", reason="ava-skills workspace member not installed")
        with store_mod.JSpaceStateStore(tmp_path / "s.sqlite3") as st:
            st.log_task("nm-sess", "unchecked task", "ok")
            row = st.recent_tasks(1)[0]
            assert row["eval_score"] is None and row["policy_ok"] is None
            stats = st.task_stats()
            # 0.0 here would be an invented aggregate over zero evaluations
            assert stats["avg_eval_score"] is None and stats["evaluated"] == 0
            out = tmp_path / "t.jsonl"
            st.export_telemetry(out)
        rec = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
        assert rec["eval_score"] is None, "export must carry null, not a defaulted number"
