# Solo personal project, no connection to employer, built with public/free-tier only
"""Flywheel tests — real ETL run, real memory-mint, real harness subprocess, honest gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes import flywheel


# -- export_rft_dataset --------------------------------------------------------------

def test_export_rft_runs_the_real_etl(engine, echo_record, data_dir):
    res = flywheel.export_rft_dataset(data_dir)
    assert res["source_traces"] == 1
    # 2 sandbox steps + 1 terminal event, all from the real trace.
    assert res["audit_events_written"] == 3 == res["audit_events"]
    assert res["records_written"] >= 1
    out = Path(res["out"])
    assert out.exists()
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert rows, "real dataset file must contain the exported episode"
    rec = rows[0]
    # The REAL scout-cli ETL schema, produced by the real module (path in the result).
    assert rec["schema_version"] == "1.0.0"
    assert "reward_components" in rec and "r_task_terminal_ok" in rec["reward_components"]
    # The echo episode really reached FINAL -> terminal event ok -> real task signal 1.0.
    assert rec["reward_components"]["r_task_terminal_ok"] == 1.0
    assert rec["meta"]["redacted"] is True
    assert "etl.py" in res["etl_module"]


def test_export_rft_refuses_without_traces(data_dir):
    with pytest.raises(flywheel.FlywheelUnavailable) as ei:
        flywheel.export_rft_dataset(data_dir)
    assert "no hermes traces" in str(ei.value)


# -- mint_memories -------------------------------------------------------------------

def test_mint_memories_real_pipeline(engine, echo_record, data_dir):
    res = flywheel.mint_memories(data_dir)
    assert res["events_captured"] == 1
    assert res["stats"]["minted"] == 1 and res["stats"]["dropped"] == 0
    store_dir = Path(res["store_dir"])
    assert store_dir.exists()
    shard_files = list(store_dir.glob("*.jsonl"))
    assert shard_files, "minted shards must land on disk"
    shard = json.loads(shard_files[0].read_text().splitlines()[0])
    assert shard["source"] == "hermes:echo"
    assert shard["ok"] is True
    assert "conftest echo task" in shard["instruction"]
    # Real measured metrics rode along (r_exec was 1.0 from the real sandbox run).
    assert shard["metrics"]["r_exec"] == 1.0
    # Re-minting the same traces dedupes by content hash — reported, not hidden.
    res2 = flywheel.mint_memories(data_dir)
    assert res2["stats"]["deduped"] == 1 and res2["stats"]["minted"] == 0


def test_mint_refuses_without_traces(data_dir):
    with pytest.raises(flywheel.FlywheelUnavailable):
        flywheel.mint_memories(data_dir)


# -- evaluate (real harness subprocess) ----------------------------------------------

def test_evaluate_runs_real_harness_mock_mode(data_dir):
    res = flywheel.evaluate(data_dir, mode="mock")
    report = Path(res["report_json"])
    assert report.exists(), "the harness must have written a real report file"
    payload = json.loads(report.read_text())
    assert payload["meta"]["mode"] == "mock"
    assert res["meta"]["total"] == payload["meta"]["total"] > 0
    assert isinstance(res["meta"]["passed"], int)
    assert Path(res["report_md"]).exists()


def test_evaluate_refuses_when_harness_missing(data_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("DOTTIE_ROOT", str(tmp_path / "empty"))
    with pytest.raises(flywheel.FlywheelUnavailable) as ei:
        flywheel.evaluate(data_dir)
    assert "ava-open-harness" in str(ei.value)


def test_evaluate_real_mode_without_ckpt_is_honest_failure_report(data_dir):
    """The harness's own anti-mock rule: real mode with no ckpt yields a structured
    honest-failure report (pass=0), not fabricated measurements. Hermes passes it through."""
    res = flywheel.evaluate(data_dir, mode="real")
    payload = json.loads(Path(res["report_json"]).read_text())
    assert payload["meta"].get("real_load_failed") is True
    assert res["meta"]["passed"] == 0


# -- train_step (honest gates; the real minutes-long GRPO run is not exercised in CI) --

def test_train_step_refuses_empty_run_dir(tmp_path):
    with pytest.raises(flywheel.FlywheelUnavailable) as ei:
        flywheel.train_step(run_dir=tmp_path)
    msg = str(ei.value)
    assert "no checkpoint tree" in msg and "refusing" in msg


def test_train_step_refuses_when_nothing_probed(monkeypatch, tmp_path):
    from hermes import resolve

    monkeypatch.setenv("DOTTIE_ROOT", str(tmp_path))
    monkeypatch.setenv("AVA_FACTORY_ROOT", str(tmp_path))
    monkeypatch.setattr(resolve, "DEFAULT_FACTORY_ROOT", tmp_path)
    with pytest.raises(flywheel.FlywheelUnavailable) as ei:
        flywheel.train_step()
    # Either the script or the checkpoint probe fails first — both are honest refusals.
    assert "rl_smoke_update.py" in str(ei.value) or "no checkpoint tree" in str(ei.value)


def test_train_step_wires_run_dir_and_device_documented():
    """The subprocess contract is documented: --run-dir/--device passthrough."""
    doc = flywheel.train_step.__doc__ or ""
    assert "--run-dir" in doc and "--device" in doc
    assert "capability" in doc  # states the no-capability-claim honesty
