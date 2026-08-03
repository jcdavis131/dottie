"""`scout tennis serve`. 33 loc, no test file until 2026-08-02.

The plugin is a BOOKMARK — its only job is resolving the vector-tennis repo and saying
whether it is there. It got that wrong:

    "status": "bookmark — repo not present"
    "repo":   "C:\\Users\\jcdav\\workspace\\vector-tennis"

while the checkout sat at ~/vector-tennis. A bookmark that reports the thing is missing,
when it is present one directory up, has failed at the only thing it does.

Third instance of the shape this session — ava/cli.py resolved to a superseded tree
(0c89edd), rtx/cli.py to a directory that did not exist (6063da7). All three were a single
hardcoded location with no alternative candidate and no override.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bigbang.core.output import set_json_mode
from bigbang.plugins.tennis import cli as tc


@pytest.fixture(autouse=True)
def _json_mode():
    set_json_mode(True)
    yield
    set_json_mode(False)


def _emitted(capsys) -> dict:
    payload = json.loads(capsys.readouterr().out)
    return payload.get("data") or payload


def test_finds_the_repo_where_it_actually_lives(monkeypatch, tmp_path):
    """The defect. ~/vector-tennis must be found, not only ~/workspace/vector-tennis."""
    monkeypatch.delenv("SCOUT_TENNIS_REPO", raising=False)
    monkeypatch.setattr(tc.Path, "home", staticmethod(lambda: tmp_path))
    real = tmp_path / "vector-tennis"
    real.mkdir()

    assert tc._tennis_repo() == real


def test_the_workspace_layout_still_works(monkeypatch, tmp_path):
    """Non-vacuity: adding the direct-home candidate must not break the other convention,
    which brain, lab, ava and rtx all use."""
    monkeypatch.delenv("SCOUT_TENNIS_REPO", raising=False)
    monkeypatch.setattr(tc.Path, "home", staticmethod(lambda: tmp_path))
    ws = tmp_path / "workspace" / "vector-tennis"
    ws.mkdir(parents=True)

    assert tc._tennis_repo() == ws


def test_env_override_wins(monkeypatch, tmp_path):
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    monkeypatch.setenv("SCOUT_TENNIS_REPO", str(elsewhere))
    assert tc._tennis_repo() == elsewhere


def test_serve_reports_present_when_it_is(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SCOUT_TENNIS_REPO", str(tmp_path))
    tc.serve(video=None)
    payload = _emitted(capsys)
    assert payload["status"] == "repo present", payload
    assert payload["video"] == "live cam"


def test_serve_still_reports_absent_when_it_is(monkeypatch, tmp_path, capsys):
    """The check must stay capable of failing — it is the whole point of a bookmark."""
    monkeypatch.setenv("SCOUT_TENNIS_REPO", str(tmp_path / "nope"))
    tc.serve(video="clip.mp4")
    payload = _emitted(capsys)
    assert payload["status"].startswith("bookmark"), payload
    assert payload["video"] == "clip.mp4"
    assert "SCOUT_TENNIS_REPO" in payload["hint"]


def test_absent_message_names_the_preferred_location(monkeypatch, tmp_path):
    """When nothing exists, name where the operator most likely wants it — not whichever
    candidate happened to be listed last."""
    monkeypatch.delenv("SCOUT_TENNIS_REPO", raising=False)
    monkeypatch.setattr(tc.Path, "home", staticmethod(lambda: tmp_path))
    got = tc._tennis_repo()
    assert got == tmp_path / "vector-tennis", got
    assert not got.exists()


def test_repo_is_resolved_per_call(monkeypatch, tmp_path):
    """A module-level constant could not be redirected after import — the shape that bit
    telemetry's _LOGS_DIR (53c5c60)."""
    monkeypatch.setenv("SCOUT_TENNIS_REPO", str(tmp_path / "one"))
    first = tc._tennis_repo()
    monkeypatch.setenv("SCOUT_TENNIS_REPO", str(tmp_path / "two"))
    assert tc._tennis_repo() != first


def test_the_old_module_constant_is_gone():
    """TENNIS_REPO was bound at import from a single hardcoded path. If it comes back,
    every fix above is bypassable by reading it."""
    assert not hasattr(tc, "TENNIS_REPO"), "module-level TENNIS_REPO reintroduced"
    assert isinstance(tc._tennis_repo(), Path)
