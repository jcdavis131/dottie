# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout apm` — New Relic APM replacement, fully local (openswap #26).

Application performance monitoring with the collector deleted. The agent is
`bigbang.core.apm.Tracer` — an import-only decorator + context manager that
records nested spans off `time.perf_counter` (never a wall clock: time.time is
~15.6 ms granular on Windows and would report 0.0 for a fast call, which this
family treats as a fabricated number). Spans go into a local sqlite file, and
New Relic's transaction/waterfall/flame UI becomes one static self-contained
HTML page. There is no license key and no ingest endpoint: the manifest disables
the network axis entirely, so "no trace left the box" is architectural.

This surface owns the real I/O and nothing else:
- `probe` runs a genuinely instrumented pipeline against the store (open, read,
  aggregate) with the real perf_counter clock and records ITS OWN measurements.
  It never writes synthetic spans — every row in the store is a real reading.
- `ingest` reads a spans JSONL emitted by an instrumented process (the one file
  read; `--stdin` for a pipe) and validates every line through core.check_span,
  so a hand-written row cannot smuggle a fake latency in.
- `report` writes the static page with write_bytes, so the file is byte-exact
  (write_text would emit CRLF on Windows and the report would diff against
  itself on every render).
`stats` and `traces` are read-only aggregates over the store.

Policy: no socket is ever opened. The only writes are the sqlite store and the
report path, both gated by enforce_or_raise(fs_write) at the call site. `detect`
reports tier=fallback as the expected steady state — New Relic's product IS the
hosted backend, so there is no local native binary that supersedes this core;
py-spy and scalene are surfaced as genuinely local optional profilers, and the
newrelic-admin agent client is surfaced but NEVER executed (its whole job is
shipping traces to the paid platform — the forbidden network tier).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import typer

from bigbang.core import apm, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib APM is the complete product for this adapter: a contextvars "
    "span recorder (decorator + context manager) on time.perf_counter with "
    "injectable clocks, an indexed sqlite span store with idempotent ingest, "
    "per-operation p50/p95/p99 + error rate, apdex over root transactions, "
    "aggregate flame layout with self-time, per-trace waterfalls and a static "
    "self-contained HTML report; tier 'fallback' is the expected steady state "
    "(New Relic APM is a hosted collector — there is no local native binary "
    "that supersedes this core to prefer)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib recorder is complete; py-spy or scalene "
    "are optional LOCAL sampling profilers for a one-off deep dive (they cannot "
    "persist a span history, so they complement this rather than replacing it)"
)

REPORT_REL = Path(".scout") / "apm-report.html"

app = make_plugin_app(
    "apm",
    "Application performance tracing (New Relic-class), fully local: "
    "perf_counter spans + sqlite store + static waterfall/flame report, zero egress",
    examples=[
        "scout --json apm probe",
        "scout --json apm stats --slow-ms 50",
        "scout --json apm traces",
        "scout --json apm report --out .scout/apm-report.html",
        "scout --json apm ingest spans.jsonl",
        "scout --json apm detect",
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
    # No local native APM CLI is a superset of this core (New Relic's product is
    # the hosted collector), so `native` stays a truthful probe that reports
    # absent. py-spy/scalene are benign local profilers; newrelic-admin is
    # surfaced but NEVER executed — it ships traces to the paid platform.
    native = openswap.probe_binary("newrelic", probe_args=("--version",))
    extras = {
        "py-spy": openswap.probe_binary("py-spy", probe_args=("--version",)),
        "scalene": openswap.probe_binary("scalene", probe_args=("--version",)),
        "newrelic-admin": openswap.probe_binary("newrelic-admin", probe_args=("--help",)),
    }
    return openswap.capability_report(
        "apm",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_APM_DB") or apm.DB_REL)


def _open_new(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write", str(path))
    return apm.open_store(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no span store at {path} — record a trace first",
            command=command,
            example="scout --json apm probe",
        )
    return apm.open_store(path), path


def _check_fail_on(value: str | None, command: str) -> None:
    if value is not None and value not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {value!r}",
            command=command,
            example=f"scout --json apm {command.split()[-1]} --fail-on error",
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json apm hello"]))
def hello():
    """Smoke check — is the apm surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "apm"},
            command="apm hello",
            example="scout --json apm probe",
            discover="scout apm detect",
        ),
        command="apm hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json apm detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="apm detect",
            example="scout --json apm probe",
            discover="scout apm stats",
        ),
        command="apm detect",
    )


@app.command(
    "probe",
    epilog=examples_epilog(
        [
            "scout --json apm probe",
            "scout --json apm probe --limit 500 --service ledger",
            "scout --json apm probe --jsonl-out .scout/apm-spans.jsonl",
        ]
    ),
)
def probe(
    limit: int = typer.Option(200, "--limit", help="spans the traced read step loads"),
    service: str = typer.Option("apm-probe", "--service", help="service name for the spans"),
    db: str | None = typer.Option(
        None, "--db", help=f"span store path (default {apm.DB_REL} or $SCOUT_APM_DB)"
    ),
    jsonl_out: str | None = typer.Option(
        None, "--jsonl-out", help="also write the recorded spans as JSONL (byte-exact)"
    ),
    record: bool = typer.Option(
        True, "--record/--no-record", help="persist the spans (off = measure and report)"
    ),
):
    """Trace a real store round-trip with the real clock. The only measured I/O.

    Every span here times ACTUAL work on this box (sqlite open, a real query, a
    real aggregation) — no synthetic rows are ever inserted, so everything in the
    store is a genuine reading. Scope note: the write that persists the trace is
    not itself inside the trace; a recorder cannot record its own final flush.
    """
    tracer = apm.Tracer(service=service)  # real clock: time.perf_counter
    conn, path = _open_new(db) if record else (apm.open_store(":memory:"), None)
    with tracer.span("apm.probe", limit=limit, recorded=record):
        with tracer.span("store.open", path=str(path or ":memory:")):
            probe_conn = apm.open_store(path or ":memory:")
        with tracer.span("store.read", limit=limit):
            loaded = apm.load_spans(probe_conn, limit=limit)
        with tracer.span("aggregate.operation_stats", spans=len(loaded)):
            stats = apm.operation_stats(loaded)
        probe_conn.close()
    spans = tracer.spans()
    written = apm.record_spans(conn, spans, ingest_ts=time.time()) if record else None
    out_path = None
    if jsonl_out:
        out_path = Path(jsonl_out)
        enforce_or_raise(_manifest(), "fs_write", str(out_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # write_bytes with explicit LF: write_text would emit CRLF on Windows and
        # the same spans would diff against themselves between platforms
        out_path.write_bytes(("\n".join(apm.to_jsonl_lines(spans)) + "\n").encode("utf-8"))
    emit(
        ok(
            {
                "db": str(path) if path else None,
                "recorded": written,
                "jsonl_out": str(out_path) if out_path else None,
                "spans": spans,
                "read_spans": len(loaded),
                "read_operations": len(stats),
                "clock": "time.perf_counter",
            },
            command="apm probe",
            example="scout --json apm stats",
            discover="scout apm traces",
        ),
        command="apm probe",
    )


@app.command(
    "ingest",
    epilog=examples_epilog(
        [
            "scout --json apm ingest .scout/apm-spans.jsonl",
            "my-daemon --emit-spans | scout --json apm ingest --stdin",
        ]
    ),
)
def ingest(
    file: str | None = typer.Argument(None, help="spans JSONL emitted by a traced process"),
    stdin: bool = typer.Option(False, "--stdin", help="read the JSONL from stdin instead"),
    db: str | None = typer.Option(None, "--db", help="span store path"),
    strict: bool = typer.Option(
        False, "--strict", help="exit 1 if any line failed validation"
    ),
):
    """Load spans from JSONL into the store. Idempotent; bad lines are reported."""
    example = "scout --json apm ingest .scout/apm-spans.jsonl"
    if stdin:
        text, source = sys.stdin.read(), "<stdin>"
    elif file:
        src = Path(file)
        if not src.is_file():
            fail_agent(f"no such spans file: {src}", command="apm ingest", example=example)
        text, source = src.read_text(encoding="utf-8"), str(src)
    else:
        fail_agent(
            "pass a JSONL path or --stdin", command="apm ingest", example=example
        )
    rows, rejected = [], []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(apm.parse_span_line(line))
        except ValueError as exc:
            # never silently skip: an unusable line is reported with its number
            rejected.append({"line": lineno, "error": str(exc)})
    conn, path = _open_new(db)
    written = apm.record_spans(conn, rows, ingest_ts=time.time())
    emit(
        ok(
            {
                "db": str(path),
                "source": source,
                "recorded": written,
                "rejected": rejected,
                "traces": sorted({r["trace_id"] for r in rows}),
            },
            command="apm ingest",
            example="scout --json apm stats",
            discover="scout apm traces",
        ),
        command="apm ingest",
    )
    if strict and rejected:
        raise typer.Exit(code=1)


@app.command(
    "stats",
    epilog=examples_epilog(
        [
            "scout --json apm stats",
            "scout --json apm stats --name store.read --limit 5000",
            "scout --json apm stats --slow-ms 100 --fail-on warning",
        ]
    ),
)
def stats(
    name: str | None = typer.Option(None, "--name", help="one operation instead of all"),
    limit: int = typer.Option(5000, "--limit", help="max spans read from the store"),
    slow_ms: float = typer.Option(apm.DEFAULT_SLOW_MS, "--slow-ms", help="p95 warning budget"),
    critical_ms: float = typer.Option(
        apm.DEFAULT_CRITICAL_MS, "--critical-ms", help="p95 error budget"
    ),
    apdex_t: float = typer.Option(
        apm.DEFAULT_APDEX_T_MS, "--apdex-t", help="apdex T threshold, ms"
    ),
    db: str | None = typer.Option(None, "--db", help="span store path"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 if any finding maps at/above this severity"
    ),
):
    """Latency board: p50/p95/p99 + error rate + apdex. Read-only, no network."""
    _check_fail_on(fail_on, "apm stats")
    conn, path = _open_existing(db, "apm stats")
    spans = apm.load_spans(conn, name=name, limit=limit)
    rows = apm.operation_stats(spans)
    diags = apm.to_diagnostics(rows, slow_ms=slow_ms, critical_ms=critical_ms)
    emit(
        ok(
            {
                "db": str(path),
                "spans": len(spans),
                "operations": rows,
                "apdex": apm.apdex(spans, t_ms=apdex_t),
                "slowest": apm.slowest(spans, limit=10),
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="apm stats",
            example="scout --json apm report",
            discover="scout apm traces",
        ),
        command="apm stats",
    )
    _gate(diags, fail_on)


@app.command(
    "traces",
    epilog=examples_epilog(
        ["scout --json apm traces", "scout --json apm traces --trace abc123 --tree"]
    ),
)
def traces(
    trace: str | None = typer.Option(None, "--trace", help="one trace id instead of the board"),
    tree: bool = typer.Option(False, "--tree", help="nest the spans (waterfall structure)"),
    limit: int = typer.Option(20, "--limit", help="traces on the board"),
    db: str | None = typer.Option(None, "--db", help="span store path"),
):
    """Transaction board, or one trace's spans. Read-only, no network."""
    conn, path = _open_existing(db, "apm traces")
    if trace:
        spans = apm.load_spans(conn, trace_id=trace, limit=100000)
        if not spans:
            fail_agent(
                f"no spans recorded for trace {trace!r}",
                command="apm traces",
                example="scout --json apm traces",
            )
        payload = {
            "db": str(path),
            "trace": apm.trace_rollup(spans)[0],
            "spans": apm.trace_tree(spans, trace) if tree else spans,
            "flame": apm.flame_layout(spans),
        }
    else:
        ids = apm.recent_trace_ids(conn, limit=limit)
        spans = [s for tid in ids for s in apm.load_spans(conn, trace_id=tid, limit=100000)]
        payload = {"db": str(path), "traces": apm.trace_rollup(spans)}
    emit(
        ok(
            payload,
            command="apm traces",
            example="scout --json apm report",
            discover="scout apm stats",
        ),
        command="apm traces",
    )


@app.command(
    "report",
    epilog=examples_epilog(
        [
            "scout --json apm report",
            "scout --json apm report --out .scout/apm-report.html --stamp",
        ]
    ),
)
def report(
    out: str | None = typer.Option(None, "--out", help=f"HTML path (default {REPORT_REL})"),
    limit: int = typer.Option(5000, "--limit", help="max spans read from the store"),
    max_traces: int = typer.Option(10, "--max-traces", help="waterfalls on the page"),
    apdex_t: float = typer.Option(
        apm.DEFAULT_APDEX_T_MS, "--apdex-t", help="apdex T threshold, ms"
    ),
    stamp: bool = typer.Option(
        False,
        "--stamp",
        help="embed a generation timestamp (off keeps the page byte-identical "
        "for identical spans, so it can be committed and diffed)",
    ),
    db: str | None = typer.Option(None, "--db", help="span store path"),
):
    """Write the static waterfall/flame page — the hosted APM UI, deleted."""
    conn, path = _open_existing(db, "apm report")
    ids = apm.recent_trace_ids(conn, limit=max_traces)
    spans = [s for tid in ids for s in apm.load_spans(conn, trace_id=tid, limit=limit)]
    out_path = Path(out or REPORT_REL)
    enforce_or_raise(_manifest(), "fs_write", str(out_path))
    page = apm.render_html(
        spans,
        generated_ts=time.time() if stamp else None,
        apdex_t_ms=apdex_t,
        max_traces=max_traces,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # write_bytes: write_text translates LF to CRLF on Windows, so the same spans
    # would render two different files and the report would diff against itself
    out_path.write_bytes(page.encode("utf-8"))
    emit(
        ok(
            {
                "db": str(path),
                "out": str(out_path),
                "bytes": len(page.encode("utf-8")),
                "spans": len(spans),
                "traces": len(ids),
                "stamped": stamp,
            },
            command="apm report",
            example="scout --json apm stats --fail-on warning",
            discover="scout apm traces",
        ),
        command="apm report",
    )


def register(root):
    root.add_typer(app, name="apm")
