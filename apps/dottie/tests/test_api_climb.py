# Solo personal project, no connection to employer, built with public/free-tier only
"""API tests for the climb surface — POST /climb (one inline iteration, 409 when one is
already running), GET /climb/log, validation, honest policy-unavailable mapping."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dottie.api import create_app
from dottie.engine import DottieEngine
from tests.conftest import UNROUTABLE_OLLAMA


@pytest.fixture()
def app(data_dir):
    return create_app(engine=DottieEngine(data_dir))


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def test_post_climb_runs_one_iteration_inline(client):
    r = client.post("/climb", json={"families": "compute", "n": 2, "backend": "echo"})
    assert r.status_code == 200
    rec = r.json()
    assert rec["scoreboard"]["overall"] == {
        "n": 2, "success_rate": 0.0,                     # echo honestly scores 0
        "mean_r_task": 0.0,
        "mean_rl_return": rec["scoreboard"]["overall"]["mean_rl_return"],
    }
    assert rec["flywheel"]["export_rft"]["status"] == "ok"
    assert rec["flywheel"]["mint"]["status"] == "ok"
    assert rec["config"]["families"] == "compute" and rec["config"]["n"] == 2

    log = client.get("/climb/log").json()
    assert log["count"] == 1
    assert log["iterations"][0]["iteration_id"] == rec["iteration_id"]
    assert log["log_path"].replace("\\", "/").endswith("climb/climb_log.jsonl")


def test_post_climb_409_when_a_climb_is_already_running(app, client):
    # Hold the app's climb lock exactly as a running iteration would.
    assert app.state.climb_lock.acquire(blocking=False)
    try:
        r = client.post("/climb", json={"families": "compute", "n": 1, "backend": "echo"})
        assert r.status_code == 409
        assert "already running" in r.json()["detail"]
    finally:
        app.state.climb_lock.release()
    # Once released, the endpoint runs again.
    ok = client.post("/climb", json={"families": "compute", "n": 1, "backend": "echo"})
    assert ok.status_code == 200
    assert client.get("/climb/log").json()["count"] == 1   # the 409 attempt logged nothing


def test_post_climb_validation(client):
    assert client.post("/climb", json={"families": "compute", "n": 0,
                                       "backend": "echo"}).status_code == 422
    assert client.post("/climb", json={"families": "mind_reading",
                                       "backend": "echo"}).status_code == 422
    assert client.post("/climb", json={"families": "compute", "backend": "echo",
                                       "evaluate": "vibes"}).status_code == 422


def test_post_climb_policy_unavailable_is_503_and_lock_released(client, monkeypatch):
    monkeypatch.setenv("DOTTIE_OLLAMA_URL", UNROUTABLE_OLLAMA)
    r = client.post("/climb", json={"families": "compute", "n": 1, "backend": "ollama"})
    assert r.status_code == 503
    assert "policy_unavailable" in r.json()["detail"]
    # The failed climb released its lock — an echo climb runs immediately after.
    ok = client.post("/climb", json={"families": "compute", "n": 1, "backend": "echo"})
    assert ok.status_code == 200


def test_climb_log_empty_is_honest(client):
    log = client.get("/climb/log").json()
    assert log == {"count": 0, "iterations": [], "log_path": log["log_path"]}
