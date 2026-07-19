# Solo personal project, no connection to employer, built with public/free-tier only
"""reviewgraph plugin — local-first code review graph for AI-assisted review.

Original implementation (concept-inspired by code-review-graph tooling, written
fresh for scout-cli). Index a repo into a SQLite symbol graph, then answer:
what did this diff touch, what does that touch, and what should a reviewer
actually read — compressed to a token budget instead of the whole repo.

Usage by LLM:
  scout --json reviewgraph index --root .
  scout --json reviewgraph status
  scout --json reviewgraph blast --hops 2
  scout --json reviewgraph context --budget 4000
  scout --json reviewgraph risks

Filesystem only — no network, no secrets. Graph lives at <root>/.scout/reviewgraph.db.
"""
from pathlib import Path
from typing import Optional

import typer

from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.plugins.reviewgraph import graph
from bigbang.plugins.reviewgraph.graph import ReviewGraphError

app = make_plugin_app(
    "reviewgraph",
    "🕸️ ReviewGraph — code graph + blast radius + compact AI review context.",
    examples=[
        "scout --json reviewgraph index --root .",
        "scout --json reviewgraph status",
        "scout --json reviewgraph blast --hops 2",
        "scout --json reviewgraph blast --diff main",
        "scout --json reviewgraph context --budget 4000",
        "scout --json reviewgraph risks --top 10",
    ],
)

_ROOT_OPT = typer.Option(
    ".", "--root", help="repo root to index/query (graph lives in <root>/.scout/)"
)


def _fail(e: Exception, *, command: str, example: str) -> None:
    fail_agent(str(e), command=command, example=example, discover="scout reviewgraph --help")


@app.command(
    "index",
    epilog=examples_epilog(
        ["scout --json reviewgraph index --root .", "scout reviewgraph index --root ~/proj"]
    ),
)
def index_cmd(root: str = _ROOT_OPT):
    """Walk the repo, parse Python (ast) + JS/TS (regex), persist the symbol graph.

    Incremental: unchanged files (mtime+sha256) are skipped on re-run.
    Unparseable files are skipped with a recorded warning, never a crash.
    """
    try:
        stats = graph.index_repo(root)
    except ReviewGraphError as e:
        _fail(e, command="reviewgraph index", example="scout reviewgraph index --root .")
        return
    emit(
        ok(
            stats,
            command="reviewgraph index",
            example=f"scout --json reviewgraph status --root {root}",
            discover="scout reviewgraph blast --help",
        ),
        command="reviewgraph index",
    )


@app.command(
    "status",
    epilog=examples_epilog(
        ["scout --json reviewgraph status", "scout reviewgraph status --root ~/proj"]
    ),
)
def status_cmd(root: str = _ROOT_OPT):
    """Graph stats — files/symbols/edges counts, last index time, stale files."""
    try:
        stats = graph.graph_status(root)
    except ReviewGraphError as e:
        _fail(e, command="reviewgraph status", example="scout reviewgraph index --root .")
        return
    emit(
        ok(
            stats,
            command="reviewgraph status",
            example=f"scout --json reviewgraph blast --root {root}",
            discover="scout reviewgraph risks --help",
        ),
        command="reviewgraph status",
    )


@app.command(
    "blast",
    epilog=examples_epilog(
        [
            "scout --json reviewgraph blast            # working diff vs HEAD (incl. staged)",
            "scout --json reviewgraph blast --diff main --hops 3",
        ]
    ),
)
def blast_cmd(
    root: str = _ROOT_OPT,
    diff: Optional[str] = typer.Option(
        None, "--diff", help="git ref to diff against (default: HEAD = working + staged)"
    ),
    hops: int = typer.Option(2, "--hops", min=0, max=6, help="reverse-dependency walk depth"),
):
    """Blast radius of the diff: changed symbols → callers/importers/subclasses.

    Impacted set is ranked by (distance, fan-in) so a reviewer sees the riskiest
    dependents first.
    """
    try:
        result = graph.compute_blast(root, diff_ref=diff, hops=hops)
    except ReviewGraphError as e:
        _fail(e, command="reviewgraph blast", example="scout reviewgraph blast --diff main")
        return
    emit(
        ok(
            result,
            command="reviewgraph blast",
            example=f"scout --json reviewgraph context --root {root}",
            discover="scout reviewgraph context --help",
        ),
        command="reviewgraph blast",
    )


@app.command(
    "context",
    epilog=examples_epilog(
        [
            "scout --json reviewgraph context",
            "scout --json reviewgraph context --diff main --budget 2000",
        ]
    ),
)
def context_cmd(
    root: str = _ROOT_OPT,
    diff: Optional[str] = typer.Option(
        None, "--diff", help="git ref to diff against (default: HEAD = working + staged)"
    ),
    hops: int = typer.Option(2, "--hops", min=0, max=6, help="blast walk depth"),
    budget: int = typer.Option(
        4000, "--budget", min=200, help="approx token budget (chars/4) for the payload"
    ),
):
    """Compact review context for an AI reviewer — read this, not the repo.

    Changed symbols with source snippets, direct dependents' signatures (no
    bodies), impacted files, and risk notes — trimmed to the token budget.
    """
    try:
        result = graph.build_context(root, diff_ref=diff, hops=hops, budget_tokens=budget)
    except ReviewGraphError as e:
        _fail(e, command="reviewgraph context", example="scout reviewgraph context --budget 4000")
        return
    emit(
        ok(
            result,
            command="reviewgraph context",
            example="scout --json reviewgraph risks",
            discover="scout reviewgraph risks --help",
        ),
        command="reviewgraph context",
    )


@app.command(
    "risks",
    epilog=examples_epilog(
        ["scout --json reviewgraph risks", "scout --json reviewgraph risks --top 20"]
    ),
)
def risks_cmd(
    root: str = _ROOT_OPT,
    top: int = typer.Option(10, "--top", min=1, max=100, help="how many entries per list"),
):
    """Repo-level hotspots: top fan-in symbols, import cycles, churn-coupled files."""
    try:
        result = graph.compute_risks(root, top=top)
    except ReviewGraphError as e:
        _fail(e, command="reviewgraph risks", example="scout reviewgraph index --root .")
        return
    emit(
        ok(
            result,
            command="reviewgraph risks",
            example="scout --json reviewgraph context",
            discover="scout reviewgraph context --help",
        ),
        command="reviewgraph risks",
    )


@app.command("db-path", epilog=examples_epilog(["scout --json reviewgraph db-path --root ."]))
def db_path_cmd(root: str = _ROOT_OPT):
    """Where the graph DB lives for a root (exists or not)."""
    p = Path(root).expanduser()
    dbp = graph.db_path(p)
    emit(
        ok(
            {"root": str(p.resolve() if p.exists() else p), "db": str(dbp),
             "exists": dbp.exists()},
            command="reviewgraph db-path",
            example="scout --json reviewgraph index --root .",
        ),
        command="reviewgraph db-path",
    )


def register(root):
    root.add_typer(app, name="reviewgraph")
