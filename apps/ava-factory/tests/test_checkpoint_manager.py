"""checkpoint_manager.load() must survive one corrupt copy — that is the triple-write's job.

Regression (measured 2026-08-05): the except inside the location loop did
`return None`, so a corrupt FIRST copy was fatal even when a good copy sat in
the next location, and resume() then raised "no checkpoint for <id>" — reporting
a damaged run as a missing one.
"""

from __future__ import annotations

import json

import pytest

from dottie.pipeline import checkpoint_manager as cm


@pytest.fixture()
def bases(tmp_path, monkeypatch):
    """Point all three write locations at throwaway dirs."""
    a, b, c = tmp_path / "local", tmp_path / "ultra", tmp_path / "ws"
    monkeypatch.setattr(cm, "_DOTTIE_RUNS", a)
    monkeypatch.setattr(cm, "_RUNS", b)
    monkeypatch.setattr(cm, "_WORKSPACE_RUNS", c)
    return a, b, c


def _write_checkpoint(base, run_id, payload):
    d = base / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "checkpoint.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )


def test_corrupt_first_copy_falls_through_to_good_copy(bases):
    a, b, _ = bases
    _write_checkpoint(a, "r1", "{ this is not json")
    _write_checkpoint(b, "r1", {"runId": "r1", "dag_version": 7, "nodes": []})
    mgr = cm.DottieCheckpointManager("r1")
    state = mgr.load()
    assert state is not None, "corrupt local copy must not mask the good ultra copy"
    assert state["dag_version"] == 7


def test_all_copies_corrupt_returns_none(bases):
    a, b, c = bases
    for base in (a, b, c):
        _write_checkpoint(base, "r2", "not json either")
    assert cm.DottieCheckpointManager("r2").load() is None


def test_missing_everywhere_returns_none(bases):
    assert cm.DottieCheckpointManager("r3").load() is None


def test_resume_uses_fallback_copy(bases):
    a, b, _ = bases
    _write_checkpoint(a, "r4", "\x00\x00")
    _write_checkpoint(
        b, "r4", {"runId": "r4", "dag_version": 2, "nodes": [{"id": "n1", "status": "pending"}]}
    )
    out = cm.DottieCheckpointManager("r4").resume()
    assert out["state"]["dag_version"] == 2
    assert len(out["next_nodes"]) == 1
