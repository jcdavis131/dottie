"""Janitor service — reclaim disk under watermarks without touching eval data.

Responsibilities:
  1. When free disk falls below ``disk.janitor_trigger_gb``, delete CONSUMED
     train shards (files + manifest ``CONSUMED -> DELETED``).
  2. When free disk falls below ``storage.evict_high_water_gb``, curriculum-aware
     eviction of oversupplied / behind-phase RAW and PACKED train shards (T10.9).
  3. Rotate ``ckpt/step_*.pt`` to ``retention.keep_last_checkpoints``, always
     preserving ``stable_p*.pt`` (and ``latest`` / ``*_final.pt``).
  4. Never delete ``val`` / ``test`` shards — structural protection in
     ``manifest.consumed_shards`` / ``mark_deleted``, plus an explicit refuse
     here so a bad row cannot slip through.

The loop is idempotent and SIGTERM-graceful. A single bad shard is logged and
skipped; ``fail()`` is not used (CONSUMED rows are not leased claims). The
container must not crash on one corrupt path.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import signal
import sys
import time
import traceback
from pathlib import Path

import yaml

from ava.pipeline.eviction import StorageConfig, evict_oversupplied, should_evict
from ava.pipeline.flow import FlowConfig, current_training_phase, free_gb, janitor_should_collect
from ava.pipeline.manifest import PROTECTED_SPLITS, Manifest, worker_id
from ava.pipeline.pack import idx_path_for

DEFAULT_CONFIG = "/app/configs/pipeline.yaml"
IDLE_POLL_SECONDS = 30.0
BATCH_LIMIT = 50

_STEP_CKPT_RE = re.compile(r"^step_(\d+)\.pt$")
_STABLE_CKPT_RE = re.compile(r"^stable_p\d+\.pt$")
_FINAL_CKPT_RE = re.compile(r".+_final\.pt$")


def _log(event: str, **fields) -> None:
    rec = {"ts": round(time.time(), 3), "svc": "janitor", "event": event}
    rec.update(fields)
    print(json.dumps(rec, sort_keys=True), flush=True)


@dataclasses.dataclass(frozen=True)
class RetentionConfig:
    delete_consumed: bool
    keep_last_checkpoints: int
    keep_stable_checkpoints: bool

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RetentionConfig":
        p = Path(path or os.environ.get("AVA_PIPELINE_CONFIG", DEFAULT_CONFIG))
        cfg = yaml.safe_load(p.read_text())
        r = cfg.get("retention", {})
        return cls(
            delete_consumed=bool(r.get("delete_consumed", True)),
            keep_last_checkpoints=int(r.get("keep_last_checkpoints", 1)),
            keep_stable_checkpoints=bool(r.get("keep_stable_checkpoints", True)),
        )


def _unlink_quiet(path: Path) -> bool:
    """Remove a file if present. Returns True if gone afterward."""
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        _log("unlink_failed", path=str(path), error=f"{type(exc).__name__}: {exc}", level="warn")
        return False


def delete_shard_files(path: str | None) -> bool:
    """Delete a packed shard's ``.bin`` and ``.idx.json``. Missing files are ok."""
    if not path:
        return True
    bin_path = Path(path)
    ok = _unlink_quiet(bin_path)
    ok = _unlink_quiet(idx_path_for(bin_path)) and ok
    return ok


def rotate_checkpoints(
    ckpt_dir: str | Path,
    *,
    keep_last: int,
    keep_stable: bool,
) -> list[str]:
    """Delete excess ``step_*.pt`` files. Returns names removed.

    Always keeps ``latest``, ``stable_p*.pt`` (when ``keep_stable``), and
    ``*_final.pt``. Only ``step_{n}.pt`` participates in the keep-last-N window.
    """
    root = Path(ckpt_dir)
    if not root.is_dir():
        return []

    stepped: list[tuple[int, Path]] = []
    for p in root.iterdir():
        if not p.is_file():
            continue
        m = _STEP_CKPT_RE.match(p.name)
        if m:
            stepped.append((int(m.group(1)), p))

    stepped.sort(key=lambda t: t[0], reverse=True)
    keep_n = max(0, int(keep_last))
    victims = [p for _, p in stepped[keep_n:]]

    removed: list[str] = []
    for p in victims:
        # Defensive: never rotate stables / finals even if naming drifts.
        if keep_stable and _STABLE_CKPT_RE.match(p.name):
            continue
        if _FINAL_CKPT_RE.match(p.name) or p.name == "latest":
            continue
        if _unlink_quiet(p):
            removed.append(p.name)
    return removed


def reclaim_consumed(
    m: Manifest,
    *,
    limit: int = BATCH_LIMIT,
) -> dict:
    """Delete up to ``limit`` CONSUMED train shards. Never touches val/test."""
    stats = {"examined": 0, "deleted": 0, "refused_protected": 0, "skipped_error": 0}
    shards = m.consumed_shards(limit=limit)
    stats["examined"] = len(shards)
    to_mark: list[str] = []

    for shard in shards:
        if shard.split in PROTECTED_SPLITS:
            stats["refused_protected"] += 1
            _log(
                "refuse_protected",
                level="warn",
                shard=shard.id,
                split=shard.split,
                note="janitor must never delete val/test",
            )
            continue
        try:
            # Resolve via module globals so tests can monkeypatch delete_shard_files.
            if not globals()["delete_shard_files"](shard.path):
                stats["skipped_error"] += 1
                continue
            to_mark.append(shard.id)
        except Exception as exc:  # noqa: BLE001 — never crash the container
            stats["skipped_error"] += 1
            _log(
                "shard_error",
                level="warn",
                shard=shard.id,
                error=f"{type(exc).__name__}: {exc}",
                tb=traceback.format_exc()[-1500:],
            )

    if to_mark:
        try:
            n = m.mark_deleted(to_mark)
            stats["deleted"] = n
        except Exception as exc:  # noqa: BLE001
            stats["skipped_error"] += len(to_mark)
            _log(
                "mark_deleted_failed",
                level="warn",
                error=f"{type(exc).__name__}: {exc}",
                shard_ids=to_mark,
                tb=traceback.format_exc()[-1500:],
            )
    return stats


class Janitor:
    def __init__(
        self,
        *,
        config_path: str | None = None,
        db_path: str | None = None,
        packed_dir: str | None = None,
        ckpt_dir: str | None = None,
        raw_dir: str | None = None,
    ) -> None:
        self.config_path = config_path or os.environ.get("AVA_PIPELINE_CONFIG", DEFAULT_CONFIG)
        self.flow = FlowConfig.load(self.config_path)
        self.retention = RetentionConfig.load(self.config_path)
        self.storage = StorageConfig.load(self.config_path)
        self.db_path = db_path or os.environ.get("AVA_STATE_DB", "/state/manifest.db")
        self.packed_dir = packed_dir or os.environ.get("AVA_PACKED_DIR", "/packed")
        self.ckpt_dir = ckpt_dir or os.environ.get("AVA_CKPT_DIR", "/ckpt")
        self.raw_dir = raw_dir or os.environ.get("AVA_RAW_DIR", "/raw")
        self.worker = worker_id()
        self._stop = False

    def _install_signal_handlers(self) -> None:
        def handler(signum, frame):
            self._stop = True
            _log("sigterm", note="will finish current pass then exit")

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    def run_once(self, m: Manifest) -> dict:
        """One janitor pass: CONSUMED reclaim, curriculum eviction, ckpt rotation."""
        disk_path = self.packed_dir
        free = free_gb(disk_path)
        result: dict = {
            "disk_free_gb": round(free, 3),
            "reclaimed": None,
            "evicted": None,
            "ckpts_removed": [],
        }

        pressure = janitor_should_collect(self.flow, disk_path=disk_path)
        result["pressure"] = bool(pressure)
        result["pressure_reason"] = pressure.reason

        if pressure and self.retention.delete_consumed:
            result["reclaimed"] = reclaim_consumed(m)
            _log("reclaim", **result["reclaimed"], reason=pressure.reason)
        elif pressure and not self.retention.delete_consumed:
            _log("reclaim_skipped", reason="delete_consumed=false", pressure=pressure.reason)

        if should_evict(free, self.storage):
            try:
                cur = current_training_phase(m)
                result["evicted"] = evict_oversupplied(
                    m, self.flow, self.storage, current_phase=cur
                )
                _log(
                    "evict",
                    **result["evicted"],
                    free_gb=result["disk_free_gb"],
                    high_water_gb=self.storage.evict_high_water_gb,
                )
            except Exception as exc:  # noqa: BLE001
                _log(
                    "evict_failed",
                    level="warn",
                    error=f"{type(exc).__name__}: {exc}",
                    tb=traceback.format_exc()[-1500:],
                )

        try:
            removed = rotate_checkpoints(
                self.ckpt_dir,
                keep_last=self.retention.keep_last_checkpoints,
                keep_stable=self.retention.keep_stable_checkpoints,
            )
            result["ckpts_removed"] = removed
            if removed:
                _log("ckpt_rotated", removed=removed, keep_last=self.retention.keep_last_checkpoints)
        except Exception as exc:  # noqa: BLE001
            _log(
                "ckpt_rotate_failed",
                level="warn",
                error=f"{type(exc).__name__}: {exc}",
                tb=traceback.format_exc()[-1500:],
            )

        return result

    def serve(self, *, once: bool = False) -> int:
        self._install_signal_handlers()
        _log(
            "start",
            worker=self.worker,
            once=once,
            packed_dir=self.packed_dir,
            ckpt_dir=self.ckpt_dir,
            janitor_trigger_gb=self.flow.janitor_trigger_gb,
            evict_high_water_gb=self.storage.evict_high_water_gb,
            delete_consumed=self.retention.delete_consumed,
            keep_last_checkpoints=self.retention.keep_last_checkpoints,
        )
        with Manifest(self.db_path) as m:
            if once:
                self.run_once(m)
                _log("stop", reason="once")
                return 0
            while not self._stop:
                self.run_once(m)
                for _ in range(int(IDLE_POLL_SECONDS * 10)):
                    if self._stop:
                        break
                    time.sleep(0.1)
        _log("stop", reason="sigterm" if self._stop else "loop_end")
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ava janitor service")
    ap.add_argument("--once", action="store_true", help="one reclaim+rotate pass then exit")
    ap.add_argument("--config", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--packed-dir", default=None)
    ap.add_argument("--ckpt-dir", default=None)
    args = ap.parse_args(argv)
    janitor = Janitor(
        config_path=args.config,
        db_path=args.db,
        packed_dir=args.packed_dir,
        ckpt_dir=args.ckpt_dir,
    )
    return janitor.serve(once=args.once)


if __name__ == "__main__":
    sys.exit(main())
