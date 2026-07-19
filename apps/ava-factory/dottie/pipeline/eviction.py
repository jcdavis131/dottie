"""Curriculum-aware high-water eviction policy (T10.9).

Pure ranking + protect rules. The janitor owns the loop and I/O; this module
decides *which* RAW/PACKED train shards are least curriculum-useful when free
disk falls below ``storage.evict_high_water_gb``.

Protect:
  - never val/test
  - never PACKED that would drop ``tokens_ready(phase)`` below ``packed_min_tokens``
  - never CLAIMED_* (leased work in flight)

Prefer (evict first):
  1. phases behind the trainer's current phase
  2. oversupplied runway (tokens_ready >= packed_ahead_max_tokens)
  3. RAW before PACKED
  4. oldest ``updated_at``
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import yaml

from dottie.pipeline.flow import FlowConfig, current_training_phase, prefetch_phases
from dottie.pipeline.manifest import (
    PACKED,
    PROTECTED_SPLITS,
    RAW,
    Manifest,
    StateError,
)

_DEFAULT_CONFIG = "/app/configs/pipeline.yaml"


@dataclasses.dataclass(frozen=True)
class StorageConfig:
    evict_high_water_gb: float
    evict_batch_limit: int

    @classmethod
    def load(cls, path: str | Path | None = None) -> "StorageConfig":
        p = Path(path or os.environ.get("AVA_PIPELINE_CONFIG", _DEFAULT_CONFIG))
        cfg = yaml.safe_load(p.read_text())
        s = cfg.get("storage", {})
        return cls(
            evict_high_water_gb=float(s.get("evict_high_water_gb", 15.0)),
            evict_batch_limit=int(s.get("evict_batch_limit", 20)),
        )


@dataclasses.dataclass(frozen=True)
class EvictionCandidate:
    id: str
    phase: int
    state: str
    path: str | None
    tokens: int
    updated_at: float
    behind: bool
    oversupplied: bool


def should_evict(free_gb: float, storage: StorageConfig) -> bool:
    """True when free disk is below the curriculum-eviction high-water mark."""
    return free_gb < storage.evict_high_water_gb


def _phase_runway(manifest: Manifest, phase: int) -> int:
    return manifest.tokens_ready(phase)


def rank_eviction_candidates(
    manifest: Manifest,
    fcfg: FlowConfig,
    *,
    current_phase: int,
    n_phases: int = 6,
) -> list[EvictionCandidate]:
    """Return train RAW/PACKED candidates sorted worst-first (evict from the front)."""
    lead = fcfg.packed_min_tokens
    ahead_max = fcfg.packed_ahead_max_tokens
    window = set(prefetch_phases(current_phase, fcfg, n_phases))

    rows = manifest.db.execute(
        "SELECT id, phase, state, path, tokens, updated_at, split FROM shards "
        "WHERE state IN (?, ?) AND split = 'train'",
        (RAW, PACKED),
    ).fetchall()

    runway_cache: dict[int, int] = {}
    out: list[EvictionCandidate] = []
    for r in rows:
        if r["split"] in PROTECTED_SPLITS:
            continue
        phase = int(r["phase"])
        state = r["state"]
        tokens = int(r["tokens"] or 0)
        if phase not in runway_cache:
            runway_cache[phase] = _phase_runway(manifest, phase)
        ready = runway_cache[phase]
        behind = phase not in window and phase < current_phase
        oversupplied = ready >= ahead_max

        # PACKED: only if removing this shard keeps the phase at/above lead.
        if state == PACKED:
            if ready - tokens < lead:
                continue
            # Prefer not to touch PACKED inside the prefetch window unless deeply oversupplied.
            if phase in window and not oversupplied:
                continue

        out.append(
            EvictionCandidate(
                id=r["id"],
                phase=phase,
                state=state,
                path=r["path"],
                tokens=tokens,
                updated_at=float(r["updated_at"] or 0.0),
                behind=behind,
                oversupplied=oversupplied,
            )
        )

    # Sort: behind first, then oversupplied, then RAW before PACKED, then oldest.
    out.sort(
        key=lambda c: (
            0 if c.behind else 1,
            0 if c.oversupplied else 1,
            0 if c.state == RAW else 1,
            c.updated_at,
        )
    )

    # Greedy PACKED filter: never schedule a set of deletions that would drop
    # any phase below the lead floor (checked against cumulative removals).
    remaining = dict(runway_cache)
    filtered: list[EvictionCandidate] = []
    for c in out:
        if c.state == PACKED:
            left = remaining.get(c.phase, 0) - c.tokens
            if left < lead:
                continue
            remaining[c.phase] = left
        filtered.append(c)
    return filtered


def delete_eviction_files(path: str | None, *, state: str) -> bool:
    """Remove shard bytes from disk. RAW = jsonl.zst; PACKED = bin + idx."""
    if not path:
        return True
    p = Path(path)
    try:
        if p.exists():
            p.unlink()
        if state == PACKED:
            from dottie.pipeline.pack import idx_path_for

            idx = Path(idx_path_for(p))
            if idx.exists():
                idx.unlink()
        return True
    except OSError:
        return False


def evict_oversupplied(
    manifest: Manifest,
    fcfg: FlowConfig,
    storage: StorageConfig,
    *,
    current_phase: int | None = None,
    limit: int | None = None,
) -> dict:
    """Delete up to ``limit`` least-useful train shards. Never val/test."""
    cur = current_phase if current_phase is not None else current_training_phase(manifest)
    batch = limit if limit is not None else storage.evict_batch_limit
    stats = {
        "examined": 0,
        "deleted": 0,
        "refused_protected": 0,
        "skipped_error": 0,
        "current_phase": cur,
    }
    candidates = rank_eviction_candidates(manifest, fcfg, current_phase=cur)[:batch]
    stats["examined"] = len(candidates)
    to_mark: list[str] = []

    for c in candidates:
        try:
            if not delete_eviction_files(c.path, state=c.state):
                stats["skipped_error"] += 1
                continue
            to_mark.append(c.id)
        except Exception:  # noqa: BLE001
            stats["skipped_error"] += 1

    if to_mark:
        try:
            stats["deleted"] = manifest.mark_deleted(to_mark)
        except StateError:
            # One protected slip — refuse all in batch rather than partial illegal transition.
            stats["refused_protected"] += len(to_mark)
            stats["deleted"] = 0
        except Exception:  # noqa: BLE001
            stats["skipped_error"] += len(to_mark)
            stats["deleted"] = 0
    return stats
