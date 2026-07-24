# Solo personal project, no connection to employer, built with public/free-tier only
"""Runtrack — local ML experiment tracker core (openswap #10: Weights & Biases).

W&B's run/metric/compare loop rebuilt on the stdlib with the server deleted:
every experiment this box runs (the trainer, the research loop, factory
checkpoint sweeps) logs runs and scalar metrics straight into sqlite and reads
them back locally. There is no wandb server, no DSN, no sync — the file IS the
tracker. That is the whole product: W&B's value proposition is a hosted
service, so "fully local, zero egress" is the honest replacement, and the
plugin's detect() reports tier=fallback as the expected steady state (like
uptime — there is no local native binary that is a superset of this core to
prefer).

The store (its own file, .scout/runtrack.db — never contends with the #2
uptime ledger's write lock):
- runs(id, name, config-json, status, created_ts, finished_ts) — one row per
  experiment; status is running -> finished | failed.
- metrics(run_id, step, key, value, ts) — one row per logged scalar; a `log`
  call writes a dict of scalars at one step (auto-incremented per run when the
  caller omits it, exactly like wandb.log).

The deterministic surface: start_run, log_metrics, finish_run, list_runs,
run_history, run_summary (first/last/min/max per key) and compare_runs
(last/best value per run for each key, with deltas against a baseline run).
Everything takes an explicit `ts`/`now` so tests are fully deterministic; the
only I/O is sqlite3.

Diagnostics mapping is a bonus, not the point: to_diagnostics() maps a run
marked "failed" onto the openswap schema as a warning, so `list --fail-on`
can gate CI on a crashed experiment exactly like a prose finding. The value,
though, is the tracker itself.

Extension points:
- Config-as-provenance: start_run(config=...) stores an arbitrary JSON blob
  (hyperparams, git sha, mini.yaml token budget) surfaced by get_run/list_runs.
- Custom step axis: pass an explicit `step` to log_metrics (wall-clock second,
  token count, epoch) instead of the auto-incremented default.
- Sweeps / leaderboards: compare_runs(run_ids, metric="min"|"max"|"last")
  builds the per-key comparison table a sweep summary or a static leaderboard
  page consumes; run_summary() is the per-run rollup underneath it.
- No network tier ever: the plugin manifest disables the network axis entirely
  (this adapter is pure local storage), so "no run ever left the box" is
  architectural, not a promise.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

from bigbang.core import openswap

STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
STATUSES = (STATUS_RUNNING, STATUS_FINISHED, STATUS_FAILED)
# statuses a run may be *finished* into (running is the start state, not a finish)
TERMINAL_STATUSES = (STATUS_FINISHED, STATUS_FAILED)
# statuses a run may be *started* in — a new run is running, never terminal
START_STATUSES = (STATUS_RUNNING,)

DB_REL = Path(".scout") / "runtrack.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    config TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    created_ts REAL NOT NULL,
    finished_ts REAL
);
CREATE INDEX IF NOT EXISTS idx_runs_name ON runs(name);
CREATE TABLE IF NOT EXISTS metrics(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    step INTEGER NOT NULL,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_run_key_step ON metrics(run_id, key, step);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the experiment store — its OWN sqlite file.

    Never the #2 uptime ledger: metric volume is bursty (a training loop logs
    many scalars per step) and must not contend with monitoring probes for the
    same write lock.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', '1')"
    )
    conn.commit()
    return conn


# ---- validation helpers -----------------------------------------------------


def _num(key: str, value: Any) -> float:
    """A metric value must be a finite real number — reject bools, NaN, inf, text.

    bool is an int subclass in Python; logging True as 1.0 silently is a classic
    footgun, so we reject it outright and make the caller be explicit.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"metric {key!r} must be a number, got {type(value).__name__}")
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"metric {key!r} must be finite, got {value!r}")
    return v


# ---- runs -------------------------------------------------------------------


def _row_to_run(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    if d.get("config"):
        try:
            d["config"] = json.loads(d["config"])
        except ValueError:
            pass  # pre-schema junk stays visible as the raw string
    return d


def start_run(
    conn: sqlite3.Connection,
    name: str,
    *,
    config: dict[str, Any] | None = None,
    status: str = STATUS_RUNNING,
    ts: float | None = None,
) -> dict[str, Any]:
    """Create a run and return its row. Duplicate names are allowed (distinct ids).

    `config` is an arbitrary JSON-able object (hyperparams, git sha, ...) or
    None. Raises ValueError on an empty name, a non-dict config, or a status
    that is not a valid start state (a new run is running, never terminal).
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("run name must be a non-empty string")
    if config is not None and not isinstance(config, dict):
        raise ValueError("config must be a JSON object (dict) or None")
    if status not in START_STATUSES:
        raise ValueError(f"start status must be one of {START_STATUSES}, got {status!r}")
    ts = time.time() if ts is None else float(ts)
    cur = conn.execute(
        "INSERT INTO runs(name, config, status, created_ts) VALUES(?, ?, ?, ?)",
        (name, json.dumps(config) if config is not None else None, status, ts),
    )
    conn.commit()
    return _row_to_run(
        conn.execute("SELECT * FROM runs WHERE id = ?", (int(cur.lastrowid),)).fetchone()
    )


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    """One run row (config decoded) or None."""
    return _row_to_run(
        conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    )


def list_runs(
    conn: sqlite3.Connection,
    *,
    name: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Newest-first run rows; None filters mean "all"."""
    rows = conn.execute(
        "SELECT * FROM runs WHERE (? IS NULL OR name = ?)"
        " AND (? IS NULL OR status = ?) ORDER BY created_ts DESC, id DESC LIMIT ?",
        (name, name, status, status, limit),
    ).fetchall()
    return [_row_to_run(r) for r in rows]


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str = STATUS_FINISHED,
    ts: float | None = None,
) -> dict[str, Any] | None:
    """Mark a run terminal (finished|failed) with a finished_ts. None if no such run.

    Raises ValueError on a non-terminal status — a run is *finished* into
    finished or failed, never back into running.
    """
    if status not in TERMINAL_STATUSES:
        raise ValueError(
            f"finish status must be one of {TERMINAL_STATUSES}, got {status!r}"
        )
    ts = time.time() if ts is None else float(ts)
    cur = conn.execute(
        "UPDATE runs SET status = ?, finished_ts = ? WHERE id = ?",
        (status, ts, run_id),
    )
    conn.commit()
    return get_run(conn, run_id) if cur.rowcount else None


# ---- metrics ----------------------------------------------------------------


def _next_step(conn: sqlite3.Connection, run_id: int) -> int:
    row = conn.execute(
        "SELECT MAX(step) AS m FROM metrics WHERE run_id = ?", (run_id,)
    ).fetchone()
    return 0 if row["m"] is None else int(row["m"]) + 1


def log_metrics(
    conn: sqlite3.Connection,
    run_id: int,
    metrics: dict[str, Any],
    *,
    step: int | None = None,
    ts: float | None = None,
) -> dict[str, Any]:
    """Log a dict of scalar metrics at one step (wandb.log, local edition).

    When `step` is omitted it auto-increments per run (max existing step + 1, or
    0), so a bare `log_metrics(run, {"loss": x})` per training step just works.
    Raises ValueError on an unknown run, an empty metrics dict, or a
    non-finite/non-numeric value — nothing partial is written.
    """
    if get_run(conn, run_id) is None:
        raise ValueError(f"no run #{run_id}")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("metrics must be a non-empty dict of {key: number}")
    # validate everything BEFORE writing anything (all-or-nothing per call)
    clean = {str(k): _num(str(k), v) for k, v in metrics.items()}
    step = _next_step(conn, run_id) if step is None else int(step)
    ts = time.time() if ts is None else float(ts)
    conn.executemany(
        "INSERT INTO metrics(run_id, step, key, value, ts) VALUES(?, ?, ?, ?, ?)",
        [(run_id, step, k, v, ts) for k, v in clean.items()],
    )
    conn.commit()
    return {
        "run_id": run_id,
        "step": step,
        "logged": len(clean),
        "keys": sorted(clean),
    }


def run_history(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    key: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Metric points for a run in step order (ascending — plot-ready).

    A `limit` returns the most-recent points, still in ascending step order.
    """
    if limit is None:
        rows = conn.execute(
            "SELECT step, key, value, ts FROM metrics WHERE run_id = ?"
            " AND (? IS NULL OR key = ?) ORDER BY step ASC, id ASC",
            (run_id, key, key),
        ).fetchall()
        return [dict(r) for r in rows]
    rows = conn.execute(
        "SELECT step, key, value, ts FROM metrics WHERE run_id = ?"
        " AND (? IS NULL OR key = ?) ORDER BY step DESC, id DESC LIMIT ?",
        (run_id, key, key, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def run_summary(conn: sqlite3.Connection, run_id: int) -> dict[str, dict[str, Any]]:
    """Per-metric rollup for one run: {key: {count, first, last, min, max, ...}}.

    first/last are the values at the smallest/largest step (id breaks ties), so
    "last" is the final logged value and min/max are the best/worst seen.
    """
    rows = conn.execute(
        "SELECT step, key, value, id FROM metrics WHERE run_id = ?"
        " ORDER BY step ASC, id ASC",
        (run_id,),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        grouped.setdefault(r["key"], []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for key, pts in grouped.items():
        values = [p["value"] for p in pts]
        out[key] = {
            "count": len(pts),
            "first": pts[0]["value"],
            "first_step": pts[0]["step"],
            "last": pts[-1]["value"],
            "last_step": pts[-1]["step"],
            "min": min(values),
            "max": max(values),
        }
    return out


# ---- comparison -------------------------------------------------------------

_COMPARE_METRICS = ("last", "min", "max")


def compare_runs(
    conn: sqlite3.Connection,
    run_ids: list[int],
    *,
    metric: str = "last",
) -> dict[str, Any]:
    """Compare runs key-by-key: last/best value per run, plus deltas vs a baseline.

    The baseline is the FIRST run in `run_ids`; `delta_last[rid]` is that run's
    last value minus the baseline's last value for the key (None when either
    side never logged it). `metric` (last|min|max) also selects a `chosen` map
    for callers that want a single per-run number. Raises ValueError on an empty
    list, an unknown metric, or a missing run — a comparison against a run that
    isn't there is a bug, not an empty column.
    """
    if not run_ids:
        raise ValueError("compare_runs needs at least one run id")
    if metric not in _COMPARE_METRICS:
        raise ValueError(f"metric must be one of {_COMPARE_METRICS}, got {metric!r}")
    summaries: dict[int, dict[str, dict[str, Any]]] = {}
    meta: dict[int, dict[str, Any]] = {}
    for rid in run_ids:
        run = get_run(conn, rid)
        if run is None:
            raise ValueError(f"no run #{rid}")
        meta[rid] = run
        summaries[rid] = run_summary(conn, rid)
    baseline = run_ids[0]
    all_keys = sorted({k for s in summaries.values() for k in s})
    keys: dict[str, Any] = {}
    for key in all_keys:

        def pick(rid: int, field: str) -> float | None:
            s = summaries[rid].get(key)
            return None if s is None else s[field]

        base_last = pick(baseline, "last")
        keys[key] = {
            "last": {rid: pick(rid, "last") for rid in run_ids},
            "min": {rid: pick(rid, "min") for rid in run_ids},
            "max": {rid: pick(rid, "max") for rid in run_ids},
            "chosen": {rid: pick(rid, metric) for rid in run_ids},
            "baseline_last": base_last,
            "delta_last": {
                rid: (
                    None
                    if pick(rid, "last") is None or base_last is None
                    else round(pick(rid, "last") - base_last, 6)
                )
                for rid in run_ids
            },
        }
    return {
        "run_ids": list(run_ids),
        "baseline": baseline,
        "metric": metric,
        "runs": {rid: meta[rid] for rid in run_ids},
        "keys": keys,
    }


# ---- family schema ----------------------------------------------------------


def to_diagnostics(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map failed runs onto the family diagnostic schema (failed = warning).

    Only failed runs emit anything, so `list --fail-on warning` gates CI on a
    crashed experiment exactly like a prose finding or an uptime outage. The
    tracker's value is the history itself; this is the optional gate on top.
    """
    diags = []
    for r in runs:
        if r.get("status") != STATUS_FAILED:
            continue
        diags.append(
            openswap.diagnostic(
                path=f"runtrack:{r.get('name', '?')}",
                line=0,
                col=0,
                rule="runtrack:failed",
                severity="warning",
                message=f"run {r.get('name')} (#{r.get('id')}) marked failed",
            )
        )
    return openswap.sort_diagnostics(diags)
