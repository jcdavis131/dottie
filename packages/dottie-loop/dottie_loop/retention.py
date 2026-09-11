"""Retention schedule and expiry jobs (spec §17 "Retention schedule requirements").

Separate windows per data class; expiry is deterministic, idempotent, observable,
and tested against legal holds and deletion requests. Windows are DATA so policy
changes are config edits.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import new_id, now_iso, parse_iso

#: data class -> retention window in days (None = long-lived, never auto-expired)
RETENTION_WINDOWS: dict[str, int | None] = {
    "raw_capture": 30,
    "redacted_operational_trace": 180,
    "curated_dataset": 365,
    "rejected_quarantined": 14,
    "model_artifact": 365,
    "approval_release_evidence": None,
    "sandbox_output": 7,
}


def expire(records: list[dict[str, Any]], *, now: datetime | None = None, legal_holds: set[str] | None = None, deletion_requests: set[str] | None = None, windows: dict[str, int | None] | None = None) -> dict[str, Any]:
    """Deterministic, idempotent expiry pass.

    Each record needs ``record_id``, ``data_class``, ``created_at`` and optionally
    ``tombstoned``, ``deletion_key``. Returns tombstone ids and a receipt; running
    the pass twice on its own output changes nothing.
    """
    now = now or datetime.now(UTC)
    holds = legal_holds or set()
    requests = deletion_requests or set()
    win = {**RETENTION_WINDOWS, **(windows or {})}
    tombstoned: list[str] = []
    held: list[str] = []
    expedited: list[str] = []
    kept: list[str] = []
    for r in sorted(records, key=lambda x: x["record_id"]):
        cls = r.get("data_class")
        if cls not in win:
            raise InvalidInputError(f"unknown data class {cls!r}", field="data_class")
        if r.get("tombstoned"):
            continue  # idempotent: already expired
        if r.get("deletion_key") in holds or r["record_id"] in holds:
            held.append(r["record_id"])
            continue
        if r.get("deletion_key") in requests:
            r["tombstoned"] = True
            r["tombstoned_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            r["reason"] = "deletion_request"
            tombstoned.append(r["record_id"])
            expedited.append(r["record_id"])
            continue
        days = win[cls]
        if days is None:
            kept.append(r["record_id"])
            continue
        if parse_iso(r["created_at"]) + timedelta(days=days) <= now:
            r["tombstoned"] = True
            r["tombstoned_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            r["reason"] = "retention_window"
            tombstoned.append(r["record_id"])
        else:
            kept.append(r["record_id"])
    return {"receipt_id": new_id("ret_"), "tombstoned": tombstoned, "expedited_by_deletion_request": expedited, "held": held, "kept": kept, "counts": {"tombstoned": len(tombstoned), "held": len(held), "kept": len(kept)}, "windows": win, "at": now_iso()}
