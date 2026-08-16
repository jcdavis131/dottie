"""status.py — publish rlm_status.json for the site (SPEC v1). Atomic.

``publish_status(registry, path, harness=None)`` writes::

    {"published_utc": iso, "source": "local",
     "sessions": [{"id", "role", "state", "turns", "last_active"}, ...],
     "refinements": <last 20 folded ledger entries>}

Resolved SPEC-vs-module points (coded against the modules):

- SPEC writes the signature as ``publish_status(registry, path)`` but the
  refinement ledger lives on the Harness, which the registry does not know.
  ``harness`` is an optional third argument; without it ``refinements`` is
  ``[]`` (honest: no ledger was consulted, nothing is fabricated).
- Registry index entries carry no role/turn count, so both are read from the
  session's own on-disk state under ``registry.root/<id>/``: role from
  session.json (guarded read — corrupt is preserved + loud, never guessed),
  turns as the trajectory.jsonl line count (live truth; the meta's saved
  count can lag live appends). A session directory that never materialized
  reports ``role=None, turns=0``.
- Atomic write via session.py's inline atomic contract (atomic.py never
  landed; registry.py imports from session.py too).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .session import (
    META_NAME,
    TRAJECTORY_NAME,
    atomic_write_json,
    read_json_guarded,
    read_jsonl_guarded,
)

if TYPE_CHECKING:
    from .harness import Harness
    from .registry import SessionRegistry

__all__ = ["REFINEMENTS_TAIL", "build_status", "collect_sessions", "publish_status"]

#: How many trailing ledger entries the site page gets (SPEC: last 20).
REFINEMENTS_TAIL = 20


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def collect_sessions(registry: SessionRegistry) -> list[dict]:
    """One row per indexed session: id, role, state, turns, last_active."""
    rows: list[dict] = []
    for entry in registry.entries():
        sid = entry["id"]
        sdir = registry.root / sid
        role = None
        meta_path = sdir / META_NAME
        if meta_path.exists():
            meta = read_json_guarded(meta_path)  # corrupt → preserve + raise, LOUD
            if isinstance(meta, dict):
                role = meta.get("role")
        turns = len(read_jsonl_guarded(sdir / TRAJECTORY_NAME))  # missing → 0
        rows.append(
            {
                "id": sid,
                "role": role,
                "state": entry.get("state"),
                "turns": turns,
                "last_active": entry.get("last_active_utc"),
            }
        )
    return rows


def build_status(
    registry: SessionRegistry,
    harness: Harness | None = None,
    *,
    refinements_tail: int = REFINEMENTS_TAIL,
) -> dict:
    """The status payload. ``source`` is always ``"local"`` — this module
    only ever reports numbers read from local published state (SPEC)."""
    refinements: list[dict] = []
    if harness is not None:
        ledger = harness.ledger()
        refinements = ledger[-int(refinements_tail):] if refinements_tail > 0 else []
    return {
        "published_utc": _utc_now(),
        "source": "local",
        "sessions": collect_sessions(registry),
        "refinements": refinements,
    }


def publish_status(
    registry: SessionRegistry,
    path: str | Path,
    harness: Harness | None = None,
    *,
    refinements_tail: int = REFINEMENTS_TAIL,
) -> dict:
    """Build the payload and atomically write it to ``path``. Returns it."""
    payload = build_status(registry, harness, refinements_tail=refinements_tail)
    atomic_write_json(Path(path), payload)
    return payload
