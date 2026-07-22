"""JSpaceStateStore — real SQLite mutations, cross-instance persistence, honest NULLs.

No mocks anywhere: every test opens a real database file under tmp_path, writes real
rows, and re-opens the file in a SECOND store instance to prove the state survives the
process boundary (the OpenClaw property the engine depends on).
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from skills.state_store import (
    JSpaceStateStore,
    StateStoreCorruptError,
    default_db_path,
)


def test_skills_library_register_get_version_bump(tmp_path):
    with JSpaceStateStore(tmp_path / "s.sqlite3") as st:
        v1 = st.register_skill(
            "github",
            "def run(): ...",
            capabilities="network",
            schema={"args": ["repo"]},
        )
        assert v1 == 1
        v2 = st.register_skill("github", "def run(repo): ...", capabilities="network")
        assert v2 == 2
        got = st.get_skill("github")
        assert got["version"] == 2 and "repo" in got["code"]
        assert (
            got["schema"] is None
        )  # v2 registered without schema — not carried over silently
        assert st.get_skill("nope") is None
        assert [s["name"] for s in st.list_skills()] == ["github"]


def test_session_context_persists_across_store_instances(tmp_path):
    db = tmp_path / "s.sqlite3"
    with JSpaceStateStore(db) as st:
        st.set_context("sess-1", "phase", "collect")
        st.set_context("sess-1", "retries", 2, channel="slack")
    # a NEW instance on the same file — the cross-loop / cross-channel re-entry path
    with JSpaceStateStore(db) as st2:
        assert st2.get_context("sess-1", "phase") == "collect"
        assert st2.get_context("sess-1", "retries", channel="slack") == 2
        assert st2.get_context("sess-1", "missing", default="d") == "d"
        st2.set_context("sess-1", "phase", "train")  # upsert overwrites
        snap = st2.session_snapshot("sess-1")
    assert snap == {"default": {"phase": "train"}, "slack": {"retries": 2}}


def test_task_logs_and_stats_keep_honest_nulls(tmp_path):
    with JSpaceStateStore(tmp_path / "s.sqlite3") as st:
        st.log_task("sess-1", "index repo", "ok", trace={"steps": 3}, policy_ok=True)
        st.log_task("sess-1", "deploy", "failed")
        st.log_task("sess-2", "eval run", "ok", eval_score=0.81)
        recent = st.recent_tasks(10)
        assert len(recent) == 3 and recent[0]["task"] == "eval run"
        assert recent[0]["eval_score"] == 0.81
        # unevaluated/unchecked stay NULL — never defaulted to a fake number
        deploy = next(r for r in recent if r["task"] == "deploy")
        assert deploy["eval_score"] is None and deploy["policy_ok"] is None
        stats = st.task_stats()
        assert stats["by_outcome"] == {"ok": 2, "failed": 1}
        assert stats["evaluated"] == 1 and abs(stats["avg_eval_score"] - 0.81) < 1e-9


def test_stats_with_no_evaluations_report_none_not_zero(tmp_path):
    with JSpaceStateStore(tmp_path / "s.sqlite3") as st:
        st.log_task("s", "t", "ok")
        assert st.task_stats()["avg_eval_score"] is None


def test_telemetry_export_appends_jsonl(tmp_path):
    out = tmp_path / "telemetry.jsonl"
    with JSpaceStateStore(tmp_path / "s.sqlite3") as st:
        st.log_task("sess-1", "a", "ok", eval_score=0.5)
        st.log_task("sess-1", "b", "refused")
        assert st.export_telemetry(out) == 2
        assert (
            st.export_telemetry(out, since_ts=9e12) == 0
        )  # nothing newer — appends nothing
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["event"] == "task" and lines[1]["outcome"] == "refused"
    assert lines[0]["eval_score"] == 0.5 and lines[1]["eval_score"] is None


def test_default_db_path_is_outside_the_repo(tmp_path, monkeypatch):
    monkeypatch.delenv("DOTTIE_STATE_DB", raising=False)
    p = default_db_path()
    assert ".dottie-claw" in str(p)  # home-dir state, never committable
    monkeypatch.setenv("DOTTIE_STATE_DB", str(tmp_path / "override.sqlite3"))
    assert default_db_path() == tmp_path / "override.sqlite3"


def test_incremental_export_is_idempotent(tmp_path):
    out = tmp_path / "t.jsonl"
    db = tmp_path / "s.sqlite3"
    with JSpaceStateStore(db) as st:
        st.log_task("s", "one", "ok")
        st.log_task("s", "two", "ok")
        assert st.export_telemetry_incremental(out) == 2
        assert st.export_telemetry_incremental(out) == 0  # watermark holds
    with JSpaceStateStore(db) as st2:  # survives reconnection
        assert st2.export_telemetry_incremental(out) == 0
        st2.log_task("s", "three", "ok")
        assert st2.export_telemetry_incremental(out) == 1
    assert len(out.read_text(encoding="utf-8").splitlines()) == 3


def test_register_skill_concurrent_bumps_are_monotonic_without_loss(tmp_path):
    """Many writers, each on its OWN connection to the same WAL file (the scout-CLI +
    engine sharing scenario the module docstring calls out), hammer register_skill on one
    skill name simultaneously. The insert-or-bump is a single atomic UPSERT, so every call
    must return a DISTINCT version and the final stored version must equal the number of
    registrations -- no bump silently lost to a read-modify-write race. This test fails
    against the old SELECT-then-UPDATE, which let two writers both read version N and both
    write N+1."""
    db = tmp_path / "s.sqlite3"
    writers = 24
    returned: list[int] = []
    guard = threading.Lock()
    ready = threading.Barrier(writers)

    def worker(i: int) -> None:
        # a fresh store == a fresh connection, exactly like separate OS processes
        with JSpaceStateStore(db) as st:
            ready.wait()  # release all threads at once to maximise contention
            v = st.register_skill("shared", f"def run(): return {i}")
            with guard:
                returned.append(v)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # every writer observed a unique version 1..writers -- none collided or was lost
    assert sorted(returned) == list(range(1, writers + 1))
    with JSpaceStateStore(db) as st:
        assert st.get_skill("shared")["version"] == writers


def test_register_skill_repeated_bumps_increment_monotonically(tmp_path):
    with JSpaceStateStore(tmp_path / "s.sqlite3") as st:
        versions = [st.register_skill("k", f"def run(): return {i}") for i in range(5)]
        assert versions == [1, 2, 3, 4, 5]  # monotonic, one per call
        assert st.get_skill("k")["version"] == 5


def test_corrupt_db_surfaces_typed_error_not_raw_crash(tmp_path):
    db = tmp_path / "s.sqlite3"
    db.write_bytes(b"NOT A SQLITE DATABASE" * 64)
    with pytest.raises(StateStoreCorruptError) as exc:
        JSpaceStateStore(db)
    assert str(db) in str(exc.value)
    assert issubclass(StateStoreCorruptError, sqlite3.DatabaseError)
