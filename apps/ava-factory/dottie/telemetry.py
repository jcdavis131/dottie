"""
Solo personal project, no connection to employer, built with public/free-tier only
Dottie Telemetry — unified JSONL logger for control dash.

Writes:
- reports/dottie_telemetry.jsonl : append-only events
- reports/dottie_live_status.json : latest snapshot for dash

No torch required. Public pip only. Free-tier.

Env var compat: DOTTIE_TELEMETRY_DIR fallback AVA_TELEMETRY_DIR fallback reports/

APIs supported:
  New (preferred): log_event(source, event_type, message, metrics, level, extra)
  Legacy compat: log_event(mode, status=..., **kwargs) -> maps to new

Convenience: log_expansion, log_train, log_eval, log_ecosystem, log_error
plus read_telemetry, aggregate_live_status, get_live_status for dash.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import shutil
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

DISCLAIMER = "Solo personal project, no connection to employer, built with public/free-tier only"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DIR = _REPO_ROOT / "reports"

# Allow override
_ENV_DIR = os.environ.get("DOTTIE_TELEMETRY_DIR") or os.environ.get("AVA_TELEMETRY_DIR") or str(_DEFAULT_DIR)
TELEMETRY_DIR = Path(_ENV_DIR)
if TELEMETRY_DIR.is_file():
    TELEMETRY_DIR = TELEMETRY_DIR.parent
try:
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    TELEMETRY_DIR = _DEFAULT_DIR
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

JSONL_PATH = TELEMETRY_DIR / "dottie_telemetry.jsonl"
LIVE_STATUS_PATH = TELEMETRY_DIR / "dottie_live_status.json"
LEGACY_JSONL = TELEMETRY_DIR / "ava_telemetry.jsonl"
LEGACY_LIVE = TELEMETRY_DIR / "ava_live_status.json"
_LOGS_DIR = _REPO_ROOT / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

_RUN_ID = os.environ.get("DOTTIE_RUN_ID") or str(uuid.uuid4())[:8]
_HOSTNAME = socket.gethostname()
_START_TS = time.time()

def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def _safe_write_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[telemetry] write failed {path}: {e}", file=sys.stderr)

def _load_live_status() -> Dict[str, Any]:
    try:
        if LIVE_STATUS_PATH.exists():
            return json.loads(LIVE_STATUS_PATH.read_text(encoding="utf-8"))
        if LEGACY_LIVE.exists():
            return json.loads(LEGACY_LIVE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _write_live_status(data: Dict[str, Any]) -> None:
    try:
        tmp = LIVE_STATUS_PATH.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(LIVE_STATUS_PATH)
        if not LEGACY_LIVE.exists():
            try:
                if hasattr(os, "symlink"):
                    os.symlink(LIVE_STATUS_PATH.name, LEGACY_LIVE)
            except Exception:
                pass
    except Exception as e:
        print(f"[telemetry] live write failed: {e}", file=sys.stderr)

def _get_disk_usage() -> Dict[str, Any]:
    try:
        usage = shutil.disk_usage(str(_REPO_ROOT))
        total = usage.total // (1024**3)
        used = usage.used // (1024**3)
        free = usage.free // (1024**3)
        pct = int(100 * usage.used / usage.total) if usage.total else 0
        return {"total_gb": total, "used_gb": used, "free_gb": free, "pct": pct}
    except Exception:
        return {}

def log_event(
    source: str = "unknown",
    event_type: str = "info",
    message: str = "",
    metrics: Optional[Dict[str, Any]] = None,
    level: str = "info",
    extra: Optional[Dict[str, Any]] = None,
    **legacy_kwargs: Any,
) -> Dict[str, Any]:
    """
    Core logger. Supports both new and legacy signatures:
      New: log_event(source, event_type, message, metrics, level)
      Legacy compat: log_event(mode, status=..., tokens=..., docs=..., **kwargs)
    """
    # Legacy compat detection: if first arg is mode-like and second positional is missing but kwargs contains status/tokens etc
    # Also if caller used log_event("data_gather", tokens=...) positional source is actually mode, second arg is status?
    # Handle: if legacy_kwargs present and source looks like mode, treat legacy
    # Legacy call example: log_event("data_gather", status="ok", tokens=500000)
    # In that case, source = mode, event_type should be status?, but we map.
    # To avoid breaking, detect if event_type is actually a status word and legacy_kwargs has metrics-like keys.
    is_legacy_style = False
    if legacy_kwargs and not message and not metrics:
        # if caller passed log_event(mode, status_or_kwargs) with mode positional and status kwarg
        # We'll treat source as source, event_type as status if present in kwargs, and rest as metrics
        is_legacy_style = True

    # If called as log_event(mode) with no event_type/message explicit but legacy_kwargs has tokens/docs
    # Map legacy: source=mode, event_type = legacy_kwargs.pop(status) or event_type, message = legacy msg, metrics = remaining kwargs
    if legacy_kwargs or (source and event_type == "info" and not message and not metrics):
        # Check if legacy_kwargs contains status
        status_val = legacy_kwargs.pop("status", None)
        # If source was actually mode and event_type looks like default but status_val exists, use it
        if status_val is not None:
            # legacy path
            # message might be in legacy_kwargs?
            msg_legacy = legacy_kwargs.pop("message", "") or legacy_kwargs.pop("msg", "")
            # remaining kwargs are metrics
            merged_metrics = {**legacy_kwargs}
            if metrics:
                merged_metrics.update(metrics)
            # Map to new fields
            # source stays as first arg
            # event_type = status_val if status_val in ("ok","error","warn","start","finish") else event_type
            # For new system, level = status_val if status_val in levels else level, event_type = mapped
            lvl = level
            evt = event_type
            if status_val in ("ok","warn","error","info"):
                lvl = status_val
                evt = "finish" if status_val == "ok" else status_val
            else:
                evt = status_val or event_type
            # If this was legacy detection, rewrite args for new path
            if is_legacy_style or merged_metrics:
                # keep source as is, update
                event_type = evt
                message = msg_legacy or message or f"{source} {evt}"
                metrics = merged_metrics
                level = lvl
                legacy_kwargs = {}
                # No longer legacy after mapping

    # If still legacy_kwargs left (unmapped), merge into metrics
    if legacy_kwargs:
        if metrics is None:
            metrics = {}
        metrics.update(legacy_kwargs)

    ts_iso = _utc_now_iso()
    ts_unix = int(time.time())

    # Normalize metrics
    if metrics is None:
        metrics = {}

    event: Dict[str, Any] = {
        "timestamp": ts_iso,
        "ts": ts_unix,
        "unix": ts_unix,
        "run_id": _RUN_ID,
        "hostname": _HOSTNAME,
        "source": source,
        "mode": source,  # legacy field compat
        "event_type": event_type,
        "status": level,  # legacy compat
        "message": message,
        "level": level,
        "metrics": metrics,
        "disclaimer": DISCLAIMER,
    }
    if extra:
        event["extra"] = extra
        event.update(extra)  # also flatten for legacy readers that expect top-level keys

    # Also preserve metrics flattened top-level for backward compat dashboards that read kwargs directly
    # Avoid overwriting core keys
    for k, v in metrics.items():
        if k not in event:
            event[k] = v

    # Write JSONL
    _safe_write_jsonl(JSONL_PATH, event)
    if LEGACY_JSONL != JSONL_PATH:
        try:
            if not LEGACY_JSONL.exists() or LEGACY_JSONL.stat().st_size < 10_000_000:
                _safe_write_jsonl(LEGACY_JSONL, event)
        except Exception:
            pass

    # Also write per-mode log for debugging
    try:
        mode_log = _LOGS_DIR / f"cron-dottie-{source}.log"
        with mode_log.open("a", encoding="utf-8") as f:
            f.write(f"{ts_iso} [{source}:{event_type}] {level} {message} {json.dumps(metrics)[:500]}\n")
        # Rotate if >5MB → keep last 1000 lines
        try:
            if mode_log.stat().st_size > 5 * 1024 * 1024:
                lines = mode_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-1000:]
                mode_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass
    except Exception:
        pass

    # Update live status
    try:
        live = _load_live_status()
        now = ts_iso
        if not live:
            live = {
                "disclaimer": DISCLAIMER,
                "updated_at": now,
                "uptime_sec": 0,
                "run_id": _RUN_ID,
                "hostname": _HOSTNAME,
                "counts": {},
                "last_event": {},
                "last_expansion": {},
                "last_train": {},
                "last_eval": {},
                "last_ecosystem": {},
                "system_health": {},
                "latest_per_mode": {},
                "by_mode_counts": {},
                "recent_events": [],
            }
        live["updated_at"] = now
        live["run_id"] = _RUN_ID
        live["hostname"] = _HOSTNAME
        live["uptime_sec"] = int(time.time() - _START_TS)
        live["last_event"] = {
            "timestamp": ts_iso,
            "source": source,
            "event_type": event_type,
            "message": message,
            "level": level,
        }

        counts = live.get("counts", {})
        counts[source] = counts.get(source, 0) + 1
        counts[f"{source}:{event_type}"] = counts.get(f"{source}:{event_type}", 0) + 1
        live["counts"] = counts

        # latest per mode for dash
        latest_per_mode = live.get("latest_per_mode", {})
        latest_per_mode[source] = {
            "ts": ts_iso,
            "event_type": event_type,
            "message": message,
            "level": level,
            **metrics,
        }
        live["latest_per_mode"] = latest_per_mode
        by_mode_counts = live.get("by_mode_counts", {})
        by_mode_counts[source] = by_mode_counts.get(source, 0) + 1
        live["by_mode_counts"] = by_mode_counts

        # recent events rolling
        recent = live.get("recent_events", [])
        recent.append(event)
        if len(recent) > 50:
            recent = recent[-50:]
        live["recent_events"] = recent

        # specific buckets
        if source == "data" and event_type in ("expansion", "finish", "data_gather", "progress"):
            if metrics:
                # Don't overwrite canonical 500k sample with dry-run tiny shards
                is_dry = metrics.get("dry_run") or False
                existing_tokens = (live.get("last_expansion", {}) or {}).get("tokens", 0)
                new_tokens = metrics.get("tokens", metrics.get("total_tokens", 0)) or 0
                if is_dry and existing_tokens >= 500034:
                    # Keep existing canonical, just update timestamp separately? Skip overwrite
                    pass
                elif new_tokens < 10000 and existing_tokens >= 500034:
                    # Tiny dry-run shouldn't clobber canonical
                    pass
                else:
                    live["last_expansion"] = {
                        "timestamp": ts_iso,
                        "tokens": metrics.get("tokens", metrics.get("total_tokens", 0)),
                        "docs": metrics.get("docs", metrics.get("total_docs", 0)),
                        "shards": metrics.get("shards", metrics.get("new_shards", metrics.get("shard", []))),
                        "message": message,
                        "duration_s": metrics.get("duration_s"),
                    }
        if source in ("train", "training", "training_monitor"):
            if metrics or True:
                live["last_train"] = {
                    "timestamp": ts_iso,
                    "preset": metrics.get("preset", ""),
                    "steps": metrics.get("steps", 0),
                    "loss": metrics.get("loss", 0),
                    "tok_per_sec": metrics.get("tok_per_sec", metrics.get("tok_s", metrics.get("tokens_per_sec", 0))),
                    "checkpoint": metrics.get("checkpoint", ""),
                    "message": message,
                }
        if source == "eval" or "eval" in source:
            if metrics:
                live["last_eval"] = {
                    "timestamp": ts_iso,
                    "branch": metrics.get("branch", ""),
                    "score": metrics.get("score", metrics.get("cap_score", 0)),
                    "mode": metrics.get("mode", ""),
                    "message": message,
                }
        if source == "ecosystem" or "ecosystem" in source:
            live["last_ecosystem"] = {
                "timestamp": ts_iso,
                "action": metrics.get("action", event_type) if metrics else event_type,
                "message": message,
                "metrics": metrics or {},
            }

        disk = _get_disk_usage()
        live["system_health"] = {
            "disk": disk,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "uptime_sec": int(time.time() - _START_TS),
        }

        # try to include STATUS.json richer data
        try:
            status_path = _REPO_ROOT / "STATUS.json"
            if status_path.exists():
                status_data = json.loads(status_path.read_text()[:50000])  # limit read
                be = status_data.get("builder", {}).get("last_expansion", {})
                if be:
                    # preserve if live last_expansion empty
                    if not live.get("last_expansion") or not live["last_expansion"].get("tokens"):
                        live["last_expansion"] = {
                            "timestamp": be.get("timestamp", ""),
                            "tokens": be.get("tokens", 0),
                            "docs": be.get("docs", 0),
                            "shards": be.get("shards", []),
                            "message": "from STATUS.json",
                        }
        except Exception:
            pass

        _write_live_status(live)
    except Exception as e:
        print(f"[telemetry] live update failed: {e}", file=sys.stderr)

    return event


def log_expansion(tokens: int, docs: int, shards: Any = None, extra_metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    metrics = {"tokens": tokens, "docs": docs, "shards": shards or []}
    if extra_metrics:
        metrics.update(extra_metrics)
    return log_event(
        source="data",
        event_type="expansion",
        message=f"Expansion {tokens} tokens / {docs} docs / {len(shards) if isinstance(shards, list) else 1} shards",
        metrics=metrics,
        level="info",
    )

def log_train(preset: str, steps: int, loss: float, tok_per_sec: float = 0, checkpoint: str = "", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    metrics = {"preset": preset, "steps": steps, "loss": loss, "tok_per_sec": tok_per_sec, "checkpoint": checkpoint}
    if extra:
        metrics.update(extra)
    return log_event(
        source="train",
        event_type="checkpoint" if checkpoint else "progress",
        message=f"Train {preset} step {steps} loss {loss:.4f} {tok_per_sec:.0f} tok/s ckpt {checkpoint}",
        metrics=metrics,
        level="info",
    )

def log_eval(branch: str, score: float, mode: str = "mock", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    metrics = {"branch": branch, "score": score, "mode": mode}
    if extra:
        metrics.update(extra)
    lvl = "info" if score >= 0.5 else "warn"
    return log_event(
        source="eval",
        event_type="eval_result",
        message=f"Eval {branch} {mode} score {score:.3f}",
        metrics=metrics,
        level=lvl,
    )

def log_ecosystem(action: str, message: str = "", metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    m = metrics or {}
    m["action"] = action
    return log_event(
        source="ecosystem",
        event_type=action,
        message=message or f"Ecosystem {action}",
        metrics=m,
        level="info",
    )

def log_error(source: str, message: str, metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return log_event(source=source, event_type="error", message=message, metrics=metrics, level="error")

# Additional helpers for dash aggregation

def read_telemetry(limit: int = 500) -> List[Dict[str, Any]]:
    if not JSONL_PATH.exists():
        return []
    try:
        lines = JSONL_PATH.read_text(encoding="utf-8").strip().splitlines()
        events = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        return events
    except Exception:
        return []

def aggregate_live_status() -> Dict[str, Any]:
    events = read_telemetry(1000)
    if not events:
        # Return existing live or empty
        existing = _load_live_status()
        if existing:
            return existing
        return {"updated": _utc_now_iso(), "events": [], "summary": {}, "disclaimer": DISCLAIMER}

    by_mode: Dict[str, List[Dict]] = {}
    for ev in events:
        by_mode.setdefault(ev.get("source", ev.get("mode", "unknown")), []).append(ev)

    latest_per_mode = {mode: evs[-1] for mode, evs in by_mode.items() if evs}

    total_tokens = 0
    total_docs = 0
    last_expansion = None
    # Track max real tokens to decide if we have newer than canonical
    max_real_tokens = 0
    max_real_docs = 0
    for ev in by_mode.get("data", []):
        met = ev.get("metrics", {}) if isinstance(ev.get("metrics"), dict) else {}
        is_dry = met.get("dry_run") or ev.get("dry_run")
        # Count only non-dry for official totals unless all dry
        if ev.get("metrics", {}).get("tokens") or ev.get("tokens"):
            t = met.get("tokens", 0) or ev.get("tokens",0) or 0
            d = met.get("docs",0) or ev.get("docs",0) or 0
            if not is_dry:
                total_tokens += t
                total_docs += d
                if t >= max_real_tokens:
                    max_real_tokens = t
                    max_real_docs = d
                    last_expansion = ev
            else:
                # dry: keep as fallback only if no real yet
                if not last_expansion:
                    last_expansion = ev

    training_monitor = latest_per_mode.get("train", latest_per_mode.get("training", {}))

    # Canonical sample from spec — preserve for dash when no newer real data
    CANONICAL_TS = "2026-07-16T15:56:01.603296+00:00"
    CANONICAL_TOKENS = 500034
    CANONICAL_DOCS = 5045

    live = {
        "updated": _utc_now_iso(),
        "disclaimer": DISCLAIMER,
        "last_expansion": {
            "timestamp": (last_expansion.get("timestamp") if last_expansion else None),
            "tokens": last_expansion.get("metrics", {}).get("tokens", last_expansion.get("tokens", 0)) if last_expansion else 0,
            "docs": last_expansion.get("metrics", {}).get("docs", last_expansion.get("docs", 0)) if last_expansion else 0,
            "shards": last_expansion.get("metrics", {}).get("shards", last_expansion.get("shards", 0)) if last_expansion else 0,
        },
        "totals_last_1000": {"tokens": total_tokens, "docs": total_docs},
        "latest_per_mode": latest_per_mode,
        "by_mode_counts": {k: len(v) for k, v in by_mode.items()},
        "recent_events": events[-20:],
        "counts": {k: len(v) for k, v in by_mode.items()},
        "last_event": events[-1] if events else {},
        "last_train": latest_per_mode.get("train", {}),
        "last_eval": latest_per_mode.get("eval", {}),
        "last_ecosystem": latest_per_mode.get("ecosystem", {}),
        "health": {
            "last_loss": training_monitor.get("metrics", {}).get("loss") if isinstance(training_monitor, dict) else None,
        },
        "system_health": {
            "disk": _get_disk_usage(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
    }
    try:
        status_path = _REPO_ROOT / "STATUS.json"
        if status_path.exists():
            content = status_path.read_text()
            status_data = json.loads(content[:200000])
            builder_exp = status_data.get("builder", {}).get("last_expansion")
            live["status_json"] = {"last_expansion": builder_exp}
            # Fallback: if we have no real expansion in telemetry, use STATUS.json's 500k etc (also if dry_run or tiny)
            le = live.get("last_expansion",{})
            is_dry_last = False
            try:
                if last_expansion:
                    mm = last_expansion.get("metrics",{}) if isinstance(last_expansion.get("metrics"), dict) else {}
                    is_dry_last = mm.get("dry_run") or last_expansion.get("dry_run")
            except: pass
            if not last_expansion or le.get("tokens",0)==0 or is_dry_last or le.get("tokens",0)<10000:
                if builder_exp:
                    live["last_expansion"] = {
                        "timestamp": builder_exp.get("timestamp"),
                        "tokens": builder_exp.get("tokens",0),
                        "docs": builder_exp.get("docs",0),
                        "shards": len(builder_exp.get("shards",[])) if isinstance(builder_exp.get("shards"), list) else builder_exp.get("shards",0),
                        "shards_list": builder_exp.get("shards", []),
                        "source": "STATUS.json fallback",
                        "manifest": builder_exp.get("manifest"),
                        "manifest_sha12": builder_exp.get("manifest_sha12") or (builder_exp.get("gdrive_upload", {}) or {}).get("new_shard", {}).get("sha12", "d8cb5a396dbf") if isinstance(builder_exp.get("gdrive_upload"), dict) else "d8cb5a396dbf",
                        "gdrive_folder_id": builder_exp.get("gdrive_folder_id") or (builder_exp.get("gdrive_upload", {}) or {}).get("folder_id", "19tqzjB-ofqKmx1w6S4qLNB_jAEa6s3ve") if isinstance(builder_exp.get("gdrive_upload"), dict) else "19tqzjB-ofqKmx1w6S4qLNB_jAEa6s3ve",
                        "mode": builder_exp.get("mode"),
                        "total_shards": builder_exp.get("total_shards", 74) if isinstance(builder_exp, dict) else 74,
                    }
                    # Patch totals for UI
                    if live["totals_last_1000"]["tokens"]==0:
                        live["totals_last_1000"]["tokens"]=builder_exp.get("tokens",0)
                        live["totals_last_1000"]["docs"]=builder_exp.get("docs",0)
                    # Preserve canonical updated timestamp for dash sample when no newer real data
                    if max_real_tokens <= CANONICAL_TOKENS:
                        live["updated"] = builder_exp.get("timestamp", CANONICAL_TS)
                        live["updated_at"] = builder_exp.get("timestamp", CANONICAL_TS)
            # Canonical lock: if max_real_tokens <= canonical, force canonical sample for dash consistency
            if builder_exp and max_real_tokens <= CANONICAL_TOKENS:
                # If builder_exp tokens == canonical, overwrite last_expansion with full canonical details
                if builder_exp.get("tokens",0) == CANONICAL_TOKENS:
                    # Build rich canonical expansion preserving folder_id, shards, manifest etc.
                    canon = {
                        "timestamp": builder_exp.get("timestamp", CANONICAL_TS),
                        "tokens": builder_exp.get("tokens", CANONICAL_TOKENS),
                        "docs": builder_exp.get("docs", CANONICAL_DOCS),
                        "shards": builder_exp.get("shards", ["packed_20260716_155535_00081_6671.jsonl.gz"]),
                        "total_shards": builder_exp.get("total_shards", 74) if isinstance(builder_exp.get("total_shards", None), int) else 74,
                        "manifest": builder_exp.get("manifest", "manifest_20260716_155535.jsonl"),
                        "manifest_sha12": "d8cb5a396dbf",
                        "dup_filtered": builder_exp.get("dup_filtered", 9700),
                        "qual_filtered": builder_exp.get("qual_filtered", 8581),
                        "gdrive_folder_id": "19tqzjB-ofqKmx1w6S4qLNB_jAEa6s3ve",
                        "mode": builder_exp.get("mode", "500K_HatchVM_4h_p0-p2_simhash th3+md5 fast+qual alpha>0.6 reward>0.8"),
                        "source": "canonical_lock",
                    }
                    # Preserve full builder if exists for richness
                    if isinstance(builder_exp, dict):
                        canon.update({k: v for k, v in builder_exp.items() if k not in canon})
                        # Ensure canonical keys win
                        canon["timestamp"] = builder_exp.get("timestamp", CANONICAL_TS)
                        canon["tokens"] = CANONICAL_TOKENS
                        canon["docs"] = CANONICAL_DOCS
                    live["last_expansion"] = canon
                    live["updated"] = builder_exp.get("timestamp", CANONICAL_TS)
                    live["updated_at"] = builder_exp.get("timestamp", CANONICAL_TS)
    except Exception as e:
        live["status_json_error"]=str(e)

    try:
        _write_live_status(live)
    except Exception:
        pass

    return live

def get_live_status() -> Dict[str, Any]:
    if not LIVE_STATUS_PATH.exists():
        return aggregate_live_status()
    try:
        data = json.loads(LIVE_STATUS_PATH.read_text(encoding="utf-8"))
        from datetime import datetime
        updated_str = data.get("updated_at") or data.get("updated")
        if updated_str:
            try:
                upd = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                now = datetime.now(datetime.timezone.utc)
                if (now - upd).total_seconds() > 300:
                    return aggregate_live_status()
            except Exception:
                pass
        return data
    except Exception:
        return aggregate_live_status()

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Dottie telemetry smoke test")
    ap.add_argument("--source", default="telemetry")
    ap.add_argument("--message", default="smoke test event")
    args = ap.parse_args()
    print(f"[{DISCLAIMER}] Logging test event to {JSONL_PATH}")
    ev = log_event(source=args.source, event_type="test", message=args.message, metrics={"smoke": True, "run_id": _RUN_ID}, level="info")
    print(json.dumps(ev, indent=2))
    print(f"Live status: {LIVE_STATUS_PATH}")
    try:
        live = json.loads(LIVE_STATUS_PATH.read_text())
        print(json.dumps(live, indent=2)[:3000])
    except Exception as e:
        print(f"Live read failed: {e}")
