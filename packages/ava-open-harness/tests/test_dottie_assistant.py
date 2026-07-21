# Solo personal project, no connection to employer, built with public/free-tier only
"""dottie_assistant eval tests — registration, YAML task, REAL mock plumbing runs
through the dottie engine + sandbox, anti-mock seed variation, honest real-mode
failures, and (when the smoke checkpoint + torch are present) a real ava-backend
run whose success rate is an honest smoke-scale measurement."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.common import MockModel, MockTokenizer
from harness.evals.dottie_assistant import (
    _import_dottie,
    dottie_assistant,
    dottie_assistant_available,
)
from harness.registry import EVAL_REGISTRY, list_evals
from harness.runner import (
    _try_load_yaml_tasks,
    resolve_eval_names,
    run_harness,
)


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


# Plumbing readiness: dottie app + the factory CodeAct substrate it imports.
_MODS, _IMPORT_ERR = _import_dottie()
_PLUMBING_READY = _MODS is not None
if _PLUMBING_READY:
    try:
        _MODS["dottie.resolve"].factory_code_root()
    except Exception:
        _PLUMBING_READY = False

# Real readiness: plumbing + torch + a real ava smoke checkpoint on disk.
_REAL_READY = (
    _PLUMBING_READY
    and _torch_available()
    and _MODS["dottie.resolve"].default_ava_ckpt() is not None
)


class TestRegistrationAndYaml:
    def test_registered_in_assistant_group(self):
        assert "dottie_assistant" in EVAL_REGISTRY
        assert EVAL_REGISTRY["dottie_assistant"]["group"] == "assistant"
        assert list_evals(group="assistant") == ["dottie_assistant"]
        # the group name resolves like any other group (README contract)
        assert resolve_eval_names("assistant") == ["dottie_assistant"]

    def test_yaml_task_loads_with_bar_and_group(self):
        tasks = _try_load_yaml_tasks()
        assert "dottie_assistant" in tasks
        t = tasks["dottie_assistant"]
        assert str(t["version"]) == "1.0"
        assert t["bar"] == "success_rate>=0.6"
        assert t["group"] == "assistant"
        assert len(tasks) >= 12  # loader count 11 -> 12


@pytest.mark.skipif(
    not _PLUMBING_READY,
    reason=f"dottie app / factory substrate unavailable: {_IMPORT_ERR}",
)
class TestMockPlumbing:
    """Mock mode runs FOR REAL through DottieEngine + the real sandbox + real
    verifiers — labeled plumbing, small n to stay fast."""

    def test_echo_zero_scripted_nonzero_through_real_engine(self):
        res = dottie_assistant(
            MockModel(seed=1),
            MockTokenizer(),
            "cpu",
            dottie_n_echo=2,
            dottie_n_scripted=1,
        )
        assert "error" not in res, res.get("error")
        assert res["plumbing_only"] is True
        m = res["measured"]
        assert m["mode_label"] == "mock_plumbing"
        # echo scores 0.0 BY CONSTRUCTION (provider no-leak guarantee)...
        assert m["echo_success_rate"] == 0.0
        # ...and the labeled synthetic scripted solver proves a nonzero rate is measurable.
        assert m["scripted_success_rate"] == 1.0
        assert res["pass"] is True
        # the runs really went through the engine: real sandbox steps recorded
        scripted = [
            d for d in m["details"] if d["backend"] == "scripted-compute-solver"
        ]
        assert scripted and all(d["n_steps"] >= 1 and d["steps_ok"] for d in scripted)
        assert all(d["terminated"] == "final" for d in m["details"])

    def test_mock_measured_varies_with_seed(self):
        # Anti-mock guard convention: a static fabricated measured dict would be
        # identical across seeds; here the task mix + per-task details vary.
        kw = {"dottie_n_echo": 2, "dottie_n_scripted": 1}
        m1 = dottie_assistant(MockModel(seed=1), MockTokenizer(), "cpu", **kw)[
            "measured"
        ]
        m2 = dottie_assistant(MockModel(seed=2), MockTokenizer(), "cpu", **kw)[
            "measured"
        ]
        assert m1 != m2, "dottie_assistant mock measured did not vary with seed"
        assert m1["task_mix"] != m2["task_mix"]

    def test_runs_via_run_harness_mock(self):
        res = run_harness(
            eval_names=["dottie_assistant"],
            mode="mock",
            dottie_n_echo=1,
            dottie_n_scripted=1,
        )
        entry = res["evals"]["dottie_assistant"]
        assert "error" not in entry, entry.get("error")
        assert entry["measured"]["mode_label"] == "mock_plumbing"
        assert res["meta"]["versions"]["dottie_assistant"] == "1.0"


class TestHonestFailures:
    """Missing dottie app / checkpoint / server → structured records, never crashes
    or invented numbers (the repo's anti-fabrication rule)."""

    def test_mock_missing_dottie_is_labeled_structured_record(self, monkeypatch):
        monkeypatch.setenv("DOTTIE_ASSISTANT_ROOT", "/nonexistent-dottie-root")
        assert dottie_assistant_available() is False
        res = dottie_assistant(MockModel(seed=1), MockTokenizer(), "cpu")
        assert res["pass"] is False
        assert res["measured"] is None
        assert res["mode_label"] == "mock_plumbing" and res["plumbing_only"] is True
        assert "dottie app not found" in res["error"]
        assert "/nonexistent-dottie-root" in res["error"]

    def test_real_missing_dottie_fails_honestly(self, monkeypatch):
        monkeypatch.setenv("DOTTIE_ASSISTANT_ROOT", "/nonexistent-dottie-root")
        res = dottie_assistant(
            object(), MockTokenizer(), "cpu"
        )  # non-MockModel → real path
        assert res["pass"] is False and res["measured"] is None
        assert "dottie app not found" in res["error"]

    @pytest.mark.skipif(
        not _PLUMBING_READY, reason=f"dottie app unavailable: {_IMPORT_ERR}"
    )
    def test_real_missing_ava_ckpt_fails_honestly(self, monkeypatch):
        monkeypatch.setenv("DOTTIE_AVA_CKPT", "/nonexistent-ckpt.pt")
        res = dottie_assistant(object(), MockTokenizer(), "cpu")
        assert res["pass"] is False and res["measured"] is None
        assert "unavailable" in res["error"] and "/nonexistent-ckpt.pt" in res["error"]

    @pytest.mark.skipif(
        not _PLUMBING_READY, reason=f"dottie app unavailable: {_IMPORT_ERR}"
    )
    def test_real_ollama_backend_unreachable_fails_honestly(self, monkeypatch):
        # port 9 (discard) on localhost: nothing listens in CI — connect refuses fast.
        monkeypatch.setenv("DOTTIE_OLLAMA_URL", "http://127.0.0.1:9")
        res = dottie_assistant(
            object(), MockTokenizer(), "cpu", dottie_backend="ollama"
        )
        assert res["pass"] is False and res["measured"] is None
        assert "'ollama' unavailable" in res["error"]

    @pytest.mark.skipif(
        not _PLUMBING_READY, reason=f"dottie app unavailable: {_IMPORT_ERR}"
    )
    def test_real_rejects_mock_only_backend(self):
        res = dottie_assistant(object(), MockTokenizer(), "cpu", dottie_backend="echo")
        assert res["pass"] is False and res["measured"] is None
        assert "unsupported real backend" in res["error"]


@pytest.mark.skipif(
    not _REAL_READY, reason="ava smoke checkpoint / torch / dottie app absent"
)
class TestRealAvaSmoke:
    """Real end-to-end: dottie engine + AvaPolicy over the real smoke checkpoint.
    The honest expectation at smoke scale is a near-zero success rate; the
    assertions check realness and honesty labels, not capability."""

    def test_real_ava_success_rate_is_honest_smoke_measurement(self):
        res = dottie_assistant(
            object(), MockTokenizer(), "cpu", dottie_n_real=2, dottie_max_steps=2
        )
        assert "error" not in res, res.get("error")
        m = res["measured"]
        assert m["backend"] == "ava"
        assert isinstance(m["success_rate"], float) and 0.0 <= m["success_rate"] <= 1.0
        assert len(m["details"]) == 2
        for d in m["details"]:
            assert isinstance(d["r_task"], float) and 0.0 <= d["r_task"] <= 1.0
        # smoke-scale honesty labels; pass is the bar applied to the REAL rate
        # (expected — and today actually — False for the smoke checkpoint).
        assert res["scale"] == "smoke"
        assert res["capability_claim"] == "none"
        assert res["pass"] is (m["success_rate"] >= 0.6)
