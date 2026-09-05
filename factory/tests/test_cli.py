from __future__ import annotations

import json
from typing import TYPE_CHECKING

from factory.cli import main

if TYPE_CHECKING:
    from factory.config import Factory


def test_check_and_lists(ws: Factory, capsys):
    assert main(["check"], factory=ws) == 0
    assert main(["train", "list"], factory=ws) == 0
    assert main(["data", "list"], factory=ws) == 0
    assert main(["next"], factory=ws) == 0
    assert main(["status"], factory=ws) == 0
    assert "factory check: 0 errors" in capsys.readouterr().out


def test_data_check_exit_codes(ws: Factory):
    assert main(["data", "check"], factory=ws) == 0
    assert main(["data", "check", "--check"], factory=ws) == 1


def test_train_flow_via_cli(ws: Factory, capsys):
    assert main(["train", "preflight", "j2"], factory=ws) == 1
    assert main(["train", "run", "j1", "--smoke"], factory=ws) == 0
    assert main(["train", "run", "--next"], factory=ws) == 0
    assert main(["train", "promote", "j1"], factory=ws) == 0
    assert (
        main(["train", "next"], factory=ws) == 1
    )  # nothing left that passes preflight
    assert "Promotion is manual" in capsys.readouterr().out


def test_start_done_via_cli(ws: Factory, capsys):
    assert main(["start", "b"], factory=ws) == 0
    assert main(["done", "b", "--evidence", "ok"], factory=ws) == 0
    assert main(["done", "b", "--evidence", "ok"], factory=ws) == 1  # already done
    err = capsys.readouterr().err
    assert "factory: b is done" in err
    node = next(
        n for n in json.loads(ws.dag_path.read_text())["nodes"] if n["id"] == "b"
    )
    assert node["status"] == "done"


def test_check_failure_exit(ws: Factory):
    ws.datasets_path.write_text("{not json")
    assert main(["check"], factory=ws) == 1
