"""Tests for dottie_rlm.cli — typer CLI (SPEC floor: cli section).

Covered: ``--help`` exits 0; ``sessions`` on an EMPTY registry exits 0;
``run`` with a FakeBackend prints the answer (and builds no kernel);
``refine``/``ledger``/``rollback`` round-trip with an idempotent second
rollback; ``status --publish`` writes an atomic local-source JSON; malformed
backend specs refuse cleanly. Anti-vacuity: after refine the ledger FILE is
non-empty. No network — every backend in here is fake:.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_rlm.cli import app

runner = CliRunner()


def base_args(tmp_path: Path) -> list[str]:
    return [
        "--root",
        str(tmp_path / "sessions"),
        "--harness",
        str(tmp_path / "harness"),
    ]


# ---------------------------------------------------------------------------
# Floor: --help and sessions on an empty registry
# ---------------------------------------------------------------------------


def test_help_exits_zero_and_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "repl", "sessions", "refine", "rollback", "ledger", "status"):
        assert command in result.output


def test_sessions_on_empty_registry_exits_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, [*base_args(tmp_path), "sessions"])
    assert result.exit_code == 0
    assert "no sessions" in result.output


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_with_fake_backend_prints_answer(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [*base_args(tmp_path), "run", "say hi", "--model", "fake:Hello from fake."],
    )
    assert result.exit_code == 0, result.output
    assert "Hello from fake." in result.output
    # The session was registered and its trajectory persisted (non-empty).
    root = tmp_path / "sessions"
    trajs = list(root.glob("*/trajectory.jsonl"))
    assert len(trajs) == 1
    assert trajs[0].stat().st_size > 0


def test_run_lists_session_afterwards(tmp_path: Path) -> None:
    args = base_args(tmp_path)
    run_result = runner.invoke(
        app, [*args, "run", "say hi", "--model", "fake:answer."]
    )
    assert run_result.exit_code == 0
    result = runner.invoke(app, [*args, "sessions"])
    assert result.exit_code == 0
    assert "role=root" in result.output
    assert "turns=2" in result.output  # user message + model answer


def test_run_with_malformed_spec_refuses_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(
        app, [*base_args(tmp_path), "run", "goal", "--model", "bogus:thing"]
    )
    assert result.exit_code == 2
    assert "Unknown backend spec" in result.output


# ---------------------------------------------------------------------------
# refine / ledger / rollback
# ---------------------------------------------------------------------------


def test_refine_ledger_rollback_roundtrip(tmp_path: Path) -> None:
    args = base_args(tmp_path)

    refine = runner.invoke(
        app, [*args, "refine", "--trigger", "kernel timeout on big loops"]
    )
    assert refine.exit_code == 0, refine.output
    assert "r-1" in refine.output

    # Anti-vacuity: the ledger FILE is non-empty after activity.
    ledger_path = tmp_path / "harness" / "refinements.jsonl"
    assert ledger_path.stat().st_size > 0

    ledger = runner.invoke(app, [*args, "ledger"])
    assert ledger.exit_code == 0
    assert "r-1" in ledger.output
    assert "kernel timeout on big loops" in ledger.output

    rollback = runner.invoke(app, [*args, "rollback", "r-1"])
    assert rollback.exit_code == 0
    assert "reversed" in rollback.output

    # Idempotent: second rollback is a clear no-op, still exit 0.
    again = runner.invoke(app, [*args, "rollback", "r-1"])
    assert again.exit_code == 0
    assert "no-op" in again.output

    unknown = runner.invoke(app, [*args, "rollback", "r-99"])
    assert unknown.exit_code == 1


def test_ledger_empty_exits_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, [*base_args(tmp_path), "ledger"])
    assert result.exit_code == 0
    assert "ledger empty" in result.output


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_publish_writes_local_source_json(tmp_path: Path) -> None:
    args = base_args(tmp_path)
    runner.invoke(app, [*args, "run", "hi", "--model", "fake:ok."])
    target = tmp_path / "rlm_status.json"
    result = runner.invoke(app, [*args, "status", "--publish", str(target)])
    assert result.exit_code == 0, result.output
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["source"] == "local"
    assert len(payload["sessions"]) == 1
    row = payload["sessions"][0]
    assert row["role"] == "root"
    assert row["turns"] == 2
    assert payload["refinements"] == []
    # No leftover temp files from the atomic write.
    assert list(tmp_path.glob("rlm_status.json.*.tmp")) == []


def test_status_without_publish_prints_payload(tmp_path: Path) -> None:
    result = runner.invoke(app, [*base_args(tmp_path), "status"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["source"] == "local"
    assert payload["sessions"] == []
