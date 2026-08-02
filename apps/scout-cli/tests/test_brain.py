"""The brain plugin. 156 loc, no test file until 2026-08-02.

GOAT scored brain D3 **0** — the only zero on that dimension in the repo — for four
hardcoded home-layout paths. After the D3 false-positive fix (1e41512) that zero was
trustworthy, and reading the file found three real defects behind it.

THE ONE THAT MATTERS. `_read_if_exists` returned `text[:8000]` — the FIRST 8000 chars —
and `memory_cmd` then did `.splitlines()[-n:]` on that. So "the last n lines of MEMORY.md"
was the last n lines of the beginning of the file. Measured on a 400-line, 11,199-char
file:

    true last line    : line 0399
    what brain showed : line 0285      (and cut mid-word)

Silently wrong rather than obviously truncated: the field is called `MEMORY.md_tail`, looks
like a tail, and was 114 lines short of one. MEMORY.md is designed to grow, so it gets
worse with use.

Everything here runs against tmp_path via SCOUT_BRAIN_ROOT, which is also the fix for D3.
"""

from __future__ import annotations

import json

import pytest

from bigbang.core.output import set_json_mode
from bigbang.plugins.brain import cli as bc


@pytest.fixture(autouse=True)
def _json_mode():
    set_json_mode(True)
    yield
    set_json_mode(False)


@pytest.fixture
def brain_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_BRAIN_ROOT", str(tmp_path))
    return tmp_path


def _emitted(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


# --- the tail bug --------------------------------------------------------------------


def _big_memory(root, lines=400):
    body = "\n".join(f"line {i:04d} ................." for i in range(lines))
    (root / "MEMORY.md").write_text(body, encoding="utf-8")
    return body


def test_the_memory_tail_is_actually_the_tail(brain_home, capsys):
    """The defect. Over READ_LIMIT the old code returned the head and called it a tail."""
    body = _big_memory(brain_home)
    assert len(body) > bc.READ_LIMIT, "fixture must exceed the cap or this proves nothing"

    bc.memory_cmd(query="", n=3)
    tail = _emitted(capsys)["MEMORY.md_tail"]
    assert tail == body.splitlines()[-3:], tail


def test_a_short_file_is_returned_whole(brain_home, capsys):
    """Non-vacuity: the tail path must not be the only path that works."""
    (brain_home / "MEMORY.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    bc.memory_cmd(query="", n=30)
    assert _emitted(capsys)["MEMORY.md_tail"] == ["alpha", "beta", "gamma"]


def test_the_tail_drops_a_partial_first_line(brain_home):
    """A slice from the end can start mid-line. Reporting that fragment as a whole line
    would be a smaller version of the same lie."""
    body = _big_memory(brain_home)
    out = bc._read_if_exists(brain_home / "MEMORY.md", tail=True)
    assert out is not None
    assert body.endswith(out), "the tail must be a genuine suffix of the file"
    assert out.splitlines()[0] in body.splitlines(), "first line is a fragment"


def test_head_mode_still_takes_the_head(brain_home):
    """tail=False is used for PROJECT.md, where the first lines carry the title."""
    body = _big_memory(brain_home)
    out = bc._read_if_exists(brain_home / "MEMORY.md", tail=False)
    assert body.startswith(out)


# --- paths are overridable (D3) -------------------------------------------------------


def test_every_path_follows_scout_brain_root(brain_home):
    for path in (bc._memory_file(), bc._daily_file(), bc._projects_root()):
        assert str(path).startswith(str(brain_home)), path


def test_root_is_resolved_per_call_not_at_import(tmp_path, monkeypatch):
    """A module-level default binds before a harness can redirect it — the shape that bit
    apps/ava-factory/dottie/telemetry.py (53c5c60) and `sync --out` here."""
    monkeypatch.setenv("SCOUT_BRAIN_ROOT", str(tmp_path / "first"))
    first = bc._brain_root()
    monkeypatch.setenv("SCOUT_BRAIN_ROOT", str(tmp_path / "second"))
    assert bc._brain_root() != first


def test_without_the_env_var_it_falls_back_to_home(monkeypatch):
    """Non-vacuity for the override: the default must still be the documented layout."""
    monkeypatch.delenv("SCOUT_BRAIN_ROOT", raising=False)
    from pathlib import Path

    assert bc._memory_file() == Path.home() / "MEMORY.md"


# --- goals: 0 must be distinguishable from "wrong layout" -----------------------------


def test_goals_says_where_it_looked_when_there_is_no_projects_root(brain_home, capsys):
    """`count: 0` alone cannot be told apart from a machine with a different layout."""
    bc.goals_cmd(active_only=True, search="")
    payload = _emitted(capsys)
    assert payload["count"] == 0
    assert payload["projects_root_exists"] is False
    assert str(brain_home) in payload["projects_root"]
    assert "SCOUT_BRAIN_ROOT" in payload["hint"]


def test_goals_finds_a_project(brain_home, capsys):
    """Non-vacuity: goals_cmd must be capable of returning something."""
    proj = brain_home / "workspace" / "projects" / "demo-goal"
    proj.mkdir(parents=True)
    (proj / "PROJECT.md").write_text("# Demo Goal\nbody\n", encoding="utf-8")
    bc.goals_cmd(active_only=True, search="")
    payload = _emitted(capsys)
    assert payload["count"] == 1
    assert payload["goals"][0]["slug"] == "demo-goal"
    assert payload["goals"][0]["title"] == "Demo Goal"
    assert payload["projects_root_exists"] is True


def test_goals_skips_archived_when_active_only(brain_home, capsys):
    proj = brain_home / "workspace" / "projects" / "old-goal"
    proj.mkdir(parents=True)
    (proj / "PROJECT.md").write_text("# Old\nstatus: archived\n", encoding="utf-8")
    bc.goals_cmd(active_only=True, search="")
    assert _emitted(capsys)["count"] == 0
    bc.goals_cmd(active_only=False, search="")
    assert _emitted(capsys)["count"] == 1


def test_goal_detail_reports_the_path_it_missed(brain_home, capsys):
    bc.goal_detail(slug="nope")
    payload = _emitted(capsys)
    assert "not found" in payload["error"]
    assert str(brain_home) in payload["path"]


# --- writes ---------------------------------------------------------------------------


def test_daily_appends_under_the_brain_root(brain_home, capsys):
    bc.daily_cmd(note="first note")
    path = brain_home / "memory"
    written = list(path.glob("*.md"))
    assert len(written) == 1, written
    assert "first note" in written[0].read_text(encoding="utf-8")
    bc.daily_cmd(note="second note")
    text = written[0].read_text(encoding="utf-8")
    assert "first note" in text and "second note" in text, "append must not overwrite"


def test_sync_writes_under_the_brain_root_not_the_real_home(brain_home, capsys):
    """The --out default used to be a typer.Option containing Path.home(), bound at import.
    Resolved per call now, so this lands in the fixture rather than the operator's tree."""
    (brain_home / "MEMORY.md").write_text("one\ntwo\n", encoding="utf-8")
    bc.sync_cmd(out=None)
    payload = _emitted(capsys)
    assert str(brain_home) in payload["synced"]
    data = json.loads((brain_home / "workspace" / "your_files" / "brain-sync.json").read_text())
    assert data["memory_lines"] == 2
    assert data["ts"].endswith("+00:00"), "utcnow() gave a naive stamp labelled Z"
