# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout logs` — Papertrail/Splunk/Loggly replacement, fully local (openswap #14).

Log aggregation with the ingest endpoint deleted: the pipeline runs on THIS box
end to end. `collect` tails every configured source (per-file byte offsets in
sqlite, so a re-run ingests only what is new), `query` filters the indexed
store by time range / minimum level / source / substring, `rollup` gives the
per-hour "how much and how bad" board, and nothing is ever shipped anywhere —
the manifest disables the network axis entirely, so "no log line left the box"
is architectural rather than a promise.

All deterministic logic (encoding detection, unit-aligned line splitting,
parsers, locale-independent timestamp parsing, the sqlite store, query and
rollup) lives in bigbang/core/logs.py; this surface adds path resolution,
argument parsing and the fs_write policy gate. Three things it gets right that
a naive tailer does not: byte offsets come from Path.stat() (os.stat) and reset
when a file shrinks (rotation), every read is open->seek->read->CLOSE so a
Windows writer can still rename its own log, and the encoding is SNIFFED —
this repo's own research-loop logs are UTF-16-LE with a BOM, and decoding them
as UTF-8 produces mojibake.

Policy: this plugin opens no socket and makes no network call. Log files are
read-only; the only writes are the sqlite store under .scout, gated by
enforce_or_raise(fs_write) at the call site. lnav is surfaced by `detect` as
the one genuinely local open CLI in this category; the papertrail and splunk
clients are surfaced for awareness but NEVER executed — their whole job is
shipping lines to the paid platform (the forbidden network tier).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import typer

from bigbang.core import logs, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib log pipeline is the complete product for this adapter: "
    "tailing collectors with per-file byte offsets (incremental re-runs, "
    "rotation/truncation detection, no held file handles), BOM/NUL encoding "
    "detection incl. UTF-16, per-source regex + jsonl + syslog parsers, "
    "locale-independent timestamp parsing, an indexed sqlite3 entry store, and "
    "time/level/source/substring queries with rollups; tier 'fallback' is the "
    "expected steady state (Papertrail, Splunk Cloud and Loggly are hosted "
    "ingest services — there is no local native binary that supersedes this "
    "core to prefer)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib pipeline is complete; install lnav "
    "separately only if you want an interactive TUI over the same files (it "
    "has no incremental offset store, so it complements this rather than "
    "replacing it)"
)

app = make_plugin_app(
    "logs",
    "Log pipeline (Papertrail/Splunk-class), fully local: tailing collectors "
    "with byte offsets + parsers + an indexed sqlite store, zero egress",
    examples=[
        "scout --json logs sources",
        "scout --json logs collect",
        "scout --json logs query --hours 24 --level warning",
        "scout --json logs rollup --hours 24 --bucket 3600",
        "scout --json logs query --level error --fail-on error",
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
    # lnav is the honest `native` probe: the one open, local, no-server CLI in
    # this category. The papertrail gem and the splunk client are surfaced for
    # awareness but NEVER executed — their whole job is shipping log lines to
    # the paid platform (the forbidden network tier).
    native = openswap.probe_binary("lnav", probe_args=("-V",))
    extras = {
        "papertrail": openswap.probe_binary("papertrail", probe_args=("--version",)),
        "splunk": openswap.probe_binary("splunk", probe_args=("version",)),
    }
    return openswap.capability_report(
        "logs",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_LOGS_DB") or logs.DB_REL)


def _open_new(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return logs.open_store(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no log store at {path} — run a collection pass first",
            command=command,
            example="scout --json logs collect",
        )
    return logs.open_store(path), path


def _sources_or_fail(sources_file: str | None, command: str) -> dict:
    try:
        return logs.load_sources(sources_file)
    except Exception as exc:
        fail_agent(
            f"bad sources file: {exc}",
            command=command,
            example="scout --json logs collect --sources my-logs.json",
        )


def _level_or_fail(level: str | None, command: str) -> str | None:
    if level is None:
        return None
    norm = logs.normalize_level(level)
    if norm is None:
        fail_agent(
            f"--level must be one of {'|'.join(logs.LEVELS)}, got {level!r}",
            command=command,
            example="scout --json logs query --level warning",
        )
    return norm


def _window(
    hours: float | None, since: str | None, until: str | None, command: str
) -> tuple[float | None, float | None]:
    """Resolve --hours / --since / --until into an epoch range.

    --since/--until accept anything core parse_timestamp understands (ISO-8601
    or an epoch); --hours is the convenience form relative to now. An explicit
    --since always wins over --hours so the two never silently fight.
    """
    lo = hi = None
    if since is not None:
        lo = logs.parse_timestamp(since)
        if lo is None:
            fail_agent(
                f"--since must be ISO-8601 or an epoch, got {since!r}",
                command=command,
                example="scout --json logs query --since 2026-07-19T00:00:00Z",
            )
    elif hours is not None:
        lo = time.time() - float(hours) * 3600.0
    if until is not None:
        hi = logs.parse_timestamp(until)
        if hi is None:
            fail_agent(
                f"--until must be ISO-8601 or an epoch, got {until!r}",
                command=command,
                example="scout --json logs query --until 2026-07-20T00:00:00Z",
            )
    return lo, hi


@app.command("hello", epilog=examples_epilog(["scout --json logs hello"]))
def hello():
    """Smoke check — is the logs surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "logs"},
            command="logs hello",
            example="scout --json logs collect",
            discover="scout logs detect",
        ),
        command="logs hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json logs detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="logs detect",
            example="scout --json logs collect",
            discover="scout logs sources",
        ),
        command="logs detect",
    )


@app.command(
    "parsers",
    epilog=examples_epilog(["scout --json logs parsers"]),
)
def parsers_cmd():
    """List the built-in per-source parsers with their regex and an example line."""
    emit(
        ok(
            {
                "parsers": logs.parser_catalog(),
                "levels": list(logs.LEVELS),
                "default_level": logs.DEFAULT_LEVEL,
                "custom": (
                    "put a `regex` with a named (?P<message>...) group on a "
                    "source to parse a format no built-in covers"
                ),
            },
            command="logs parsers",
            example="scout --json logs collect --sources my-logs.json",
            discover="scout logs sources",
        ),
        command="logs parsers",
    )


@app.command(
    "sources",
    epilog=examples_epilog(
        [
            "scout --json logs sources",
            "scout --json logs sources --root ../..",
            "scout --json logs sources --sources my-logs.json",
        ]
    ),
)
def sources_cmd(
    sources_file: str | None = typer.Option(
        None, "--sources", help="JSON sources overlay (policy-as-config)"
    ),
    root: str = typer.Option(
        ".", "--root", help="directory relative source paths/globs resolve against"
    ),
    db: str | None = typer.Option(None, "--db", help="log store path"),
):
    """Effective source set + matched files + stored tail positions. Read-only."""
    sources = _sources_or_fail(sources_file, "logs sources")
    path = _db_path(db)
    # a board with no store yet is a legitimate answer (offsets read as 0), so
    # this command opens the store read-mostly instead of demanding a pass first
    conn = logs.open_store(path) if path.exists() else logs.open_store(":memory:")
    board = logs.source_status(conn, sources, root=root)
    emit(
        ok(
            {
                "db": str(path) if path.exists() else None,
                "root": Path(root).as_posix(),
                "overlay": sources_file,
                "count": len(sources),
                "sources": board,
                "tracked_files": sum(len(s["files"]) for s in board),
            },
            command="logs sources",
            example="scout --json logs collect",
            discover="scout logs parsers",
        ),
        command="logs sources",
    )


@app.command(
    "collect",
    epilog=examples_epilog(
        [
            "scout --json logs collect",
            "scout --json logs collect --root ../.. --include-partial",
            "scout --json logs collect --sources my-logs.json --no-record",
        ]
    ),
)
def collect(
    sources_file: str | None = typer.Option(
        None, "--sources", help="JSON sources overlay (policy-as-config)"
    ),
    root: str = typer.Option(
        ".", "--root", help="directory relative source paths/globs resolve against"
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"log store path (default {logs.DB_REL} or $SCOUT_LOGS_DB)",
    ),
    max_bytes: int = typer.Option(
        logs.DEFAULT_MAX_BYTES,
        "--max-bytes",
        help="per-file read cap per pass; `capped: true` means run another pass",
    ),
    include_partial: bool = typer.Option(
        False,
        "--include-partial/--no-include-partial",
        help="also consume a trailing line with no newline yet (right for a "
        "static file, wrong for a live tail)",
    ),
    record: bool = typer.Option(
        True,
        "--record/--no-record",
        help="persist entries + offsets (off = parse-and-report only, offsets "
        "untouched, so a dry run never advances the tail)",
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any newly collected line maps at/above this severity "
        "(error|warning) — the cron/CI gate hook",
    ),
):
    """One tailing pass: detect encoding, seek to the stored offset, parse, store."""
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command="logs collect",
            example="scout --json logs collect --fail-on error",
        )
    sources = _sources_or_fail(sources_file, "logs collect")
    real = _db_path(db)
    if record or real.exists():
        # --no-record still opens the REAL store (read-only use) so the pass
        # resumes from the true offsets instead of re-reading every file from 0
        conn, path = _open_new(db)
        path = path if record else None
    else:
        conn, path = logs.open_store(":memory:"), None  # nothing to resume from
    res = logs.collect(
        conn,
        sources,
        root=root,
        record=record,
        max_bytes=max_bytes,
        include_partial=include_partial,
    )
    # The gate looks at THIS pass's level counts, not the whole store — a stale
    # error from last week must not fail today's cron run.
    triggered = False
    gate: dict | None = None
    if fail_on is not None:
        gate_rank = openswap.severity_rank(fail_on)
        hits = {
            lv: n
            for lv, n in res["by_level"].items()
            if (sev := logs.severity_for_level(lv)) is not None
            and openswap.severity_rank(sev) <= gate_rank
        }
        triggered = bool(hits)
        gate = {"fail_on": fail_on, "triggered": triggered, "counts": hits}
    emit(
        ok(
            {"db": str(path) if path else None, **res, "gate": gate},
            command="logs collect",
            example="scout --json logs query --hours 24 --level warning",
            discover="scout logs sources",
        ),
        command="logs collect",
    )
    if triggered:
        raise typer.Exit(code=1)


@app.command(
    "query",
    epilog=examples_epilog(
        [
            "scout --json logs query --hours 24 --level warning",
            "scout --json logs query --source research-loop --contains diverged",
            "scout --json logs query --since 2026-07-19T00:00:00Z --limit 200",
            "scout --json logs query --level error --fail-on error",
        ]
    ),
)
def query_cmd(
    source: str | None = typer.Option(None, "--source", help="filter to one source"),
    level: str | None = typer.Option(
        None,
        "--level",
        help="MINIMUM severity: warning also returns error and critical "
        f"({'|'.join(logs.LEVELS)})",
    ),
    hours: float | None = typer.Option(
        None, "--hours", help="window ending now (ignored when --since is given)"
    ),
    since: str | None = typer.Option(
        None, "--since", help="ISO-8601 or epoch lower bound (inclusive)"
    ),
    until: str | None = typer.Option(
        None, "--until", help="ISO-8601 or epoch upper bound (inclusive)"
    ),
    contains: str | None = typer.Option(
        None, "--contains", help="substring of the message OR the raw line"
    ),
    limit: int = typer.Option(100, "--limit", help="max entries returned"),
    oldest_first: bool = typer.Option(
        False, "--oldest-first", help="ascending time order (default: newest first)"
    ),
    db: str | None = typer.Option(None, "--db", help="log store path"),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any matched entry maps at/above this severity "
        "(error|warning) — the cron/CI gate hook",
    ),
):
    """Filter the indexed store by time, minimum level, source and substring."""
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command="logs query",
            example="scout --json logs query --fail-on error",
        )
    norm_level = _level_or_fail(level, "logs query")
    lo, hi = _window(hours, since, until, "logs query")
    conn, path = _open_existing(db, "logs query")
    entries = logs.query(
        conn,
        source=source,
        level=norm_level,
        since=lo,
        until=hi,
        contains=contains,
        limit=limit,
        newest_first=not oldest_first,
    )
    diags = logs.to_diagnostics(entries)
    emit(
        ok(
            {
                "db": str(path),
                "window": {"since": lo, "until": hi},
                "filters": {
                    "source": source,
                    "level": norm_level,
                    "contains": contains,
                    "limit": limit,
                },
                "count": len(entries),
                "entries": entries,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="logs query",
            example="scout --json logs rollup --hours 24",
            discover="scout logs rollup",
        ),
        command="logs query",
    )
    if fail_on is not None:
        gate_rank = openswap.severity_rank(fail_on)
        if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
            raise typer.Exit(code=1)


@app.command(
    "rollup",
    epilog=examples_epilog(
        [
            "scout --json logs rollup --hours 24",
            "scout --json logs rollup --hours 168 --bucket 86400",
            "scout --json logs rollup --source trainer --level warning",
        ]
    ),
)
def rollup_cmd(
    source: str | None = typer.Option(None, "--source", help="filter to one source"),
    level: str | None = typer.Option(
        None, "--level", help="minimum severity counted"
    ),
    hours: float | None = typer.Option(
        None, "--hours", help="window ending now (ignored when --since is given)"
    ),
    since: str | None = typer.Option(
        None, "--since", help="ISO-8601 or epoch lower bound (inclusive)"
    ),
    until: str | None = typer.Option(
        None, "--until", help="ISO-8601 or epoch upper bound (inclusive)"
    ),
    bucket: float = typer.Option(
        3600.0, "--bucket", help="time bucket width in seconds (3600 = hourly)"
    ),
    db: str | None = typer.Option(None, "--db", help="log store path"),
):
    """Counts by level, by source and per time bucket — read-only."""
    norm_level = _level_or_fail(level, "logs rollup")
    lo, hi = _window(hours, since, until, "logs rollup")
    conn, path = _open_existing(db, "logs rollup")
    try:
        res = logs.rollup(
            conn,
            source=source,
            level=norm_level,
            since=lo,
            until=hi,
            bucket_seconds=bucket,
        )
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="logs rollup",
            example="scout --json logs rollup --hours 24 --bucket 3600",
        )
    emit(
        ok(
            {"db": str(path), **res},
            command="logs rollup",
            example="scout --json logs query --hours 24 --level error",
            discover="scout logs query",
        ),
        command="logs rollup",
    )


def register(root):
    root.add_typer(app, name="logs")
