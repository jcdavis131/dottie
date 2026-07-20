# Solo personal project, no connection to employer, built with public/free-tier only
"""API tests for verified tasks — {family, seed} submissions, r_task + verifier detail
exposure, and the /tasks/batch climb endpoint."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from dottie.api import create_app
from dottie.engine import DottieEngine
from dottie.tasks import FAMILIES


@pytest.fixture()
def client(data_dir):
    app = create_app(engine=DottieEngine(data_dir))
    with TestClient(app) as c:
        yield c


def _wait_done(client: TestClient, task_id: str, timeout_s: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout_s
    row = None
    while time.monotonic() < deadline:
        row = client.get(f"/tasks/{task_id}").json()
        if row["status"] in ("done", "error"):
            return row
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish within {timeout_s}s: {row}")


def test_submit_verified_task_exposes_r_task_and_verifier(client):
    r = client.post("/tasks", json={"family": "compute", "seed": 4, "backend": "echo"})
    assert r.status_code == 202
    body = r.json()
    assert body["family"] == "compute" and body["seed"] == 4
    row = _wait_done(client, body["task_id"])
    assert row["status"] == "done"
    assert row["family"] == "compute" and row["seed"] == 4
    # Echo cannot pass the verifier: r_task honestly 0.0, surfaced at top level and in comps.
    assert row["r_task"] == 0.0
    assert row["reward_components"]["r_task"] == 0.0
    assert "rl_return" in row["reward_components"]
    detail = row["verifier"]
    assert detail["family"] == "compute" and detail["seed"] == 4
    assert (
        detail["expected"] and detail["expected"] not in row["prompt"]
    )  # no leakage, live
    assert "note" in detail


def test_submit_requires_exactly_one_form(client):
    both = client.post(
        "/tasks", json={"prompt": "x", "family": "compute", "backend": "echo"}
    )
    assert both.status_code == 422
    neither = client.post("/tasks", json={"backend": "echo"})
    assert neither.status_code == 422
    bad_family = client.post(
        "/tasks", json={"family": "mind_reading", "backend": "echo"}
    )
    assert bad_family.status_code == 422


def test_freeform_submission_unchanged(client):
    r = client.post("/tasks", json={"prompt": "free-form", "backend": "echo"})
    assert r.status_code == 202
    row = _wait_done(client, r.json()["task_id"])
    assert row["r_task"] is None and row["verifier"] is None
    assert row["family"] is None and row["use_skills"] is False


def test_batch_mixed_runs_all_families(client):
    n = len(FAMILIES)
    r = client.post("/tasks/batch", json={"family": "mixed", "n": n, "backend": "echo"})
    assert r.status_code == 202
    body = r.json()
    assert body["batch_size"] == n
    assert [t["family"] for t in body["tasks"]] == list(FAMILIES)
    assert [t["seed"] for t in body["tasks"]] == list(range(n))
    for t in body["tasks"]:
        row = _wait_done(client, t["task_id"])
        assert row["status"] == "done", row.get("error")
        assert row["r_task"] == 0.0  # echo never beats a verifier
        assert row["verifier"]["family"] == t["family"]
    assert client.get("/tasks").json()["counts"]["done"] == n


def test_batch_explicit_seeds_and_validation(client):
    r = client.post(
        "/tasks/batch",
        json={"family": "extract", "n": 2, "seeds": [7, 9], "backend": "echo"},
    )
    assert r.status_code == 202
    assert [t["seed"] for t in r.json()["tasks"]] == [7, 9]
    for t in r.json()["tasks"]:
        _wait_done(client, t["task_id"])
    bad = client.post(
        "/tasks/batch",
        json={"family": "extract", "n": 3, "seeds": [1], "backend": "echo"},
    )
    assert bad.status_code == 422


def test_batch_rejected_whole_when_queue_cannot_admit(data_dir, monkeypatch):
    """All-or-nothing admission: a batch larger than the queue cap is rejected entirely and
    releases every slot it briefly held (a normal submit still works afterwards)."""
    monkeypatch.setenv("DOTTIE_QUEUE_MAX", "3")
    app = create_app(engine=DottieEngine(data_dir))
    with TestClient(app) as small:
        r = small.post(
            "/tasks/batch", json={"family": "compute", "n": 4, "backend": "echo"}
        )
        assert r.status_code == 429
        assert "batch" in r.json()["detail"]
        ok = small.post("/tasks", json={"family": "compute", "backend": "echo"})
        assert ok.status_code == 202
        _wait_done(small, ok.json()["task_id"])
