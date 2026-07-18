# Solo personal project, no connection to employer, built with public/free-tier only
"""API tests — submit/poll real echo tasks, status shape (incl. capability_note), flywheel
endpoints over HTTP, honest error mapping."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from dottie.api import create_app
from dottie.engine import DottieEngine


@pytest.fixture()
def client(data_dir):
    app = create_app(engine=DottieEngine(data_dir))
    with TestClient(app) as c:
        yield c


def _wait_done(client: TestClient, task_id: str, timeout_s: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        row = client.get(f"/tasks/{task_id}").json()
        if row["status"] in ("done", "error"):
            return row
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish within {timeout_s}s: {row}")


def test_submit_echo_task_and_poll_to_completion(client):
    r = client.post("/tasks", json={"prompt": "api echo task", "backend": "echo"})
    assert r.status_code == 202
    task_id = r.json()["task_id"]
    row = _wait_done(client, task_id)
    assert row["status"] == "done"
    assert row["terminated"] == "final"
    assert row["n_steps"] == 2
    assert row["final"].startswith("EchoPolicy plumbing run complete")
    comps = row["reward_components"]
    assert comps["r_exec"] == 1.0 and comps["r_task"] is None


def test_task_listing_and_counts(client):
    ids = [client.post("/tasks", json={"prompt": f"t{i}", "backend": "echo"}).json()["task_id"]
           for i in range(2)]
    for tid in ids:
        _wait_done(client, tid)
    body = client.get("/tasks").json()
    assert body["counts"]["total"] == 2
    assert body["counts"].get("done") == 2
    listed = {t["task_id"] for t in body["tasks"]}
    assert set(ids) <= listed


def test_unknown_task_404(client):
    assert client.get("/tasks/doesnotexist").status_code == 404


def test_bad_backend_rejected_by_validation(client):
    r = client.post("/tasks", json={"prompt": "x", "backend": "skynet"})
    assert r.status_code == 422


def test_empty_prompt_rejected(client):
    assert client.post("/tasks", json={"prompt": "", "backend": "echo"}).status_code == 422


def test_ollama_task_fails_honestly_via_api(client, monkeypatch):
    from tests.conftest import UNROUTABLE_OLLAMA

    monkeypatch.setenv("DOTTIE_OLLAMA_URL", UNROUTABLE_OLLAMA)
    task_id = client.post(
        "/tasks", json={"prompt": "no server", "backend": "ollama"}
    ).json()["task_id"]
    row = _wait_done(client, task_id)
    assert row["status"] == "error"
    assert "policy_unavailable" in row["error"]
    assert "unreachable" in row["error"]


def test_status_shape_is_stable_and_honest(client):
    s = client.get("/status").json()
    assert s["service"] == "dottie" and s["codename"] == "openclaw"
    # The honest capability statement is part of the stable contract.
    assert "capability_note" in s
    assert "smoke-scale" in s["capability_note"]
    backends = s["backends"]
    assert set(backends) == {"ollama", "ava", "echo"}
    # Real probes: booleans measured now, not asserted to specific values (env-dependent) —
    # except echo, which is always available, and ollama on this CI box (no server).
    assert isinstance(backends["ollama"]["available"], bool)
    assert backends["echo"]["available"] is True and backends["echo"]["plumbing_only"] is True
    assert "capability_note" in backends["ava"]
    integ = s["integrations"]
    for key in ("factory_code", "harness", "skills_memory_mint", "rft_etl",
                "rl_smoke_update", "ava_checkpoint"):
        assert key in integ and isinstance(integ[key]["available"], bool)
    assert s["data"]["traces"] == 0
    assert s["data"]["tasks"]["total"] == 0


def test_flywheel_endpoints_gate_then_run(client):
    # Before any traces: honest 503 with the true reason.
    r = client.post("/flywheel/export-rft")
    assert r.status_code == 503 and "no dottie traces" in r.json()["detail"]
    r = client.post("/flywheel/mint")
    assert r.status_code == 503

    # Run a real echo task, then the same endpoints do real work.
    tid = client.post("/tasks", json={"prompt": "fw", "backend": "echo"}).json()["task_id"]
    _wait_done(client, tid)
    exp = client.post("/flywheel/export-rft")
    assert exp.status_code == 200
    assert exp.json()["records_written"] >= 1
    mint = client.post("/flywheel/mint")
    assert mint.status_code == 200
    assert mint.json()["stats"]["minted"] == 1


def test_flywheel_evaluate_mock_over_http(client):
    r = client.post("/flywheel/evaluate", json={"mode": "mock"})
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["mode"] == "mock" and body["meta"]["total"] > 0


def test_flywheel_train_step_gates_honestly_over_http(client, tmp_path):
    r = client.post("/flywheel/train-step", json={"run_dir": str(tmp_path)})
    assert r.status_code == 503
    assert "no checkpoint tree" in r.json()["detail"]
