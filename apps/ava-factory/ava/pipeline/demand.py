"""Train → data demand channel (closed-loop actuator signal).

Only collectors fetch outside information. The trainer publishes a small
``demand.json`` snapshot that collectors/curators poll — expand / curate /
examples — without the GPU process ever touching the network.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ava.pipeline.flow import FlowConfig, N_PHASES, prefetch_phases

_DEFAULT_DEMAND = "/state/demand.json"


def demand_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("AVA_DEMAND_PATH")
    if env:
        return Path(env)
    db = os.environ.get("AVA_STATE_DB", "/state/manifest.db")
    return Path(db).resolve().parent / "demand.json"


@dataclass(frozen=True)
class PhaseDemand:
    phase: int
    tokens_ready: int
    packed_min: int
    deficit: int
    effort: float
    actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class DemandSnapshot:
    ts: float
    step: int
    trainer_phase: int
    preset: str
    phases: tuple[PhaseDemand, ...]
    boost_task_types: Mapping[str, float] = field(default_factory=dict)
    curate_stricter: bool = False
    reasons: tuple[str, ...] = ()
    schema: int = 1

    def effort_map(self) -> dict[int, float]:
        return {p.phase: p.effort for p in self.phases}

    def actions_for(self, phase: int) -> tuple[str, ...]:
        for p in self.phases:
            if p.phase == phase:
                return p.actions
        return ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ts": self.ts,
            "step": self.step,
            "trainer_phase": self.trainer_phase,
            "preset": self.preset,
            "phases": [asdict(p) for p in self.phases],
            "boost_task_types": dict(self.boost_task_types),
            "curate_stricter": self.curate_stricter,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "DemandSnapshot":
        phases = tuple(
            PhaseDemand(
                phase=int(p["phase"]),
                tokens_ready=int(p["tokens_ready"]),
                packed_min=int(p["packed_min"]),
                deficit=int(p["deficit"]),
                effort=float(p["effort"]),
                actions=tuple(p.get("actions") or ()),
            )
            for p in (d.get("phases") or [])
        )
        return cls(
            ts=float(d.get("ts") or 0),
            step=int(d.get("step") or 0),
            trainer_phase=int(d.get("trainer_phase") or 0),
            preset=str(d.get("preset") or ""),
            phases=phases,
            boost_task_types={str(k): float(v) for k, v in (d.get("boost_task_types") or {}).items()},
            curate_stricter=bool(d.get("curate_stricter")),
            reasons=tuple(d.get("reasons") or ()),
            schema=int(d.get("schema") or 1),
        )


def compute_demand(
    *,
    tokens_ready_by_phase: Mapping[int, int] | Mapping[str, int],
    cfg: FlowConfig,
    trainer_phase: int,
    step: int = 0,
    preset: str = "",
    failed_shards: int = 0,
    active_shards: int = 1,
    lm_trend: float | None = None,
    now: float | None = None,
) -> DemandSnapshot:
    """Derive expand/curate/examples from runway + light training signals.

    ``lm_trend`` > 0 means recent lm_loss is rising (need more / better examples).
    """
    ready: dict[int, int] = {}
    for k, v in tokens_ready_by_phase.items():
        ready[int(k)] = int(v)

    window = prefetch_phases(trainer_phase, cfg, N_PHASES)
    packed_min = int(cfg.packed_min_tokens)
    deficits: dict[int, int] = {}
    for p in range(N_PHASES):
        tok = ready.get(p, 0)
        deficits[p] = max(0, packed_min - tok) if p in window else 0

    total_def = sum(deficits.values()) or 1
    reasons: list[str] = []
    phase_rows: list[PhaseDemand] = []
    boost: dict[str, float] = {}
    curate = False

    fail_frac = failed_shards / max(1, active_shards)
    if fail_frac >= 0.15:
        curate = True
        reasons.append(f"fail_frac={fail_frac:.0%} → curate")

    if lm_trend is not None and lm_trend > 0:
        boost["deliberate"] = 1.5
        boost["automatic"] = 1.2
        reasons.append(f"lm_trend={lm_trend:+.4f} → examples")

    for p in range(N_PHASES):
        tok = ready.get(p, 0)
        deficit = deficits[p]
        actions: list[str] = []
        if deficit > 0:
            actions.append("expand")
            if p == trainer_phase:
                reasons.append(f"P{p} deficit {deficit/1e6:.0f}M tok → expand")
        if curate and p in window:
            actions.append("curate")
        if p in window and "deliberate" in boost:
            actions.append("examples")
        effort = (deficit / total_def) if total_def else 0.0
        # Keep a floor on the trainer phase so miners never idle the GPU phase.
        if p == trainer_phase and effort < 0.15 and tok < packed_min * 2:
            effort = max(effort, 0.15)
        phase_rows.append(PhaseDemand(
            phase=p,
            tokens_ready=tok,
            packed_min=packed_min,
            deficit=deficit,
            effort=round(effort, 4),
            actions=tuple(dict.fromkeys(actions)),
        ))

    if not reasons:
        reasons.append("runway healthy — maintain mixture")

    return DemandSnapshot(
        ts=float(now if now is not None else time.time()),
        step=step,
        trainer_phase=trainer_phase,
        preset=preset,
        phases=tuple(phase_rows),
        boost_task_types=boost,
        curate_stricter=curate,
        reasons=tuple(reasons),
    )


def write_demand(snapshot: DemandSnapshot, path: str | Path | None = None) -> Path:
    """Atomic JSON write so readers never see a partial file."""
    dest = demand_path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(prefix="demand.", suffix=".json", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return dest


def read_demand(path: str | Path | None = None) -> DemandSnapshot | None:
    p = demand_path(path)
    if not p.is_file():
        return None
    try:
        return DemandSnapshot.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def apply_demand_weights(
    base_weights: Sequence[tuple[str, float]],
    *,
    source_task_types: Mapping[str, str],
    demand: DemandSnapshot | None,
    phase: int,
) -> list[tuple[str, float]]:
    """Reweight collector mixture from demand (expand + examples).

    Returns a new list; never mutates ``base_weights``. If demand is missing,
    returns the base mixture unchanged.
    """
    if demand is None or not base_weights:
        return [(n, float(w)) for n, w in base_weights]

    effort = demand.effort_map().get(phase, 0.0)
    actions = set(demand.actions_for(phase))
    expand_mult = 1.0 + 2.0 * effort if "expand" in actions else 1.0 + effort
    boost = demand.boost_task_types

    out: list[tuple[str, float]] = []
    for name, w in base_weights:
        mult = expand_mult
        tt = source_task_types.get(name, "automatic")
        if "examples" in actions and tt in boost:
            mult *= float(boost[tt])
        out.append((name, max(1e-6, float(w) * mult)))
    return out
