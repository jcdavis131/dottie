"""
harness timeline — append-only timeline.jsonl store + offset-indexed streaming stats.

Store layout (per run, under the checkpoint base):

    <base>/<run_id>/timeline.jsonl       append-only event records (v3.3 schema)
    <base>/<run_id>/timeline.idx.jsonl   one index line per event: byte offset + hot fields

`g_history_stats` mines every run's timeline into per-role failure rates that feed
graph-plan's failureRisk. It is served by ``dottie_loop.run_history.HistoryIndex``:
per file, a (size, mtime) signature, the byte offset parsed so far and that file's
partial aggregates, so a growing file is resumed from its tail, an unchanged store
costs one stat per run, and the merged result is reused until something changes.
Torn final lines (a writer mid-append) are skipped and re-attempted on growth.

``SCOUT_CHECKPOINT_BASE`` overrides the base (default ~/.cache/scout/checkpoints).
"""
from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Must match the v3.3 schema pinned in cli.py checkpoint_cmd / ops_cmd.
REQUIRED_FIELDS = ["nodeId", "agentId", "attempt", "latency", "tokens", "status", "errorClass"]



def default_base() -> Path:
    """``SCOUT_CHECKPOINT_BASE`` or ~/.cache/scout/checkpoints (one definition, in dottie_loop)."""
    from dottie_loop.run_history import default_base as _base

    return _base()


def append_event(run_id: str, record: dict, base: Path | None = None) -> dict:
    """Append one event to <base>/<run_id>/timeline.jsonl + its offset index. Never raises."""
    if not run_id:
        return {"ok": False, "error": "run_id required"}
    missing = sorted(f for f in REQUIRED_FIELDS if f not in record)
    if missing:
        return {"ok": False, "error": f"missing fields: {', '.join(missing)}"}
    base = base or default_base()
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    timeline_path = run_dir / "timeline.jsonl"
    idx_path = run_dir / "timeline.idx.jsonl"
    with timeline_path.open("a", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        offset = f.tell()
        f.write(json.dumps(record) + "\n")
    idx_line = {
        "offset": offset,
        "ts": time.time(),
        "agentId": record.get("agentId"),
        "status": record.get("status"),
        "errorClass": record.get("errorClass"),
    }
    with idx_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(idx_line) + "\n")
    return {"ok": True, "run_id": run_id, "offset": offset, "path": str(timeline_path)}


def g_history_stats(base: Path | None = None) -> dict:
    """Mine every run's timeline.jsonl into per-role / per-run (and per-tier) aggregates.

    Served by :mod:`dottie_loop.run_history`: an incremental, (size, mtime) +
    byte-offset indexed cache, so a plan no longer re-reads every past run.
    Same keys as before (``events``, ``per_role``, ``per_run``) plus
    ``per_tier``. The default base's index is also persisted next to the store
    for cold processes. Treat the result as read-only.
    """
    from dottie_loop.run_history import history_stats

    return history_stats(base)


def g_history_summary(stats: dict) -> str | None:
    """One-line G_history summary for graph memory; None when nothing has been mined."""
    events = stats.get("events", 0)
    if not events:
        return None
    error_counts: dict[str, int] = {}
    for rs in stats.get("per_role", {}).values():
        for cls, n in rs.get("error_classes", {}).items():
            if cls != "none":
                error_counts[cls] = error_counts.get(cls, 0) + n
    top = max(error_counts, key=lambda c: error_counts[c]) if error_counts else "none"
    runs = len(stats.get("per_run", {}))
    return f"mined {events} events across {runs} runs; top errorClass={top}"
