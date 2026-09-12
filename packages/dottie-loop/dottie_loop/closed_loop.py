"""Closed-loop automation (spec §26, §37C LoopDecision).

Fresh evidence may trigger retraining; it may not trigger authority. The trigger
evaluates freshness PER METRIC SOURCE by event time (never file mtime), applies the
threshold predicates, enforces a single retraining lease and a cooldown measured
from the prior run's terminal timestamp, and emits a LoopDecision even when
nothing changes. ``--promote`` without ``--approve-prod`` exits without production
change; even with approval the trigger writes a record only.
"""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import BlockedError
from dottie_loop.hashing import age_seconds, new_id, now_iso, parse_iso
from dottie_loop.schema import active

if TYPE_CHECKING:
    from collections.abc import Iterator

#: §26 trigger thresholds — data, so they are auditable and changeable as config.
THRESHOLDS: dict[str, float] = {
    "verifier_score_min": 8.0,
    "agent_ok_rate_min": 0.90,
    "ok_rate_drop_max": 0.05,
    "eval_drop_max": 0.02,
    "new_verified_traces_min": 500,
    "canary_floor_delta": 0.01,
    "cooldown_hours": 24,
    "freshness_hours": 48,
}

REQUIRED_SOURCES = ("verifier", "agent_ok", "eval", "traces")


@dataclass
class MetricSource:
    name: str
    value: float
    event_time: str
    provenance: str = "measured"  # measured | synthetic | mock | unversioned
    version: str | None = None


@dataclass
class Lease:
    owner: str
    started_at: str
    heartbeat_at: str
    expires_at: str

    def live(self, now: datetime) -> bool:
        return parse_iso(self.expires_at) > now


class LeaseFile:
    """A single active retraining lease on disk (§26 "Concurrency and cooldown").

    Records owner, start, heartbeat and expiry. A crashed job may be reclaimed only
    after its expiry has passed AND no live runner heartbeat exists — the caller
    passes the set of live runner names it can actually see.
    """

    def __init__(self, path: Path, ttl_seconds: int = 3600) -> None:
        self.path = Path(path)
        self.ttl = ttl_seconds

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Exclusive inter-process lock spanning the whole read-check-write.

        Without this, two trainers starting at once could both read "no lease"
        and both acquire. The lock file is a sidecar so it exists even when
        the lease itself does not yet.
        """
        lock_path = self.path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def read(self) -> Lease | None:
        if not self.path.exists():
            return None
        d = json.loads(self.path.read_text(encoding="utf-8"))
        return Lease(**d)

    def _write(self, lease: Lease) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(lease.__dict__, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def acquire(self, owner: str, *, now: datetime | None = None, live_runners: set[str] | None = None) -> Lease:
        now = now or datetime.now(UTC)
        with self._locked():
            cur = self.read()
            if cur is not None:
                if cur.live(now):
                    raise BlockedError(f"active retraining lease held by {cur.owner} until {cur.expires_at}", "lease")
                if cur.owner in (live_runners or set()):
                    raise BlockedError(f"lease expired but runner {cur.owner} is still live; not reclaiming", "lease")
            iso = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            exp = (now + timedelta(seconds=self.ttl)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            lease = Lease(owner=owner, started_at=iso, heartbeat_at=iso, expires_at=exp)
            self._write(lease)
            return lease

    def heartbeat(self, owner: str, *, now: datetime | None = None) -> Lease:
        now = now or datetime.now(UTC)
        with self._locked():
            cur = self.read()
            if cur is None or cur.owner != owner:
                raise BlockedError("heartbeat from a non-owner", "lease")
            cur.heartbeat_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            cur.expires_at = (now + timedelta(seconds=self.ttl)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            self._write(cur)
            return cur

    def release(self, owner: str, *, terminal_at: str | None = None) -> dict[str, Any]:
        with self._locked():
            cur = self.read()
            if cur is None or cur.owner != owner:
                raise BlockedError("release from a non-owner", "lease")
            self.path.unlink()
            # cooldown starts from the TERMINAL timestamp, which the caller persists
            return {"released": owner, "terminal_at": terminal_at or now_iso()}


def validate_freshness(sources: dict[str, MetricSource], now: datetime) -> list[str]:
    """Names every stale/missing/synthetic/mock/unversioned required source."""
    blockers: list[str] = []
    limit = THRESHOLDS["freshness_hours"] * 3600
    for name in REQUIRED_SOURCES:
        src = sources.get(name)
        if src is None:
            blockers.append(f"{name}: missing")
            continue
        if src.provenance in ("synthetic", "mock"):
            blockers.append(f"{name}: {src.provenance} evidence is not evidence")
        if src.provenance == "unversioned" or not src.version:
            blockers.append(f"{name}: unversioned")
        try:
            age = age_seconds(src.event_time, now)
        except ValueError:
            blockers.append(f"{name}: unparseable event time")
            continue
        if age > limit:
            blockers.append(f"{name}: stale ({age / 3600:.1f}h > {THRESHOLDS['freshness_hours']}h)")
    return blockers


def evaluate_trigger(
    sources: dict[str, MetricSource],
    *,
    baseline: dict[str, float],
    lease: Lease | None,
    last_terminal_at: str | None,
    canary: dict[str, float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """collect → validate freshness → evaluate predicates → no_change | blocked | trigger."""
    now = now or datetime.now(UTC)
    blockers = validate_freshness(sources, now)
    if lease is not None and lease.live(now):
        blockers.append(f"active retraining lease held by {lease.owner}")
    if last_terminal_at:
        cooldown = timedelta(hours=THRESHOLDS["cooldown_hours"])
        if parse_iso(last_terminal_at) + cooldown > now:
            blockers.append("cooldown not elapsed since prior terminal timestamp")
    predicates: dict[str, bool] = {}
    if not blockers:
        v = sources["verifier"].value
        ok = sources["agent_ok"].value
        ev = sources["eval"].value
        n = sources["traces"].value
        predicates = {
            "verifier_below_min": v < THRESHOLDS["verifier_score_min"],
            "ok_rate_below_floor": ok < THRESHOLDS["agent_ok_rate_min"],
            "ok_rate_drop": (baseline.get("agent_ok", ok) - ok) > THRESHOLDS["ok_rate_drop_max"],
            "eval_drop": (baseline.get("eval", ev) - ev) > THRESHOLDS["eval_drop_max"],
            "enough_new_traces": n >= THRESHOLDS["new_verified_traces_min"],
        }
        if canary is not None:
            predicates["canary_below_floor"] = canary.get("challenger", 0.0) < canary.get("baseline", 0.0) - THRESHOLDS["canary_floor_delta"]
    regression = any(predicates.get(k) for k in ("verifier_below_min", "ok_rate_below_floor", "ok_rate_drop", "eval_drop"))
    if blockers:
        decision = "blocked"
    elif regression and predicates["enough_new_traces"]:
        decision = "trigger"
    elif regression:
        decision = "blocked"
        blockers.append(f"regression observed but only {int(sources['traces'].value)} new verified traces (< {int(THRESHOLDS['new_verified_traces_min'])})")
    else:
        decision = "no_change"
    return {
        "schema": active("loop-decision"),
        "decision_id": new_id("loop_"),
        "decision": decision,
        "metric_sources": {k: {"value": s.value, "event_time": s.event_time, "provenance": s.provenance, "version": s.version} for k, s in sources.items()},
        "baseline": baseline,
        "thresholds": dict(THRESHOLDS),
        "predicates": predicates,
        "trace_count": sources["traces"].value if "traces" in sources else None,
        "cooldown_from": last_terminal_at,
        "lease": None if lease is None else {"owner": lease.owner, "live": lease.live(now)},
        "canary": canary,
        "blockers": blockers,
        "at": now_iso(),
    }


def promote_guard(*, promote: bool, approve_prod: bool, decision: dict[str, Any]) -> dict[str, Any]:
    """``--promote`` without ``--approve-prod`` exits without production change.

    Even with approval this writes a RECORD only; deployment is an operator action.
    """
    if not promote:
        return {"production_change": False, "record": None, "reason": "promotion not requested"}
    if not approve_prod:
        return {"production_change": False, "record": None, "reason": "promotion requested without --approve-prod; exiting without production change"}
    if decision.get("decision") != "trigger":
        return {"production_change": False, "record": None, "reason": f"loop decision is {decision.get('decision')}, not trigger"}
    return {
        "production_change": False,
        "record": {"kind": "promotion_packet", "decision_id": decision["decision_id"], "requires": "operator deployment after approval", "at": now_iso()},
        "reason": "promotion record written; deployment is a separate operator action",
    }


def write_decision(decision: dict[str, Any], path: Path) -> None:
    """LoopDecision is emitted even when nothing changes; append-only JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(decision, sort_keys=True) + "\n")


def load_sources(path: Path) -> dict[str, MetricSource]:
    """Read ``{"name": {"value", "event_time", "provenance", "version"}}`` from JSON."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: MetricSource(name=k, value=float(v["value"]), event_time=v["event_time"], provenance=v.get("provenance", "unversioned"), version=v.get("version")) for k, v in raw.items()}
