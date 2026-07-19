# Solo personal project, no connection to employer, built with public/free-tier only
"""Engine tests — EchoPolicy end-to-end through the REAL CodeAct sandbox, real trace capture,
real reward components, honest failure propagation."""

from __future__ import annotations

import json

import pytest

from dottie.engine import DottieEngine
from dottie.policy import DottiePolicyUnavailable
from tests.conftest import UNROUTABLE_OLLAMA


def test_echo_end_to_end_real_sandbox(engine):
    rec = engine.run_task("plumbing end-to-end", backend="echo")
    assert rec["terminated"] == "final" and rec["reached_final"] is True
    assert rec["backend"] == "echo" and rec["plumbing_only"] is True
    assert rec["n_steps"] == 2
    # Step 1 really executed in the sandbox subprocess: real stdout, real value.
    assert "dottie-echo 42" in rec["steps"][0]["stdout"]
    assert rec["steps"][0]["value"] == "42"
    assert rec["steps"][0]["ok"] is True
    # Step 2 made one REAL recorded tool call (the sandbox's wrapped get_clock).
    assert [c["tool"] for c in rec["steps"][1]["tool_calls"]] == ["get_clock"]
    # FINAL is sanitized (loop strips the FINAL: label) and labeled as plumbing.
    assert rec["final"].startswith("EchoPolicy plumbing run complete")
    assert "not a capability measurement" in rec["final"]
    assert rec["wall_s"] > 0.0


def test_reward_components_are_real_and_r_task_unscored(echo_record):
    comps = echo_record["reward_components"]
    # Both blocks executed cleanly -> R_exec exactly 1.0 (2/2, a measured fraction).
    assert comps["r_exec"] == 1.0
    # Exactly one successful tool call -> the factory's documented single-call dampening.
    assert comps["r_codeuse"] == 0.5
    assert comps["redundant_calls"] == 0
    # Honesty: no verifier for open-ended tasks -> r_task is null, with the note saying why.
    assert comps["r_task"] is None
    assert "unscored" in comps["r_task_note"]


def test_trace_record_appended_as_jsonl(engine):
    engine.run_task("first", backend="echo")
    engine.run_task("second", backend="echo")
    lines = engine.traces_path.read_text().splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert [r["prompt"] for r in rows] == ["first", "second"]
    assert all(r["schema_version"] == "1.0.0" for r in rows)
    assert engine.trace_count() == 2


def test_ollama_backend_unavailable_propagates_no_trace(engine, monkeypatch):
    monkeypatch.setenv("DOTTIE_OLLAMA_URL", UNROUTABLE_OLLAMA)
    with pytest.raises(DottiePolicyUnavailable):
        engine.run_task("this must not fabricate", backend="ollama")
    # No fake trace was written for the failed task.
    assert engine.trace_count() == 0


def test_empty_prompt_rejected(engine):
    with pytest.raises(ValueError):
        engine.run_task("   ", backend="echo")


def test_unknown_backend_rejected(engine):
    with pytest.raises(ValueError):
        engine.run_task("x", backend="skynet")


def test_data_dir_env_default(monkeypatch, tmp_path):
    monkeypatch.setenv("DOTTIE_DATA_DIR", str(tmp_path / "envd"))
    e = DottieEngine()
    assert e.data_dir == tmp_path / "envd"
