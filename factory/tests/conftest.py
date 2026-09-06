"""A throwaway workspace: one fake repo with a script that writes a gate report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factory.config import Factory

REPORT_SCRIPT = """
import json, sys, pathlib
value = 0.1 if "--bad" in sys.argv else 0.9
pathlib.Path("out").mkdir(exist_ok=True)
pathlib.Path("out/report.json").write_text(json.dumps({"m": {"value": value}, "generated_at": "2026-09-05T00:00:00Z"}))
print("wrote report", value)
"""


def node(nid, deps=(), status="ready", repo="r1", priority=3, size="S"):
    return {
        "id": nid,
        "title": f"title {nid}",
        "repo": repo,
        "kind": "infra",
        "status": status,
        "priority": priority,
        "size": size,
        "depends_on": list(deps),
    }


@pytest.fixture
def ws(tmp_path: Path) -> Factory:
    work = tmp_path / "ws"
    r1 = work / "r1"
    (r1 / "src").mkdir(parents=True)
    (r1 / "write_report.py").write_text(REPORT_SCRIPT, encoding="utf-8")
    (r1 / "src" / "x.bin").write_bytes(b"cache-bytes")
    (r1 / "present.txt").write_text("here", encoding="utf-8")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    dag = {
        "version": 1,
        "updated": "2026-09-05",
        "nodes": [
            node("a", status="done"),
            node("b", priority=1),
            node("c", ["b"], status="blocked"),
            node("v", repo="vercel", status="blocked", priority=2),
            node("p", status="parked"),
        ],
    }
    (cfg / "dag.json").write_text(json.dumps(dag), encoding="utf-8")
    repos = {
        "repos": {
            "r1": {
                "role": "game",
                "default_branch": "main",
                "validate": ["{python} -c \"print('validate ok')\""],
                "ci": None,
                "deploy": None,
                "notes": "",
            },
            "vercel": {"role": "service", "virtual": True, "notes": ""},
        }
    }
    (cfg / "repos.json").write_text(json.dumps(repos), encoding="utf-8")
    queue = {
        "jobs": [
            {
                "id": "j1",
                "repo": "r1",
                "dag_node": "c",
                "priority": 1,
                "needs_cuda": False,
                "est_hours": 1,
                "needs": ["write_report.py", "present.txt"],
                "smoke": "{python} write_report.py --smoke",
                "run": "{python} write_report.py",
                "eval": None,
                "gate": {
                    "report": "out/report.json",
                    "metric": "m.value",
                    "op": ">=",
                    "threshold": 0.5,
                    "baseline": 0.4,
                },
                "promote": ["copy out/report.json somewhere"],
            },
            {
                "id": "j2",
                "repo": "r1",
                "dag_node": "c",
                "priority": 2,
                "needs_cuda": False,
                "est_hours": 1,
                "needs": ["does-not-exist.py"],
                "smoke": "{python} write_report.py",
                "run": "{python} write_report.py",
                "eval": None,
                "gate": {
                    "report": "out/report.json",
                    "metric": "m.value",
                    "op": ">=",
                    "threshold": 0.5,
                },
                "promote": ["n/a"],
            },
        ]
    }
    (cfg / "queue.json").write_text(json.dumps(queue), encoding="utf-8")
    datasets = {
        "datasets": [
            {
                "id": "d-report",
                "repo": "r1",
                "path": "out/report.json",
                "provenance": "real",
                "source": "t",
                "refresh": "{python} write_report.py",
                "cadence_days": 7,
                "fresh_key": "json:generated_at",
                "required": True,
                "restore_from": [],
                "consumers": ["c"],
            },
            {
                "id": "d-cache",
                "repo": "r1",
                "path": "data/x.bin",
                "provenance": "real",
                "source": "t",
                "refresh": None,
                "cadence_days": None,
                "required": True,
                "restore_from": ["r1/missing.bin", "r1/src/x.bin"],
                "consumers": ["c"],
            },
            {
                "id": "d-static",
                "repo": "r1",
                "path": "present.txt",
                "provenance": "real",
                "source": "t",
                "refresh": None,
                "cadence_days": None,
                "required": False,
                "restore_from": [],
                "consumers": [],
            },
        ]
    }
    (cfg / "datasets.json").write_text(json.dumps(datasets), encoding="utf-8")
    return Factory(
        workspace=work,
        dag_path=cfg / "dag.json",
        repos_path=cfg / "repos.json",
        queue_path=cfg / "queue.json",
        datasets_path=cfg / "datasets.json",
        runs_dir=tmp_path / "runs",
        env={
            "PATH": __import__("os").environ.get("PATH", ""),
            "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        },
    )
