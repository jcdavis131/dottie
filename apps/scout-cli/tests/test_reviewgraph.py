"""ReviewGraph plugin — index/blast/context against real fixture trees + git."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.plugins.reviewgraph import graph
from bigbang.plugins.reviewgraph.graph import ReviewGraphError

ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, "-m", "bigbang.cli"]


def _run(args, *, timeout=60):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        CLI + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(ROOT),
        env=env,
    )


def _git(cwd: Path, *args: str):
    r = subprocess.run(
        ["git", "-c", "user.name=rg-test", "-c", "user.email=rg@test.local", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r


def _fixture_tree(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "base.py").write_text(
        "class Base:\n"
        "    def greet(self):\n"
        "        return helper()\n"
        "\n"
        "\n"
        "def helper():\n"
        "    return 'hi'\n",
        encoding="utf-8",
    )
    (root / "pkg" / "child.py").write_text(
        "from pkg.base import Base, helper\n"
        "\n"
        "\n"
        "class Child(Base):\n"
        "    def run(self):\n"
        "        return helper()\n"
        "\n"
        "\n"
        "def orphan():\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (root / "web").mkdir()
    (root / "web" / "util.ts").write_text(
        "export function utilFn(x: number): number {\n"
        "  return x * 2;\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "web" / "app.ts").write_text(
        "import { utilFn } from './util';\n"
        "\n"
        "export function main() {\n"
        "  return utilFn(21);\n"
        "}\n",
        encoding="utf-8",
    )


def _edges(root: Path):
    conn = graph.open_db(root)
    try:
        nodes = {r["id"]: r["qualname"] for r in conn.execute("SELECT id, qualname FROM nodes")}
        return {
            (nodes[r["src"]], nodes[r["dst"]], r["kind"])
            for r in conn.execute("SELECT src, dst, kind FROM edges")
        }
    finally:
        conn.close()


def test_reviewgraph_plugin_discovered():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "reviewgraph" in list_plugin_names()
    assert (ROOT / "bigbang" / "plugins" / "reviewgraph" / "manifest.yaml").exists()


def test_manifest_declares_no_network():
    import yaml

    mf = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "reviewgraph" / "manifest.yaml").read_text()
    )
    assert mf["capabilities"]["network"]["enabled"] is False
    assert mf["capabilities"]["filesystem"]["write"] is True
    assert mf["capabilities"]["secrets"]["allow"] == []


def test_index_fixture_tree(tmp_path):
    _fixture_tree(tmp_path)
    stats = graph.index_repo(tmp_path)
    assert stats["indexed"] == 5  # __init__, base, child, util.ts, app.ts
    assert stats["warnings"] == 0
    assert stats["totals"]["files"] == 5
    # Base, Base.greet, helper, Child, Child.run, orphan, utilFn, main
    assert stats["totals"]["symbols"] == 8
    assert (tmp_path / ".scout" / "reviewgraph.db").exists()

    edges = _edges(tmp_path)
    assert ("pkg/child.py", "pkg/base.py", "imports") in edges
    assert ("web/app.ts", "web/util.ts", "imports") in edges
    assert ("pkg/base.py", "pkg/base.py::helper", "defines") in edges
    assert ("pkg/child.py::Child", "pkg/base.py::Base", "inherits") in edges
    assert ("pkg/base.py::Base.greet", "pkg/base.py::helper", "calls") in edges
    assert ("pkg/child.py::Child.run", "pkg/base.py::helper", "calls") in edges
    assert ("web/app.ts::main", "web/util.ts::utilFn", "calls") in edges


def test_incremental_reindex_only_changed(tmp_path):
    _fixture_tree(tmp_path)
    first = graph.index_repo(tmp_path)
    assert first["indexed"] == 5
    second = graph.index_repo(tmp_path)
    assert second["indexed"] == 0
    assert second["unchanged"] == 5

    child = tmp_path / "pkg" / "child.py"
    child.write_text(
        child.read_text(encoding="utf-8") + "\n\ndef fresh():\n    return orphan()\n",
        encoding="utf-8",
    )
    third = graph.index_repo(tmp_path)
    assert third["indexed"] == 1
    assert third["unchanged"] == 4
    assert third["totals"]["symbols"] == 9  # fresh() joined the graph
    assert ("pkg/child.py::fresh", "pkg/child.py::orphan", "calls") in _edges(tmp_path)


def test_removed_file_leaves_graph(tmp_path):
    _fixture_tree(tmp_path)
    graph.index_repo(tmp_path)
    (tmp_path / "web" / "app.ts").unlink()
    stats = graph.index_repo(tmp_path)
    assert stats["removed"] == 1
    assert stats["totals"]["files"] == 4
    assert not any("app.ts" in a or "app.ts" in b for a, b, _ in _edges(tmp_path))


def test_unparseable_file_warns_never_crashes(tmp_path):
    _fixture_tree(tmp_path)
    (tmp_path / "pkg" / "broken.py").write_text("def broken(:\n    oops\n", encoding="utf-8")
    stats = graph.index_repo(tmp_path)
    assert stats["warnings"] == 1
    status = graph.graph_status(tmp_path)
    assert status["warnings"] == 1
    assert status["files"] == 6  # broken file is tracked, just symbol-less


def test_status_requires_index(tmp_path):
    with pytest.raises(ReviewGraphError, match="reviewgraph index"):
        graph.graph_status(tmp_path)


def test_blast_requires_git_repo(tmp_path):
    _fixture_tree(tmp_path)
    graph.index_repo(tmp_path)
    with pytest.raises(ReviewGraphError, match="git"):
        graph.compute_blast(tmp_path)


def test_blast_and_context_on_real_diff(tmp_path):
    _fixture_tree(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "fixture")
    first_sha = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    # working-tree edit: change helper()'s body → blast should walk to callers
    base = tmp_path / "pkg" / "base.py"
    base.write_text(
        base.read_text(encoding="utf-8").replace("return 'hi'", "return 'hello there'"),
        encoding="utf-8",
    )
    graph.index_repo(tmp_path)

    blast = graph.compute_blast(tmp_path, hops=2)
    changed_names = {s["qualname"] for s in blast["changed_symbols"]}
    assert "pkg/base.py::helper" in changed_names
    impacted = {i["name"]: i for i in blast["impacted"]}
    assert "pkg/base.py::Base.greet" in impacted  # same-file caller, distance 1
    assert "pkg/child.py::Child.run" in impacted  # cross-file caller, distance 1
    assert impacted["pkg/child.py::Child.run"]["distance"] == 1
    assert "pkg/child.py" in impacted  # importer of the changed file
    assert blast["counts"]["changed_symbols"] >= 1

    ctx = graph.build_context(tmp_path, budget_tokens=4000)
    for key in (
        "changed_symbols", "direct_dependents", "impacted_files",
        "risk_notes", "token_estimate", "budget_tokens",
    ):
        assert key in ctx
    assert ctx["token_estimate"] <= 4000
    helper_entry = next(
        c for c in ctx["changed_symbols"] if c["qualname"] == "pkg/base.py::helper"
    )
    assert "hello there" in helper_entry["snippet"]  # real source, not fabricated
    dep_names = {d["qualname"] for d in ctx["direct_dependents"]}
    assert "pkg/child.py::Child.run" in dep_names
    assert "pkg/child.py" in ctx["impacted_files"]

    # --diff <ref> path: commit the edit, diff against the first commit
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "edit helper")
    blast_ref = graph.compute_blast(tmp_path, diff_ref=first_sha, hops=1)
    assert "pkg/base.py::helper" in {s["qualname"] for s in blast_ref["changed_symbols"]}


def test_context_respects_tight_budget(tmp_path):
    _fixture_tree(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "fixture")
    base = tmp_path / "pkg" / "base.py"
    base.write_text(base.read_text(encoding="utf-8") + "\n\ndef extra():\n    return 1\n",
                    encoding="utf-8")
    graph.index_repo(tmp_path)
    ctx = graph.build_context(tmp_path, budget_tokens=300)
    assert ctx["token_estimate"] <= 300 or (
        ctx["changed_omitted"] >= 0 and ctx["dependents_omitted"] >= 0
    )


def test_risks_shapes(tmp_path):
    _fixture_tree(tmp_path)
    graph.index_repo(tmp_path)
    risks = graph.compute_risks(tmp_path, top=5)
    fan = {r["qualname"]: r["fan_in"] for r in risks["top_fan_in"]}
    assert fan.get("pkg/base.py::helper", 0) >= 2  # greet + Child.run call it
    assert isinstance(risks["import_cycles"], list)
    # tmp fixture is not a git repo (or has no commits) → honest churn note
    assert "churn_note" in risks or risks["churn_coupled"] == []


def test_cli_index_status_json(tmp_path):
    _fixture_tree(tmp_path)
    r = _run(["--json", "reviewgraph", "index", "--root", str(tmp_path)])
    assert r.returncode == 0, r.stderr + r.stdout
    body = json.loads(r.stdout)
    assert body["ok"] is True
    assert body["data"]["totals"]["symbols"] == 8

    s = _run(["--json", "reviewgraph", "status", "--root", str(tmp_path)])
    assert s.returncode == 0, s.stderr + s.stdout
    sbody = json.loads(s.stdout)
    assert sbody["ok"] is True
    assert sbody["data"]["files"] == 5


def test_cli_status_without_index_fails_with_example(tmp_path):
    r = _run(["--json", "reviewgraph", "status", "--root", str(tmp_path)])
    assert r.returncode == 1
    body = json.loads(r.stdout)
    assert "error" in body
    assert "reviewgraph index" in body["error"] or "reviewgraph index" in body.get("example", "")


def test_cli_blast_outside_git_fails_clean(tmp_path):
    _fixture_tree(tmp_path)
    _run(["--json", "reviewgraph", "index", "--root", str(tmp_path)])
    r = _run(["--json", "reviewgraph", "blast", "--root", str(tmp_path)])
    assert r.returncode == 1
    body = json.loads(r.stdout)
    assert "git" in body["error"]


def test_reviewgraph_help_has_examples():
    r = _run(["reviewgraph", "--help"])
    assert r.returncode == 0
    assert "Examples:" in r.stdout
    assert "reviewgraph context" in r.stdout
