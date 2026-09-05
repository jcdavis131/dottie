"""Shared plumbing: workspace resolution, registries, the DAG bridge, running commands.

Everything takes a :class:`Factory` so tests can point one at a temp workspace;
``Factory.from_env()`` is what the CLI uses. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DOTTIE = HERE.parent
DAG_PATH = DOTTIE / "docs" / "project_dag.json"
REPOS_PATH = HERE / "repos.json"
QUEUE_PATH = HERE / "train_queue.json"
DATASETS_PATH = HERE / "datasets.json"
RUNS_DIR = HERE / "runs"

PROVENANCE = {"real", "honest-synthetic", "placeholder", "unknown"}
ROLES = {"center", "game", "site", "service", "library", "archived"}
GATE_OPS = {">=", "<=", ">", "<"}


class FactoryError(Exception):
    """A user-facing failure: printed, exit 1, no traceback."""


@dataclass
class Factory:
    workspace: Path
    dag_path: Path = DAG_PATH
    repos_path: Path = REPOS_PATH
    queue_path: Path = QUEUE_PATH
    datasets_path: Path = DATASETS_PATH
    runs_dir: Path = RUNS_DIR
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))

    @classmethod
    def from_env(cls) -> Factory:
        ws = os.environ.get("FACTORY_WORKSPACE")
        return cls(workspace=Path(ws).expanduser().resolve() if ws else DOTTIE.parent)

    # ---- registries -------------------------------------------------------
    def repos(self) -> dict[str, dict]:
        return load_json(self.repos_path).get("repos", {})

    def jobs(self) -> list[dict]:
        return load_json(self.queue_path).get("jobs", [])

    def datasets(self) -> list[dict]:
        return load_json(self.datasets_path).get("datasets", [])

    def repo_dir(self, name: str) -> Path:
        return self.workspace / name

    def repo(self, name: str) -> dict:
        repos = self.repos()
        if name not in repos:
            raise FactoryError(
                f"unknown repo {name!r}; registered: {', '.join(sorted(repos))}"
            )
        return repos[name]

    def job(self, job_id: str) -> dict:
        for j in self.jobs():
            if j.get("id") == job_id:
                return j
        raise FactoryError(f"unknown job {job_id!r}; run `factory train list`")

    def dataset(self, ds_id: str) -> dict:
        for d in self.datasets():
            if d.get("id") == ds_id:
                return d
        raise FactoryError(f"unknown dataset {ds_id!r}; run `factory data list`")

    # ---- DAG bridge -------------------------------------------------------
    def dag(self) -> dict:
        return dag_module().load(self.dag_path)

    def save_dag(self, dag: dict) -> None:
        errors = dag_module().validate(dag)
        if errors:
            raise FactoryError(
                "refusing to save a malformed DAG:\n  " + "\n  ".join(errors)
            )
        dag["updated"] = time.strftime("%Y-%m-%d")
        save_json(self.dag_path, dag)

    def node(self, dag: dict, node_id: str) -> dict:
        for n in dag.get("nodes", []):
            if n.get("id") == node_id:
                return n
        raise FactoryError(f"unknown DAG node {node_id!r}; run `factory next`")

    def groups(self) -> dict[str, list[dict]]:
        return dag_module().classify(self.dag())


def dag_module():
    """Import scripts/dag_next.py (the DAG's own validator) without packaging it."""
    scripts = str(DOTTIE / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import dag_next

    return dag_next


# ---- files ------------------------------------------------------------------
def load_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise FactoryError(f"missing registry {path}") from e
    except json.JSONDecodeError as e:
        raise FactoryError(f"{path}: invalid JSON: {e}") from e


def save_json(path: Path, obj: Any) -> None:
    Path(path).write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# ---- commands -----------------------------------------------------------------
def split_cmd(cmd: str) -> list[str]:
    """`{python}` expands to the running interpreter; no shell is ever involved."""
    return [sys.executable if tok == "{python}" else tok for tok in shlex.split(cmd)]


def run_cmd(
    cmd: str, cwd: Path, *, log: Path | None = None, env: dict[str, str] | None = None
) -> int:
    """Run one registry command in `cwd`, streaming output (and teeing to `log`)."""
    argv = split_cmd(cmd)
    if not argv:
        raise FactoryError("empty command")
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"$ {cmd}\n")
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                fh.write(line)
            return proc.wait()
    return subprocess.run(argv, cwd=str(cwd), env=env, check=False).returncode


def git(repo: Path, *args: str) -> str | None:
    """Output of a read-only git command, or None when git or the repo is absent."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_head(repo: Path) -> str | None:
    return git(repo, "rev-parse", "--short", "HEAD")


def git_branch(repo: Path) -> str | None:
    return git(repo, "branch", "--show-current")


def git_dirty(repo: Path) -> bool | None:
    out = git(repo, "status", "--porcelain")
    return None if out is None else bool(out)


def now_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def table(rows: list[list[str]], header: list[str]) -> str:
    """Plain aligned text table; no dependency, fits a terminal and a job summary."""
    cols = [header, *rows]
    widths = [max(len(str(r[i])) for r in cols) for i in range(len(header))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*header), fmt.format(*("-" * w for w in widths))]
    lines += [fmt.format(*(str(c) for c in r)) for r in rows]
    return "\n".join(lines)
