# Solo personal project, no connection to employer, built with public/free-tier only
"""
scout graphify — Personal Graphify baked into Scout control plane.

Wraps pgraphify: build / query / path / explain / impact / task / onboard / cost / sync.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer

from bigbang.core.output import emit
from bigbang.plugins.graphify import runner

app = typer.Typer(
    name="graphify",
    help="🕸️ Personal Graphify (pgraphify) — query-first knowledge graph for Scout/Ava/Lab/Vector",
    no_args_is_help=True,
)


@app.command("status")
def status_cmd():
    """Show pgraphify install + active graph.json."""
    emit(runner.status_payload(), command="graphify status")


@app.command("build")
def build_cmd(
    path: str = typer.Argument(".", help="Primary project path to index"),
    out: Optional[str] = typer.Option(None, "--out", help="Output dir (default: <path>/graphify-out)"),
    roots: Optional[str] = typer.Option(
        None,
        "--roots",
        help="Comma-separated extra roots for multi-repo corpus",
    ),
    ecosystem: bool = typer.Option(
        False,
        "--ecosystem",
        help="Include ~/scout-cli, ~/ava-agi-factory-v6-4, ~/personal-graphify (+ references)",
    ),
    max_files: int = typer.Option(4000, "--max-files", help="Max files across roots"),
):
    """Build knowledge graph (Tree-sitter AST + personal patterns)."""
    root_list = [r.strip() for r in roots.split(",") if r.strip()] if roots else None
    result = runner.run_build(
        path=path,
        out=out,
        roots=root_list,
        max_files=max_files,
        ecosystem=ecosystem,
    )
    emit(result, command="graphify build")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("query")
def query_cmd(
    question: str = typer.Argument(..., help='e.g. "how does Scout connect to Ava?"'),
    graph: Optional[str] = typer.Option(None, "--graph", help="Path to graph.json"),
    semantic: bool = typer.Option(False, "--semantic", help="Ollama mxbai-embed-large rerank"),
):
    """Scoped subgraph query (~10-70x token reduction vs naive grep)."""
    args = [question]
    if semantic:
        args.append("--semantic")
    result = runner.run_text_command("query", args, graph=graph)
    emit(result, command="graphify query")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("path")
def path_cmd(
    source: str = typer.Argument(..., help="Source concept"),
    target: str = typer.Argument(..., help="Target concept"),
    graph: Optional[str] = typer.Option(None, "--graph"),
    semantic: bool = typer.Option(False, "--semantic"),
):
    """Shortest path between two concepts."""
    args = [source, target]
    if semantic:
        args.append("--semantic")
    result = runner.run_text_command("path", args, graph=graph)
    emit(result, command="graphify path")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("explain")
def explain_cmd(
    node: str = typer.Argument(..., help="Concept / node label"),
    graph: Optional[str] = typer.Option(None, "--graph"),
    snippet: bool = typer.Option(False, "--snippet", help="Include code snippet if available"),
    semantic: bool = typer.Option(False, "--semantic"),
):
    """Explain a node — neighbors, degree, community."""
    args = [node]
    if snippet:
        args.append("--snippet")
    if semantic:
        args.append("--semantic")
    result = runner.run_text_command("explain", args, graph=graph)
    emit(result, command="graphify explain")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("impact")
def impact_cmd(
    node: str = typer.Argument(..., help="Node to analyze"),
    graph: Optional[str] = typer.Option(None, "--graph"),
    direction: str = typer.Option("both", "--direction", help="downstream|upstream|both"),
    depth: int = typer.Option(3, "--depth"),
    semantic: bool = typer.Option(False, "--semantic"),
):
    """Impact BFS — what breaks if you change this?"""
    args = [node, "--direction", direction, "--depth", str(depth)]
    if semantic:
        args.append("--semantic")
    result = runner.run_text_command("impact", args, graph=graph)
    emit(result, command="graphify impact")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("task")
def task_cmd(
    task: str = typer.Argument(..., help='Natural language task e.g. "wire Scout to Ava J-space"'),
    graph: Optional[str] = typer.Option(None, "--graph"),
    semantic: bool = typer.Option(False, "--semantic"),
):
    """Task compiler — minimal files + plan + copy-paste context."""
    args = [task]
    if semantic:
        args.append("--semantic")
    result = runner.run_text_command("task", args, graph=graph)
    emit(result, command="graphify task")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("onboard")
def onboard_cmd(
    graph: Optional[str] = typer.Option(None, "--graph"),
    top: int = typer.Option(12, "--top"),
):
    """Onboard — god nodes, hot files, entry points, suggested questions."""
    result = runner.run_text_command("onboard", ["--top", str(top)], graph=graph)
    emit(result, command="graphify onboard")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("cost")
def cost_cmd(graph: Optional[str] = typer.Option(None, "--graph")):
    """Token savings dashboard from cost.json."""
    result = runner.run_text_command("cost", [], graph=graph)
    emit(result, command="graphify cost")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("sync")
def sync_cmd(
    graph: Optional[str] = typer.Option(None, "--graph", help="Source graph.json (default: local or personal)"),
):
    """Copy scout graph.json into ~/personal-graphify/references/spaces/scout-cli-graph.json."""
    result = runner.sync_to_personal(src_graph=graph)
    emit(result, command="graphify sync")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("ecosystem")
def ecosystem_cmd(
    out: Optional[str] = typer.Option(
        None,
        "--out",
        help="Default: ~/personal-graphify/graphify-out",
    ),
    max_files: int = typer.Option(4000, "--max-files"),
):
    """Rebuild the multi-root personal ecosystem graph (Scout + Ava + personal-graphify)."""
    home = Path.home()
    primary = str((home / "personal-graphify").resolve())
    out_dir = out or str((home / "personal-graphify" / "graphify-out").resolve())
    result = runner.run_build(
        path=primary,
        out=out_dir,
        ecosystem=True,
        max_files=max_files,
    )
    emit(result, command="graphify ecosystem")
    if not result.get("ok"):
        raise typer.Exit(code=1)
