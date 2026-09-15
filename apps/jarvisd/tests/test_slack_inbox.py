"""Slack inbox drain: one bad file never stops the good ones, and nothing opens twice.

The `open_goal` hook is a fake shaped like `Jarvis.goal`'s return dict, so these
tests never need a database. The one test that does want the real registration
path builds a throwaway `State` and goes through `Jarvis.goal` itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jarvisd.slack_inbox import (
    SlackInboxError,
    clean_text,
    default_state_path,
    drain,
)


def _write(inbox: Path, name: str, payload: Any) -> Path:
    p = inbox / name
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _item(ts: str, text: str = "ship the thing", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "channel_message",
        "channel": "C0BVDL26PSB",
        "channel_name": "#agent-ops",
        "user": "U0C08PGHVNF",
        "text": text,
        "ts": ts,
        "thread_ts": "",
    }
    base.update(kw)
    return base


class _FakeGoals:
    """Stands in for `Jarvis.goal`: records calls, returns its shape."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.fail_on: set[str] = set()

    def __call__(self, agent: str, repo: str, text: str) -> dict[str, Any]:
        self.calls.append((agent, repo, text))
        if text in self.fail_on:
            return {"ok": False, "error": "boom"}
        goal_id = len(self.calls)
        return {"ok": True, "goal": {"id": goal_id, "text": text, "status": "open"}}


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    d = tmp_path / "inbox"
    d.mkdir()
    return d


@pytest.fixture
def fake() -> _FakeGoals:
    return _FakeGoals()


def test_happy_path_opens_goals_and_moves_files(inbox: Path, fake: _FakeGoals) -> None:
    _write(inbox, "a.json", _item("111.1", "<@U0C0F0Z2UM8> ship the thing"))
    _write(inbox, "b.json", _item("222.2", "fix the flaky test", thread_ts="111.1"))

    out = drain(inbox, fake, agent="scout", repo="dottie")

    assert out["ok"] is True
    assert [g["text"] for g in out["opened"]] == ["ship the thing", "fix the flaky test"]
    assert fake.calls[0] == ("scout", "dottie", "ship the thing")
    # files moved out of the inbox
    assert list((inbox / "_done").glob("*.json")) != []
    assert list(inbox.glob("*.json")) == []
    # dedupe state records provenance, including the thread context
    seen = json.loads(default_state_path(inbox).read_text(encoding="utf-8"))["seen"]
    assert seen["111.1"]["goal_id"] == 1
    assert seen["222.2"]["thread_ts"] == "111.1"
    assert seen["222.2"]["channel_name"] == "#agent-ops"


def test_malformed_items_quarantined_not_crashing(inbox: Path, fake: _FakeGoals) -> None:
    _write(inbox, "good.json", _item("111.1", "real work"))
    _write(inbox, "bad-json.json", "{not json")
    _write(inbox, "no-ts.json", {"kind": "channel_message", "text": "nope"})
    _write(inbox, "weird-kind.json", _item("333.3", "x", kind="carrier_pigeon"))
    _write(inbox, "empty.json", _item("444.4", "   "))
    _write(inbox, "not-object.json", [1, 2, 3])

    out = drain(inbox, fake)

    assert [g["text"] for g in out["opened"]] == ["real work"]
    reasons = {q["path"].rsplit("/", 1)[-1]: q["reason"] for q in out["quarantined"]}
    assert reasons["bad-json.json"] == "malformed JSON"
    assert reasons["no-ts.json"] == "missing ts"
    assert "unknown kind" in reasons["weird-kind.json"]
    assert reasons["empty.json"] == "empty text after cleaning"
    assert reasons["not-object.json"] == "not a JSON object"
    assert len(out["quarantined"]) == 5
    # quarantined files left the inbox with the reason stamped in
    qdir = inbox / "_quarantine"
    stamped = json.loads((qdir / "no-ts.json").read_text(encoding="utf-8"))
    assert stamped["_quarantine_reason"] == "missing ts"
    assert list(inbox.glob("*.json")) == []


def test_dedupe_by_ts_across_runs(inbox: Path, fake: _FakeGoals) -> None:
    _write(inbox, "a.json", _item("111.1", "do it"))
    first = drain(inbox, fake)
    assert len(first["opened"]) == 1

    # same Slack message redelivered as a new file: must not open a second goal
    _write(inbox, "a-retry.json", _item("111.1", "do it"))
    second = drain(inbox, fake)
    assert second["opened"] == []
    assert second["skipped_seen"] == ["111.1"]
    assert len(fake.calls) == 1


def test_dedupe_within_one_run(inbox: Path, fake: _FakeGoals) -> None:
    _write(inbox, "a.json", _item("111.1", "do it"))
    _write(inbox, "b.json", _item("111.1", "do it"))
    out = drain(inbox, fake)
    assert len(out["opened"]) == 1
    assert out["skipped_seen"] == ["111.1"]


def test_dry_run_changes_nothing(inbox: Path, fake: _FakeGoals) -> None:
    _write(inbox, "a.json", _item("111.1", "do it"))
    _write(inbox, "bad.json", "{nope")

    out = drain(inbox, fake, dry_run=True)

    assert out["dry_run"] is True
    assert fake.calls == []
    assert [w["ts"] for w in out["would_open"]] == ["111.1"]
    assert len(out["quarantined"]) == 1  # still reported, not moved
    assert (inbox / "a.json").exists()  # files stay put
    assert not default_state_path(inbox).exists()  # no state written


def test_open_failure_stays_for_retry(inbox: Path, fake: _FakeGoals) -> None:
    fake.fail_on.add("unlucky")
    _write(inbox, "a.json", _item("111.1", "unlucky"))
    _write(inbox, "b.json", _item("222.2", "lucky"))

    out = drain(inbox, fake)

    assert [g["text"] for g in out["opened"]] == ["lucky"]
    assert len(out["failed"]) == 1
    assert out["failed"][0]["reason"] == "boom"
    assert (inbox / "a.json").exists()  # left for a later run
    seen = json.loads(default_state_path(inbox).read_text(encoding="utf-8"))["seen"]
    assert "111.1" not in seen  # not marked seen: it never became a goal


def test_corrupt_dedupe_state_is_a_hard_stop(inbox: Path, fake: _FakeGoals) -> None:
    _write(inbox, "a.json", _item("111.1", "do it"))
    sp = default_state_path(inbox)
    sp.parent.mkdir(parents=True)
    sp.write_text("{corrupt", encoding="utf-8")

    with pytest.raises(SlackInboxError, match="dedupe state unreadable"):
        drain(inbox, fake)
    assert fake.calls == []  # nothing opened on the way out


def test_clean_text_strips_leading_mentions() -> None:
    assert clean_text("<@U0C0F0Z2UM8> ship it") == "ship it"
    assert clean_text("<!channel> <@U1> hello") == "hello"
    assert clean_text("  padded  ") == "padded"
    assert clean_text(None) == ""
    assert clean_text(123) == ""
    # a mention mid-text is content, not a prefix: left alone
    assert clean_text("ask <@U1> about it") == "ask <@U1> about it"


def test_real_jarvis_goal_registration(tmp_path: Path) -> None:
    """End to end through the real `Jarvis.goal` into a throwaway SQLite DB."""
    from jarvisd.config import Config
    from jarvisd.state import State
    from jarvisd.tools import Jarvis

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write(inbox, "a.json", _item("999.9", "slack says hi"))

    db = tmp_path / "jarvis.db"
    state = State(db)
    try:
        jarvis = Jarvis(Config(db_path=db), state)
        out = drain(inbox, jarvis.goal, agent="cameron", repo="dottie")
    finally:
        state.close()

    assert out["ok"] is True
    assert len(out["opened"]) == 1
    state2 = State(db)
    try:
        goals = state2.goals(status=None)
    finally:
        state2.close()
    assert len(goals) == 1
    assert goals[0]["text"] == "slack says hi"
    assert goals[0]["agent"] == "cameron"
    assert goals[0]["status"] == "open"


def test_drain_lock_is_exclusive(tmp_path: Path) -> None:
    """Two drains on one state file can never interleave: the lock is exclusive.

    Deterministic (no timing): while one holder owns the lock, a second open
    file description cannot take it even non-blocking.
    """
    import fcntl

    from jarvisd.slack_inbox import _drain_lock, _lock_path

    state = tmp_path / "state.json"
    with _drain_lock(state):
        assert _lock_path(state).exists()
        with open(_lock_path(state), "a+b") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    # After release, a non-blocking lock succeeds again.
    with open(_lock_path(state), "a+b") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(other.fileno(), fcntl.LOCK_UN)
