"""Run history: per-role / per-run / per-tier aggregates over scout's timeline store.

The store is scout's append-only ``<base>/<run_id>/timeline.jsonl`` (one event
per node attempt; ``bigbang.plugins.harness.timeline.append_event`` writes it).
``scout harness graph-plan``, ``runner.build_plan`` (every plan, in scout and in
jarvisd) and the decision context's run-history provider all read these
aggregates, so they must be cheap on the hot path.

:class:`HistoryIndex` keeps, per timeline file, its ``(size, mtime)`` signature,
the byte offset parsed so far, and that file's partial aggregates. A call
re-stats the known files; a file that grew is resumed from its offset (only
the new tail is parsed), a file that shrank or was rewritten is re-parsed, and
the directory is re-listed only when the base directory's mtime moved (a new
run directory). When no signature changed, the merged result from the last call
is returned as is. The index can persist itself next to the store
(``<base>/.history-index.json``) so a cold process (``scout route``) does not
re-parse every past run either; a persisted index is a cache, validated against
the same signatures, and any read or write failure falls back to parsing.

Torn final lines (a writer mid-append) are left unparsed and retried when the
file grows, exactly as the previous implementation did.

Stdlib only.
"""

from __future__ import annotations

import contextlib
import json
import os
import statistics
import threading
from pathlib import Path
from typing import Any

INDEX_NAME = ".history-index.json"
INDEX_VERSION = 1
FAILURE_STATUSES = frozenset({"fail", "failed", "error", "timeout"})


def default_base() -> Path:
    """scout's checkpoint base: ``SCOUT_CHECKPOINT_BASE`` or ``~/.cache/scout/checkpoints``."""
    env = os.environ.get("SCOUT_CHECKPOINT_BASE", "").strip()
    return Path(env).expanduser() if env else Path.home() / ".cache" / "scout" / "checkpoints"


def _is_failure(row: dict[str, Any]) -> bool:
    return str(row.get("status", "")).lower() in FAILURE_STATUSES


def _latency(row: dict[str, Any]) -> float:
    try:
        return float(row.get("latency", row.get("latency_ms", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _empty_partial() -> dict[str, Any]:
    return {"events": 0, "failures": 0, "roles": {}, "tiers": {}}


def _fold(partial: dict[str, Any], row: dict[str, Any]) -> None:
    """Fold one event into a file's partial aggregates."""
    failed = _is_failure(row)
    lat = _latency(row)
    partial["events"] += 1
    if failed:
        partial["failures"] += 1
    role = str(row.get("agentId", "unknown"))
    rs = partial["roles"].setdefault(role, {"runs": 0, "failures": 0, "error_classes": {}, "latencies": []})
    rs["runs"] += 1
    if failed:
        rs["failures"] += 1
    cls = str(row.get("errorClass", "none"))
    rs["error_classes"][cls] = rs["error_classes"].get(cls, 0) + 1
    rs["latencies"].append(lat)
    tier = row.get("tier")
    if isinstance(tier, str) and tier:
        ts = partial["tiers"].setdefault(tier, {"events": 0, "failures": 0, "retries": 0, "latencies": []})
        ts["events"] += 1
        if failed:
            ts["failures"] += 1
        try:
            if int(row.get("attempt") or 1) > 1:
                ts["retries"] += 1
        except (TypeError, ValueError):
            pass
        ts["latencies"].append(lat)


class HistoryIndex:
    """Incremental aggregates over ``<base>/*/timeline.jsonl``. Thread-safe."""

    def __init__(self, base: Path, *, persist: bool = False) -> None:
        self.base = Path(base)
        self.persist = persist
        self._lock = threading.Lock()
        self._files: dict[str, dict[str, Any]] = {}  # run_id -> {"sig", "offset", "partial"}
        self._base_mtime: float | None = None
        self._merged: dict[str, Any] | None = None
        self._loaded = False

    # -- persistence -----------------------------------------------------------

    def _index_path(self) -> Path:
        return self.base / INDEX_NAME

    def _load(self) -> None:
        self._loaded = True
        if not self.persist:
            return
        try:
            doc = json.loads(self._index_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(doc, dict) or doc.get("version") != INDEX_VERSION or not isinstance(doc.get("files"), dict):
            return
        for run_id, st in doc["files"].items():
            if isinstance(st, dict) and isinstance(st.get("sig"), list) and isinstance(st.get("partial"), dict):
                self._files[run_id] = {"sig": tuple(st["sig"]), "offset": int(st.get("offset", 0)), "partial": st["partial"]}

    def _save(self) -> None:
        if not self.persist:
            return
        doc = {"version": INDEX_VERSION, "files": {k: {"sig": list(v["sig"]), "offset": v["offset"], "partial": v["partial"]} for k, v in self._files.items()}}
        path = self._index_path()
        tmp = path.with_name(f"{INDEX_NAME}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            with contextlib.suppress(OSError):
                tmp.unlink()

    # -- scanning ----------------------------------------------------------------

    def _run_ids(self) -> list[str] | None:
        """Run directories with a timeline, re-listed only when the base mtime moved."""
        try:
            mtime = self.base.stat().st_mtime
        except OSError:
            return []
        if self._base_mtime == mtime and self._merged is not None:
            return None  # same set of run dirs as last time
        self._base_mtime = mtime
        return sorted(p.parent.name for p in self.base.glob("*/timeline.jsonl"))

    def _refresh_file(self, run_id: str) -> bool:
        """Bring one file's partial up to date. Returns True when anything changed."""
        path = self.base / run_id / "timeline.jsonl"
        try:
            st = path.stat()
        except OSError:
            return self._files.pop(run_id, None) is not None
        sig = (st.st_size, st.st_mtime)
        cur = self._files.get(run_id)
        if cur is not None and tuple(cur["sig"]) == sig:
            return False
        if cur is None or not (st.st_size > cur["sig"][0] and st.st_size >= cur["offset"]):
            cur = {"sig": sig, "offset": 0, "partial": _empty_partial()}  # new, shrank or rewritten
        try:
            with path.open("rb") as f:
                f.seek(cur["offset"])
                tail = f.read()
        except OSError:
            return self._files.pop(run_id, None) is not None
        consumed = 0
        for line in tail.split(b"\n"):
            if not line.strip():
                consumed += len(line) + 1
                continue
            try:
                row = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                break  # torn / undecodable line: leave the offset before it, retry on growth
            if isinstance(row, dict):
                _fold(cur["partial"], row)
            consumed += len(line) + 1
        cur["offset"] += min(consumed, len(tail))
        cur["sig"] = sig
        self._files[run_id] = cur
        return True

    def _merge(self) -> dict[str, Any]:
        per_role: dict[str, dict[str, Any]] = {}
        per_run: dict[str, dict[str, Any]] = {}
        per_tier: dict[str, dict[str, Any]] = {}
        role_lat: dict[str, list[float]] = {}
        tier_lat: dict[str, list[float]] = {}
        total = 0
        for run_id in sorted(self._files):
            p = self._files[run_id]["partial"]
            if not p["events"]:
                continue
            total += p["events"]
            per_run[run_id] = {"events": p["events"], "failures": p["failures"]}
            for role, rs in p["roles"].items():
                agg = per_role.setdefault(role, {"runs": 0, "failures": 0, "error_classes": {}})
                agg["runs"] += rs["runs"]
                agg["failures"] += rs["failures"]
                for cls, n in rs["error_classes"].items():
                    agg["error_classes"][cls] = agg["error_classes"].get(cls, 0) + n
                role_lat.setdefault(role, []).extend(rs["latencies"])
            for tier, ts in p["tiers"].items():
                agg = per_tier.setdefault(tier, {"runs": 0, "events": 0, "failures": 0, "retries": 0, "failed_runs": 0})
                agg["runs"] += 1
                agg["events"] += ts["events"]
                agg["failures"] += ts["failures"]
                agg["retries"] += ts["retries"]
                agg["failed_runs"] += 1 if ts["failures"] else 0
                tier_lat.setdefault(tier, []).extend(ts["latencies"])
        for role, rs in per_role.items():
            lats = role_lat.get(role, [])
            rs["fail_rate"] = round(rs["failures"] / rs["runs"], 4) if rs["runs"] else 0.0
            rs["p50_latency"] = statistics.median(lats) if lats else 0.0
        for tier, ts in per_tier.items():
            lats = tier_lat.get(tier, [])
            ts["success_rate"] = round(1.0 - ts["failed_runs"] / ts["runs"], 4) if ts["runs"] else 0.0
            ts["recovery_rate"] = round(ts["retries"] / ts["events"], 4) if ts["events"] else 0.0
            ts["p50_latency"] = statistics.median(lats) if lats else 0.0
        return {"events": total, "per_role": per_role, "per_run": per_run, "per_tier": per_tier}

    def stats(self) -> dict[str, Any]:
        """``{"events", "per_role", "per_run", "per_tier"}``. Treat the result as read-only."""
        with self._lock:
            if not self._loaded:
                self._load()
            listed = self._run_ids()
            changed = False
            if listed is not None:
                for gone in set(self._files) - set(listed):
                    del self._files[gone]
                    changed = True
                run_ids = listed
            else:
                run_ids = sorted(self._files)
            for run_id in run_ids:
                changed = self._refresh_file(run_id) or changed
            if changed or self._merged is None:
                self._merged = self._merge()
                if changed:
                    self._save()
            return self._merged


_INDEXES: dict[tuple[str, bool], HistoryIndex] = {}
_INDEXES_LOCK = threading.Lock()


def index_for(base: Path | None = None, *, persist: bool | None = None) -> HistoryIndex:
    """The process-wide index for ``base`` (default: scout's checkpoint base, persisted)."""
    b = Path(base) if base is not None else default_base()
    if persist is None:
        # persist the default store's index, but never under a test runner that
        # did not point SCOUT_CHECKPOINT_BASE somewhere (same rule as traces)
        under_test = bool(os.environ.get("PYTEST_CURRENT_TEST")) and not os.environ.get("SCOUT_CHECKPOINT_BASE")
        persist = base is None and not under_test
    p = persist
    key = (str(b.resolve() if b.exists() else b), p)
    with _INDEXES_LOCK:
        idx = _INDEXES.get(key)
        if idx is None:
            idx = _INDEXES[key] = HistoryIndex(b, persist=p)
        return idx


def history_stats(base: Path | None = None) -> dict[str, Any]:
    """Aggregates for ``base`` via the cached index (see :class:`HistoryIndex`)."""
    return index_for(base).stats()
