"""Local integration tests for the harness router API — stdlib + numpy only.

Spins the real ``handler`` class in an ``http.server.HTTPServer`` on a daemon
thread and round-trips through ``urllib.request``, so the exact request path a
serverless invocation takes (headers, body parsing, JSON envelope) is what is
tested. The api module is file-path-imported because the package is not a
workspace member.

Model state is controlled per test via ``DOTTIE_HARNESS_WEIGHTS`` /
``DOTTIE_HARNESS_META_DIR`` plus the module's ``_reset()`` cache hook: a tiny
fixture weights file (n_buckets 32, embed 4, hidden 4, fixed numpy seed)
covers the loaded-model cases; a nonexistent path covers graceful degradation.
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import numpy as np
import pytest

_API_PATH = Path(__file__).resolve().parent.parent / "api" / "index.py"

_spec = importlib.util.spec_from_file_location("dottie_harness_api_index", _API_PATH)
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)

TIER_VOCAB = ["deterministic", "llm", "deep_research", "action_operator", "agentic_epic"]
DENSE_FEATURES = ["n_words", "n_chain_signals", "has_code_terms", "latency_ms", "tokens_est", "attempt"]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _write_fixture_weights(path: Path) -> None:
    """Tiny schema_version-1 weights file: n_buckets 32, embed 4, hidden 4."""
    n_buckets, embed_dim, hidden_dim = 32, 4, 4
    rng = np.random.default_rng(7)
    doc = {
        "schema_version": 1,
        "model_version": "test-fixture-v0",
        "gate_passed": False,
        "trained_at": "2026-08-09T00:00:00+00:00",
        "provenance": {"note": "random test fixture — not a trained model"},
        "config": {
            "n_buckets": n_buckets,
            "embed_dim": embed_dim,
            "hidden_dim": hidden_dim,
            "dense_features": DENSE_FEATURES,
            "tier_vocab": TIER_VOCAB,
            "seed": 7,
        },
        "norms": {
            "dense_mean": [0.0] * 6,
            "dense_std": [1.0] * 6,
        },
        "weights": {
            "embedding": rng.normal(size=(n_buckets, embed_dim)).tolist(),
            "w1": rng.normal(size=(embed_dim + 6, hidden_dim)).tolist(),
            "b1": rng.normal(size=hidden_dim).tolist(),
            "w_tier": rng.normal(size=(hidden_dim, 5)).tolist(),
            "b_tier": rng.normal(size=5).tolist(),
            "w_risk": rng.normal(size=hidden_dim).tolist(),
            "b_risk": float(rng.normal()),
            "w_cost": rng.normal(size=hidden_dim).tolist(),
            "b_cost": float(rng.normal()),
        },
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """Yield a base URL for a live server; env decides model/meta state.

    Default state: no weights (nonexistent path) and an empty meta dir, so the
    package's own vendored artifacts never leak into a test. Individual tests
    flip env vars via the returned helper BEFORE their first request.
    """
    monkeypatch.setenv("DOTTIE_HARNESS_WEIGHTS", str(tmp_path / "nope" / "missing.json"))
    empty_meta = tmp_path / "empty_meta"
    empty_meta.mkdir()
    monkeypatch.setenv("DOTTIE_HARNESS_META_DIR", str(empty_meta))
    api._reset()

    httpd = HTTPServer(("127.0.0.1", 0), api.handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        api._reset()


def _get(base: str, path: str):
    # http://127.0.0.1 test server only
    with urllib.request.urlopen(base + path) as resp:  # noqa: S310
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _post(base: str, path: str, body: dict | None, raw: bytes | None = None):
    data = raw if raw is not None else json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _arm_fixture_weights(tmp_path) -> None:
    weights = tmp_path / "fixture_weights.json"
    _write_fixture_weights(weights)
    os.environ["DOTTIE_HARNESS_WEIGHTS"] = str(weights)
    api._reset()


# ---------------------------------------------------------------------------
# (1)-(2) health
# ---------------------------------------------------------------------------


def test_health_without_weights(server):
    status, doc = _get(server, "/api/health")
    assert status == 200
    assert doc["ok"] is True
    assert doc["model_loaded"] is False
    assert doc["model_version"] is None
    assert doc["gate_passed"] is None
    assert doc["corpus_stats"] is None


def test_health_with_fixture_weights(server, tmp_path):
    _arm_fixture_weights(tmp_path)
    status, doc = _get(server, "/api/health")
    assert status == 200
    assert doc["model_loaded"] is True
    assert doc["model_version"] == "test-fixture-v0"
    assert doc["gate_passed"] is False


# ---------------------------------------------------------------------------
# (3)-(5) route
# ---------------------------------------------------------------------------


def test_route_with_weights(server, tmp_path):
    _arm_fixture_weights(tmp_path)
    status, doc = _post(server, "/api/route", {"goal": "compare stripe vs lemon squeezy pricing"})
    assert status == 200
    assert doc["ok"] is True
    assert doc["moma_tier"] == "deep_research"
    assert doc["model_loaded"] is True
    learned = doc["learned"]
    assert learned is not None
    assert learned["tier"] in TIER_VOCAB
    assert 0.0 <= learned["risk"] <= 1.0
    assert len(learned["tier_probs"]) == 5
    assert learned["model_version"] == "test-fixture-v0"


def test_route_zero_keyword_goal_confidence_floor(server):
    # The original CLI KeyErrors on this input (cli.py:103 indexes scores by
    # the forced intent 'llm'); the port must return 200 with confidence 0.4.
    status, doc = _post(server, "/api/route", {"goal": "summarize this document please"})
    assert status == 200
    assert doc["ok"] is True
    assert doc["intent"] == "llm"
    assert doc["confidence"] == 0.4
    assert doc["learned"] is None
    assert doc["model_loaded"] is False


def test_route_missing_goal_is_400(server):
    status, doc = _post(server, "/api/route", {})
    assert status == 400
    assert doc["ok"] is False

    status_empty, _ = _post(server, "/api/route", {"goal": "   "})
    assert status_empty == 400

    status_bad, doc_bad = _post(server, "/api/route", None, raw=b"{not json")
    assert status_bad == 400
    assert "JSON" in doc_bad["error"] or "body" in doc_bad["error"]


# ---------------------------------------------------------------------------
# (6)-(7) plan
# ---------------------------------------------------------------------------


def test_plan_epic_template(server):
    status, doc = _post(server, "/api/plan", {"goal": "ship the harness loop"})
    assert status == 200
    assert doc["ok"] is True
    assert doc["tierHint"] == "agentic_epic"
    ids = [s["id"] for s in doc["steps"]]
    assert ids == ["intent-decompose", "dag-architect", "layer-exec", "build", "verify-budget"]
    assert len(doc["steps"]) == 5
    for step in doc["steps"]:
        if step["role"] in ("builder", "executor"):
            assert step["failureRisk"] == 0.35
            assert step["sideEffect"] == "WRITE_DESTRUCTIVE"
    assert doc["risk_provenance"] == "static priors — no mined run history in serverless"


def test_plan_heartbeat_template(server):
    status, doc = _post(server, "/api/plan", {"goal": "heartbeat monitor tick"})
    assert status == 200
    assert len(doc["steps"]) == 3
    assert [s["id"] for s in doc["steps"]] == ["observe-tick", "orient-filter", "act-noop"]


# ---------------------------------------------------------------------------
# (8) stats, (9) determinism, 404
# ---------------------------------------------------------------------------


def test_stats_nulls_when_nothing_vendored(server):
    status, doc = _get(server, "/api/stats")
    assert status == 200
    assert doc["ok"] is True
    assert doc["corpus_meta"] is None
    assert doc["champion"] is None


def test_route_is_deterministic(server, tmp_path):
    _arm_fixture_weights(tmp_path)
    goal = {"goal": "build then deploy the api and monitor the pipeline after launch"}
    status_a, doc_a = _post(server, "/api/route", goal)
    status_b, doc_b = _post(server, "/api/route", goal)
    assert status_a == status_b == 200
    assert doc_a == doc_b


def test_unknown_path_404(server):
    try:
        urllib.request.urlopen(server + "/api/nope")  # noqa: S310
        raised = False
    except urllib.error.HTTPError as exc:
        raised = True
        assert exc.code == 404
        assert json.loads(exc.read().decode("utf-8")) == {"ok": False, "error": "not found"}
    assert raised
