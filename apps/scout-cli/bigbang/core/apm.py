# Solo personal project, no connection to employer, built with public/free-tier only
"""APM — application performance tracing core (openswap #26: New Relic APM).

New Relic sells an agent that instruments your process and a hosted backend that
keeps the traces. This adapter deletes the backend and rewrites the agent in the
stdlib: `Tracer` is an import-only decorator + context manager that records
nested spans with `time.perf_counter`, spans land in a local sqlite file, and the
transaction/waterfall/flame UI becomes ONE static self-contained HTML page. There
is no license key, no collector endpoint, and the plugin manifest disables the
network axis entirely — "no trace left the box" is architectural, not a ToS
promise.

Three properties decide whether an APM-lite is worth writing instead of renting:

[1] The clock. Durations come from a MONOTONIC counter, never a wall clock.
    `time.time()` on Windows has ~15.6 ms granularity, so a 200 us function
    measures 0.0 — a fabricated zero, which is the exact failure this family
    forbids. `Tracer(clock=...)` defaults to time.perf_counter and REFUSES
    time.time outright (see Tracer.__init__). Wall time is recorded separately
    and once per trace (`wall_start`) purely to answer "when", and every span
    offset is derived from the monotonic clock. Both clocks are injectable, so
    tests pin them and never race a real one.

[2] Honest missing readings. A span has EITHER a duration OR a labelled reason
    it has none — never both, never neither, and never an invented 0.0.
    `check_span` enforces that invariant on construction AND on ingest, so a
    hand-written JSONL row cannot smuggle a fake latency into the store:
      - ok / error      -> duration_ms is required (error also names the failure)
      - unfinished      -> no duration; the process exited inside the span
      - unmeasured      -> no duration; the clock went BACKWARDS (a non-monotonic
                          clock was injected), so the delta is not a measurement
    Aggregates inherit the discipline: percentiles are computed over the measured
    subset only, `unmeasured` is counted beside them, and when nothing was
    measured every numeric field is None with `unmeasured_reason` saying why.

[3] Correct nesting without threading a context object through every call.
    Parenting comes from a contextvars.ContextVar, so `with tracer.span(...)` and
    `@tracer.trace()` nest correctly across call depth, threads and asyncio tasks
    (each gets its own context copy). The parent is restored by writing the saved
    parent back rather than by resetting the ContextVar token, because start/end
    may legitimately happen in different frames.

Deterministic reads on top of the store: operation_stats (per-operation
p50/p95/p99 + error rate), apdex (New Relic's signature score, computed over root
spans = transactions), slowest, trace_rollup, trace_tree (waterfall) and
flame_layout (an aggregate icicle with self-time). render_html turns them into
the static page; it takes `generated_ts` as an argument and omits the stamp when
it is None, so identical input renders byte-identical output and a report can
live in git next to the data that produced it.

Extension points:
- Instrument anything: `tracer = apm.Tracer(service="trainer")` then decorate.
  Nothing here imports the CLI, so a daemon can use the core directly.
- Ship spans between processes: to_jsonl_lines / parse_span_line round-trip the
  validated schema; `scout apm ingest` is just that parser plus a store write.
  The store's UNIQUE(trace_id, span_id) makes re-ingesting the same file a no-op.
- Budgets as config: to_diagnostics(slow_ms=, critical_ms=, error_rate_error=)
  maps operations onto the openswap diagnostic schema, so `--fail-on` gates a
  latency regression exactly like a prose lint finding.
- No network tier ever: New Relic's product IS the hosted collector, so there is
  no native binary to prefer and detect() reports tier=fallback as the expected
  steady state.
"""

from __future__ import annotations

import contextvars
import html
import itertools
import json
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bigbang.core import openswap

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# ---- schema constants -------------------------------------------------------

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_UNFINISHED = "unfinished"
STATUS_UNMEASURED = "unmeasured"
STATUSES = (STATUS_OK, STATUS_ERROR, STATUS_UNFINISHED, STATUS_UNMEASURED)
# the two statuses that REQUIRE a duration; the others require a reason instead
MEASURED_STATUSES = (STATUS_OK, STATUS_ERROR)

OPEN_REASON = "span is still open (no end recorded yet)"
ABANDONED_REASON = "span never ended (process exited mid-span)"
BACKWARDS_CLOCK_REASON = (
    "injected clock went backwards (end < start) — a negative latency is not a "
    "measurement, so none is recorded"
)

SPAN_FIELDS = (
    "trace_id",
    "span_id",
    "parent_id",
    "name",
    "service",
    "depth",
    "start_offset_ms",
    "duration_ms",
    "status",
    "error",
    "attrs",
    "wall_start",
)

# latency budgets (ms) and the apdex threshold; every one is a call parameter, so
# the numbers are config rather than code
DEFAULT_SLOW_MS = 500.0
DEFAULT_CRITICAL_MS = 2000.0
DEFAULT_APDEX_T_MS = 500.0
# an operation erroring at/above this share of its measured calls is an error-
# severity finding; anything above zero is still at least a warning
DEFAULT_ERROR_RATE_ERROR = 0.05

DB_REL = Path(".scout") / "apm.db"
SCHEMA_VERSION = "1"

_MAX_ANCESTRY = 512  # cycle backstop for hand-written / corrupted parent links


# ---- the recorder -----------------------------------------------------------

# One ContextVar holds the innermost live span, so nesting needs no plumbing and
# each thread / asyncio task gets its own copy of the stack.
_CURRENT_SPAN: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "bigbang_apm_span", default=None
)


def _ms(delta: float) -> float:
    """Seconds -> milliseconds at 3dp (microsecond), with -0.0 normalized to 0.0."""
    value = round(float(delta) * 1000.0, 3)
    return 0.0 if value == 0 else value


def _default_trace_id() -> str:
    """A collision-safe trace id. Injectable so tests get stable ids instead."""
    return uuid.uuid4().hex[:16]


def public_span(span: dict[str, Any]) -> dict[str, Any]:
    """The serializable view of a span — private bookkeeping keys stripped."""
    return {k: span.get(k) for k in SPAN_FIELDS}


def current_span() -> dict[str, Any] | None:
    """The span live in THIS context, or None. Read-only view."""
    live = _CURRENT_SPAN.get()
    return None if live is None else public_span(live)


def clear_context() -> None:
    """Forget any span left live in this context (leaked-span recovery).

    A process that abandons a span without ending it keeps parenting new spans to
    the dead one — that is inherent to a ContextVar-based recorder, not a bug to
    hide. Tracer.abandon_open() is the honest fix because it KEEPS the abandoned
    spans (with their reason); this is the blunt reset for a supervisor that
    reuses a context, e.g. a pooled worker thread or a test suite.
    """
    _CURRENT_SPAN.set(None)


class Tracer:
    """Records nested spans off a monotonic clock. Import-only, zero egress.

    `clock` must be MONOTONIC (default time.perf_counter). Passing time.time is
    refused rather than tolerated: it is a wall clock with ~15.6 ms granularity
    on Windows, so fast calls would measure 0.0 and this module would report
    fabricated zeros. `wall` is the separate wall clock stamped ONCE per trace to
    answer "when did this happen"; it never contributes to a duration.
    """

    def __init__(
        self,
        *,
        service: str = "app",
        clock: Callable[[], float] = time.perf_counter,
        wall: Callable[[], float] = time.time,
        trace_id_factory: Callable[[], str] = _default_trace_id,
    ) -> None:
        if clock is time.time:
            raise ValueError(
                "clock must be monotonic — time.time is a wall clock (~15.6ms "
                "granularity on Windows) and would measure 0.0 for fast calls; "
                "use time.perf_counter or a pinned test clock"
            )
        if not callable(clock) or not callable(wall):
            raise ValueError("clock and wall must be callables returning seconds")
        self.service = str(service)
        self._clock = clock
        self._wall = wall
        self._new_trace_id = trace_id_factory
        self._ids = itertools.count(1)
        self._open: list[dict[str, Any]] = []
        self._done: list[dict[str, Any]] = []

    # -- lifecycle ----------------------------------------------------------

    def start(self, name: str, **attrs: Any) -> dict[str, Any]:
        """Open a span, parented to whatever span is live in this context."""
        label = str(name).strip()
        if not label:
            raise ValueError("span name must be a non-empty string")
        parent = _CURRENT_SPAN.get()
        now = float(self._clock())
        if parent is None:
            trace_id = str(self._new_trace_id())
            trace_start, wall_start, depth = now, float(self._wall()), 0
        else:
            trace_id = parent["trace_id"]
            trace_start = parent["_trace_start"]
            wall_start = parent["wall_start"]
            depth = int(parent["depth"]) + 1
        span = {
            "trace_id": trace_id,
            "span_id": next(self._ids),
            "parent_id": None if parent is None else parent["span_id"],
            "name": label,
            "service": self.service,
            "depth": depth,
            "start_offset_ms": _ms(now - trace_start),
            # an open span already satisfies the invariant: no duration, and a
            # reason saying so. It can never read as a fabricated 0.0.
            "duration_ms": None,
            "status": STATUS_UNFINISHED,
            "error": OPEN_REASON,
            "attrs": dict(attrs),
            "wall_start": wall_start,
            "_start": now,
            "_trace_start": trace_start,
            "_parent": parent,
        }
        self._open.append(span)
        _CURRENT_SPAN.set(span)
        return span

    def end(
        self,
        span: dict[str, Any],
        *,
        status: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Close a span with a real measured duration (or a labelled reason)."""
        now = float(self._clock())
        if span not in self._open:
            raise ValueError(f"span {span.get('name')!r} is not open on this tracer")
        if status is not None and status not in MEASURED_STATUSES:
            raise ValueError(
                f"end() status must be one of {'|'.join(MEASURED_STATUSES)}; "
                "unfinished/unmeasured are recorded by the tracer, not requested"
            )
        delta = now - float(span["_start"])
        if delta < 0:
            # a backwards clock cannot produce a latency; say so instead of
            # clamping to zero, which would look like a real sub-microsecond call
            span["duration_ms"] = None
            span["status"] = STATUS_UNMEASURED
            span["error"] = BACKWARDS_CLOCK_REASON
        else:
            span["duration_ms"] = _ms(delta)
            span["status"] = status or (STATUS_ERROR if error else STATUS_OK)
            span["error"] = str(error) if error else None
            if span["status"] == STATUS_ERROR and not span["error"]:
                raise ValueError("an error span must name the failure")
        _CURRENT_SPAN.set(span["_parent"])
        self._open.remove(span)
        self._done.append(span)
        return span

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[dict[str, Any]]:
        """`with tracer.span("db.query", table="spans"): ...` — exceptions recorded.

        A raising body is recorded as status=error with the exception named, then
        the exception is RE-RAISED: instrumentation that swallows failures is
        worse than none.
        """
        live = self.start(name, **attrs)
        try:
            yield live
        except BaseException as exc:
            self.end(live, status=STATUS_ERROR, error=f"{type(exc).__name__}: {exc}")
            raise
        self.end(live)

    def trace(
        self, name: str | None = None, **attrs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator form: `@tracer.trace()` (name defaults to __qualname__)."""

        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            label = str(name or getattr(fn, "__qualname__", None) or fn)

            @wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.span(label, **attrs):
                    return fn(*args, **kwargs)

            return wrapper

        return decorate

    def abandon_open(self, reason: str = ABANDONED_REASON) -> list[dict[str, Any]]:
        """Close every still-open span as unfinished, naming why (crash path).

        Innermost first, so the ContextVar ends up back at the outermost span's
        parent. The spans are KEPT (with no duration and a reason) rather than
        dropped — a trace that ends in a crash is the most interesting one.
        """
        label = str(reason).strip() or ABANDONED_REASON
        closed: list[dict[str, Any]] = []
        for span in reversed(self._open):
            span["duration_ms"] = None
            span["status"] = STATUS_UNFINISHED
            span["error"] = label
            _CURRENT_SPAN.set(span["_parent"])
            self._done.append(span)
            closed.append(span)
        self._open.clear()
        return [public_span(s) for s in closed]

    # -- reads --------------------------------------------------------------

    def spans(self) -> list[dict[str, Any]]:
        """Closed spans, ordered (trace_id, span_id) — the flush contract."""
        rows = sorted(self._done, key=lambda s: (s["trace_id"], s["span_id"]))
        return [public_span(s) for s in rows]

    def open_spans(self) -> list[dict[str, Any]]:
        """Spans currently live in this context, outermost first."""
        return [public_span(s) for s in self._open]


# ---- schema validation (the anti-fabrication gate) --------------------------


def _str_field(row: dict[str, Any], key: str, *, default: str | None = None) -> str:
    raw = row.get(key, default)
    text = "" if raw is None else str(raw).strip()
    if not text:
        raise ValueError(f"span field {key!r} must be a non-empty string")
    return text


def _int_field(
    row: dict[str, Any], key: str, *, required: bool = True, minimum: int | None = None
) -> int | None:
    raw = row.get(key)
    if raw is None:
        if required:
            raise ValueError(f"span field {key!r} is required")
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"span field {key!r} must be an integer, got {raw!r}")
    if minimum is not None and raw < minimum:
        raise ValueError(f"span field {key!r} must be >= {minimum}, got {raw}")
    return int(raw)


def _float_field(
    row: dict[str, Any],
    key: str,
    *,
    required: bool = True,
    minimum: float | None = None,
) -> float | None:
    raw = row.get(key)
    if raw is None:
        if required:
            raise ValueError(f"span field {key!r} is required")
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"span field {key!r} must be a number, got {raw!r}")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"span field {key!r} must be finite, got {raw!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"span field {key!r} must be >= {minimum:g}, got {value:g}")
    return value


def check_span(row: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize one span row, or raise ValueError. The honesty gate.

    Every path into the store goes through here (the tracer's own spans, an
    ingested JSONL line, a hand-built fixture), so the invariants below hold for
    everything the aggregates read:
    - ok/error carry a finite non-negative duration_ms; error also NAMES the
      failure; ok must NOT also carry an error (a reading is a value or a fault,
      never both).
    - unfinished/unmeasured carry NO duration and MUST name why, so a missing
      measurement can never be mistaken for a fast one.
    - depth agrees with parentage (a root is depth 0; a child is >= 1), so the
      waterfall's indentation cannot lie about the call structure.
    """
    if not isinstance(row, dict):
        raise ValueError(f"span must be a JSON object, got {type(row).__name__}")
    name = _str_field(row, "name")
    status = str(row.get("status") or "").strip()
    if status not in STATUSES:
        raise ValueError(
            f"span {name!r}: status must be one of {'|'.join(STATUSES)}, got {status!r}"
        )
    parent_id = _int_field(row, "parent_id", required=False, minimum=0)
    depth = _int_field(row, "depth", required=False, minimum=0)
    depth = 0 if depth is None else depth
    if parent_id is None and depth != 0:
        raise ValueError(f"span {name!r}: a root span (no parent_id) must have depth 0")
    if parent_id is not None and depth < 1:
        raise ValueError(
            f"span {name!r}: a child span (parent {parent_id}) needs depth >= 1"
        )
    duration = _float_field(row, "duration_ms", required=False, minimum=0.0)
    error = row.get("error")
    error = None if error is None else str(error).strip() or None
    if status in MEASURED_STATUSES:
        if duration is None:
            raise ValueError(
                f"span {name!r}: status {status!r} requires duration_ms — a reading "
                "has either a value or a labelled reason, never neither"
            )
        if status == STATUS_OK and error:
            raise ValueError(
                f"span {name!r}: an ok span must not also carry an error ({error!r})"
            )
        if status == STATUS_ERROR and not error:
            raise ValueError(f"span {name!r}: an error span must name the failure")
    else:
        if duration is not None:
            raise ValueError(
                f"span {name!r}: status {status!r} must not carry a duration_ms "
                f"({duration!r}) — it was not measured"
            )
        if not error:
            raise ValueError(
                f"span {name!r}: status {status!r} must name WHY no duration exists"
            )
    attrs = row.get("attrs") or {}
    if not isinstance(attrs, dict):
        raise ValueError(f"span {name!r}: attrs must be an object, got {attrs!r}")
    try:
        json.dumps(attrs)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"span {name!r}: attrs must be JSON-serializable — {exc}"
        ) from exc
    offset = _float_field(row, "start_offset_ms", required=False, minimum=0.0)
    return {
        "trace_id": _str_field(row, "trace_id"),
        "span_id": _int_field(row, "span_id", minimum=0),
        "parent_id": parent_id,
        "name": name,
        "service": _str_field(row, "service", default="app"),
        "depth": depth,
        "start_offset_ms": 0.0 if offset is None else offset,
        "duration_ms": duration,
        "status": status,
        "error": error,
        "attrs": attrs,
        "wall_start": _float_field(row, "wall_start", required=False),
    }


def to_jsonl_lines(spans: list[dict[str, Any]]) -> list[str]:
    """Validated spans as compact, key-sorted JSON lines (byte-stable)."""
    return [
        json.dumps(check_span(s), sort_keys=True, separators=(",", ":")) for s in spans
    ]


def parse_span_line(line: str) -> dict[str, Any]:
    """One JSONL line -> a validated span row. Raises ValueError on junk."""
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not JSON: {exc}") from exc
    return check_span(row)


# ---- store (its own sqlite file) --------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    span_id INTEGER NOT NULL,
    parent_id INTEGER,
    name TEXT NOT NULL,
    service TEXT NOT NULL,
    depth INTEGER NOT NULL,
    start_offset_ms REAL NOT NULL,
    duration_ms REAL,
    status TEXT NOT NULL,
    error TEXT,
    attrs TEXT,
    wall_start REAL,
    ingest_ts REAL NOT NULL,
    UNIQUE(trace_id, span_id)
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id, span_id);
CREATE INDEX IF NOT EXISTS idx_spans_name ON spans(service, name);
CREATE INDEX IF NOT EXISTS idx_spans_wall ON spans(wall_start);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the span store — its OWN sqlite file.

    Never the shared uptime ledger: span volume is bursty by nature (one traced
    request can write dozens of rows) and must not contend with monitoring
    probes for the same write lock. pathlib only, so the same call works from a
    Windows shell and a container.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def record_spans(
    conn: sqlite3.Connection, spans: list[dict[str, Any]], *, ingest_ts: float
) -> dict[str, Any]:
    """Persist validated spans; re-ingesting the same spans is a no-op.

    Every row is checked BEFORE anything is written, so a bad batch fails whole
    rather than half-landing. UNIQUE(trace_id, span_id) + INSERT OR IGNORE makes
    `ingest` idempotent, and the return value distinguishes new rows from
    duplicates instead of reporting the batch size as if it were all new.
    """
    rows = [check_span(s) for s in spans]
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO spans(trace_id, span_id, parent_id, name, service,"
        " depth, start_offset_ms, duration_ms, status, error, attrs, wall_start,"
        " ingest_ts) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r["trace_id"],
                r["span_id"],
                r["parent_id"],
                r["name"],
                r["service"],
                r["depth"],
                r["start_offset_ms"],
                r["duration_ms"],
                r["status"],
                r["error"],
                json.dumps(r["attrs"], sort_keys=True) if r["attrs"] else None,
                r["wall_start"],
                float(ingest_ts),
            )
            for r in rows
        ],
    )
    conn.commit()
    inserted = conn.total_changes - before
    return {
        "seen": len(rows),
        "inserted": inserted,
        "duplicates": len(rows) - inserted,
    }


def _row_to_span(row: sqlite3.Row) -> dict[str, Any]:
    span = {k: row[k] for k in SPAN_FIELDS}
    span["attrs"] = json.loads(row["attrs"]) if row["attrs"] else {}
    return span


def load_spans(
    conn: sqlite3.Connection,
    *,
    trace_id: str | None = None,
    name: str | None = None,
    status: str | None = None,
    min_ms: float | None = None,
    since: float | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Filter stored spans. Every filter value is a bound parameter.

    `min_ms` compares against duration_ms, so unmeasured spans (NULL) never
    satisfy it — a span with no reading must not sneak into a "slower than X"
    result as if it were fast OR slow.
    """
    rows = conn.execute(
        "SELECT trace_id, span_id, parent_id, name, service, depth,"
        " start_offset_ms, duration_ms, status, error, attrs, wall_start FROM spans"
        " WHERE (? IS NULL OR trace_id = ?)"
        " AND (? IS NULL OR name = ?)"
        " AND (? IS NULL OR status = ?)"
        " AND (? IS NULL OR duration_ms >= ?)"
        " AND (? IS NULL OR wall_start >= ?)"
        " ORDER BY id DESC LIMIT ?",
        (
            trace_id,
            trace_id,
            name,
            name,
            status,
            status,
            min_ms,
            min_ms,
            since,
            since,
            int(limit),
        ),
    )
    out = [_row_to_span(r) for r in rows]
    out.sort(key=lambda s: (s["trace_id"], s["span_id"]))
    return out


def recent_trace_ids(conn: sqlite3.Connection, *, limit: int = 20) -> list[str]:
    """Newest trace ids first (by wall_start, then insertion order)."""
    rows = conn.execute(
        "SELECT trace_id, MAX(COALESCE(wall_start, -1)) AS w, MAX(id) AS last_id"
        " FROM spans GROUP BY trace_id ORDER BY w DESC, last_id DESC LIMIT ?",
        (int(limit),),
    )
    return [str(r["trace_id"]) for r in rows]


# ---- aggregates (pure) ------------------------------------------------------


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (no interpolation). None for an empty sample.

    Nearest-rank means every reported number is an OBSERVED duration, not an
    average of two, which is what makes a p99 quotable.
    """
    if not 0 < q <= 100:
        raise ValueError(f"percentile q must be in (0, 100], got {q!r}")
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    idx = math.ceil(q / 100.0 * len(vals)) - 1
    return vals[max(0, min(len(vals) - 1, idx))]


def _reason_summary(spans: list[dict[str, Any]]) -> str:
    """Distinct reasons behind unmeasured spans, so a None is always explained."""
    seen: list[str] = []
    for s in spans:
        if s.get("duration_ms") is None:
            reason = f"{s.get('status')}: {s.get('error')}"
            if reason not in seen:
                seen.append(reason)
    return "; ".join(seen)


def operation_stats(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-operation latency table, slowest total first.

    Percentiles cover the MEASURED subset only and `unmeasured` is reported
    beside them; when nothing was measured every numeric field is None and
    `unmeasured_reason` names the cause. No field is ever filled with a guess.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in spans:
        groups.setdefault((s["service"], s["name"]), []).append(s)
    out: list[dict[str, Any]] = []
    for (service, name), rows in groups.items():
        durs = [r["duration_ms"] for r in rows if r["duration_ms"] is not None]
        errors = sum(1 for r in rows if r["status"] == STATUS_ERROR)
        unmeasured = len(rows) - len(durs)
        reason = _reason_summary(rows)
        stat: dict[str, Any] = {
            "service": service,
            "name": name,
            "calls": len(rows),
            "measured": len(durs),
            "unmeasured": unmeasured,
            "errors": errors,
            "error_rate": None,
            "p50_ms": percentile(durs, 50),
            "p95_ms": percentile(durs, 95),
            "p99_ms": percentile(durs, 99),
            "max_ms": max(durs) if durs else None,
            "mean_ms": round(sum(durs) / len(durs), 3) if durs else None,
            "total_ms": round(sum(durs), 3) if durs else None,
            "unmeasured_reason": None,
        }
        if durs:
            stat["error_rate"] = round(errors / len(durs), 4)
            if unmeasured:
                stat["unmeasured_reason"] = (
                    f"{unmeasured} of {len(rows)} calls carried no duration ({reason})"
                    " — excluded from the percentiles above"
                )
        else:
            stat["unmeasured_reason"] = (
                f"none of {len(rows)} calls carried a duration ({reason})"
            )
        out.append(stat)
    out.sort(
        key=lambda s: (
            0 if s["total_ms"] is not None else 1,
            -(s["total_ms"] or 0.0),
            s["service"],
            s["name"],
        )
    )
    return out


def apdex(
    spans: list[dict[str, Any]],
    *,
    t_ms: float = DEFAULT_APDEX_T_MS,
    roots_only: bool = True,
) -> dict[str, Any]:
    """New Relic's Apdex over transactions (root spans by default).

    Per the Apdex definition: satisfied <= T, tolerating <= 4T, everything
    slower is frustrated, and an ERRORED transaction is frustrated regardless of
    how fast it failed. Unmeasured transactions are counted separately and
    excluded — with none measured the score is None and `score_error` says why,
    because a made-up 1.0 for an unmeasured service is the worst possible lie in
    a performance tool.
    """
    if t_ms <= 0:
        raise ValueError(f"apdex t_ms must be > 0, got {t_ms!r}")
    pool = [s for s in spans if not roots_only or s["parent_id"] is None]
    satisfied = tolerating = frustrated = 0
    unmeasured = 0
    for s in pool:
        d = s["duration_ms"]
        if d is None:
            unmeasured += 1
        elif s["status"] == STATUS_ERROR or d > 4 * t_ms:
            frustrated += 1
        elif d <= t_ms:
            satisfied += 1
        else:
            tolerating += 1
    measured = satisfied + tolerating + frustrated
    report: dict[str, Any] = {
        "t_ms": float(t_ms),
        "transactions": len(pool),
        "roots_only": roots_only,
        "measured": measured,
        "unmeasured": unmeasured,
        "satisfied": satisfied,
        "tolerating": tolerating,
        "frustrated": frustrated,
        "score": None,
        "score_error": None,
    }
    if measured:
        report["score"] = round((satisfied + tolerating / 2.0) / measured, 4)
    else:
        report["score_error"] = (
            f"no measured transactions among {len(pool)} candidates"
            f" ({_reason_summary(pool) or 'none recorded'})"
        )
    return report


def slowest(spans: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    """Measured spans, slowest first. Unmeasured spans are never ranked."""
    ranked = [s for s in spans if s["duration_ms"] is not None]
    ranked.sort(key=lambda s: (-s["duration_ms"], s["trace_id"], s["span_id"]))
    return ranked[: max(0, int(limit))]


def _ancestry(span: dict[str, Any], by_id: dict[Any, dict[str, Any]]) -> dict[str, Any]:
    """Ancestor keys root-first, plus honest orphan / cycle / truncated flags.

    Hand-written or half-flushed span files really do contain parent ids that are
    missing (orphan) or that loop back (cycle), and a legitimate call chain can
    be deeper than we are willing to walk. All three are DIFFERENT facts and get
    different flags — labelling a 600-deep legal chain a "cycle" would be a
    fabricated diagnosis:
    - cycle:     a parent id repeats. The walk is unsafe AND the structure is
                 unusable (attaching it would build a circular tree).
    - truncated: _MAX_ANCESTRY reached without repeating. The stack path above
                 that point is unknown, but the immediate parent link is fine.
    - orphan:    the named parent is not in this window.
    """
    ids: list[Any] = []
    seen = {(span["trace_id"], span["span_id"])}
    cursor, orphan, cycle, truncated = span, False, False, False
    while cursor["parent_id"] is not None:
        key = (cursor["trace_id"], cursor["parent_id"])
        if key in seen:
            cycle = True
            break
        parent = by_id.get(key)
        if parent is None:
            orphan = True
            break
        seen.add(key)
        ids.append(key)
        cursor = parent
        if len(ids) >= _MAX_ANCESTRY:
            truncated = True
            break
    ids.reverse()
    return {"ids": ids, "orphan": orphan, "cycle": cycle, "truncated": truncated}


def _index(spans: list[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    return {(s["trace_id"], s["span_id"]): s for s in spans}


def trace_tree(spans: list[dict[str, Any]], trace_id: str) -> list[dict[str, Any]]:
    """One trace as nested nodes (the waterfall's structure), start order.

    Spans whose parent is missing or circular are attached at the top level with
    the flag that says so, never dropped: a partial trace is still evidence. Only
    a CYCLE forces a span to the top level — a merely deep (truncated) chain has
    a perfectly good parent link and nests normally, so the result is always
    acyclic and therefore JSON-serializable.
    """
    rows = [s for s in spans if s["trace_id"] == trace_id]
    rows.sort(key=lambda s: (s["start_offset_ms"], s["span_id"]))
    by_id = _index(rows)
    nodes = {
        s["span_id"]: {
            **s,
            "children": [],
            "orphan": False,
            "cycle": False,
            "truncated": False,
        }
        for s in rows
    }
    roots: list[dict[str, Any]] = []
    for s in rows:
        node = nodes[s["span_id"]]
        anc = _ancestry(s, by_id)
        node["orphan"] = anc["orphan"]
        node["cycle"] = anc["cycle"]
        node["truncated"] = anc["truncated"]
        parent = None if s["parent_id"] is None else nodes.get(s["parent_id"])
        if parent is None or anc["cycle"]:
            roots.append(node)
        else:
            parent["children"].append(node)
    return roots


def trace_rollup(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-trace summary rows, newest wall_start first.

    `duration_ms` prefers the root span's own measurement and says so in
    `duration_from`; with no measured root it falls back to the extent of the
    measured spans (start_offset + duration) and labels THAT. With nothing
    measured at all it is None with `duration_error` — never a zero.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in spans:
        groups.setdefault(s["trace_id"], []).append(s)
    out: list[dict[str, Any]] = []
    for trace_id, rows in groups.items():
        roots = [s for s in rows if s["parent_id"] is None]
        root = (
            min(roots, key=lambda s: (s["start_offset_ms"], s["span_id"]))
            if roots
            else None
        )
        measured = [s for s in rows if s["duration_ms"] is not None]
        duration: float | None = None
        source = None
        if root is not None and root["duration_ms"] is not None:
            duration, source = root["duration_ms"], "root-span"
        elif measured:
            duration = round(
                max(s["start_offset_ms"] + s["duration_ms"] for s in measured), 3
            )
            source = "measured-span-extent"
        walls = [s["wall_start"] for s in rows if s["wall_start"] is not None]
        out.append(
            {
                "trace_id": trace_id,
                "root": root["name"] if root else None,
                "root_error": None if root else "no root span in this window",
                "services": sorted({s["service"] for s in rows}),
                "spans": len(rows),
                "errors": sum(1 for s in rows if s["status"] == STATUS_ERROR),
                "unmeasured": len(rows) - len(measured),
                "duration_ms": duration,
                "duration_from": source,
                "duration_error": None
                if duration is not None
                else f"no measured span in the trace ({_reason_summary(rows)})",
                "wall_start": min(walls) if walls else None,
            }
        )
    out.sort(key=lambda r: (-(r["wall_start"] or 0.0), r["trace_id"]))
    return out


def flame_layout(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate flame graph (icicle): one block per distinct call STACK.

    Spans are folded by their stack path (root>child>grandchild), so 400 calls
    to the same nested helper become one block whose width is their summed time —
    the aggregate view a per-trace waterfall cannot give.

    self_ms is total minus the summed duration of that span's direct children.
    Concurrent children can legitimately exceed their parent's wall duration, so
    a negative remainder is clamped to 0 and COUNTED in `clamped` rather than
    rendered as a negative bar or silently absorbed.
    """
    by_id = _index(spans)
    children: dict[Any, list[dict[str, Any]]] = {}
    for s in spans:
        if s["parent_id"] is not None:
            children.setdefault((s["trace_id"], s["parent_id"]), []).append(s)
    nodes: dict[tuple[str, ...], dict[str, Any]] = {}
    skipped_cycles = skipped_deep = 0
    for s in spans:
        anc = _ancestry(s, by_id)
        if anc["cycle"]:
            skipped_cycles += 1
            continue
        if anc["truncated"]:
            # the stack above _MAX_ANCESTRY is unknown, and folding the span into
            # a SHORTER path would attribute its time to the wrong stack
            skipped_deep += 1
            continue
        path = tuple([by_id[k]["name"] for k in anc["ids"]] + [s["name"]])
        node = nodes.setdefault(
            path,
            {
                "path": list(path),
                "depth": len(path) - 1,
                "calls": 0,
                "measured": 0,
                "unmeasured": 0,
                "total_ms": 0.0,
                "self_ms": 0.0,
                "clamped": 0,
            },
        )
        node["calls"] += 1
        if s["duration_ms"] is None:
            node["unmeasured"] += 1
            continue
        node["measured"] += 1
        node["total_ms"] = round(node["total_ms"] + s["duration_ms"], 3)
        kids = sum(
            c["duration_ms"]
            for c in children.get((s["trace_id"], s["span_id"]), [])
            if c["duration_ms"] is not None
        )
        own = s["duration_ms"] - kids
        if own < 0:
            own = 0.0
            node["clamped"] += 1
        node["self_ms"] = round(node["self_ms"] + own, 3)
    roots = sorted(
        (p for p in nodes if len(p) == 1),
        key=lambda p: (-nodes[p]["total_ms"], p),
    )
    grand_total = round(sum(nodes[p]["total_ms"] for p in roots), 3)
    blocks: list[dict[str, Any]] = []
    if grand_total > 0:
        cursor = 0.0
        for path in roots:
            cursor = _lay_block(path, nodes, cursor, grand_total, blocks)
    return {
        "blocks": blocks,
        "total_ms": grand_total,
        "stacks": len(nodes),
        "skipped_cycles": skipped_cycles,
        "skipped_deep": skipped_deep,
        "layout_error": None
        if grand_total > 0
        else f"no measured span to scale the graph ({_reason_summary(spans)})",
    }


def _lay_block(
    path: tuple[str, ...],
    nodes: dict[tuple[str, ...], dict[str, Any]],
    left: float,
    total: float,
    out: list[dict[str, Any]],
) -> float:
    """Emit one block at `left` percent, then lay its children inside it."""
    node = nodes[path]
    width = 100.0 * node["total_ms"] / total
    out.append(
        {
            **node,
            "left_pct": round(left, 4),
            "width_pct": round(width, 4),
            "label": path[-1],
        }
    )
    kids = sorted(
        (p for p in nodes if len(p) == len(path) + 1 and p[: len(path)] == path),
        key=lambda p: (-nodes[p]["total_ms"], p),
    )
    cursor = left
    for kid in kids:
        cursor = _lay_block(kid, nodes, cursor, total, out)
    return left + width


# ---- family schema ----------------------------------------------------------


def to_diagnostics(
    stats: list[dict[str, Any]],
    *,
    slow_ms: float = DEFAULT_SLOW_MS,
    critical_ms: float = DEFAULT_CRITICAL_MS,
    error_rate_error: float = DEFAULT_ERROR_RATE_ERROR,
) -> list[dict[str, Any]]:
    """Map operation stats onto the family diagnostic schema.

    Latency is judged on p95 (a mean hides the tail that users actually feel):
    >= critical_ms is an error, >= slow_ms a warning. Any error at all is at
    least a warning and becomes an error at/above `error_rate_error`. Operations
    with unmeasured calls emit their own warning naming the reason, so a hole in
    the data is a finding rather than an absence — that is how `--fail-on` can
    gate a latency regression the same way it gates a prose lint finding.
    """
    diags: list[dict[str, Any]] = []
    for st in stats:
        path = f"apm://{st['service']}/{st['name']}"
        p95 = st["p95_ms"]
        if p95 is not None and p95 >= critical_ms:
            diags.append(
                openswap.diagnostic(
                    path=path,
                    line=0,
                    col=0,
                    rule="apm:critical-latency",
                    severity="error",
                    message=(
                        f"{st['name']} p95 {p95:g}ms >= {critical_ms:g}ms critical "
                        f"budget over {st['measured']} calls"
                    ),
                )
            )
        elif p95 is not None and p95 >= slow_ms:
            diags.append(
                openswap.diagnostic(
                    path=path,
                    line=0,
                    col=0,
                    rule="apm:slow",
                    severity="warning",
                    message=(
                        f"{st['name']} p95 {p95:g}ms >= {slow_ms:g}ms budget over "
                        f"{st['measured']} calls"
                    ),
                )
            )
        if st["errors"]:
            rate = st["error_rate"]
            severity = (
                "error" if rate is not None and rate >= error_rate_error else "warning"
            )
            shown = "unknown" if rate is None else f"{100 * rate:.1f}%"
            diags.append(
                openswap.diagnostic(
                    path=path,
                    line=0,
                    col=0,
                    rule="apm:errors",
                    severity=severity,
                    message=f"{st['name']} failed {st['errors']}x ({shown} of measured calls)",
                )
            )
        if st["unmeasured"]:
            diags.append(
                openswap.diagnostic(
                    path=path,
                    line=0,
                    col=0,
                    rule="apm:unmeasured",
                    severity="warning",
                    message=f"{st['name']}: {st['unmeasured_reason']}",
                )
            )
    return openswap.sort_diagnostics(diags)


# ---- the static page (the hosted UI, deleted) --------------------------------

_CSS = """
body { font-family: system-ui, sans-serif; margin: 1.5rem; color: #1c2430; }
h2 { margin-top: 1.6rem; font-size: 1.05rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: .8rem; }
th, td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid #d8dee6;
  vertical-align: top; font-size: .86rem; }
td.n { text-align: right; font-variant-numeric: tabular-nums; }
.mono { font-family: ui-monospace, monospace; font-size: .82em; color: #55606e; }
.track { position: relative; height: 1rem; background: #eef1f5; border-radius: .2rem;
  min-width: 12rem; }
.bar { position: absolute; top: 0; height: 1rem; border-radius: .2rem;
  background: #2b6cb0; min-width: 1px; }
.bar.err { background: #b3261e; }
.none { color: #8a5a00; font-size: .8em; }
.flame { position: relative; height: 1.15rem; margin-bottom: 1px; }
.blk { position: absolute; top: 0; height: 1.15rem; overflow: hidden; color: #fff;
  font-size: .72rem; line-height: 1.15rem; padding-left: .2rem; box-sizing: border-box;
  background: #6b46c1; border-right: 1px solid #fff; white-space: nowrap; }
.blk:nth-child(even) { background: #805ad5; }
footer { margin-top: 1.5rem; color: #55606e; font-size: .8rem; }
"""


def _iso(ts: float | None) -> str:
    """UTC stamp with no locale and no timezone dependence."""
    if ts is None:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(float(ts)))


def _num(value: float | None, reason: str | None = None) -> str:
    """A number, or a labelled gap — never a substituted zero."""
    if value is None:
        note = html.escape(reason or "not measured")
        return f'<span class="none" title="{note}">unmeasured</span>'
    return f"{value:,.3f}".rstrip("0").rstrip(".") or "0"


def _ops_table(stats: list[dict[str, Any]]) -> str:
    e = html.escape
    head = (
        "<tr><th>operation</th><th>calls</th><th>errors</th><th>p50 ms</th>"
        "<th>p95 ms</th><th>p99 ms</th><th>max ms</th><th>total ms</th></tr>"
    )
    rows = [
        "<tr>"
        f'<td><b>{e(st["name"])}</b> <span class="mono">{e(st["service"])}</span></td>'
        f'<td class="n">{st["calls"]}</td>'
        f'<td class="n">{st["errors"]}</td>'
        f'<td class="n">{_num(st["p50_ms"], st["unmeasured_reason"])}</td>'
        f'<td class="n">{_num(st["p95_ms"], st["unmeasured_reason"])}</td>'
        f'<td class="n">{_num(st["p99_ms"], st["unmeasured_reason"])}</td>'
        f'<td class="n">{_num(st["max_ms"], st["unmeasured_reason"])}</td>'
        f'<td class="n">{_num(st["total_ms"], st["unmeasured_reason"])}</td>'
        "</tr>"
        for st in stats
    ]
    body = "\n".join(rows) or '<tr><td colspan="8">no spans recorded</td></tr>'
    return f"<table>{head}{body}</table>"


def _waterfall(spans: list[dict[str, Any]], roll: dict[str, Any]) -> str:
    """One trace as positioned bars; unmeasured spans get a reason, not a bar."""
    e = html.escape
    rows = [s for s in spans if s["trace_id"] == roll["trace_id"]]
    rows.sort(key=lambda s: (s["start_offset_ms"], s["span_id"]))
    span_of_scale = roll["duration_ms"] or 0.0
    out = []
    for s in rows:
        indent = "&nbsp;" * (2 * int(s["depth"]))
        label = f"{indent}{e(s['name'])}"
        if s["duration_ms"] is None:
            cell = f'<span class="none">{e(str(s["error"]))}</span>'
            shown = '<span class="none">unmeasured</span>'
        elif span_of_scale > 0:
            left = 100.0 * s["start_offset_ms"] / span_of_scale
            width = max(0.15, 100.0 * s["duration_ms"] / span_of_scale)
            cls = "bar err" if s["status"] == STATUS_ERROR else "bar"
            cell = (
                f'<div class="track"><div class="{cls}" style="left:{min(left, 100):.4f}%;'
                f'width:{min(width, 100):.4f}%"></div></div>'
            )
            shown = _num(s["duration_ms"])
        else:
            cell = '<span class="none">trace has no measured extent to scale against</span>'
            shown = _num(s["duration_ms"])
        err = (
            f'<div class="mono">{e(str(s["error"]))}</div>'
            if s["error"] and s["duration_ms"] is not None
            else ""
        )
        out.append(
            f'<tr><td class="mono">{label}{err}</td><td>{cell}</td>'
            f'<td class="n">{shown}</td></tr>'
        )
    header = (
        f"<h2>{e(str(roll['root'] or '(no root span)'))} "
        f'<span class="mono">{e(roll["trace_id"])} · {roll["spans"]} spans · '
        f"{_num(roll['duration_ms'], roll['duration_error'])} ms "
        f"({e(str(roll['duration_from'] or 'no measurement'))}) · "
        f"started {e(_iso(roll['wall_start']))}</span></h2>"
    )
    return (
        header
        + "<table><tr><th>span</th><th>timeline</th><th>ms</th></tr>"
        + "\n".join(out)
        + "</table>"
    )


def _flame(layout: dict[str, Any]) -> str:
    e = html.escape
    if not layout["blocks"]:
        return f'<p class="none">{e(str(layout["layout_error"]))}</p>'
    by_depth: dict[int, list[dict[str, Any]]] = {}
    for b in layout["blocks"]:
        by_depth.setdefault(int(b["depth"]), []).append(b)
    rows = []
    for depth in sorted(by_depth):
        blocks = "".join(
            f'<div class="blk" style="left:{b["left_pct"]:.4f}%;width:{b["width_pct"]:.4f}%"'
            f' title="{e(" > ".join(b["path"]))} — total {b["total_ms"]:g}ms, '
            f'self {b["self_ms"]:g}ms, {b["calls"]} calls">{e(b["label"])}</div>'
            for b in by_depth[depth]
        )
        rows.append(f'<div class="flame">{blocks}</div>')
    return "".join(rows)


def render_html(
    spans: list[dict[str, Any]],
    *,
    title: str = "APM — local trace explorer",
    generated_ts: float | None = None,
    apdex_t_ms: float = DEFAULT_APDEX_T_MS,
    max_traces: int = 10,
) -> str:
    """The hosted APM UI as ONE static self-contained page — no JS, no assets.

    Byte-identical for identical input: there is no implicit clock read anywhere
    in here. `generated_ts` is a parameter, and when it is None the page says the
    generation time was not recorded instead of inventing one — which is what
    lets a report be committed next to the data and diffed.
    """
    e = html.escape
    rolls = trace_rollup(spans)
    stats = operation_stats(spans)
    score = apdex(spans, t_ms=apdex_t_ms)
    layout = flame_layout(spans)
    measured = sum(1 for s in spans if s["duration_ms"] is not None)
    waterfalls = "".join(_waterfall(spans, r) for r in rolls[: max(0, int(max_traces))])
    stamp = (
        f"generated {e(_iso(generated_ts))}"
        if generated_ts is not None
        else "generation time not recorded (deterministic render)"
    )
    apdex_cell = (
        f"{score['score']:.4f}"
        if score["score"] is not None
        else f"unmeasured — {e(str(score['score_error']))}"
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<style>{_CSS}</style></head>
<body>
<h1>{e(title)}</h1>
<p>{len(spans)} spans ({measured} measured, {len(spans) - measured} unmeasured) ·
{len(rolls)} traces · apdex(T={apdex_t_ms:g}ms) {apdex_cell} ·
{score["satisfied"]} satisfied / {score["tolerating"]} tolerating /
{score["frustrated"]} frustrated
· fully local — no trace on this page ever left the box</p>
<h2>operations</h2>
{_ops_table(stats)}
<h2>flame (aggregate, {layout["stacks"]} stacks over {layout["total_ms"]:g}ms)</h2>
{_flame(layout)}
{waterfalls}
<footer>{stamp} · durations from time.perf_counter (monotonic); wall clock is
recorded once per trace for "when" only</footer>
</body></html>
"""
