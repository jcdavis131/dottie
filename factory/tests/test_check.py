from __future__ import annotations

import json

from factory.check import check, render
from factory.config import Factory


def test_fixture_registries_are_clean(ws: Factory):
    errors, warnings = check(ws)
    assert errors == []
    assert warnings == []


def test_real_registries_are_clean():
    errors, _warnings = check(Factory.from_env())
    assert errors == [], "\n".join(errors)


def test_unknown_dag_node_and_repo(ws: Factory):
    q = json.loads(ws.queue_path.read_text())
    q["jobs"][0]["dag_node"] = "ghost"
    q["jobs"][0]["repo"] = "nowhere"
    ws.queue_path.write_text(json.dumps(q))
    errors, _ = check(ws)
    assert any("dag_node 'ghost'" in e for e in errors)
    assert any("repo 'nowhere'" in e for e in errors)


def test_absolute_paths_rejected(ws: Factory):
    d = json.loads(ws.datasets_path.read_text())
    d["datasets"][0]["path"] = "/etc/passwd"
    d["datasets"][1]["restore_from"] = ["../outside"]
    ws.datasets_path.write_text(json.dumps(d))
    errors, _ = check(ws)
    assert sum("path must be a relative path" in e for e in errors) == 1
    assert any("restore_from" in e for e in errors)


def test_dag_repo_without_registry_row(ws: Factory):
    dag = json.loads(ws.dag_path.read_text())
    dag["nodes"].append(
        {
            "id": "z",
            "title": "z",
            "repo": "unregistered",
            "kind": "infra",
            "status": "ready",
            "priority": 3,
            "size": "S",
            "depends_on": [],
        }
    )
    ws.dag_path.write_text(json.dumps(dag))
    errors, _ = check(ws)
    assert any("'unregistered' has no row" in e for e in errors)


def test_bad_gate_and_env(ws: Factory):
    q = json.loads(ws.queue_path.read_text())
    q["jobs"][0]["gate"]["op"] = "~="
    q["jobs"][0]["env"] = {"X": 1}
    ws.queue_path.write_text(json.dumps(q))
    errors, _ = check(ws)
    assert any("gate.op" in e for e in errors)
    assert any("env must map" in e for e in errors)


def test_warning_for_repo_without_validate(ws: Factory):
    r = json.loads(ws.repos_path.read_text())
    r["repos"]["r1"]["validate"] = []
    ws.repos_path.write_text(json.dumps(r))
    errors, warnings = check(ws)
    assert errors == []
    assert any("no validate commands" in w for w in warnings)
    assert "1 warning" in render(errors, warnings)


def test_missing_registry_is_one_error(ws: Factory):
    ws.repos_path.unlink()
    errors, _ = check(ws)
    assert len(errors) == 1 and "missing registry" in errors[0]
