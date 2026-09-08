"""A throwaway workspace: one fake repo with a script that writes a gate report."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factory.config import Factory, sha256_of

REPORT_SCRIPT = """
import json, sys, pathlib
value = 0.1 if "--bad" in sys.argv else 0.9
pathlib.Path("out").mkdir(exist_ok=True)
pathlib.Path("out/report.json").write_text(json.dumps({"m": {"value": value}, "generated_at": "2026-09-05T00:00:00Z"}))
print("wrote report", value)
"""


def _write_mission(path: Path, repo: Path, dataset: Path, sha: str) -> Path:
    mission = {
        "schema_version": 1,
        "id": "fixture-real-mission",
        "repository": {"path": str(repo), "code_sha": sha},
        "datasets": [{
            "id": "fixture-real-data",
            "path": "data/input.csv",
            "source": "https://example.invalid/data",
            "revision": "fixture-revision-1",
            "license": "CC0-1.0",
            "sha256": sha256_of(dataset),
            "identity_verified": True,
        }],
        "train": {"argv": [sys.executable, "train.py"]},
        "evaluation": {
            "argv": [sys.executable, "evaluate.py"],
            "report": "out/report.json",
            "max_age_seconds": 60,
            "contract_revision": "fixture-contract-v1",
        },
        "resources": {
            "ram_mb": 1,
            "disk_mb": 1,
            "gpu": "none",
            "exclusive_gpu": False,
            "max_parallel_jobs": 1,
        },
        "denied_dependencies": ["wandb"],
        "metrics": [
            {"name": "score", "path": "metrics.score", "op": ">=", "threshold": 0.8}
        ],
        "outputs": [
            {"kind": kind, "source": source, "destination": destination}
            for kind, source, destination in (
                ("model", "out/model.bin", "release/model.bin"),
                ("checkpoint", "out/checkpoint.bin", "release/checkpoint.bin"),
                ("tokenizer", "out/tokenizer.json", "release/tokenizer.json"),
                ("config", "out/config.json", "release/config.json"),
            )
        ],
        "protected_artifacts": ["protected.bin"],
        "approval_policy": {"reviewer_required": True, "shipper_required": True},
        "evidence_kind": "real",
    }
    path.write_text(json.dumps(mission), encoding="utf-8")
    return path


@pytest.fixture
def mission_fixture(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    dataset = repo / "data" / "input.csv"
    dataset.write_text("x,y\n1,2\n", encoding="utf-8")
    (repo / "protected.bin").write_bytes(b"protected")
    (repo / "train.py").write_text(
        "from pathlib import Path\n"
        "Path('out').mkdir(exist_ok=True)\n"
        "Path('out/model.bin').write_bytes(b'model')\n"
        "Path('out/checkpoint.bin').write_bytes(b'checkpoint')\n"
        "Path('out/tokenizer.json').write_text('{}')\n"
        "Path('out/config.json').write_text('{}')\n",
        encoding="utf-8",
    )
    (repo / "evaluate.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "Path('out/report.json').write_text(json.dumps("
        "{'contract_revision': 'fixture-contract-v1', 'metrics': {'score': 0.9}}))\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=repo,
        check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    mission_path = _write_mission(tmp_path / "mission.json", repo, dataset, sha)
    return repo, mission_path


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
