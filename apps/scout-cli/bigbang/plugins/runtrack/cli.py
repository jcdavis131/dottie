# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout runtrack` — Weights & Biases replacement, fully local (openswap #10).

Experiment tracking with the server deleted: start a run, log scalar metrics
per step, finish it, then list / show / compare — all against a local sqlite
file (.scout/runtrack.db). There is no wandb server, no DSN, no sync; the file
IS the tracker, and the manifest disables the network axis entirely, so "no run
ever left the box" is architectural rather than a promise. All deterministic
logic (the run/metric store, summaries, comparison + deltas) lives in
bigbang/core/runtrack.py; this surface adds only path resolution, argument
parsing, and the fs_write policy gate. There is no native binary tier to
prefer — W&B's product is the hosted service, so `detect` reports
tier=fallback as the expected steady state (scope honesty, not degradation).

Policy: this plugin makes no network call and opens no socket. mlflow (the
open, local, file-backed tracker) is surfaced by `detect` as an optional local
alternative; wandb's own CLI is surfaced for awareness but NEVER executed — its
whole job is syncing runs to the paid SaaS (the forbidden network tier).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from bigbang.core import openswap, runtrack
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib sqlite tracker is the complete product for this adapter: "
    "runs with JSON config, per-step scalar metrics, run summaries "
    "(first/last/min/max per key), and cross-run comparison with deltas — all "
    "file-backed with zero network; tier 'fallback' is the expected steady "
    "state (W&B's product is the hosted service — there is no local native "
    "binary that supersedes this core to prefer)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib sqlite tracker is complete; run mlflow "
    "separately only if you want its web UI over the same local files"
)

app = make_plugin_app(
    "runtrack",
    "Experiment tracking (Weights & Biases-class), fully local: stdlib sqlite "
    "run/metric store with cross-run comparison, zero egress",
    examples=[
        "scout --json runtrack start trainer --config '{\"lr\": 3e-4}'",
        "scout --json runtrack log 1 --metric loss=0.42 --metric acc=0.91",
        "scout --json runtrack finish 1 --status finished",
        "scout --json runtrack compare 1 2 --metric min",
        "scout --json runtrack list --fail-on warning",
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
    # No local native binary supersedes this core (W&B's product is the hosted
    # service). mlflow is a benign optional local alternative; the wandb CLI is
    # surfaced but NEVER executed — its whole job is syncing runs to the paid
    # SaaS (the forbidden network tier).
    native = openswap.probe_binary("mlflow", probe_args=("--version",))
    extras = {"wandb": openswap.probe_binary("wandb", probe_args=("--version",))}
    return openswap.capability_report(
        "runtrack",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_RUNTRACK_DB") or runtrack.DB_REL)


def _open_new(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return runtrack.open_store(path), path


def _open_existing(db: str | None, command: str, *, write: bool = False) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no run store at {path} — start a run first",
            command=command,
            example="scout --json runtrack start my-run",
        )
    if write:
        enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return runtrack.open_store(path), path


def _parse_metrics(pairs: list[str] | None, blob: str | None, command: str) -> dict:
    """key=value pairs and/or a JSON object -> a {key: float} dict."""
    out: dict[str, float] = {}
    if blob:
        try:
            parsed = json.loads(blob)
        except ValueError as exc:
            fail_agent(
                f"--metrics must be valid JSON: {exc}",
                command=command,
                example="scout --json runtrack log 1 --metrics '{\"loss\": 0.5}'",
            )
        if not isinstance(parsed, dict):
            fail_agent(
                "--metrics must be a JSON object",
                command=command,
                example="scout --json runtrack log 1 --metrics '{\"loss\": 0.5}'",
            )
        out.update(parsed)
    for pair in pairs or []:
        if "=" not in pair:
            fail_agent(
                f"--metric must be key=value, got {pair!r}",
                command=command,
                example="scout --json runtrack log 1 --metric loss=0.42",
            )
        k, v = pair.split("=", 1)
        try:
            out[k.strip()] = float(v)
        except ValueError:
            fail_agent(
                f"metric {k.strip()!r} value must be a number, got {v!r}",
                command=command,
                example="scout --json runtrack log 1 --metric loss=0.42",
            )
    if not out:
        fail_agent(
            "no metrics given — pass --metric key=value or --metrics '{...}'",
            command=command,
            example="scout --json runtrack log 1 --metric loss=0.42",
        )
    return out


@app.command("hello", epilog=examples_epilog(["scout --json runtrack hello"]))
def hello():
    """Smoke check — is the runtrack surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "runtrack"},
            command="runtrack hello",
            example="scout --json runtrack start my-run",
            discover="scout runtrack detect",
        ),
        command="runtrack hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json runtrack detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="runtrack detect",
            example="scout --json runtrack start my-run",
            discover="scout runtrack list",
        ),
        command="runtrack detect",
    )


@app.command(
    "start",
    epilog=examples_epilog(
        [
            "scout --json runtrack start trainer",
            'scout --json runtrack start trainer --config \'{"lr": 3e-4, "bf16": true}\'',
        ]
    ),
)
def start(
    name: str = typer.Argument(..., help="run name (duplicates allowed; ids differ)"),
    config: str | None = typer.Option(
        None, "--config", help="JSON object of hyperparams/provenance stored on the run"
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"run store path (default {runtrack.DB_REL} or $SCOUT_RUNTRACK_DB)",
    ),
):
    """Create a run and print its id — the handle for `log`/`finish`/`show`."""
    cfg = None
    if config:
        try:
            cfg = json.loads(config)
        except ValueError as exc:
            fail_agent(
                f"--config must be valid JSON: {exc}",
                command="runtrack start",
                example="scout --json runtrack start trainer --config '{\"lr\": 3e-4}'",
            )
    conn, path = _open_new(db)
    try:
        run = runtrack.start_run(conn, name, config=cfg)
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="runtrack start",
            example="scout --json runtrack start trainer",
        )
    emit(
        ok(
            {"run": run, "db": str(path)},
            command="runtrack start",
            example=f"scout --json runtrack log {run['id']} --metric loss=0.5",
            discover="scout runtrack list",
        ),
        command="runtrack start",
    )


@app.command(
    "log",
    epilog=examples_epilog(
        [
            "scout --json runtrack log 1 --metric loss=0.42 --metric acc=0.91",
            "scout --json runtrack log 1 --metrics '{\"loss\": 0.42}' --step 100",
        ]
    ),
)
def log_cmd(
    run_id: int = typer.Argument(..., help="run id from `runtrack start`"),
    metric: list[str] = typer.Option(
        None, "--metric", help="key=value scalar (repeatable)"
    ),
    metrics: str | None = typer.Option(
        None, "--metrics", help="JSON object of {key: number}"
    ),
    step: int | None = typer.Option(
        None, "--step", help="step index (default: auto-increment per run)"
    ),
    db: str | None = typer.Option(None, "--db", help="run store path"),
):
    """Log a dict of scalar metrics at one step (auto-incremented if omitted)."""
    values = _parse_metrics(metric, metrics, "runtrack log")
    conn, path = _open_existing(db, "runtrack log", write=True)
    try:
        res = runtrack.log_metrics(conn, run_id, values, step=step)
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="runtrack log",
            example="scout --json runtrack log 1 --metric loss=0.42",
        )
    emit(
        ok(
            {**res, "db": str(path)},
            command="runtrack log",
            example=f"scout --json runtrack show {run_id}",
            discover="scout runtrack show " + str(run_id),
        ),
        command="runtrack log",
    )


@app.command(
    "finish",
    epilog=examples_epilog(
        [
            "scout --json runtrack finish 1",
            "scout --json runtrack finish 1 --status failed",
        ]
    ),
)
def finish(
    run_id: int = typer.Argument(..., help="run id from `runtrack start`"),
    status: str = typer.Option(
        runtrack.STATUS_FINISHED,
        "--status",
        help="terminal status: " + "|".join(runtrack.TERMINAL_STATUSES),
    ),
    db: str | None = typer.Option(None, "--db", help="run store path"),
):
    """Mark a run terminal (finished|failed) with a finish timestamp."""
    if status not in runtrack.TERMINAL_STATUSES:
        fail_agent(
            f"--status must be one of {'|'.join(runtrack.TERMINAL_STATUSES)}, "
            f"got {status!r}",
            command="runtrack finish",
            example="scout --json runtrack finish 1 --status failed",
        )
    conn, path = _open_existing(db, "runtrack finish", write=True)
    run = runtrack.finish_run(conn, run_id, status=status)
    if run is None:
        fail_agent(
            f"no run #{run_id} in {path}",
            command="runtrack finish",
            example="scout --json runtrack list",
        )
    emit(
        ok(
            {"run": run, "db": str(path)},
            command="runtrack finish",
            example="scout --json runtrack list",
            discover="scout runtrack list",
        ),
        command="runtrack finish",
    )


@app.command(
    "list",
    epilog=examples_epilog(
        [
            "scout --json runtrack list",
            "scout --json runtrack list --name trainer --status failed",
            "scout --json runtrack list --fail-on warning",
        ]
    ),
)
def list_cmd(
    name: str | None = typer.Option(None, "--name", help="filter by exact run name"),
    status: str | None = typer.Option(
        None, "--status", help="filter by status (running|finished|failed)"
    ),
    limit: int = typer.Option(50, "--limit", help="max runs returned, newest first"),
    db: str | None = typer.Option(None, "--db", help="run store path"),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any run maps at/above this severity (a failed run is a "
        "warning) — the CI gate hook",
    ),
):
    """List runs, newest first — read-only. Optional gate on failed runs."""
    if status is not None and status not in runtrack.STATUSES:
        fail_agent(
            f"--status must be one of {'|'.join(runtrack.STATUSES)}, got {status!r}",
            command="runtrack list",
            example="scout --json runtrack list --status failed",
        )
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command="runtrack list",
            example="scout --json runtrack list --fail-on warning",
        )
    conn, path = _open_existing(db, "runtrack list")
    runs = runtrack.list_runs(conn, name=name, status=status, limit=limit)
    diags = runtrack.to_diagnostics(runs)
    emit(
        ok(
            {
                "db": str(path),
                "runs": runs,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="runtrack list",
            example="scout --json runtrack show <id>",
            discover="scout runtrack compare <id> <id>",
        ),
        command="runtrack list",
    )
    if fail_on is not None:
        gate_rank = openswap.severity_rank(fail_on)
        if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
            raise typer.Exit(code=1)


@app.command(
    "show",
    epilog=examples_epilog(
        [
            "scout --json runtrack show 1",
            "scout --json runtrack show 1 --key loss --limit 50",
        ]
    ),
)
def show(
    run_id: int = typer.Argument(..., help="run id from `runtrack list`"),
    key: str | None = typer.Option(None, "--key", help="only this metric's history"),
    limit: int | None = typer.Option(
        None, "--limit", help="cap history points (most recent), default all"
    ),
    db: str | None = typer.Option(None, "--db", help="run store path"),
):
    """One run: metadata, per-metric summary, and metric history — read-only."""
    conn, path = _open_existing(db, "runtrack show")
    run = runtrack.get_run(conn, run_id)
    if run is None:
        fail_agent(
            f"no run #{run_id} in {path}",
            command="runtrack show",
            example="scout --json runtrack list",
        )
    emit(
        ok(
            {
                "db": str(path),
                "run": run,
                "summary": runtrack.run_summary(conn, run_id),
                "history": runtrack.run_history(conn, run_id, key=key, limit=limit),
            },
            command="runtrack show",
            example=f"scout --json runtrack finish {run_id}",
            discover="scout runtrack list",
        ),
        command="runtrack show",
    )


@app.command(
    "compare",
    epilog=examples_epilog(
        [
            "scout --json runtrack compare 1 2",
            "scout --json runtrack compare 1 2 3 --metric min",
        ]
    ),
)
def compare(
    run_ids: list[int] = typer.Argument(..., help="two or more run ids to compare"),
    metric: str = typer.Option(
        "last", "--metric", help="per-run value to pick: last|min|max"
    ),
    db: str | None = typer.Option(None, "--db", help="run store path"),
):
    """Compare runs key-by-key: last/best per run + deltas vs the first run."""
    conn, path = _open_existing(db, "runtrack compare")
    try:
        result = runtrack.compare_runs(conn, run_ids, metric=metric)
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="runtrack compare",
            example="scout --json runtrack compare 1 2 --metric min",
        )
    emit(
        ok(
            {"db": str(path), **result},
            command="runtrack compare",
            example="scout --json runtrack show " + str(run_ids[0]),
            discover="scout runtrack list",
        ),
        command="runtrack compare",
    )


def register(root):
    root.add_typer(app, name="runtrack")
