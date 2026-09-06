"""JSON API round trips (spec §5)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.testclient import TestClient


def test_remember_then_recall(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/api/memories",
        json={"text": "jarvisd binds port 8790 not 8787", "scope": "repo:dottie", "tags": ["ports"]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    mem = r.json()["memory"]
    assert mem["agent"] == "tester" and mem["tags"] == ["ports"]
    # a different client (agent) recalls it
    other = {**auth_headers, "X-Agent-Id": "cursor"}
    got = client.get("/api/recall", params={"q": "8790"}, headers=other).json()
    assert got["ok"] and got["results"][0]["id"] == mem["id"]
    listed = client.get("/api/memories", params={"repo": "dottie"}, headers=other).json()
    assert listed["memories"][0]["id"] == mem["id"]
    assert client.get("/api/recall", headers=other).status_code == 400


def test_bad_json_and_missing_goal(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post("/api/route", content=b"{not json", headers=auth_headers)
    assert r.status_code == 400 and "malformed" in r.json()["error"]
    r = client.post("/api/route", json={"goal": ""}, headers=auth_headers)
    assert r.status_code == 400 and "goal" in r.json()["error"]
    r = client.post("/api/memories", json={"text": ""}, headers=auth_headers)
    assert r.status_code == 400
    assert client.get("/api/nope", headers=auth_headers).status_code == 404


def test_claims_board(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = {"repo": "dottie", "area": "apps/jarvisd", "note": "building"}
    assert client.post("/api/claims", json=body, headers=auth_headers).json()["ok"] is True
    cursor = {**auth_headers, "X-Agent-Id": "cursor"}
    conflict = client.post("/api/claims", json=body, headers=cursor)
    assert conflict.status_code == 400 and conflict.json()["holder"]["agent"] == "tester"
    board = client.get("/api/claims", params={"repo": "dottie"}, headers=cursor).json()["claims"]
    assert len(board) == 1
    rel = client.request("DELETE", "/api/claims", json={"repo": "dottie", "area": "apps/jarvisd"}, headers=auth_headers)
    assert rel.json()["released"] is True
    assert client.get("/api/claims", headers=cursor).json()["claims"] == []
    assert client.post("/api/claims", json={"repo": "x"}, headers=cursor).status_code == 400


def test_inbox_round_trip(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.post("/api/inbox", json={"to": "cursor", "body": "take README"}, headers=auth_headers).json()["ok"]
    cursor = {**auth_headers, "X-Agent-Id": "cursor"}
    box = client.get("/api/inbox", params={"mark_read": "1"}, headers=cursor).json()
    assert box["messages"][0]["body"] == "take README" and box["messages"][0]["from_agent"] == "tester"
    assert client.get("/api/inbox", headers=cursor).json()["messages"] == []
    assert client.get("/api/inbox", params={"all": "1"}, headers=cursor).json()["messages"]


def test_goals_round_trip(client: TestClient, auth_headers: dict[str, str]) -> None:
    g = client.post("/api/goals", json={"repo": "dottie", "text": "green CI"}, headers=auth_headers).json()["goal"]
    assert client.get("/api/goals", params={"repo": "dottie"}, headers=auth_headers).json()["goals"][0]["id"] == g["id"]
    done = client.patch("/api/goals", json={"id": g["id"], "result": {"sha": "abc"}}, headers=auth_headers).json()
    assert done["goal"]["status"] == "done" and done["goal"]["result"] == {"sha": "abc"}
    assert client.get("/api/goals", params={"repo": "dottie"}, headers=auth_headers).json()["goals"] == []
    assert client.patch("/api/goals", json={"id": "x"}, headers=auth_headers).status_code == 400
    assert client.patch("/api/goals", json={"id": 999}, headers=auth_headers).status_code == 400


def test_timeline_and_export(client: TestClient, auth_headers: dict[str, str]) -> None:
    client.post("/api/memories", json={"text": "exported row"}, headers=auth_headers)
    r = client.get("/api/export/memories", headers=auth_headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    rows = [json.loads(x) for x in r.text.splitlines()]
    assert rows[0]["text"] == "exported row"
    assert client.get("/api/export/secrets", headers=auth_headers).status_code == 404
    assert client.get("/api/timeline", headers=auth_headers).json() == {"ok": True, "timeline": []}


def test_route_plan_shapes(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post("/api/route", json={"goal": "compare Stripe vs Lemon Squeezy Aug 2026"}, headers=auth_headers)
    assert r.status_code == 200
    doc = r.json()
    if not doc["ok"]:
        assert doc["error"].startswith("scout unavailable")
        return
    for key in ("intent", "intent_scores", "complexity", "tier", "moma_tier", "confidence", "routed_agents", "routed_count", "latency_ms", "tokens_est", "measured"):
        assert key in doc
    assert doc["intent"] == "deep_research"
    tl = client.get("/api/timeline", headers=auth_headers).json()["timeline"]
    assert tl[0]["kind"] == "route" and tl[0]["agent"] == "tester"
    p = client.post("/api/plan", json={"goal": "ship the daemon"}, headers=auth_headers).json()
    assert p["ok"] and p["tierHint"] and p["steps"][0]["idx"] == 0 and "failureRisk" in p["steps"][0]
