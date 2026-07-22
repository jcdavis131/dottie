# Solo personal project, no connection to employer, built with public/free-tier only
"""The experiment ledger — a real SQLite state machine for the research loop.

The ledger is the single source of truth the four workers poll and update. It enforces a legal
state machine (illegal transitions raise, never silently corrupt), holds the current global
baseline (the hill being climbed), and records every experiment's real artifacts and outcome.

State machine::

    pending ─implement─▶ ready_for_training ─train─▶ evaluation_pending ─evaluate─▶ sota
        │                     │                            │                          │
        └─fail(3x)─▶          └─NaN/crash─▶                └─no improvement─▶ rejected │
       failed_validation     failed_training                                          │
                                                          (evaluate promotes ─▶ updates baseline)

Nothing here fabricates: metrics are written by the workers only from real runs; an absent
metric stays ``None``.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class LedgerError(RuntimeError):
    """A ledger operation could not be completed (bad id, corrupt row, disk error)."""


class IllegalTransition(LedgerError):
    """A requested state transition is not permitted by the state machine."""


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

PENDING = "pending"
READY_FOR_TRAINING = "ready_for_training"
EVALUATION_PENDING = "evaluation_pending"
SOTA = "sota"
REJECTED = "rejected"
FAILED_VALIDATION = "failed_validation"
FAILED_TRAINING = "failed_training"

STATES = (
    PENDING,
    READY_FOR_TRAINING,
    EVALUATION_PENDING,
    SOTA,
    REJECTED,
    FAILED_VALIDATION,
    FAILED_TRAINING,
)
TERMINAL_STATES = (SOTA, REJECTED, FAILED_VALIDATION, FAILED_TRAINING)

# Legal transitions: state -> allowed next states. A worker that tries anything else gets an
# IllegalTransition (the loop stays honest even if a worker has a bug).
_TRANSITIONS: Dict[str, tuple] = {
    PENDING: (READY_FOR_TRAINING, FAILED_VALIDATION),
    READY_FOR_TRAINING: (EVALUATION_PENDING, FAILED_TRAINING),
    EVALUATION_PENDING: (SOTA, REJECTED),
    SOTA: (),
    REJECTED: (),
    FAILED_VALIDATION: (),
    FAILED_TRAINING: (),
}


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass
class Experiment:
    """One row of the experiment ledger. JSON blobs hold the workers' real artifacts."""

    id: str
    state: str
    created_ts: float
    updated_ts: float
    hypothesis: Dict[str, Any] = field(default_factory=dict)
    implementation: Optional[Dict[str, Any]] = None
    workspace: Optional[str] = None
    train_metrics: Optional[Dict[str, Any]] = None
    eval_verdict: Optional[Dict[str, Any]] = None
    writeup: Optional[str] = None
    failure: Optional[str] = None
    attempts: int = 0

    @property
    def name(self) -> str:
        return str(self.hypothesis.get("hypothesis_name") or self.id)


@dataclass
class Baseline:
    """The current global best — the hill the loop climbs. Seeded from the honest current state."""

    metric_name: str
    metric_value: float
    higher_is_better: bool
    architecture: str
    experiment_id: Optional[str]
    updated_ts: float
    notes: str = ""
    #: Spread of the run that SET this baseline, when one was recorded. Without it the
    #: significance gate can only compare a candidate's own SEM against a POINT estimate,
    #: which is ~1.4 SE_diff (~84%) — not the 95% "significant" implies. Carrying the
    #: baseline's own SEM lets the gate use a real two-sample SE_diff instead. Optional
    #: because hand-seeded and legacy baselines genuinely have no spread to record, and
    #: inventing one would be worse than admitting it is absent.
    metric_sem: Optional[float] = None
    metric_sem_n: Optional[int] = None
    #: Per-seed metric values of the run/calibration that SET this baseline, in seed order.
    #: When a candidate records `per_seed` at the SAME seeds, the evaluator can run a PAIRED
    #: significance test (differences cancel the shared seed variance — §5.3.R93: the
    #: unmodified model alone swings 0.343 across seeds, so unpaired tests are mostly
    #: measuring that). Optional: legacy/hand-seeded baselines genuinely have none.
    per_seed: Optional[List[float]] = None

    def improves(self, value: float) -> bool:
        """Is ``value`` a real improvement over this baseline (strict, direction-aware)?"""
        return value > self.metric_value if self.higher_is_better else value < self.metric_value


_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id           TEXT PRIMARY KEY,
    state        TEXT NOT NULL,
    created_ts   REAL NOT NULL,
    updated_ts   REAL NOT NULL,
    hypothesis   TEXT NOT NULL,          -- JSON
    implementation TEXT,                 -- JSON
    workspace    TEXT,
    train_metrics TEXT,                  -- JSON
    eval_verdict TEXT,                   -- JSON
    writeup      TEXT,
    failure      TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_experiments_state ON experiments(state);
CREATE TABLE IF NOT EXISTS baseline (
    singleton    INTEGER PRIMARY KEY CHECK (singleton = 1),
    metric_name  TEXT NOT NULL,
    metric_value REAL NOT NULL,
    higher_is_better INTEGER NOT NULL,
    architecture TEXT NOT NULL,
    experiment_id TEXT,
    updated_ts   REAL NOT NULL,
    notes        TEXT NOT NULL DEFAULT '',
    metric_sem   REAL,
    metric_sem_n INTEGER,
    per_seed     TEXT
);
"""


def _loads(v: Optional[str]) -> Optional[Dict[str, Any]]:
    return json.loads(v) if v else None


class Ledger:
    """SQLite-backed experiment ledger. Cheap to open; safe for the four short-lived workers."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)
            self._migrate(c)

    @staticmethod
    def _migrate(c: sqlite3.Connection) -> None:
        """Additive column migrations for ledgers created before a field existed.

        `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so new columns never
        appear on a live ledger without this. Every migration must be ADDITIVE and
        nullable: a daemon running older code reads rows by name and writes an explicit
        column list, so it keeps working against a migrated database — which matters here
        because the research daemon holds this file open for hours and does not reload."""
        have = {r["name"] for r in c.execute("PRAGMA table_info(baseline)")}
        for col, decl in (("metric_sem", "REAL"), ("metric_sem_n", "INTEGER"),
                          ("per_seed", "TEXT")):
            if col not in have:
                c.execute(f"ALTER TABLE baseline ADD COLUMN {col} {decl}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            # Read-only media (e.g. the ledger bind-mounted :ro into the server container):
            # switching journal modes writes the db header. Reads work fine without WAL.
            pass
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # -- baseline -----------------------------------------------------------

    def seed_baseline(self, baseline: Baseline, *, overwrite: bool = False) -> Baseline:
        """Install the baseline if absent (or ``overwrite``). Returns the effective baseline."""
        existing = self.get_baseline()
        if existing is not None and not overwrite:
            return existing
        with self._conn() as c:
            c.execute(
                "INSERT INTO baseline (singleton, metric_name, metric_value, higher_is_better, "
                "architecture, experiment_id, updated_ts, notes, metric_sem, metric_sem_n, "
                "per_seed) "
                "VALUES (1,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(singleton) DO UPDATE SET metric_name=excluded.metric_name, "
                "metric_value=excluded.metric_value, higher_is_better=excluded.higher_is_better, "
                "architecture=excluded.architecture, experiment_id=excluded.experiment_id, "
                "updated_ts=excluded.updated_ts, notes=excluded.notes, "
                "metric_sem=excluded.metric_sem, metric_sem_n=excluded.metric_sem_n, "
                "per_seed=excluded.per_seed",
                (baseline.metric_name, float(baseline.metric_value),
                 1 if baseline.higher_is_better else 0, baseline.architecture,
                 baseline.experiment_id, baseline.updated_ts, baseline.notes,
                 None if baseline.metric_sem is None else float(baseline.metric_sem),
                 None if baseline.metric_sem_n is None else int(baseline.metric_sem_n),
                 None if baseline.per_seed is None
                 else json.dumps([float(v) for v in baseline.per_seed])),
            )
        return baseline

    def get_baseline(self) -> Optional[Baseline]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM baseline WHERE singleton = 1").fetchone()
        if row is None:
            return None
        return Baseline(
            metric_name=row["metric_name"], metric_value=row["metric_value"],
            higher_is_better=bool(row["higher_is_better"]), architecture=row["architecture"],
            experiment_id=row["experiment_id"], updated_ts=row["updated_ts"], notes=row["notes"],
            metric_sem=row["metric_sem"], metric_sem_n=row["metric_sem_n"],
            per_seed=json.loads(row["per_seed"]) if row["per_seed"] else None,
        )

    def promote_baseline(self, experiment_id: str, metric_value: float, *,
                         architecture: Optional[str] = None, notes: str = "",
                         metric_sem: Optional[float] = None,
                         metric_sem_n: Optional[int] = None,
                         per_seed: Optional[List[float]] = None,
                         ts: Optional[float] = None) -> Baseline:
        """Move the baseline to a new SOTA. Caller must have already verified real improvement.

        ``per_seed`` carries the winning candidate's cross-seed values onto the new
        baseline so the NEXT comparison can be paired at the same seeds."""
        cur = self.get_baseline()
        if cur is None:
            raise LedgerError("no baseline to promote from; call seed_baseline first")
        new = Baseline(
            metric_name=cur.metric_name, metric_value=float(metric_value),
            higher_is_better=cur.higher_is_better,
            architecture=architecture or cur.architecture, experiment_id=experiment_id,
            updated_ts=ts if ts is not None else time.time(), notes=notes,
            metric_sem=metric_sem, metric_sem_n=metric_sem_n, per_seed=per_seed,
        )
        return self.seed_baseline(new, overwrite=True)

    # -- experiments --------------------------------------------------------

    def create(self, hypothesis: Dict[str, Any], *, ts: Optional[float] = None) -> Experiment:
        now = ts if ts is not None else time.time()
        exp = Experiment(id=uuid.uuid4().hex[:12], state=PENDING, created_ts=now,
                         updated_ts=now, hypothesis=dict(hypothesis))
        with self._conn() as c:
            c.execute(
                "INSERT INTO experiments (id, state, created_ts, updated_ts, hypothesis, attempts)"
                " VALUES (?,?,?,?,?,0)",
                (exp.id, exp.state, exp.created_ts, exp.updated_ts, json.dumps(exp.hypothesis)),
            )
        return exp

    def get(self, experiment_id: str) -> Experiment:
        with self._conn() as c:
            row = c.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        if row is None:
            raise LedgerError(f"no experiment {experiment_id!r}")
        return self._row(row)

    def next_in_state(self, state: str) -> Optional[Experiment]:
        """Oldest experiment in ``state`` (FIFO) — what a worker should pick up, or None."""
        if state not in STATES:
            raise LedgerError(f"unknown state {state!r}")
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM experiments WHERE state = ? ORDER BY created_ts ASC LIMIT 1",
                (state,),
            ).fetchone()
        return self._row(row) if row else None

    def list(self, *, state: Optional[str] = None, limit: int = 100) -> List[Experiment]:
        q = "SELECT * FROM experiments"
        args: tuple = ()
        if state is not None:
            q += " WHERE state = ?"
            args = (state,)
        q += " ORDER BY created_ts DESC LIMIT ?"
        with self._conn() as c:
            rows = c.execute(q, args + (int(limit),)).fetchall()
        return [self._row(r) for r in rows]

    def counts(self) -> Dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT state, COUNT(*) n FROM experiments GROUP BY state").fetchall()
        out = {s: 0 for s in STATES}
        for r in rows:
            out[r["state"]] = r["n"]
        out["total"] = sum(out[s] for s in STATES)
        return out

    def transition(self, experiment_id: str, to_state: str, *,
                   ts: Optional[float] = None, **fields: Any) -> Experiment:
        """Move an experiment to ``to_state`` (enforcing the state machine) and set fields.

        Recognised ``fields``: implementation, workspace, train_metrics, eval_verdict, writeup,
        failure (dicts are JSON-encoded), and ``attempts`` (int). Raises IllegalTransition if the
        move is not permitted from the current state."""
        exp = self.get(experiment_id)
        if to_state not in STATES:
            raise LedgerError(f"unknown target state {to_state!r}")
        if to_state not in _TRANSITIONS[exp.state]:
            raise IllegalTransition(
                f"experiment {experiment_id}: {exp.state} -> {to_state} is not a legal transition "
                f"(allowed: {_TRANSITIONS[exp.state] or 'none — terminal'})")
        return self._write(experiment_id, to_state, ts=ts, **fields)

    def set_fields(self, experiment_id: str, *, ts: Optional[float] = None,
                   **fields: Any) -> Experiment:
        """Update fields WITHOUT a state change (e.g. bump attempts mid-self-correction)."""
        exp = self.get(experiment_id)
        return self._write(experiment_id, exp.state, ts=ts, **fields)

    # -- internals ----------------------------------------------------------

    _JSON_FIELDS = {"implementation", "train_metrics", "eval_verdict"}
    _TEXT_FIELDS = {"workspace", "writeup", "failure"}

    def _write(self, experiment_id: str, state: str, *, ts: Optional[float] = None,
               **fields: Any) -> Experiment:
        sets = ["state = ?", "updated_ts = ?"]
        args: List[Any] = [state, ts if ts is not None else time.time()]
        for k, v in fields.items():
            if k in self._JSON_FIELDS:
                sets.append(f"{k} = ?")
                args.append(json.dumps(v) if v is not None else None)
            elif k in self._TEXT_FIELDS:
                sets.append(f"{k} = ?")
                args.append(str(v) if v is not None else None)
            elif k == "attempts":
                sets.append("attempts = ?")
                args.append(int(v))
            else:
                raise LedgerError(f"unknown experiment field {k!r}")
        args.append(experiment_id)
        with self._conn() as c:
            cur = c.execute(f"UPDATE experiments SET {', '.join(sets)} WHERE id = ?", args)
            if cur.rowcount == 0:
                raise LedgerError(f"no experiment {experiment_id!r}")
        return self.get(experiment_id)

    @staticmethod
    def _row(row: sqlite3.Row) -> Experiment:
        return Experiment(
            id=row["id"], state=row["state"], created_ts=row["created_ts"],
            updated_ts=row["updated_ts"], hypothesis=_loads(row["hypothesis"]) or {},
            implementation=_loads(row["implementation"]), workspace=row["workspace"],
            train_metrics=_loads(row["train_metrics"]), eval_verdict=_loads(row["eval_verdict"]),
            writeup=row["writeup"], failure=row["failure"], attempts=row["attempts"],
        )
