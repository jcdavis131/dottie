"""Training-monitor honesty (SPEC build-priority #4, TODOS §5.3.R102).

The bug: when no live trainer metrics exist, `mode_monitor` fell back to
STATUS.json and reported the DATA BUILDER's token/doc counts as training
"steps", then computed staleness off the builder's clock -- crying
"training stale at step 500044" (and "stale 15.4h") when training had never
run. The contract these tests lock in:

  * training steps/loss/staleness come ONLY from real trainer telemetry;
  * absent that telemetry, the status is "not_running", steps=0, stale=False;
  * builder activity is surfaced separately (builder_tokens/docs/age), never
    as training progress;
  * a genuinely stale *trainer* (telemetry present, old timestamp) still
    reports stale=True / "warn".
"""
from __future__ import annotations

import argparse
import json

import pytest

from scripts.dottie_continuous_loop import mode_monitor


def _run(monkeypatch, tmp_path, collect_return, status_json=None):
    """Drive mode_monitor with a forced pipeline_status and a temp repo root."""
    import scripts.dottie_continuous_loop as loop
    import dottie.pipeline_status as ps

    monkeypatch.setattr(loop, "_REPO_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(ps, "collect_status", lambda *a, **k: collect_return, raising=False)
    if status_json is not None:
        (tmp_path / "STATUS.json").write_text(json.dumps(status_json), encoding="utf-8")
    return mode_monitor(argparse.Namespace())


def test_no_training_reports_not_running_never_builder_stale(monkeypatch, tmp_path):
    """No live trainer + an old, large builder expansion. The builder's 500k
    tokens must NOT become training steps, and its 20h-old clock must NOT mark
    training stale."""
    status = {"builder": {"last_expansion": {
        "tokens": 500034, "docs": 1606, "timestamp": "2020-01-01T00:00:00Z"}}}
    res = _run(monkeypatch, tmp_path, collect_return=None, status_json=status)

    assert res["status"] == "not_running"
    assert res["steps"] == 0, "builder tokens must never be reported as training steps"
    assert res["stale"] is False, "the builder's clock must not mark training stale"
    # builder activity is still surfaced, just clearly labelled as the builder's
    assert res["detail"]["builder_tokens"] == 500034
    assert res["detail"]["builder_docs"] == 1606
    assert res["detail"].get("builder_age_s", 0) > 1800, "builder age recorded for context"


def test_no_status_file_is_not_running(monkeypatch, tmp_path):
    """Nothing running and no STATUS.json at all: still 'not_running', not a crash
    and not a false step count."""
    res = _run(monkeypatch, tmp_path, collect_return=None, status_json=None)
    assert res["status"] == "not_running"
    assert res["steps"] == 0 and res["stale"] is False


def test_real_recent_training_is_reported(monkeypatch, tmp_path):
    """Live trainer telemetry with a recent row: real steps, not stale, not
    'not_running'."""
    pipeline = {
        "trainer": {"last": {"step": 1200, "lm_loss": 2.31}, "age_s": 5,
                    "stale": False, "stale_after_s": 1800},
        "mode": {"label": "train"}, "preset": "nano",
    }
    res = _run(monkeypatch, tmp_path, collect_return=pipeline)
    assert res["steps"] == 1200
    assert res["loss"] == pytest.approx(2.31)
    assert res["stale"] is False
    assert res["status"] != "not_running"


def test_real_trainer_staleness_is_preserved(monkeypatch, tmp_path):
    """A genuine stale trainer (telemetry present, age > 1800s) must still warn --
    the fix removes only the FALSE builder-clock staleness, not real staleness."""
    pipeline = {
        "trainer": {"last": {"step": 1200, "lm_loss": 2.31}, "age_s": 4000,
                    "stale": False, "stale_after_s": 1800},
        "mode": {"label": "train"}, "preset": "nano",
    }
    res = _run(monkeypatch, tmp_path, collect_return=pipeline)
    assert res["stale"] is True
    assert res["status"] == "warn"
    assert res["steps"] == 1200, "real training steps must survive a staleness warning"
