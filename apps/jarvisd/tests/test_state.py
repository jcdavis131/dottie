"""State CRUD, FTS recall, claim conflicts, export."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from jarvisd.state import TABLES, ClaimConflictError, State, repo_scope


def test_remember_and_recall_fts(state: State) -> None:
    assert state.fts_enabled
    a = state.remember("claude", "repo:dottie", "the auth middleware lives in auth.py", ["auth"])
    state.remember("cursor", "global", "coffee is in the kitchen")
    assert a["id"] == 1 and a["tags"] == ["auth"] and a["agent"] == "claude"
    hits = state.recall("middleware")
    assert [h["id"] for h in hits] == [1]
    assert state.recall("kitchen", scope="repo:dottie") == []
    assert len(state.recall("kitchen", scope="global")) == 1
    # a query with FTS syntax characters must not raise
    assert state.recall('auth "middleware" (x) *') != []


def test_recall_like_fallback(state: State) -> None:
    state.remember("a", "global", "fallback path via LIKE scan")
    state.fts_enabled = False
    hits = state.recall("like scan")
    assert len(hits) == 1
    assert state.recall("50%_wild") == []


def test_recall_empty_query_lists_newest(state: State) -> None:
    for i in range(3):
        state.remember("a", "global", f"memory {i}")
    assert [m["text"] for m in state.recall("", limit=2)] == ["memory 2", "memory 1"]


def test_remember_rejects_empty(state: State) -> None:
    with pytest.raises(ValueError, match="empty"):
        state.remember("a", "global", "   ")


def test_claim_conflict_and_release(state: State) -> None:
    c = state.claim("claude", "dottie", "apps/jarvisd", "building")
    assert c["released_ts"] is None
    # same agent re-claims: no conflict, note refreshed
    again = state.claim("claude", "dottie", "apps/jarvisd", "still building")
    assert again["id"] == c["id"] and again["note"] == "still building"
    with pytest.raises(ClaimConflictError) as ei:
        state.claim("cursor", "dottie", "apps/jarvisd")
    assert ei.value.holder["agent"] == "claude"
    with pytest.raises(ClaimConflictError):
        state.release("cursor", "dottie", "apps/jarvisd")
    assert state.release("cursor", "dottie", "apps/jarvisd", force=True)["released"] is True
    assert state.claims(repo="dottie") == []
    assert len(state.claims(repo="dottie", include_released=True)) == 1
    assert state.release("claude", "dottie", "apps/jarvisd") == {"released": False, "claim": None}


def test_messages_inbox(state: State) -> None:
    state.send("claude", "cursor", "hello")
    state.send("claude", "cursor", "second")
    assert state.unread_count("cursor") == 2
    assert state.inbox("claude") == []
    got = state.inbox("cursor", mark_read=True)
    assert [m["body"] for m in got] == ["hello", "second"]
    assert all(m["read_ts"] for m in got)
    assert state.unread_count("cursor") == 0
    assert state.inbox("cursor") == []
    assert len(state.inbox("cursor", unread_only=False)) == 2


def test_goals(state: State) -> None:
    g = state.add_goal("claude", "dottie", "ship jarvisd")
    assert g["status"] == "open" and g["result"] is None
    assert [x["id"] for x in state.goals(repo="dottie")] == [g["id"]]
    done = state.goal_done(g["id"], {"pr": 42})
    assert done is not None and done["status"] == "done" and done["result"] == {"pr": 42}
    assert state.goals(repo="dottie") == []
    assert state.goals(repo="dottie", status=None)[0]["status"] == "done"
    assert state.goal_done(999) is None
    with pytest.raises(ValueError, match="status"):
        state.goal_done(g["id"], status="bogus")


def test_timeline_and_context(state: State) -> None:
    state.timeline_add("claude", "dottie", "route", {"tier": "llm"})
    state.timeline_add("claude", "other", "run", {"run_id": "r1"})
    state.remember("claude", repo_scope("dottie"), "scoped memory")
    state.remember("claude", "global", "global memory")
    state.claim("cursor", "dottie", "README")
    state.add_goal("claude", "dottie", "goal")
    state.send("cursor", "claude", "ping")
    ctx = state.context("claude", "dottie")
    assert ctx["scope"] == "repo:dottie"
    assert [e["kind"] for e in ctx["timeline"]] == ["route"]
    assert [m["text"] for m in ctx["memories"]] == ["scoped memory"]
    assert ctx["claims"][0]["agent"] == "cursor"
    assert len(ctx["goals"]) == 1 and ctx["unread"] == 1
    assert state.timeline(kind="run")[0]["payload"] == {"run_id": "r1"}
    sess = state.touch_session("claude", "dottie")
    assert sess["agent"] == "claude"
    assert state.counts()["sessions"] == 1


def test_counts_export_and_migration_idempotent(db_path) -> None:
    s = State(db_path)
    s.remember("a", "global", "persisted")
    s.close()
    s2 = State(db_path)  # re-running migrations against an existing file is safe
    assert s2.counts()["memories"] == 1
    rows = list(s2.export("memories"))
    assert rows[0]["text"] == "persisted" and rows[0]["tags"] == []
    assert set(s2.counts()) == set(TABLES)
    with pytest.raises(ValueError, match="unknown table"):
        list(s2.export("nope"))
    s2.close()


def test_pair_code_is_expired_at_its_expiration_second(
    state: State, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 1_000}
    monkeypatch.setattr("jarvisd.state.time.time", lambda: clock["now"])
    code = state.pair_create("tester", expire_min=1)["code"]

    clock["now"] = 1_060

    assert state.pair_verify(code)["error"] == "expired"
    assert state.pair_status(code)["error"] == "unknown code"


def test_paired_aggregate_excludes_expiration_second(
    state: State, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 1_000}
    monkeypatch.setattr("jarvisd.state.time.time", lambda: clock["now"])
    code = state.pair_create("tester", expire_min=1)["code"]
    assert state.pair_verify(code)["ok"] is True

    clock["now"] = 1_060

    assert state.pair_status(code)["paired"] is False
    assert state.pair_status()["paired_count"] == 0


def test_pair_code_has_one_winner_across_store_connections(db_path) -> None:
    stores = [State(db_path), State(db_path)]
    code = stores[0].pair_create("tester")["code"]
    ready = Barrier(2)

    def verify(store: State) -> dict:
        ready.wait()
        return store.pair_verify(code)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(verify, stores))
        assert sum(result["ok"] is True for result in results) == 1
        assert sum(result.get("error") == "already paired" for result in results) == 1
    finally:
        for store in stores:
            store.close()


def test_threads_share_one_connection(state: State) -> None:
    import threading

    def work(i: int) -> None:
        for j in range(20):
            state.remember(f"t{i}", "global", f"row {i}-{j}")

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state.counts()["memories"] == 80


def test_conductor_state_persists_exact_scope_and_reopens(db_path) -> None:
    state = State(db_path)
    feedback = state.conductor_feedback_push(
        "repo-a", "agent-a", "mission-a", "note", "keep this", 0.25
    )
    scratch = state.conductor_scratchpad_write(
        "repo-a", "agent-a", "mission-a", "breadcrumb"
    )
    todo = state.conductor_todo_create(
        "repo-a", "agent-a", "mission-a", "ship slice", "mid"
    )
    state.close()

    reopened = State(db_path)
    try:
        snapshot = reopened.conductor_snapshot("repo-a", "mission-a")
        assert snapshot["feedback"] == [feedback]
        assert snapshot["scratchpad"] == [scratch]
        assert snapshot["todos"] == [todo]
        assert all(
            row["repo"] == "repo-a" and row["mission"] == "mission-a"
            for rows in snapshot.values()
            for row in rows
        )
    finally:
        reopened.close()


def test_conductor_validation_rejects_invalid_and_oversized_values(state: State) -> None:
    with pytest.raises(ValueError, match="repo"):
        state.conductor_feedback_push("", "agent", "mission", "note", "text", 0)
    with pytest.raises(ValueError, match="kind"):
        state.conductor_feedback_push("repo", "agent", "mission", "command", "text", 0)
    with pytest.raises(ValueError, match="message"):
        state.conductor_feedback_push("repo", "agent", "mission", "note", "x" * 2001, 0)
    with pytest.raises(ValueError, match="strength"):
        state.conductor_feedback_push("repo", "agent", "mission", "note", "text", 2)
    with pytest.raises(ValueError, match="text"):
        state.conductor_scratchpad_write("repo", "agent", "mission", "x" * 4001)
    with pytest.raises(ValueError, match="priority"):
        state.conductor_todo_create("repo", "agent", "mission", "text", "urgent")
    with pytest.raises(ValueError, match="status"):
        state.conductor_todo_move("repo", "agent", "mission", 1, "running")


def test_conductor_todo_move_has_one_in_progress_per_repo_mission(state: State) -> None:
    first = state.conductor_todo_create("repo", "a", "mission", "first", "mid")
    second = state.conductor_todo_create("repo", "b", "mission", "second", "high")

    state.conductor_todo_move("repo", "a", "mission", first["id"], "in_progress")
    state.conductor_todo_move("repo", "b", "mission", second["id"], "in_progress")

    todos = state.conductor_snapshot("repo", "mission")["todos"]
    assert [(todo["text"], todo["status"]) for todo in todos] == [
        ("first", "open"),
        ("second", "in_progress"),
    ]


def test_conductor_concurrent_moves_preserve_unique_in_progress(db_path) -> None:
    stores = [State(db_path), State(db_path)]
    todos = [
        stores[0].conductor_todo_create("repo", "seed", "mission", f"todo-{i}", "mid")
        for i in range(2)
    ]
    ready = Barrier(2)

    def move(pair: tuple[State, dict]) -> dict:
        store, todo = pair
        ready.wait()
        return store.conductor_todo_move(
            "repo", "worker", "mission", todo["id"], "in_progress"
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(move, zip(stores, todos, strict=True)))
        snapshot = stores[0].conductor_snapshot("repo", "mission")
        assert sum(todo["status"] == "in_progress" for todo in snapshot["todos"]) == 1
    finally:
        for store in stores:
            store.close()


def test_conductor_failed_move_rolls_back_displaced_todo(state: State) -> None:
    existing = state.conductor_todo_create(
        "repo", "owner", "mission", "existing", "mid"
    )
    state.conductor_todo_move(
        "repo", "owner", "mission", existing["id"], "in_progress"
    )

    with pytest.raises(ValueError, match="not found"):
        state.conductor_todo_move("repo", "attacker", "mission", 999, "in_progress")

    todos = state.conductor_snapshot("repo", "mission")["todos"]
    assert [(todo["id"], todo["status"], todo["agent"]) for todo in todos] == [
        (existing["id"], "in_progress", "owner")
    ]


def test_conductor_scratch_snapshot_keeps_latest_window_in_chronological_order(
    state: State,
) -> None:
    for index in range(55):
        state.conductor_scratchpad_write(
            "repo", "agent", "mission", f"scratch-{index:02d}"
        )

    scratchpad = state.conductor_snapshot("repo", "mission")["scratchpad"]

    assert [row["text"] for row in scratchpad] == [
        f"scratch-{index:02d}" for index in range(5, 55)
    ]


def test_conductor_feedback_snapshot_keeps_latest_window_in_chronological_order(
    state: State,
) -> None:
    created = [
        state.conductor_feedback_push(
            "repo", "agent", "mission", "note", f"feedback-{index:02d}", 0
        )
        for index in range(55)
    ]

    feedback = state.conductor_snapshot("repo", "mission")["feedback"]

    assert [row["id"] for row in feedback] == [
        row["id"] for row in created[-50:]
    ]


def test_conductor_todo_snapshot_keeps_newest_window_in_chronological_order(
    state: State,
) -> None:
    created = [
        state.conductor_todo_create(
            "repo", "agent", "mission", f"todo-{index:03d}", "mid"
        )
        for index in range(105)
    ]

    todos = state.conductor_snapshot("repo", "mission")["todos"]

    assert [row["id"] for row in todos] == [
        row["id"] for row in created[-100:]
    ]


def test_conductor_todo_snapshot_retains_older_in_progress_plus_newest_99(
    state: State,
) -> None:
    active = state.conductor_todo_create(
        "repo", "owner", "mission", "active", "high"
    )
    state.conductor_todo_move(
        "repo", "owner", "mission", active["id"], "in_progress"
    )
    newer = [
        state.conductor_todo_create(
            "repo", "agent", "mission", f"newer-{index:03d}", "mid"
        )
        for index in range(105)
    ]

    todos = state.conductor_snapshot("repo", "mission")["todos"]

    assert len(todos) == 100
    assert [row["id"] for row in todos] == [
        active["id"],
        *(row["id"] for row in newer[-99:]),
    ]
    assert todos[0]["status"] == "in_progress"
