"""Router traces: one JSONL line per routed goal, one more when its run finishes.

These lines are the ONLY input the router training loop accepts
(``scout router pack``). Synthetic rows never train a champion, so every line
says where it came from:

* ``source: production``: a real goal routed by a real surface;
* ``source: test``: written under a test runner. The pack refuses these.

Where: ``~/.dottie/traces/route-YYYYMMDD.jsonl`` (UTC day). ``DOTTIE_TRACE_DIR``
overrides the directory; ``DOTTIE_TRACES=0`` turns tracing off. Under pytest
(``PYTEST_CURRENT_TEST`` set) with no ``DOTTIE_TRACE_DIR``, nothing is written
at all, so a test can never append to the real path.

What: the goal's sha256 and task features (never the text, unless the owner
opts in with ``DOTTIE_TRACE_TEXT=1``), every backend's answer, the
authoritative decision, and later the observed outcome of ``scout harness run``
(success/failure, recovery rung, escalation). Writes never raise: a full disk
must not stop a route.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dottie_loop.hashing import now_iso

TRACE_SCHEMA = "dottie-router-trace-1"
SOURCES = ("production", "test")


def trace_dir() -> Path | None:
    """Directory traces go to, or None when tracing must not write."""
    if os.environ.get("DOTTIE_TRACES", "").strip().lower() in ("0", "false", "off", "no"):
        return None
    env = os.environ.get("DOTTIE_TRACE_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None  # a test never writes the real trace path
    return Path.home() / ".dottie" / "traces"


def trace_source() -> str:
    """production | test. A test runner always tags test, whatever the env claims."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "test"
    env = os.environ.get("DOTTIE_TRACE_SOURCE", "").strip().lower()
    return env if env in SOURCES else "production"


def trace_path(day: datetime | None = None) -> Path | None:
    base = trace_dir()
    if base is None:
        return None
    day = day or datetime.now(UTC)
    return base / f"route-{day.strftime('%Y%m%d')}.jsonl"


def _append(row: dict[str, Any]) -> str | None:
    path = trace_path()
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        return None
    return str(path)


def new_trace_id() -> str:
    return f"rt_{uuid.uuid4().hex[:20]}"


def record_route(
    decision: dict[str, Any],
    *,
    surface: str,
    goal: str,
    features: dict[str, Any],
    context: Any = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append the route line. Returns ``{"trace_id", "path"}`` (path None when not written).

    With a decision ``context`` the line also stores the context summary exactly
    as System One was served it (private texts only under the opt-in) and
    ``state_sha256``, the hash of :func:`dottie_loop.backends.system_one_state`
    for this goal + context, so ``scout router pack`` can rebuild the same state
    and prove it did. ``extra`` adds decision-record fields (latency, cache).
    """
    from dottie_loop.backends import state_sha256, system_one_state, trace_text_enabled
    from dottie_loop.context import context_summary

    trace_id = new_trace_id()
    row: dict[str, Any] = {
        "schema": TRACE_SCHEMA,
        "kind": "route",
        "trace_id": trace_id,
        "at": now_iso(),
        "source": trace_source(),
        "surface": surface,
        "goal_sha256": features.get("goal_sha256"),
        "features": features,
        "backends": decision.get("advisory", {}),
        "decision": {
            "tier": decision.get("moma_tier"),
            "spec_tier": decision.get("spec_tier"),
            "authority": decision.get("authority"),
            "heuristic_tier": decision.get("heuristic_tier"),
            "intent": decision.get("intent"),
            "escalated_from_insufficiency": decision.get("escalated_from_insufficiency", False),
        },
    }
    if trace_text_enabled():
        row["goal_text"] = goal
    summary = context_summary(context)
    if summary is not None:
        row["context"] = summary
        row["state_sha256"] = state_sha256(system_one_state(goal, summary, features=features))
    if extra:
        row["decision_record"] = extra
    return {"trace_id": trace_id, "path": _append(row)}


def record_outcome(trace_id: str | None, outcome: dict[str, Any], *, surface: str) -> str | None:
    """Append the outcome line for an earlier route line. No trace id, no write."""
    if not trace_id:
        return None
    row = {
        "schema": TRACE_SCHEMA,
        "kind": "outcome",
        "trace_id": trace_id,
        "at": now_iso(),
        "source": trace_source(),
        "surface": surface,
        "outcome": outcome,
    }
    return _append(row)


def read_traces(paths: list[Path]) -> tuple[list[dict[str, Any]], int]:
    """Parse trace files; returns (rows, unreadable_line_count). Bad lines are counted, not guessed."""
    rows: list[dict[str, Any]] = []
    bad = 0
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            bad += 1
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(obj, dict) and obj.get("schema") == TRACE_SCHEMA:
                rows.append(obj)
            else:
                bad += 1
    return rows, bad


def join_outcomes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One dict per route line with its outcome (or None) attached."""
    outcomes = {r["trace_id"]: r for r in rows if r.get("kind") == "outcome" and r.get("trace_id")}
    joined = []
    for r in rows:
        if r.get("kind") != "route":
            continue
        o = outcomes.get(r.get("trace_id"))
        joined.append({**r, "outcome": o.get("outcome") if o else None, "outcome_source": o.get("source") if o else None})
    return joined
