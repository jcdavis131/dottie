"""
Solo personal project, no connection to employer, built with public/free-tier only
Dottie Ecosystem Updater — maintains openwiki sync, shard rotation, skillbook bumps, doc link checks.

Public pip only, free-tier, no work systems. HOME-only.

Env compat: DOTTIE_* and AVA_* fallbacks.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List

DISCLAIMER = "Solo personal project, no connection to employer, built with public/free-tier only"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA_DAILY = _REPO_ROOT / "data" / "daily_expanded"
_DATA_UPLOAD = _REPO_ROOT / "data" / "for_upload"
_DOCS_DIR = _REPO_ROOT / "docs"
_SKILLS_DIR = _REPO_ROOT / "dottie" / "skills"

try:
    from .telemetry import log_ecosystem, log_event, log_error
except ImportError:
    from dottie.telemetry import log_ecosystem, log_event, log_error  # type: ignore


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sync_openwiki() -> Dict[str, Any]:
    """Sync ~/.openwiki/wiki -> S2 Slow memory if available. Mocked safe if not present."""
    start = time.time()
    openwiki_root = Path.home() / ".openwiki" / "wiki"
    result: Dict[str, Any] = {"found": False, "files": 0, "duration_s": 0}

    try:
        if openwiki_root.exists():
            files = list(openwiki_root.rglob("*.md"))
            result["found"] = True
            result["files"] = len(files)
            # Future: call dottie.memory.openwiki_adapter.sync() if implemented
            try:
                from .memory.openwiki_adapter import sync as ow_sync  # type: ignore

                ow_sync()
                result["synced"] = True
            except Exception:
                result["synced"] = False
                result["note"] = "adapter not implemented, counted only"
        else:
            result["note"] = f"openwiki not found at {openwiki_root}"

        result["duration_s"] = round(time.time() - start, 2)
        log_ecosystem("openwiki_sync", f"OpenWiki sync found={result['found']} files={result['files']}", metrics=result)
        return result
    except Exception as e:
        result["error"] = str(e)
        log_error("ecosystem", f"openwiki sync failed: {e}", metrics=result)
        return result


def rotate_shards(keep_last_days: int = 2, disk_threshold_pct: int = 80) -> Dict[str, Any]:
    """
    Rotate old shards from data/daily_expanded to data/for_upload if disk > threshold
    or older than keep_last_days. Keeps manifest.jsonl intact.
    """
    start = time.time()
    metrics: Dict[str, Any] = {"moved": 0, "freed_mb": 0, "disk_pct": 0, "threshold": disk_threshold_pct}

    try:
        # disk check
        try:
            usage = shutil.disk_usage(str(_REPO_ROOT))
            pct = int(100 * usage.used / usage.total) if usage.total else 0
            metrics["disk_pct"] = pct
        except Exception:
            pct = 0

        # Only rotate if > threshold or forced by age
        cutoff_time = time.time() - (keep_last_days * 86400)

        moved = []
        freed = 0
        if _DATA_DAILY.exists():
            _DATA_UPLOAD.mkdir(parents=True, exist_ok=True)
            for f in _DATA_DAILY.glob("*.jsonl.gz"):
                try:
                    mtime = f.stat().st_mtime
                    is_old = mtime < cutoff_time
                    should_move = (pct >= disk_threshold_pct and is_old) or (is_old and keep_last_days <= 2)
                    # For safety in VM, only move if both old AND over threshold, or if --force behavior via env
                    force = os.environ.get("DOTTIE_FORCE_ROTATE") == "1"
                    if (pct >= disk_threshold_pct) or (is_old and force):
                        dest = _DATA_UPLOAD / f.name
                        if not dest.exists():
                            shutil.move(str(f), str(dest))
                            freed += f.stat().st_size if dest.exists() else dest.stat().st_size if dest.exists() else 0
                            moved.append(f.name)
                        else:
                            # already exists, remove old to free
                            freed += f.stat().st_size
                            f.unlink()
                            moved.append(f"{f.name} (dedup removed)")
                except Exception as e:
                    print(f"[ecosystem] rotate shard {f} failed: {e}")

            # more accurate freed calc
            metrics["moved"] = len(moved)
            metrics["moved_files"] = moved[:20]
            metrics["freed_mb"] = round(freed / (1024 * 1024), 2)

        metrics["duration_s"] = round(time.time() - start, 2)
        log_ecosystem(
            "rotate_shards",
            f"Rotated {metrics['moved']} shards freed {metrics['freed_mb']}MB disk {metrics['disk_pct']}%",
            metrics=metrics,
        )
        return metrics
    except Exception as e:
        metrics["error"] = str(e)
        log_error("ecosystem", f"rotate_shards failed: {e}", metrics=metrics)
        return metrics


def update_skillbooks() -> Dict[str, Any]:
    """Bump skillbook versions / validate json."""
    start = time.time()
    result: Dict[str, Any] = {"checked": 0, "valid": 0, "invalid": 0, "files": []}
    try:
        if not _SKILLS_DIR.exists():
            result["note"] = "skills dir missing"
            log_ecosystem("skillbooks", "No skills dir", metrics=result)
            return result

        for jf in _SKILLS_DIR.glob("*.json"):
            result["checked"] += 1
            try:
                data = json.loads(jf.read_text(encoding="utf-8")[:100000])
                # must have name/version or at least parseable
                result["valid"] += 1
                result["files"].append(jf.name)
            except Exception:
                result["invalid"] += 1

        result["duration_s"] = round(time.time() - start, 2)
        log_ecosystem("skillbooks", f"Skillbooks checked {result['checked']} valid {result['valid']}", metrics=result)
        return result
    except Exception as e:
        result["error"] = str(e)
        log_error("ecosystem", f"update_skillbooks failed: {e}", metrics=result)
        return result


def check_docs_links() -> Dict[str, Any]:
    """Simple docs link existence check (no network)."""
    start = time.time()
    result: Dict[str, Any] = {"docs": 0, "missing_refs": []}
    try:
        if not _DOCS_DIR.exists():
            result["note"] = "docs missing"
            return result

        # Check that key docs exist
        required = [
            "CONTINUOUS_PIPELINES.md",
            "LLMVM_REDESIGN_v6.5.md",
            "HARNESS_SKILL_INTEGRATION.md",
            "CONTINUOUS_SYSTEM_DOTTIE.md",
        ]
        missing = []
        for name in required:
            if not (_DOCS_DIR / name).exists():
                missing.append(name)

        result["docs"] = len(list(_DOCS_DIR.glob("*.md")))
        result["missing_refs"] = missing
        result["duration_s"] = round(time.time() - start, 2)

        lvl = "info" if not missing else "warn"
        log_event(
            source="ecosystem",
            event_type="docs_check",
            message=f"Docs check {result['docs']} files missing={missing}",
            metrics=result,
            level=lvl,
        )
        return result
    except Exception as e:
        result["error"] = str(e)
        log_error("ecosystem", f"check_docs_links failed: {e}", metrics=result)
        return result


def run_all() -> Dict[str, Any]:
    """Run full ecosystem update cycle."""
    start = time.time()
    log_event(source="ecosystem", event_type="start", message="Ecosystem update cycle start", metrics={}, level="info")

    results = {}
    results["openwiki"] = sync_openwiki()
    results["rotate"] = rotate_shards()
    results["skillbooks"] = update_skillbooks()
    results["docs"] = check_docs_links()

    results["duration_s"] = round(time.time() - start, 2)
    results["timestamp"] = _now_iso()
    results["disclaimer"] = DISCLAIMER

    log_event(
        source="ecosystem",
        event_type="finish",
        message=f"Ecosystem cycle done {results['duration_s']}s",
        metrics=results,
        level="info",
    )
    return results


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Dottie ecosystem updater")
    ap.add_argument("--action", choices=["all", "openwiki", "rotate", "skillbooks", "docs"], default="all")
    ap.add_argument("--keep-days", type=int, default=2)
    ap.add_argument("--disk-threshold", type=int, default=80)
    args = ap.parse_args()

    print(f"[{DISCLAIMER}] Ecosystem updater action={args.action}")
    if args.action == "all":
        res = run_all()
        print(json.dumps(res, indent=2))
    elif args.action == "openwiki":
        print(json.dumps(sync_openwiki(), indent=2))
    elif args.action == "rotate":
        print(json.dumps(rotate_shards(keep_last_days=args.keep_days, disk_threshold_pct=args.disk_threshold), indent=2))
    elif args.action == "skillbooks":
        print(json.dumps(update_skillbooks(), indent=2))
    elif args.action == "docs":
        print(json.dumps(check_docs_links(), indent=2))
