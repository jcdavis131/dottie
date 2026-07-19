"""Backpressure and flow control.

This module is what turns three programs racing each other into a pipeline.

The invariant we want: the GPU is the bottleneck. Collectors and curators run
ahead of the trainer, but only far enough ahead to keep it fed -- never far
enough to fill the disk. Three predicates enforce that:

  collector_should_pause()  raw backlog / packed runway / disk floor
  trainer_data_state()      READY | STARVED | CRITICAL_DISK
  janitor_should_collect()  disk pressure

Phase coordination (pacer):
  current_training_phase()  trainer heartbeat in `runs`, else metrics tail
  pick_target_phase()       starved runway in the prefetch window wins
  curator_claim_phases()    curators pack trainer-current before older RAW

Nothing here touches the network or the filesystem beyond a cheap stat / tail,
so it is safe to poll every loop iteration.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import os
import shutil
import time
from pathlib import Path
from typing import Sequence

import yaml

from dottie.pipeline.manifest import Manifest

_DEFAULT_CONFIG = "/app/configs/pipeline.yaml"
N_PHASES = 6


class DataState(enum.Enum):
    READY = "READY"
    STARVED = "DATA_STARVED"
    CRITICAL_DISK = "CRITICAL_DISK"


@dataclasses.dataclass(frozen=True)
class PauseReason:
    paused: bool
    reason: str = ""

    def __bool__(self) -> bool:  # `if collector_should_pause(...):`
        return self.paused


@dataclasses.dataclass(frozen=True)
class FlowConfig:
    low_water_gb: float
    janitor_trigger_gb: float
    critical_gb: float
    raw_max_bytes: int
    packed_ahead_max_tokens: int
    packed_min_tokens: int
    starved_poll_seconds: float
    starved_warn_seconds: float
    prefetch_phases: int
    delete_consumed: bool

    @classmethod
    def load(cls, path: str | Path | None = None) -> "FlowConfig":
        p = Path(path or os.environ.get("AVA_PIPELINE_CONFIG", _DEFAULT_CONFIG))
        cfg = yaml.safe_load(p.read_text())
        disk, bp = cfg["disk"], cfg["backpressure"]
        return cls(
            low_water_gb=float(disk["low_water_gb"]),
            janitor_trigger_gb=float(disk["janitor_trigger_gb"]),
            critical_gb=float(disk["critical_gb"]),
            raw_max_bytes=int(bp["raw_max_bytes"]),
            packed_ahead_max_tokens=int(bp["packed_ahead_max_tokens"]),
            packed_min_tokens=int(bp["packed_min_tokens"]),
            starved_poll_seconds=float(bp["starved_poll_seconds"]),
            starved_warn_seconds=float(bp["starved_warn_seconds"]),
            prefetch_phases=int(cfg["collector"]["prefetch_phases"]),
            delete_consumed=bool(cfg["retention"]["delete_consumed"]),
        )


def free_gb(path: str | Path = "/") -> float:
    """Free space in GB (1e9 bytes).

    Docker Desktop's Linux VM reports the *virtual* disk free space (often
    hundreds of GB) even when the Windows host is nearly full. Prefer an
    explicit host probe path when present: ``$AVA_DISK_PROBE`` or ``/host_disk``
    (compose bind-mount of the host drive, read-only). Fall back to ``path``.
    """
    probes: list[str] = []
    env_probe = os.environ.get("AVA_DISK_PROBE")
    if env_probe:
        probes.append(env_probe)
    probes.append("/host_disk")
    probes.append(str(path))
    last_err: OSError | None = None
    for probe in probes:
        try:
            if probe == "/host_disk" and not Path(probe).exists():
                continue
            return shutil.disk_usage(probe).free / 1e9
        except OSError as exc:
            last_err = exc
            continue
    if last_err is not None:
        raise last_err
    return shutil.disk_usage(str(path)).free / 1e9


# ---------------------------------------------------------------------------
# Collector

def collector_should_pause(
    manifest: Manifest,
    cfg: FlowConfig,
    *,
    phase: int,
    disk_path: str | Path = "/raw",
) -> PauseReason:
    """Should the collector stop fetching?

    Ordered cheapest-first, and disk before queue depth: running out of disk is
    unrecoverable mid-write, a deep queue merely wastes time.

    Starved-phase exception: when the *trainer's current phase* is below
    ``packed_min_tokens``, raw-backlog and packed-ahead pauses are skipped so
    collectors can refill the phase the GPU is actually on. Prefetch of an
    empty *next* phase must still respect ``raw_max_bytes`` — otherwise
    collectors fill the disk while the current phase already has lead.
    Disk low-water still always wins.
    """
    fg = free_gb(disk_path)
    if fg < cfg.low_water_gb:
        return PauseReason(True, f"disk {fg:.1f}GB < low_water {cfg.low_water_gb}GB")

    ahead = manifest.tokens_ready(phase)
    phase_starved = ahead < cfg.packed_min_tokens
    trainer_phase = current_training_phase(manifest)
    trainer_starved = manifest.tokens_ready(trainer_phase) < cfg.packed_min_tokens
    # Only bypass queue pauses when the GPU itself needs data now.
    skip_queue_pauses = phase_starved and trainer_starved

    if not skip_queue_pauses:
        raw = manifest.raw_bytes()
        if raw >= cfg.raw_max_bytes:
            return PauseReason(
                True,
                f"raw backlog {raw/1e9:.1f}GB >= max {cfg.raw_max_bytes/1e9:.1f}GB",
            )
        if ahead >= cfg.packed_ahead_max_tokens:
            return PauseReason(
                True,
                f"packed runway {ahead/1e9:.2f}B tokens >= max "
                f"{cfg.packed_ahead_max_tokens/1e9:.2f}B",
            )

    return PauseReason(False)


def prefetch_phases(current_phase: int, cfg: FlowConfig, n_phases: int = N_PHASES) -> list[int]:
    """Phases the collector should work on: current, then lookahead.

    Prefetching the next phase is what prevents a GPU stall at a phase boundary,
    where the mixture changes and no packed data for the new phase exists yet.
    """
    return [p for p in range(current_phase, current_phase + cfg.prefetch_phases) if p < n_phases]


def starved_phase(manifest: Manifest, cfg: FlowConfig, phases: Sequence[int]) -> int | None:
    """The earliest phase below the minimum runway, if any. Collector prioritizes it."""
    for p in phases:
        if manifest.tokens_ready(p) < cfg.packed_min_tokens:
            return p
    return None


def _phase_from_metrics(
    reports_dir: str | Path | None = None,
    preset: str | None = None,
) -> int | None:
    """Best-effort phase from the trainer's metrics jsonl tail."""
    reports = Path(reports_dir or os.environ.get("AVA_REPORTS_DIR", "/reports"))
    preset = preset or os.environ.get("AVA_PRESET", "nano")
    path = reports / f"metrics_{preset}.jsonl"
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - 131_072))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    phase: int | None = None
    for ln in raw.splitlines():
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if row.get("event") in ("step", "phase_enter", "data_starved", "checkpoint"):
            p = row.get("phase")
            if isinstance(p, int):
                phase = p
            elif isinstance(p, float):
                phase = int(p)
    return phase


def current_training_phase(
    manifest: Manifest,
    *,
    reports_dir: str | Path | None = None,
    preset: str | None = None,
) -> int:
    """Phase the trainer is on.

    Preference order:
      1. latest ``runs`` heartbeat (written by ``ava.train``)
      2. tail of ``metrics_{preset}.jsonl`` (works before a trainer restart)
      3. ``$AVA_PHASE``, else 0
    """
    try:
        row = manifest.db.execute(
            "SELECT phase FROM runs ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row is not None and row["phase"] is not None:
            return int(row["phase"])
    except Exception:
        pass
    from_metrics = _phase_from_metrics(reports_dir, preset)
    if from_metrics is not None:
        return from_metrics
    return int(os.environ.get("AVA_PHASE", "0"))


def pick_target_phase(manifest: Manifest, cfg: FlowConfig) -> int:
    """A starved phase (below min runway) beats the trainer's current phase."""
    cur = current_training_phase(manifest)
    phases = prefetch_phases(cur, cfg, N_PHASES)
    starved = starved_phase(manifest, cfg, phases)
    return starved if starved is not None else cur


def curator_claim_phases(manifest: Manifest, cfg: FlowConfig) -> list[int]:
    """Phases a curator should try to claim, in priority order.

    Starved runway first, then the rest of the prefetch window. Older phases
    outside the window are intentionally omitted so curators do not keep packing
    phase-0 while the trainer is starved on phase-3.
    """
    cur = current_training_phase(manifest)
    window = prefetch_phases(cur, cfg, N_PHASES)
    starved = starved_phase(manifest, cfg, window)
    if starved is None:
        return list(window)
    return [starved] + [p for p in window if p != starved]


# ---------------------------------------------------------------------------
# Trainer

def trainer_data_state(
    manifest: Manifest,
    cfg: FlowConfig,
    *,
    phase: int,
    disk_path: str | Path = "/packed",
) -> tuple[DataState, str]:
    fg = free_gb(disk_path)
    if fg < cfg.critical_gb:
        return DataState.CRITICAL_DISK, f"free disk {fg:.1f}GB < critical {cfg.critical_gb}GB"

    ready = manifest.tokens_ready(phase)
    if ready <= 0:
        return DataState.STARVED, f"phase {phase}: no packed tokens ready"
    # Having *some* data is enough to keep stepping; packed_min_tokens is the
    # comfort threshold that tells collectors to hurry, not a hard stop.
    return DataState.READY, f"phase {phase}: {ready/1e6:.0f}M tokens ready"


class StarvationTracker:
    """Rate-limits DATA_STARVED logging and reports sustained starvation.

    A brief starve at a phase boundary is normal. A sustained one means the
    curators cannot keep up and the run should be investigated, not silently
    crawled through.
    """

    def __init__(self, cfg: FlowConfig) -> None:
        self._cfg = cfg
        self._since: float | None = None
        self._last_warn: float = 0.0

    def record(self, starved: bool) -> str | None:
        now = time.monotonic()
        if not starved:
            self._since = None
            return None
        if self._since is None:
            self._since = now
        elapsed = now - self._since
        if elapsed >= self._cfg.starved_warn_seconds and now - self._last_warn >= self._cfg.starved_warn_seconds:
            self._last_warn = now
            return (f"DATA_STARVED for {elapsed:.0f}s -- curators are not keeping up "
                    f"with the trainer. Check `make ps` and curator replica count.")
        return None

    @property
    def starved_seconds(self) -> float:
        return 0.0 if self._since is None else time.monotonic() - self._since


# ---------------------------------------------------------------------------
# Janitor

def janitor_should_collect(cfg: FlowConfig, *, disk_path: str | Path = "/packed") -> PauseReason:
    fg = free_gb(disk_path)
    if fg < cfg.janitor_trigger_gb:
        return PauseReason(True, f"disk {fg:.1f}GB < trigger {cfg.janitor_trigger_gb}GB")
    return PauseReason(False, f"disk {fg:.1f}GB ok")
