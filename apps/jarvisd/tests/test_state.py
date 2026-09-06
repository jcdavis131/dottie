"""State CRUD, FTS recall, claim conflicts, export."""

from __future__ import annotations

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
