# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout metrics` — Datadog Infrastructure Monitoring replacement, local (openswap #15).

Datadog charges for an agent that reads the box and for the hosted time series
that keeps the readings. Both are deleted here. The agent becomes three stdlib
measurements — shutil.disk_usage, ctypes GlobalMemoryStatusEx (or /proc/meminfo
off Windows), and a performance counter read through typeperf or Get-Counter —
and the hosted series becomes an append-only JSONL log plus a sqlite3 rollup
table under .scout/. There is no API key and no intake host: the manifest
disables the network axis outright, so "no telemetry left this box" is
architectural rather than a retention promise.

Every row records HOW it was measured (the exact API or argv) and WHICH
mechanism produced it, and bigbang/core/metrics.reading() refuses to construct a
row that does not — provenance is enforced at the constructor, not asked for in
review. Aggregation preserves it: each rollup window carries the distinct `how`
strings of the samples behind its min/max/mean. A failed measurement keeps its
error instead of a number, and rollups count those separately from the
statistics they exclude, because 0% busy and "could not measure" are opposite
facts and a monitoring tool that conflates them is worse than none.

The only real I/O in this file is _run_counter (subprocess.run of typeperf or
powershell, local, bounded by a timeout) — the core takes it as an injected
callable, so the whole pipeline is unit-testable offline, the certmon `_fetch`
pattern. `detect` reports tier=native when a counter backend is on PATH and
tier=fallback when it is not: the fallback still collects disk and memory
everywhere and says so, and cpu.busy_pct then records source="unsupported" with
the reason rather than disappearing from the series. netdata/telegraf are
surfaced as optional local agents and NEVER executed beyond a version probe —
they are collectors in their own right and starting one is not this plugin's
call.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import typer

from bigbang.core import metrics, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib host collection is the complete product for disk and memory: "
    "shutil.disk_usage per filesystem, ctypes GlobalMemoryStatusEx on Windows "
    "and /proc/meminfo on Linux, an append-only JSONL record plus sqlite "
    "min/max/mean rollups with per-window provenance, and threshold gating; "
    "tier 'fallback' loses only cpu.busy_pct, which needs a Windows "
    "performance-counter backend (typeperf or powershell Get-Counter) and is "
    "recorded as source='unsupported' with its reason when neither is on PATH"
)
INSTALL_HINT = (
    "nothing to install — typeperf and Get-Counter ship with Windows; on "
    "Linux/macOS disk and memory still collect and cpu.busy_pct honestly "
    "reports that no counter backend exists"
)

app = make_plugin_app(
    "metrics",
    "Collect this host's metrics (Datadog-class) into an append-only JSONL log "
    "plus sqlite rollups — stdlib only, provenance-stamped, zero egress",
    examples=[
        "scout --json metrics collect",
        "scout --json metrics collect --path . --fail-on error",
        "scout --json metrics rollup --window 300",
        "scout --json metrics show",
        "scout --json metrics detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only when used
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # Unlike the SaaS-only adapters in this family, a genuine native tier exists
    # here and this plugin DOES use it: typeperf is the Windows-native counter
    # reader, powershell Get-Counter the second choice. netdata/telegraf are
    # surfaced for awareness and NEVER executed beyond a version probe — each is
    # a collecting agent, and starting one behind the user's back is exactly the
    # behaviour this family refuses.
    native = openswap.probe_binary("typeperf", probe_args=("-?",))
    extras = {
        "powershell": openswap.probe_binary(
            "powershell",
            probe_args=("-NoProfile", "-Command", "$PSVersionTable.PSEdition"),
        ),
        "netdata": openswap.probe_binary("netdata", probe_args=("-v",)),
        "telegraf": openswap.probe_binary("telegraf", probe_args=("--version",)),
    }
    return openswap.capability_report(
        "metrics",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    # relative default beside the family's other ledgers; env override for cron
    return Path(db or os.environ.get("SCOUT_METRICS_DB") or metrics.DB_REL)


def _log_path(log: str | None) -> Path:
    return Path(log or os.environ.get("SCOUT_METRICS_JSONL") or metrics.SAMPLES_REL)


def _open_existing(db: str | None, command: str):
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no metrics ledger at {path} — collect a sample first",
            command=command,
            example="scout --json metrics collect",
            discover="scout metrics detect",
        )
    return metrics.open_ledger(path), path


def _run_counter(argv: list[str]) -> dict:
    """The one real I/O boundary: run a LOCAL counter command, capture stdout.

    Not under test (the core is what's tested, with canned stdout injected).
    Bounded by a hard timeout because a wedged perf-counter subsystem must not
    hang a cron collection, and a timeout is returned as a nonzero result so the
    core records it as an unmeasured reading rather than a crash.
    """
    try:
        r = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": f"timeout: {argv[0]}"}


def _budgets(warn_pct: float | None, error_pct: float | None) -> dict:
    """Threshold overrides for to_diagnostics — policy as options, not as code.

    Given, they replace BOTH the disk and memory budgets; omitted, each metric
    keeps its own default (disk 85/95, memory 90/97 — a box can run at 92%
    memory all day, a disk at 92% is a page).
    """
    out: dict[str, float] = {}
    if warn_pct is not None:
        out["disk_warn_pct"] = out["mem_warn_pct"] = float(warn_pct)
    if error_pct is not None:
        out["disk_error_pct"] = out["mem_error_pct"] = float(error_pct)
    return out


def _persist(rows: list[dict], log_path: Path, db_path: Path) -> dict:
    """Append to the JSONL record FIRST, then derive the sqlite ledger from it.

    The order is the durability story: the log is the evidence, the ledger is a
    query surface built from it, so a crash between the two costs a rollup and
    never a measurement. fs_write is enforced here because the plugin loader does
    not check capabilities at the call site for us.
    """
    enforce_or_raise(_manifest(), "fs_write_arg", str(log_path))
    written = metrics.append_jsonl(log_path, rows)
    conn = metrics.open_ledger(db_path)
    try:
        metrics.record_samples(conn, rows)
    finally:
        conn.close()
    return written


def _history(conn, metric: str, scope: str | None, limit: int) -> list[dict]:
    """Raw samples for one series, or an actionable failure — never an empty board.

    A `show --metric` that silently returned nothing would read as "measured and
    fine"; the empty case is a typo'd metric name or a box that never collected,
    and both deserve to be said out loud.
    """
    rows = metrics.series(conn, metric, scope=scope, limit=limit)
    if not rows:
        conn.close()
        fail_agent(
            f"no samples recorded for metric {metric!r}"
            + (f" scope {scope!r}" if scope else ""),
            command="metrics show",
            example="scout --json metrics collect",
            discover="scout --json metrics show",
        )
    return rows


def _validate_fail_on(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json metrics collect --fail-on error",
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    gate_rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json metrics hello"]))
def hello():
    """Smoke check — is the metrics surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "metrics", "system": platform.system()},
            command="metrics hello",
            example="scout --json metrics collect",
            discover="scout metrics detect",
        ),
        command="metrics hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json metrics detect"]))
def detect():
    """Report the capability tier (native = a counter backend is on PATH)."""
    emit(
        ok(
            _capability(),
            command="metrics detect",
            example="scout --json metrics collect",
            discover="scout metrics show",
        ),
        command="metrics detect",
    )


@app.command(
    "collect",
    epilog=examples_epilog(
        [
            "scout --json metrics collect",
            "scout --json metrics collect --path . --path ..",
            "scout --json metrics collect --fail-on error",
            "scout --json metrics collect --no-record",
        ]
    ),
)
def collect(
    path: list[str] = typer.Option(
        None,
        "--path",
        help="filesystem to measure (repeatable; default = the volume this cwd is on)",
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"sqlite ledger (default {metrics.DB_REL} or $SCOUT_METRICS_DB)",
    ),
    log: str | None = typer.Option(
        None,
        "--log",
        help=f"append-only JSONL record (default {metrics.SAMPLES_REL} or $SCOUT_METRICS_JSONL)",
    ),
    record: bool = typer.Option(
        True, "--record/--no-record", help="persist (off = measure-and-report only)"
    ),
    warn_pct: float | None = typer.Option(
        None, "--warn-pct", help="warn at/above this % (default: disk 85, mem 90)"
    ),
    error_pct: float | None = typer.Option(
        None, "--error-pct", help="error at/above this % (default: disk 95, mem 97)"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any reading maps at/above this severity (error|warning) "
        "— the disk-pressure cron gate",
    ),
):
    """Measure this host once: disk + memory + CPU counter. The real collection.

    Writes the JSONL record first and the sqlite ledger second: the log is the
    durable evidence and the ledger is derived from it, so a failure in between
    loses a query surface, never a measurement.
    """
    _validate_fail_on(fail_on, "metrics collect")
    pass_ = metrics.sample_host(runner=_run_counter, paths=list(path) if path else None)
    rows = pass_["readings"]
    log_path, db_path = _log_path(log), _db_path(db)
    written = _persist(rows, log_path, db_path) if record else None
    diags = metrics.to_diagnostics(rows, **_budgets(warn_pct, error_pct))
    emit(
        ok(
            {
                "ts": pass_["ts"],
                "host": pass_["host"],
                "system": pass_["system"],
                "recorded": record,
                "log": written or {"path": str(log_path), "rows": 0},
                "db": str(db_path) if record else None,
                "by_source": pass_["by_source"],
                "readings": rows,
                "errors": pass_["errors"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="metrics collect",
            example="scout --json metrics rollup --window 300",
            discover="scout metrics show",
        ),
        command="metrics collect",
    )
    _gate(diags, fail_on)


@app.command(
    "rollup",
    epilog=examples_epilog(
        [
            "scout --json metrics rollup",
            "scout --json metrics rollup --window 3600",
            "scout --json metrics rollup --window 60 --no-persist",
        ]
    ),
)
def rollup(
    window: float = typer.Option(
        metrics.DEFAULT_WINDOW_S, "--window", help="window width in seconds"
    ),
    db: str | None = typer.Option(None, "--db", help="sqlite ledger path"),
    since: float | None = typer.Option(
        None, "--since", help="only samples at/after this epoch second"
    ),
    until: float | None = typer.Option(
        None, "--until", help="only samples at/before this epoch second"
    ),
    persist: bool = typer.Option(
        True, "--persist/--no-persist", help="write the windows into the rollups table"
    ),
    limit: int = typer.Option(50, "--limit", help="windows to include in the output"),
):
    """Fold raw samples into min/max/mean windows. Idempotent, no measurement.

    Buckets are absolute (floor(ts / window)), so re-running over an overlapping
    range replaces the same windows instead of double-counting them.
    """
    if window <= 0:
        fail_agent(
            f"--window must be > 0 seconds, got {window}",
            command="metrics rollup",
            example="scout --json metrics rollup --window 300",
        )
    conn, path = _open_existing(db, "metrics rollup")
    if persist:
        enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    res = metrics.rollup(
        conn, window_s=window, since=since, until=until, persist=persist
    )
    conn.close()
    shown = res["windows"][-int(limit) :] if limit > 0 else res["windows"]
    emit(
        ok(
            {
                "db": str(path),
                "window_s": res["window_s"],
                "samples": res["samples"],
                "windows_total": len(res["windows"]),
                "persisted": res["persisted"],
                "windows": shown,
            },
            command="metrics rollup",
            example="scout --json metrics show --windows",
            discover="scout metrics show",
        ),
        command="metrics rollup",
    )


@app.command(
    "show",
    epilog=examples_epilog(
        [
            "scout --json metrics show",
            "scout --json metrics show --metric disk.used_pct",
            "scout --json metrics show --windows --window 300",
            "scout --json metrics show --fail-on warning",
        ]
    ),
)
def show(
    db: str | None = typer.Option(None, "--db", help="sqlite ledger path"),
    log: str | None = typer.Option(None, "--log", help="append-only JSONL record path"),
    metric: str | None = typer.Option(
        None, "--metric", help="one metric (e.g. disk.used_pct) instead of the board"
    ),
    scope: str | None = typer.Option(
        None, "--scope", help="with --metric: one scope (a mount path, or 'host')"
    ),
    history: int = typer.Option(
        0,
        "--history",
        help="with --metric: N raw samples newest-first instead of the board",
    ),
    show_windows: bool = typer.Option(
        False, "--windows", help="read persisted rollup windows instead of raw samples"
    ),
    window: float | None = typer.Option(
        None, "--window", help="with --windows: only this window width"
    ),
    limit: int = typer.Option(50, "--limit", help="max rows"),
    warn_pct: float | None = typer.Option(
        None, "--warn-pct", help="warn at/above this % (default: disk 85, mem 90)"
    ),
    error_pct: float | None = typer.Option(
        None, "--error-pct", help="error at/above this % (default: disk 95, mem 97)"
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 if the latest board maps at/above this severity"
    ),
):
    """Read what was recorded — no measurement, no subprocess, no network.

    The board is the newest reading per series with its age, failures first, and
    it always ships the provenance of the JSONL log beside the numbers so a
    stale or truncated record is visible rather than implied.
    """
    _validate_fail_on(fail_on, "metrics show")
    conn, path = _open_existing(db, "metrics show")
    data: dict = {
        "db": str(path),
        "log": metrics.jsonl_stats(_log_path(log)),
    }
    diags: list[dict] = []
    if show_windows:
        data["windows"] = metrics.windows(
            conn, metric=metric, window_s=window, limit=limit
        )
    elif metric and history > 0:
        data["metric"] = metric
        data["history"] = _history(conn, metric, scope, history)
    else:
        board = metrics.latest(conn, metric=metric)[:limit]
        diags = metrics.to_diagnostics(board, **_budgets(warn_pct, error_pct))
        data["board"] = board
        data["diagnostics"] = diags
        data["summary"] = openswap.summarize(diags)
    conn.close()
    emit(
        ok(
            data,
            command="metrics show",
            example="scout --json metrics show --metric disk.used_pct --history 10",
            discover="scout --json metrics collect",
        ),
        command="metrics show",
    )
    _gate(diags, fail_on)


def register(root):
    root.add_typer(app, name="metrics")
