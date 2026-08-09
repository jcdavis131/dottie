"""
harness timeline — append-only timeline.jsonl store + offset-indexed streaming stats.

Store layout (per run, under the checkpoint base):

    <base>/<run_id>/timeline.jsonl       append-only event records (v3.3 schema)
    <base>/<run_id>/timeline.idx.jsonl   one index line per event: byte offset + hot fields

`g_history_stats` mines every run's timeline into per-role failure rates that feed
graph-plan's failureRisk. Parsing is streaming: a module cache keyed on
(size, mtime) remembers the last byte offset parsed per file, so a growing file is
resumed from its tail rather than re-read. Torn final lines (a writer mid-append)
are skipped silently and re-attempted on the next growth.

stdlib only: json, os, time, statistics, pathlib.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

# Must match the v3.3 schema pinned in cli.py checkpoint_cmd / ops_cmd.
REQUIRED_FIELDS = ["nodeId", "agentId", "attempt", "latency", "tokens", "status", "errorClass"]

_FAILURE_STATUSES = {"fail", "failed", "error", "timeout"}

# str(timeline_path) -> ((size, mtime), {"offset": bytes_parsed, "events": [rows...]})
_CACHE: dict[str, tuple[tuple[int, float], dict]] = {}


def default_base() -> Path:
    return Path.home() / ".cache" / "scout" / "checkpoints"


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
    with open(timeline_path, "a", encoding="utf-8") as f:
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
    with open(idx_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(idx_line) + "\n")
    return {"ok": True, "run_id": run_id, "offset": offset, "path": str(timeline_path)}


def _is_failure(row: dict) -> bool:
    status = str(row.get("status", "")).lower()
    return status in _FAILURE_STATUSES


def _latency(row: dict) -> float:
    return row.get("latency", row.get("latency_ms", 0))


def _tokens(row: dict) -> int:
    return row.get("tokens", row.get("tokens_est", 0))


def _read_events(path: Path) -> list:
    """Streaming read with (size, mtime) cache: resume from the last parsed byte offset."""
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        _CACHE.pop(key, None)
        return []
    sig = (st.st_size, st.st_mtime)
    cached = _CACHE.get(key)
    state = None
    if cached is not None:
        cached_sig, cached_state = cached
        if cached_sig == sig:
            return cached_state["events"]
        if st.st_size > cached_sig[0] and st.st_size >= cached_state["offset"]:
            # Grown (mtime moved): resume from the previously indexed byte offset
            # and parse only the new tail lines.
            state = cached_state
        # else: shrank, or same size with a different mtime — full re-parse.
    if state is None:
        state = {"offset": 0, "events": []}
    with open(path, "rb") as f:
        f.seek(state["offset"])
        tail = f.read()
    consumed = 0
    for line in tail.split(b"\n"):
        if not line.strip():
            consumed += len(line) + 1
            continue
        try:
            row = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            # Torn/undecodable final line — leave the offset before it and retry next pass.
            break
        state["events"].append(row)
        consumed += len(line) + 1
    state["offset"] += min(consumed, len(tail))
    _CACHE[key] = (sig, state)
    return state["events"]


def g_history_stats(base: Path | None = None) -> dict:
    """Mine every run's timeline.jsonl into per-role / per-run aggregates."""
    base = base or default_base()
    per_role: dict[str, dict] = {}
    per_run: dict[str, dict] = {}
    role_latencies: dict[str, list] = {}
    total = 0
    for timeline_path in sorted(base.glob("*/timeline.jsonl")):
        run_id = timeline_path.parent.name
        events = _read_events(timeline_path)
        if not events:
            continue
        run_stats = per_run.setdefault(run_id, {"events": 0, "failures": 0})
        for row in events:
            total += 1
            run_stats["events"] += 1
            failed = _is_failure(row)
            if failed:
                run_stats["failures"] += 1
            role = str(row.get("agentId", "unknown"))
            rs = per_role.setdefault(role, {"runs": 0, "failures": 0, "error_classes": {}})
            rs["runs"] += 1
            if failed:
                rs["failures"] += 1
            cls = str(row.get("errorClass", "none"))
            rs["error_classes"][cls] = rs["error_classes"].get(cls, 0) + 1
            role_latencies.setdefault(role, []).append(float(_latency(row) or 0))
    for role, rs in per_role.items():
        lats = role_latencies.get(role, [])
        rs["fail_rate"] = round(rs["failures"] / rs["runs"], 4) if rs["runs"] else 0.0
        rs["p50_latency"] = statistics.median(lats) if lats else 0.0
    return {"events": total, "per_role": per_role, "per_run": per_run}


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
