# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout search` — Elastic Cloud/Algolia replacement, fully local (openswap #20).

Full-text search with the cluster deleted: index a corpus (files under the paths
you name, filtered by globs) into a sqlite3 FTS5 table, then query it with BM25
ranking and snippet highlighting. There is no node, no shard, no API key, no
hosted index — the file IS the search engine (.scout/search.db), and the manifest
disables the network axis entirely, so "no document ever left the box" is
architectural rather than a promise. All deterministic logic (discovery, the
incremental mtime/hash reindex, ranking, snippets, the staleness audit) lives in
bigbang/core/search.py; this surface adds only path resolution, argument parsing,
the fs_write policy gate, and the honest FTS5 failure.

FTS5 is a compile-time sqlite option, so it is PROBED, never assumed: `detect`
reports the probe (virtual table + tokenizer + bm25() + snippet(), end to end)
and every command that opens an index turns a failed probe into a real error with
sqlite's own message attached, instead of an index that silently matches nothing.

Policy: this plugin makes no network call and opens no socket. It reads the paths
you pass and writes exactly one sqlite file, gated by the manifest's fs_write
capability. `recollindex`/`rg` are surfaced by `detect` as optional local helpers;
`ecctl` (Elastic Cloud's control CLI) is surfaced for awareness but NEVER
executed — its whole job is driving the paid SaaS (the forbidden network tier).
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from bigbang.core import openswap, search
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib sqlite3 FTS5 index is the complete product for this adapter: "
    "glob-filtered corpus discovery, incremental reindex by mtime or content "
    "hash, BM25 ranking with per-column weights, snippet highlighting, path "
    "filters and pagination, plus a stat-only staleness audit — all file-backed "
    "with zero network; tier 'fallback' is the expected steady state (Elastic "
    "Cloud's product is the managed cluster — no local native binary supersedes "
    "this core to prefer)"
)
INSTALL_HINT = (
    "nothing to install — python's own sqlite3 ships FTS5; install recoll only "
    "if you also want desktop-wide indexing, or ripgrep for unindexed greps"
)

app = make_plugin_app(
    "search",
    "Full-text search (Elastic Cloud-class), fully local: sqlite3 FTS5 index "
    "with BM25 ranking and snippet highlighting, zero egress",
    examples=[
        "scout --json search index docs README.md --ext md",
        'scout --json search query "fts5 ranking"',
        'scout --json search query "bm25" --path docs --limit 5',
        "scout --json search stats --fail-on warning",
        "scout --json search detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only on writes
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # No local native binary supersedes this core (Elastic Cloud's product is the
    # managed cluster; Meilisearch/Quickwit ship as servers). recollindex is a
    # benign optional local indexer, rg an unindexed complement; ecctl is
    # surfaced but NEVER executed — its whole job is driving the paid SaaS.
    native = openswap.probe_binary("recollindex", probe_args=("-h",))
    extras = {
        "rg": openswap.probe_binary("rg", probe_args=("--version",)),
        "ecctl": openswap.probe_binary("ecctl", probe_args=("version",)),
    }
    report = openswap.capability_report(
        "search",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    # the capability that actually decides whether this adapter works at all
    report["fts5"] = search.fts5_probe()
    return report


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_SEARCH_DB") or search.DB_REL)


def _open_new(db: str | None, command: str):
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write", str(path))
    return _open(path, command), path


def _open_existing(db: str | None, command: str):
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no search index at {path} — index a corpus first",
            command=command,
            example="scout --json search index docs --ext md",
            discover="scout search detect",
        )
    return _open(path, command), path


def _open(path: Path, command: str):
    """Open the index, turning a missing FTS5 into an honest, actionable error."""
    try:
        return search.open_index(path)
    except search.Fts5UnavailableError as exc:
        fail_agent(
            str(exc),
            command=command,
            example="scout --json search detect",
            discover="scout search detect",
        )


def _ext_globs(exts: list[str] | None) -> list[str]:
    """['md', '.MD', '*.md'] -> ['*.md'] — an extension filter with NO wildcard.

    Windows-safety, measured not assumed: click emulates cmd.exe by expanding any
    argv token that glob-matches files in the CWD *before* the parser sees it, so
    `--glob "*.md"` run from a directory containing README.md silently arrives as
    `--glob README.md` (quoting does not help — the shell is not the one
    expanding). `--ext md` carries no wildcard, so nothing can rewrite it; it is
    the recommended filter, and --glob stays for real patterns.
    """
    out: list[str] = []
    for raw in exts or []:
        ext = str(raw).strip().lstrip("*").lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        pattern = f"*{ext}"
        if pattern not in out:
            out.append(pattern)
    return out


def _check_fail_on(value: str | None, command: str, example: str) -> None:
    if value is not None and value not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {value!r}",
            command=command,
            example=example,
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    """Exit 1 when any diagnostic is at/above the requested severity."""
    if fail_on is None:
        return
    gate_rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json search hello"]))
def hello():
    """Smoke check — is the search surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "search"},
            command="search hello",
            example="scout --json search index docs --ext md",
            discover="scout search detect",
        ),
        command="search hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json search detect"]))
def detect():
    """Report the capability tier + the FTS5 probe (fallback IS the product here)."""
    emit(
        ok(
            _capability(),
            command="search detect",
            example="scout --json search index docs --ext md",
            discover="scout search stats",
        ),
        command="search detect",
    )


@app.command(
    "index",
    epilog=examples_epilog(
        [
            "scout --json search index docs --ext md",
            "scout --json search index docs README.md --ext md --ext txt --mode hash",
            "scout --json search index . --exclude-dir vendor --exclude-dir out",
            'scout --json search index docs --glob "docs/**/*.md"  # see --glob help',
            "scout --json search index docs --force --optimize",
        ]
    ),
)
def index(
    roots: list[str] = typer.Argument(
        ..., help="files and/or directories to index (no implicit default — say what)"
    ),
    ext: list[str] = typer.Option(
        None,
        "--ext",
        help="only index this extension, repeatable (md / .md / *.md all mean "
        "*.md) — wildcard-free, so prefer it over --glob on Windows",
    ),
    glob: list[str] = typer.Option(
        None,
        "--glob",
        help="include glob, repeatable (default: the text-extension set; a "
        'pattern with "/" matches the whole path, otherwise the file name). '
        "Windows: click expands a bare *.md against the CWD before parsing — "
        "use --ext for extension filters",
    ),
    exclude: list[str] = typer.Option(
        None, "--exclude", help="exclude glob, repeatable (wins over --glob)"
    ),
    exclude_dir: list[str] = typer.Option(
        None,
        "--exclude-dir",
        help=f"directory names to prune (default: {', '.join(search.DEFAULT_EXCLUDE_DIRS)})",
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"index path (default {search.DB_REL} or $SCOUT_SEARCH_DB)",
    ),
    max_kb: int = typer.Option(
        search.DEFAULT_MAX_FILE_KB, "--max-kb", help="skip files larger than this"
    ),
    mode: str = typer.Option(
        search.MODE_MTIME,
        "--mode",
        help="change detection: mtime (fast; misses mtime-preserving edits) or "
        "hash (re-reads every candidate, catches them)",
    ),
    prune: bool = typer.Option(
        True,
        "--prune/--no-prune",
        help="drop rows whose file is gone (scoped to the roots being indexed)",
    ),
    force: bool = typer.Option(
        False, "--force", help="reindex every candidate, changed or not"
    ),
    optimize: bool = typer.Option(
        False, "--optimize", help="merge the FTS b-tree after the pass (bulk indexes)"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any skipped file maps at/above this severity "
        "(unreadable=warning, too-large/binary=info) — the CI gate hook",
    ),
):
    """Index (or incrementally reindex) a corpus into the local FTS5 index."""
    _check_fail_on(fail_on, "search index", "scout --json search index docs --fail-on warning")
    if mode not in search.REINDEX_MODES:
        fail_agent(
            f"--mode must be one of {'|'.join(search.REINDEX_MODES)}, got {mode!r}",
            command="search index",
            example="scout --json search index docs --mode hash",
        )
    missing = [r for r in roots if not Path(r).exists()]
    if missing and len(missing) == len(roots):
        # every root is a typo/absent path: indexing would report a cheerful
        # ok:true with zero documents, which is the silent no-op the family bans
        fail_agent(
            f"none of these roots exist: {missing} — nothing to index",
            command="search index",
            example="scout --json search index docs --ext md",
            discover="scout search stats",
        )
    include = [*_ext_globs(ext), *(glob or [])]
    conn, path = _open_new(db, "search index")
    try:
        result = search.index_paths(
            conn,
            roots,
            include=include or None,
            exclude=exclude or None,
            exclude_dirs=exclude_dir or None,
            max_kb=max_kb,
            mode=mode,
            prune=prune,
            force=force,
            optimize=optimize,
        )
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="search index",
            example="scout --json search index docs --ext md",
        )
    diags = search.to_diagnostics(result)
    emit(
        ok(
            {"db": str(path),
             # what was ACTUALLY applied — provenance beats assuming the shell
             # handed us the patterns we typed
             "include": include or list(search.default_include()),
             "exclude": list(exclude or []),
             **result, "diagnostics": diags,
             "summary": openswap.summarize(diags)},
            command="search index",
            example='scout --json search query "your terms"',
            discover="scout search stats",
        ),
        command="search index",
    )
    _gate(diags, fail_on)


@app.command(
    "query",
    epilog=examples_epilog(
        [
            'scout --json search query "fts5 ranking"',
            'scout --json search query "bm25 OR tokenizer" --limit 5',
            'scout --json search query "tokenizer" --path docs',
            'scout --json search query "C++ (unsafe)" --literal',
            'scout --json search query "release notes" --fail-empty',
        ]
    ),
)
def query(
    text: str = typer.Argument(
        ...,
        help="FTS5 query: bare terms, \"a phrase\", term*, AND/OR/NOT, "
        "path: term — or pass --literal to search the string itself",
    ),
    db: str | None = typer.Option(None, "--db", help="index path"),
    limit: int = typer.Option(search.DEFAULT_LIMIT, "--limit", help="hits per page"),
    offset: int = typer.Option(0, "--offset", help="hits to skip (pagination)"),
    literal: bool = typer.Option(
        False, "--literal", help="treat the query as one phrase, operators and all"
    ),
    path: str | None = typer.Option(
        None,
        "--path",
        help="restrict to a glob (sqlite GLOB) — or, wildcard-free, to that "
        'path/subtree: --path docs means docs and everything under it',
    ),
    snippet_tokens: int = typer.Option(
        search.DEFAULT_SNIPPET_TOKENS, "--snippet-tokens", help="snippet width in tokens"
    ),
    mark_open: str = typer.Option(
        search.MARK_OPEN, "--mark-open", help="text before each matched term"
    ),
    mark_close: str = typer.Option(
        search.MARK_CLOSE, "--mark-close", help="text after each matched term"
    ),
    ellipsis: str = typer.Option(
        search.ELLIPSIS, "--ellipsis", help="marker for elided snippet text"
    ),
    path_weight: float = typer.Option(
        search.DEFAULT_PATH_WEIGHT, "--path-weight", help="BM25 weight of the path column"
    ),
    body_weight: float = typer.Option(
        search.DEFAULT_BODY_WEIGHT, "--body-weight", help="BM25 weight of the body column"
    ),
    fail_empty: bool = typer.Option(
        False, "--fail-empty", help="exit 1 when nothing matched — the CI assertion hook"
    ),
):
    """Rank the index against a query: BM25 order + highlighted snippets."""
    conn, dbpath = _open_existing(db, "search query")
    try:
        result = search.query(
            conn,
            text,
            limit=limit,
            offset=offset,
            literal=literal,
            path_glob=path,
            snippet_tokens=snippet_tokens,
            mark=(mark_open, mark_close),
            ellipsis=ellipsis,
            path_weight=path_weight,
            body_weight=body_weight,
        )
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="search query",
            example='scout --json search query "bm25 ranking" --literal',
            discover="scout search stats",
        )
    emit(
        ok(
            {"db": str(dbpath), **result},
            command="search query",
            example="scout --json search stats",
            discover="scout search stats",
        ),
        command="search query",
    )
    if fail_empty and not result["hits"]:
        raise typer.Exit(code=1)


@app.command(
    "stats",
    epilog=examples_epilog(
        [
            "scout --json search stats",
            "scout --json search stats --no-check",
            "scout --json search stats --fail-on warning",
        ]
    ),
)
def stats(
    db: str | None = typer.Option(None, "--db", help="index path"),
    check: bool = typer.Option(
        True,
        "--check/--no-check",
        help="stat every indexed path to report missing/stale rows (no bodies read)",
    ),
    limit: int = typer.Option(20, "--limit", help="cap the missing/stale lists"),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if the index maps at/above this severity (missing/stale = "
        "warning) — the reindex-before-you-trust-it gate",
    ),
):
    """Corpus rollup + freshness audit — read-only, no bodies read, no network."""
    _check_fail_on(fail_on, "search stats", "scout --json search stats --fail-on warning")
    conn, path = _open_existing(db, "search stats")
    report = search.stats(conn, check=check, limit=limit)
    diags = search.to_diagnostics(report)
    emit(
        ok(
            {"db": str(path), **report, "diagnostics": diags,
             "summary": openswap.summarize(diags)},
            command="search stats",
            example='scout --json search query "your terms"',
            discover="scout --json search index <root> --ext md",
        ),
        command="search stats",
    )
    _gate(diags, fail_on)


def register(root):
    root.add_typer(app, name="search")
