"""JSON API round trips (spec §5)."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
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


def test_pair_create_verify_status(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post("/api/pair/create", json={"expire_min": 99}, headers=auth_headers).json()
    assert created["ok"] is True
    code = created["code"]
    assert len(code) == 6 and created["agent"] == "tester"
    assert created["exp"] - created["created"] == 600
    status = client.get("/api/pair/status", params={"code": code}, headers=auth_headers).json()
    assert status["ok"] is True and status["paired"] is False
    bad = client.post("/api/pair/verify", json={"code": "ZZZZZZ"}, headers=auth_headers).json()
    assert bad["ok"] is False and bad["paired"] is False and "unknown" in bad["error"]
    verified = client.post("/api/pair/verify", json={"code": code}, headers=auth_headers).json()
    assert verified["ok"] is True and verified["paired"] is True
    replay = client.post("/api/pair/verify", json={"code": code}, headers=auth_headers).json()
    assert replay["ok"] is False and replay["error"] == "already paired"
    status2 = client.get("/api/pair/status", params={"code": code}, headers=auth_headers).json()
    assert status2["paired"] is True
    agg = client.get("/api/pair/status", headers=auth_headers).json()
    assert agg["ok"] is True and agg["paired_count"] >= 1
    # expired codes fail honestly
    store = client.app.state.store
    with store._lock:
        store._conn.execute("UPDATE pairings SET exp = ? WHERE code = ?", (int(time.time()) - 1, code))
    expired = client.post("/api/pair/verify", json={"code": code}, headers=auth_headers).json()
    assert expired["ok"] is False and expired["error"] == "expired"


def test_pair_verify_has_exactly_one_concurrent_winner(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    code = client.post(
        "/api/pair/create", json={"expire_min": 10}, headers=auth_headers
    ).json()["code"]
    store = client.app.state.store
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.pair_verify(code), range(8)))
    assert sum(result["ok"] is True for result in results) == 1
    assert sum(result.get("error") == "already paired" for result in results) == 7
    assert store.pair_status(code)["paired"] is True


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


def test_conductor_snapshot_requires_auth_and_scopes_from_query(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    assert client.get("/api/conductor/snapshot").status_code == 401
    headers = {**auth_headers, "X-Agent-Id": "edge-actor"}
    created = client.post(
        "/api/conductor/rpc?repo=fixed-repo&mission=mission-a",
        headers=headers,
        json={
            "method": "feedback.push",
            "params": {"kind": "note", "message": "real feedback", "strength": 0.5},
        },
    )
    assert created.status_code == 200

    snapshot = client.get(
        "/api/conductor/snapshot?repo=fixed-repo&mission=mission-a", headers=headers
    )
    assert snapshot.status_code == 200
    doc = snapshot.json()
    assert doc["ok"] is True
    assert doc["feedback"][0]["repo"] == "fixed-repo"
    assert doc["feedback"][0]["agent"] == "edge-actor"
    assert doc["feedback"][0]["mission"] == "mission-a"
    assert doc["daemon"]["version"]
    assert doc["daemon"]["uptime_s"] >= 0
    assert doc["daemon"]["process_id"] > 0
    assert doc["persistence"]["kind"] == "sqlite"
    assert doc["auth"]["read_only"] is True
    assert doc["capabilities"]["write"] == [
        "feedback.push",
        "scratchpad.write",
        "todo.create",
        "todo.move",
    ]
    assert "command" not in json.dumps(doc).lower()
    assert len(snapshot.content) <= 64 * 1024


def test_conductor_rpc_strict_body_allowlist_and_spoof_rejection(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    url = "/api/conductor/rpc?repo=fixed&mission=m"
    before = client.app.state.store.counts()
    for method in [
        "command.run",
        "pty.open",
        "tunnel.create",
        "guardrail.toggle",
        "scout.run",
        "feedback.compact",
    ]:
        response = client.post(
            url, headers=auth_headers, json={"method": method, "params": {}}
        )
        assert response.status_code in {400, 403}
    after = client.app.state.store.counts()
    assert after == before

    spoof = client.post(
        url,
        headers=auth_headers,
        json={
            "method": "todo.create",
            "params": {"text": "x", "priority": "mid"},
            "repo": "attacker",
        },
    )
    assert spoof.status_code == 400
    nested_spoof = client.post(
        url,
        headers=auth_headers,
        json={
            "method": "todo.create",
            "params": {"text": "x", "priority": "mid", "agent": "attacker"},
        },
    )
    assert nested_spoof.status_code == 400
    assert client.post(
        url,
        headers={**auth_headers, "content-type": "application/json"},
        content=b'{"method":"todo.create","params":{"text":"' + b"x" * (16 * 1024) + b'"}}',
    ).status_code == 413


def test_conductor_rpc_rejects_chunked_body_over_limit(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    def chunks():
        yield b'{"method":"scratchpad.write","params":{"text":"'
        yield b"x" * (16 * 1024)
        yield b'"}}'

    response = client.post(
        "/api/conductor/rpc?repo=fixed&mission=m",
        headers=auth_headers,
        content=chunks(),
    )

    assert response.status_code == 413
    snapshot = client.get(
        "/api/conductor/snapshot?repo=fixed&mission=m", headers=auth_headers
    ).json()
    assert snapshot["scratchpad"] == []


def test_conductor_snapshot_stays_under_transport_limit(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    store = client.app.state.store
    for index in range(20):
        store.conductor_scratchpad_write(
            "fixed", "tester", "m", f"{index:02d}-" + ("界" * 3997)
        )

    response = client.get(
        "/api/conductor/snapshot?repo=fixed&mission=m", headers=auth_headers
    )

    assert response.status_code == 200
    assert len(response.content) <= 64 * 1024
    scratchpad = response.json()["scratchpad"]
    assert len(scratchpad) < 20
    assert scratchpad[-1]["text"].startswith("19-")


def test_conductor_snapshot_trims_oldest_feedback_and_preserves_order(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    store = client.app.state.store
    created = [
        store.conductor_feedback_push(
            "fixed",
            "tester",
            "m",
            "note",
            f"{index:02d}-" + ("界" * 997),
            0.5,
        )
        for index in range(50)
    ]

    response = client.get(
        "/api/conductor/snapshot?repo=fixed&mission=m", headers=auth_headers
    )

    assert response.status_code == 200
    assert len(response.content) <= 64 * 1024
    feedback = response.json()["feedback"]
    ids = [row["id"] for row in feedback]
    assert len(feedback) < len(created)
    assert ids == sorted(ids)
    assert ids[-1] == created[-1]["id"]
    assert created[0]["id"] not in ids


def test_conductor_snapshot_size_trim_always_retains_in_progress_todo(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    store = client.app.state.store
    active = store.conductor_todo_create(
        "fixed", "active-agent", "m", "active-" + ("A" * 993), "high"
    )
    store.conductor_todo_move(
        "fixed", "active-agent", "m", active["id"], "in_progress"
    )
    for index in range(80):
        todo = store.conductor_todo_create(
            "fixed", "tester", "m", f"{index:02d}-" + ("界" * 330), "mid"
        )
        if index % 2 == 0:
            store.conductor_todo_move(
                "fixed", "tester", "m", todo["id"], "completed"
            )

    response = client.get(
        "/api/conductor/snapshot?repo=fixed&mission=m", headers=auth_headers
    )

    assert response.status_code == 200
    assert len(response.content) <= 64 * 1024
    active_rows = [
        todo for todo in response.json()["todos"] if todo["status"] == "in_progress"
    ]
    assert [todo["id"] for todo in active_rows] == [active["id"]]


def test_conductor_rpc_round_trip(client: TestClient, auth_headers: dict[str, str]) -> None:
    url = "/api/conductor/rpc?repo=fixed&mission=m"
    scratch = client.post(
        url,
        headers=auth_headers,
        json={"method": "scratchpad.write", "params": {"text": "breadcrumb"}},
    )
    todo = client.post(
        url,
        headers=auth_headers,
        json={"method": "todo.create", "params": {"text": "next", "priority": "high"}},
    )
    moved = client.post(
        url,
        headers=auth_headers,
        json={
            "method": "todo.move",
            "params": {"id": todo.json()["result"]["id"], "status": "in_progress"},
        },
    )
    assert scratch.status_code == todo.status_code == moved.status_code == 200
    snapshot = moved.json()["snapshot"]
    assert snapshot["scratchpad"][0]["text"] == "breadcrumb"
    assert snapshot["todos"][0]["status"] == "in_progress"
