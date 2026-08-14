"""
Tests for `scout harness route --learned` — the learned-router augmentation.

Pattern borrowed from tests/test_harness_timeline.py:

- HOME isolation via conftest.py (throwaway HOME) already active, inherited by
  subprocesses; plus the autouse per-test HOME fixture below.
- subprocess `python -m bigbang.cli --json ...` to exercise real CLI discovery,
  with SCOUT_ORCH_MODEL / SCOUT_ORCH_INFER pointing at tmp fixtures so the
  tests never depend on the real champion artifacts built by a parallel lane.

All goals here contain >=1 routing keyword ('build' / 'compare'): zero-keyword
goals crash route itself (pre-existing cli.py:103 KeyError 'llm', out of scope).

Fixture weights are SYNTHETIC (random, seed 0) — a schema-valid file for
exercising the plumbing, not a trained model; provenance is labeled inside it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Per-test HOME so each test sees a fresh store (pattern: test_harness_timeline.py)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _run_cli(*args, env: dict | None = None) -> dict:
    """Run `python -m bigbang.cli <args>` and return parsed JSON (envelope or raw)."""
    cmd = [sys.executable, "-m", "bigbang.cli", *args]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=12,
        env={**os.environ, **(env or {})},
    )
    assert r.returncode == 0, f"cli failed {' '.join(cmd)} exit {r.returncode} stderr {r.stderr} stdout {r.stdout[:2000]}"
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"stdout not json for {' '.join(cmd)}: {e} stdout={r.stdout[:2000]}")
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict) else payload
    return {"raw": payload, "data": data, "stdout": r.stdout}


TIER_VOCAB = ["deterministic", "llm", "deep_research", "action_operator", "agentic_epic"]
DENSE_FEATURES = ["n_words", "n_chain_signals", "has_code_terms", "latency_ms", "tokens_est", "attempt"]

GOAL_BUILD = "build a data pipeline and test the api endpoints for the harness"
GOAL_COMPARE = "compare Stripe vs Lemon Squeezy Aug 2026"


def make_fixture_weights(tmp_path: Path) -> Path:
    """Tiny VALID schema_version-1 weights file (synthetic, numpy seed 0)."""
    import numpy as np

    rng = np.random.default_rng(0)
    n_buckets, embed_dim, hidden_dim, n_tiers = 32, 4, 4, 5
    doc = {
        "schema_version": 1,
        "model_version": "orch-test-fixture-1",
        "gate_passed": False,
        "trained_at": "2026-08-09T00:00:00+00:00",
        "provenance": {"source": "synthetic test fixture — random weights seed 0, NOT a trained model"},
        "config": {
            "n_buckets": n_buckets,
            "embed_dim": embed_dim,
            "hidden_dim": hidden_dim,
            "dense_features": DENSE_FEATURES,
            "tier_vocab": TIER_VOCAB,
            "seed": 0,
        },
        "norms": {"dense_mean": [0.0] * 6, "dense_std": [1.0] * 6},
        "weights": {
            "embedding": rng.normal(size=(n_buckets, embed_dim)).tolist(),
            "w1": rng.normal(size=(embed_dim + 6, hidden_dim)).tolist(),
            "b1": rng.normal(size=(hidden_dim,)).tolist(),
            "w_tier": rng.normal(size=(hidden_dim, n_tiers)).tolist(),
            "b_tier": rng.normal(size=(n_tiers,)).tolist(),
            "w_risk": rng.normal(size=(hidden_dim,)).tolist(),
            "b_risk": 0.1,
            "w_cost": rng.normal(size=(hidden_dim,)).tolist(),
            "b_cost": 0.2,
        },
    }
    path = tmp_path / "fixture_champion_weights.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _learned_env(tmp_path: Path, weights: Path, infer: Path | None = None) -> dict:
    return {
        "SCOUT_ORCH_MODEL": str(weights),
        "SCOUT_ORCH_INFER": str(infer if infer is not None else tmp_path / "nonexistent.py"),
    }


def test_learned_route_internal_impl(tmp_path):
    weights = make_fixture_weights(tmp_path)
    out = _run_cli("--json", "harness", "route", GOAL_BUILD, "--learned",
                   env=_learned_env(tmp_path, weights))
    d = out["data"]
    # learned keys
    assert d.get("learned_tier") in TIER_VOCAB, d.get("learned_tier")
    probs = d.get("learned_probs")
    assert isinstance(probs, dict) and sorted(probs.keys()) == sorted(TIER_VOCAB), probs
    assert abs(sum(probs.values()) - 1.0) < 1e-6, probs
    assert 0.0 <= d.get("risk") <= 1.0, d.get("risk")
    assert "cost" in d
    assert d.get("model_version") == "orch-test-fixture-1"
    assert "gate_passed" in d
    assert d.get("gate_passed") is False
    assert d.get("learned_source") == "champion_weights"
    assert d.get("infer_impl") == "internal"
    # baseline heuristic route keys still present
    for key in ("intent", "moma_tier", "routed_agents", "graph_memory"):
        assert key in d, f"baseline key {key} missing from {sorted(d.keys())}"


def test_learned_route_shared_module_impl(tmp_path):
    weights = make_fixture_weights(tmp_path)
    fake_infer = tmp_path / "fake_orch_infer.py"
    fake_infer.write_text(textwrap.dedent("""
        import json
        from pathlib import Path

        def load_weights(path):
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            return {"config": doc["config"], "model_version": "marker-shared-9"}

        def predict(w, goal, dense=None):
            return {
                "tier": "llm",
                "tier_probs": [0.2, 0.2, 0.2, 0.2, 0.2],
                "risk": 0.5,
                "cost": 1.0,
                "model_version": w["model_version"],
                "gate_passed": True,
            }
    """), encoding="utf-8")
    out = _run_cli("--json", "harness", "route", GOAL_BUILD, "--learned",
                   env=_learned_env(tmp_path, weights, infer=fake_infer))
    d = out["data"]
    assert d.get("infer_impl") == "shared_module"
    assert d.get("model_version") == "marker-shared-9"
    assert d.get("learned_tier") == "llm"
    assert d.get("gate_passed") is True
    assert d.get("learned_source") == "champion_weights"


def test_learned_route_fallback_missing_weights(tmp_path):
    absent = tmp_path / "absent.json"
    out = _run_cli("--json", "harness", "route", GOAL_BUILD, "--learned",
                   env=_learned_env(tmp_path, absent))
    d = out["data"]
    assert d.get("learned_tier") is None
    assert "learned_tier" in d  # explicit null, not absent
    assert d.get("learned_fallback") == "heuristic"
    assert str(absent) in d.get("learned_reason", ""), d.get("learned_reason")
    # heuristic fields intact
    for key in ("intent", "moma_tier", "routed_agents", "graph_memory"):
        assert key in d, f"baseline key {key} missing"


def test_learned_route_fallback_invalid_weights(tmp_path):
    weights = make_fixture_weights(tmp_path)
    doc = json.loads(weights.read_text(encoding="utf-8"))
    doc["weights"]["w_tier"] = doc["weights"]["w_tier"][:2]  # truncate: wrong shape
    bad = tmp_path / "bad_weights.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    out = _run_cli("--json", "harness", "route", GOAL_BUILD, "--learned",
                   env=_learned_env(tmp_path, bad))
    d = out["data"]
    assert d.get("learned_tier") is None
    assert d.get("learned_fallback") == "heuristic"
    assert d.get("learned_reason", "").startswith("weights invalid"), d.get("learned_reason")


def test_route_without_flag_has_no_learned_keys():
    """Mirror of test_harness_timeline.py::test_route_regression_unchanged, so a
    conflict with the pinned regression test surfaces here first."""
    out = _run_cli("--json", "harness", "route", GOAL_COMPARE)
    d = out["data"]
    for key in ("learned_tier", "learned_probs", "learned_source", "learned_fallback",
                "learned_reason", "infer_impl", "risk", "cost", "model_version", "gate_passed"):
        assert key not in d, f"unexpected learned key {key} without --learned"
    sg = d.get("stickiness_guard")
    assert sg is not None and sg.get("passed") is True
    assert "G_history" in d.get("graph_memory", {})


def test_learned_route_deterministic(tmp_path):
    weights = make_fixture_weights(tmp_path)
    env = _learned_env(tmp_path, weights)
    a = _run_cli("--json", "harness", "route", GOAL_BUILD, "--learned", env=env)["data"]
    b = _run_cli("--json", "harness", "route", GOAL_BUILD, "--learned", env=env)["data"]
    assert a["learned_tier"] == b["learned_tier"]
    assert a["risk"] == b["risk"]
    assert a["cost"] == b["cost"]
