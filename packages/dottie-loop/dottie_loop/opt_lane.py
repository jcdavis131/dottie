"""Correctness-gated code-optimization lane (research sequence stage 2).

Speed credit exists only after ``task_ok`` / correctness. Timing is calibrated:
warm-up samples are discarded and the reported value is a robust statistic
(median or quantile), never a one-shot wall clock. Sandbox/environment
provenance is recorded. The report shape is readable by factory gates
(``factory.correctness``, ``factory.speed_credit``).
"""

from __future__ import annotations

import os
import platform
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import digest, new_id, now_iso, sha256_hex
from dottie_loop.schema import active

if TYPE_CHECKING:
    from collections.abc import Callable

MIN_WARMUP = 1
MIN_MEASURED = 3
STATISTICS = ("median", "quantile")
SANDBOX_KINDS = ("local", "factory", "forge", "recorded")


@dataclass
class SandboxProvenance:
    kind: str
    python: str
    platform: str
    hostname_hash: str
    env_names: list[str]
    extra: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if self.kind not in SANDBOX_KINDS:
            raise InvalidInputError(f"unknown sandbox kind {self.kind!r}", field="kind")

    def to_dict(self) -> dict[str, Any]:
        names = list(self.env_names)
        return {
            "kind": self.kind,
            "python": self.python,
            "platform": self.platform,
            "hostname_hash": self.hostname_hash,
            "env_names": names,
            "env_names_digest": digest(names),
            "extra": dict(self.extra),
            "recorded_at": self.recorded_at,
        }


def capture_sandbox(kind: str = "local", extra: dict[str, Any] | None = None) -> SandboxProvenance:
    """Record environment identity without dumping secret values."""
    env_names = sorted(
        k for k in os.environ if k.startswith(("DOTTIE_", "FACTORY_", "CUDA", "TORCH"))
    )
    return SandboxProvenance(
        kind=kind,
        python=sys.version.split()[0],
        platform=platform.platform(),
        hostname_hash=sha256_hex(platform.node())[:16],
        env_names=env_names,
        extra=dict(extra or {}),
    )


def quantile(xs: list[float], q: float) -> float:
    """Linear-interpolation quantile. ``q`` in [0, 1]."""
    if not xs:
        raise InvalidInputError("quantile needs at least one sample", field="samples")
    if not 0.0 <= q <= 1.0:
        raise InvalidInputError("quantile q must be in [0, 1]", field="quantile")
    ys = sorted(xs)
    if q <= 0.0:
        return ys[0]
    if q >= 1.0:
        return ys[-1]
    pos = (len(ys) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ys) - 1)
    frac = pos - lo
    return ys[lo] * (1.0 - frac) + ys[hi] * frac


def median(xs: list[float]) -> float:
    return quantile(xs, 0.5)


def run_calibrated(
    fn: Callable[[], Any],
    *,
    warmup: int,
    repeats: int,
    clock: Callable[[], float] | None = None,
) -> list[float]:
    """Time ``fn`` with discarded warm-ups. ``clock`` is injectable for tests."""
    if warmup < MIN_WARMUP:
        raise InvalidInputError(
            f"warmup must be >= {MIN_WARMUP} (one-shot wall clock is rejected)",
            field="warmup",
        )
    if repeats < MIN_MEASURED:
        raise InvalidInputError(
            f"measured repeats must be >= {MIN_MEASURED} (one-shot wall clock is rejected)",
            field="repeats",
        )
    tick = clock or time.perf_counter
    samples: list[float] = []
    for i in range(warmup + repeats):
        t0 = tick()
        fn()
        dt = tick() - t0
        if dt < 0:
            raise InvalidInputError("clock moved backwards", field="clock")
        if i >= warmup:
            samples.append(dt)
    return samples


def calibrate_timing(
    samples_s: list[float],
    *,
    warmup_n: int,
    statistic: Literal["median", "quantile"] = "median",
    q: float = 0.5,
) -> dict[str, Any]:
    """Reduce already-measured (post-warmup) samples to one robust statistic."""
    if warmup_n < MIN_WARMUP:
        raise InvalidInputError(
            f"warmup_n must be >= {MIN_WARMUP}; one-shot timing is rejected",
            field="warmup_n",
        )
    if len(samples_s) < MIN_MEASURED:
        raise InvalidInputError(
            f"need >= {MIN_MEASURED} measured samples after warmup; one-shot is rejected",
            field="samples_s",
        )
    if any(s < 0 for s in samples_s):
        raise InvalidInputError("samples must be non-negative seconds", field="samples_s")
    if statistic not in STATISTICS:
        raise InvalidInputError(
            f"statistic must be one of {STATISTICS}", field="statistic"
        )
    value = median(samples_s) if statistic == "median" else quantile(samples_s, q)
    return {
        "warmup_n": warmup_n,
        "measured_n": len(samples_s),
        "statistic": statistic,
        "quantile": q if statistic == "quantile" else 0.5,
        "value_s": round(value, 9),
        "samples_s": [round(s, 9) for s in samples_s],
        "warmup_discarded": True,
    }


def speed_percentile(measured_s: float, baseline_s: list[float]) -> float:
    """Fraction of baseline samples slower than ``measured_s``. Higher is faster."""
    if not baseline_s:
        raise InvalidInputError("baseline distribution is required", field="baseline_s")
    if any(s < 0 for s in baseline_s):
        raise InvalidInputError("baseline samples must be non-negative", field="baseline_s")
    return round(sum(1 for b in baseline_s if b > measured_s) / len(baseline_s), 6)


def build_report(
    *,
    task_ok: bool,
    timing: dict[str, Any],
    sandbox: SandboxProvenance | dict[str, Any],
    baseline_s: list[float] | None = None,
    speed_percentile_value: float | None = None,
    trace_id: str | None = None,
    correctness_evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Factory-readable report. Speed credit is zeroed when correctness fails."""
    if not isinstance(task_ok, bool):
        raise InvalidInputError("task_ok must be True or False", field="task_ok")
    if "value_s" not in timing or not timing.get("warmup_discarded"):
        raise InvalidInputError("timing must come from calibrate_timing", field="timing")
    if baseline_s is not None:
        pct = speed_percentile(float(timing["value_s"]), baseline_s)
    elif speed_percentile_value is not None:
        if not 0.0 <= speed_percentile_value <= 1.0:
            raise InvalidInputError(
                "speed_percentile must be in [0, 1]", field="speed_percentile"
            )
        pct = float(speed_percentile_value)
    else:
        pct = None

    correctness = 1.0 if task_ok else 0.0
    rejected = not task_ok
    if rejected:
        speed_credit = 0.0
        reason = "speed:no_credit(correctness failed)"
    elif pct is None:
        speed_credit = None
        reason = "speed:unknown(no baseline)"
    else:
        speed_credit = pct
        reason = "speed:credited(after correctness)"

    sandbox_d = sandbox.to_dict() if isinstance(sandbox, SandboxProvenance) else dict(sandbox)
    report = {
        "schema": active("opt-lane-report"),
        "report_id": new_id("opt_"),
        "trace_id": trace_id,
        "task_ok": task_ok,
        "correctness": correctness,
        "speed_percentile": pct,
        "speed_credit": speed_credit,
        "speed_rejected": rejected,
        "reason": reason,
        "timing": dict(timing),
        "sandbox": sandbox_d,
        "correctness_evidence": list(correctness_evidence or []),
        "factory": {
            "correctness": correctness,
            "speed_percentile": pct,
            "speed_credit": 0.0 if speed_credit is None else speed_credit,
        },
        "computed_at": now_iso(),
    }
    return report


def factory_pass(report: dict[str, Any], *, speed_threshold: float = 0.0) -> dict[str, Any]:
    """Two-metric gate: correctness first, then speed credit.

    A fast-but-wrong report cannot pass. Missing speed after a correct run is
    ``no_metric`` (fail-closed), never an imputed pass.
    """
    correctness = report.get("correctness")
    if correctness != 1.0:
        return {
            "outcome": "fail",
            "metric": "factory.correctness",
            "value": correctness,
            "reason": report.get("reason") or "correctness failed",
        }
    credit = report.get("speed_credit")
    if not isinstance(credit, int | float) or isinstance(credit, bool):
        return {
            "outcome": "no_metric",
            "metric": "factory.speed_credit",
            "value": credit,
            "reason": "speed credit missing after correctness",
        }
    ok = float(credit) >= speed_threshold
    return {
        "outcome": "pass" if ok else "fail",
        "metric": "factory.speed_credit",
        "value": float(credit),
        "threshold": speed_threshold,
        "reason": report.get("reason"),
    }


__all__ = [
    "MIN_MEASURED",
    "MIN_WARMUP",
    "SandboxProvenance",
    "build_report",
    "calibrate_timing",
    "capture_sandbox",
    "factory_pass",
    "median",
    "quantile",
    "run_calibrated",
    "speed_percentile",
]
