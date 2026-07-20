# Solo personal project, no connection to employer, built with public/free-tier only
"""Bridge to the shared J-Space state store (packages/ava-skills, skills.state_store).

The SAME SQLite file scout's Hermes/OpenClaw profiles read and write (default
``~/.dottie-claw/state/jspace_state.sqlite3``, override ``DOTTIE_STATE_DB``) — one
brain across surfaces: a task started via scout is visible to the engine's session
context and vice versa (channels: ``cli`` for scout, ``engine`` here).

Honest degradation: when ava-skills is not resolvable this returns None and the
engine runs exactly as before — persistence is an enhancement, never a dependency,
and its absence is recorded in the trace (``jspace_state: unavailable``).
"""

from __future__ import annotations

import sys
from typing import Any

from dottie import resolve

CHANNEL = "engine"


def shared_store():
    """A JSpaceStateStore on the shared DB, or None (honest) when unresolvable."""
    try:
        from skills.state_store import JSpaceStateStore
    except ImportError:
        try:
            root = str(resolve.skills_root())
            if root not in sys.path:
                sys.path.insert(0, root)
            from skills.state_store import JSpaceStateStore
        except Exception:
            return None
    try:
        return JSpaceStateStore()
    except Exception:
        return None


def record_task(
    session_id: str, task: str, outcome: str, *, trace: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Log the run + update cross-channel re-entry state. Returns what happened."""
    store = shared_store()
    if store is None:
        return {"persistence": "unavailable"}
    with store:
        store.log_task(session_id, task, outcome, trace=trace)
        store.set_context(session_id, "last_task", task, channel=CHANNEL)
        store.set_context(session_id, "last_outcome", outcome, channel=CHANNEL)
    return {"persistence": "on", "channel": CHANNEL}


def session_context(session_id: str) -> dict[str, Any] | None:
    """All channels' persisted state for a session (what an OpenClaw loop re-enters
    with) — None when the store is unavailable."""
    store = shared_store()
    if store is None:
        return None
    with store:
        return store.session_snapshot(session_id)
