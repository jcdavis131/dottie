from __future__ import annotations

import json

import pytest

from factory import software
from factory.config import Factory, FactoryError


def test_next_lists_frontier(ws: Factory):
    text = software.next_nodes(ws)
    assert "b" in text and "c" in text


def test_start_moves_ready_node_and_persists(ws: Factory):
    out = software.start(ws, "b")
    assert (
        "in_progress" in out
        and "validate:" in out
        and "jarvis: JARVIS_URL unset" in out
    )
    dag = json.loads(ws.dag_path.read_text())
    node = next(n for n in dag["nodes"] if n["id"] == "b")
    assert node["status"] == "in_progress" and node["started_on"]


def test_start_refuses_blocked_parked_and_repeat(ws: Factory):
    with pytest.raises(FactoryError, match="not ready"):
        software.start(ws, "c")
    with pytest.raises(FactoryError, match="not ready"):
        software.start(ws, "p")
    software.start(ws, "b")
    with pytest.raises(FactoryError, match="already in progress"):
        software.start(ws, "b")


def test_start_virtual_repo_says_operator(ws: Factory):
    dag = json.loads(ws.dag_path.read_text())
    next(n for n in dag["nodes"] if n["id"] == "v")["depends_on"] = []
    ws.dag_path.write_text(json.dumps(dag))
    assert "operator work" in software.start(ws, "v")


def test_done_requires_in_progress_and_evidence_then_unblocks(ws: Factory):
    with pytest.raises(FactoryError, match="not in_progress"):
        software.done(ws, "b", "x")
    software.start(ws, "b")
    with pytest.raises(FactoryError, match="evidence"):
        software.done(ws, "b", "  ")
    out = software.done(ws, "b", "tests green")
    assert "now ready: c" in out
    node = next(
        n for n in json.loads(ws.dag_path.read_text())["nodes"] if n["id"] == "b"
    )
    assert node["status"] == "done" and node["evidence"] == "tests green"


def test_save_refuses_malformed_dag(ws: Factory):
    dag = ws.dag()
    dag["nodes"][0]["depends_on"] = ["nope"]
    with pytest.raises(FactoryError, match="malformed"):
        ws.save_dag(dag)


def test_validate_runs_commands(ws: Factory, capsys):
    assert software.validate(ws, "r1") == 0
    assert "validate gate passed" in capsys.readouterr().out


def test_validate_stops_at_first_failure(ws: Factory, capsys):
    r = json.loads(ws.repos_path.read_text())
    r["repos"]["r1"]["validate"] = [
        '{python} -c "import sys; sys.exit(3)"',
        "{python} -c \"print('never')\"",
    ]
    ws.repos_path.write_text(json.dumps(r))
    assert software.validate(ws, "r1") == 3
    out = capsys.readouterr().out
    assert "FAILED (3)" in out and "never" not in out


def test_validate_unknown_and_virtual(ws: Factory):
    with pytest.raises(FactoryError, match="unknown repo"):
        software.validate(ws, "zzz")
    with pytest.raises(FactoryError, match="no checkout"):
        software.validate(ws, "vercel")


def test_status_renders_repos_and_tally(ws: Factory):
    text = software.status(ws)
    assert "r1" in text and "vercel" not in text and "DAG:" in text
