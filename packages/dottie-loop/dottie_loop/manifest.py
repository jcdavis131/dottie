"""Two-arm experiment evidence (research learning, JustVugg/colibri).

colibri (github.com/JustVugg/colibri) enforces one rule mechanically, in
``c/experiment_manifest.py``: a speed claim is filed only as a record whose
headline numbers a reader can re-derive from raw evidence the record itself
carries — full 40-hex commit, three or more raw samples per arm, a median
computed from those samples (never a claimed one), the changed configuration
key computed from a diff of the two arms (never declared), and a passing
named correctness gate. Its own tree shows the soft spots: a claimed outcome
is never checked against the derived direction, a failed trial arm cannot be
filed at all, and run order is not recorded, so two runs an hour apart can
be reported as one comparison.

This module ports the rule, not the prose, and closes those two spots:

* Every headline number here is a COMPUTED property, never an input field.
  There is no "claimed median" or "claimed changed variable" to disagree
  with the data, because the record does not accept one.
* A failed trial arm is still filed (negative results are first-class); a
  failed BASELINE arm is refused, because a broken baseline measures
  nothing. ``gate_eligible`` is false whenever either arm failed its
  correctness check.
* Run order is required to know whether the two arms were interleaved
  (colibri's own experiment log: two identical runs on a quiet box differed
  by 38.8%; an unpaired sweep disagreed about the SIGN of an effect that
  seven-of-eight alternating pairs resolved). A blocked or unrecorded order
  is filed but never gate-eligible.

No model is called anywhere in this module. It reduces the lists it is
given; it does not run a benchmark, a training job, or an inference engine.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import digest, new_id, now_iso
from dottie_loop.opt_lane import MIN_MEASURED
from dottie_loop.schema import active

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: colibri's own floor ("at least three raw throughput samples per arm").
#: Below it a record is not merely underpowered, it is not admissible.
MIN_ARM_SAMPLES = MIN_MEASURED

#: A commit must be a full git SHA (colibri: "commit must be a full
#: 40-character git SHA"); a short SHA is not an identity, it is a guess.
_COMMIT_LEN = 40

#: An arm's run-order label repeated this many times in a row still counts
#: as interleaved (ABBA, like colibri's own alternating-pair control); a
#: longer run is a blocked order — one arm measured before the other, which
#: colibri's own tuning notes call unable to separate drift from effect.
MAX_INTERLEAVED_RUN = 2

ARM_NAMES = ("baseline", "trial")


def _finite_positive_samples(xs: Sequence[float], *, field_name: str) -> tuple[float, ...]:
    if not isinstance(xs, (list, tuple)) or len(xs) < MIN_ARM_SAMPLES:
        raise InvalidInputError(
            f"{field_name} needs at least {MIN_ARM_SAMPLES} raw samples", field=field_name
        )
    out = []
    for x in xs:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise InvalidInputError(f"{field_name} values must be numbers", field=field_name)
        v = float(x)
        if not math.isfinite(v) or v <= 0:
            raise InvalidInputError(
                f"{field_name} values must be finite and positive", field=field_name
            )
        out.append(v)
    return tuple(out)


def _hex(value: object, *, length: int, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != length:
        raise InvalidInputError(f"{field_name} must be {length} hex characters", field=field_name)
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise InvalidInputError(f"{field_name} must be hexadecimal", field=field_name) from exc
    return value.lower()


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(f"{field_name} must be a non-empty string", field=field_name)
    return value


@dataclass(frozen=True)
class ExperimentArm:
    """One side of a two-arm comparison. Every summary number below is
    computed from ``raw_samples``; nothing here is a caller-supplied claim.
    """

    commit: str
    config: Mapping[str, Any]
    raw_samples: tuple[float, ...]
    quality_method: str
    quality_passed: bool
    evidence_uri: str
    evidence_sha256: str
    dirty_tree: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "commit", _hex(self.commit, length=_COMMIT_LEN, field_name="commit"))
        if not isinstance(self.config, dict):
            object.__setattr__(self, "config", dict(self.config))
        object.__setattr__(
            self, "raw_samples", _finite_positive_samples(self.raw_samples, field_name="raw_samples")
        )
        _text(self.quality_method, field_name="quality_method")
        if not isinstance(self.quality_passed, bool):
            raise InvalidInputError("quality_passed must be a bool", field="quality_passed")
        _text(self.evidence_uri, field_name="evidence_uri")
        object.__setattr__(
            self, "evidence_sha256", _hex(self.evidence_sha256, length=64, field_name="evidence_sha256")
        )
        if self.dirty_tree:
            raise InvalidInputError(
                "an arm measured against a dirty working tree cannot be filed as evidence",
                field="dirty_tree",
            )

    @property
    def n(self) -> int:
        return len(self.raw_samples)

    @property
    def median(self) -> float:
        """Re-derived from ``raw_samples``, per run — never a stored claim."""
        return statistics.median(self.raw_samples)

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "config": dict(self.config),
            "raw_samples": list(self.raw_samples),
            "n": self.n,
            "median": self.median,
            "quality": {"method": self.quality_method, "passed": self.quality_passed},
            "evidence": {"uri": self.evidence_uri, "sha256": self.evidence_sha256},
        }


def _config_diff(baseline: Mapping[str, Any], trial: Mapping[str, Any]) -> tuple[str, ...]:
    keys = sorted(set(baseline) | set(trial))
    _missing = object()
    return tuple(k for k in keys if baseline.get(k, _missing) != trial.get(k, _missing))


def order_kind(run_order: Sequence[str]) -> str:
    """Classify a run-order sequence: ``interleaved``, ``blocked`` or
    ``not_recorded``. Never inferred from anything but the sequence given.
    """
    if not run_order:
        return "not_recorded"
    run_len = 1
    for prev, cur in pairwise(run_order):
        run_len = run_len + 1 if cur == prev else 1
        if run_len > MAX_INTERLEAVED_RUN:
            return "blocked"
    return "interleaved"


@dataclass(frozen=True)
class ExperimentManifest:
    """A filed, two-arm comparison. Construction never raises on a losing
    or failed TRIAL arm (negative results are first-class); it raises only
    on structural defects (bad commit, too few samples, a failed baseline,
    a dirty tree) that make the record unreviewable, never on the verdict.
    """

    hypothesis: str
    baseline: ExperimentArm
    trial: ExperimentArm
    lower_is_better: bool = True
    run_order: tuple[str, ...] = ()
    manifest_id: str = field(default_factory=lambda: new_id("man_"))
    created_at: str = field(default_factory=now_iso)
    version: int = 1

    def __post_init__(self) -> None:
        _text(self.hypothesis, field_name="hypothesis")
        if self.version != 1:
            raise InvalidInputError("version must be 1", field="version")
        if not self.baseline.quality_passed:
            raise InvalidInputError(
                "a baseline arm that failed its own correctness check measures nothing",
                field="baseline.quality_passed",
            )
        if self.run_order:
            counts = {name: self.run_order.count(name) for name in ARM_NAMES}
            unknown = set(self.run_order) - set(ARM_NAMES)
            if unknown:
                raise InvalidInputError(
                    f"run_order names must be in {ARM_NAMES}, got {sorted(unknown)}",
                    field="run_order",
                )
            if counts["baseline"] != self.baseline.n or counts["trial"] != self.trial.n:
                raise InvalidInputError(
                    "run_order must name each arm exactly as many times as it has samples",
                    field="run_order",
                )

    @property
    def order_kind(self) -> str:
        return order_kind(self.run_order)

    @property
    def changed_variables(self) -> tuple[str, ...]:
        """Computed from the two arms' config, never declared by a caller."""
        return _config_diff(self.baseline.config, self.trial.config)

    @property
    def quality_ok(self) -> bool:
        return self.baseline.quality_passed and self.trial.quality_passed

    @property
    def delta(self) -> float:
        return self.trial.median - self.baseline.median

    @property
    def direction(self) -> str:
        if self.delta == 0:
            return "tie"
        trial_better = (self.delta < 0) if self.lower_is_better else (self.delta > 0)
        return "trial_better" if trial_better else "baseline_better"

    @property
    def gate_eligible(self) -> bool:
        """Correctness first, mechanically: a failed trial or an
        unrecorded/blocked run order can never pass a gate, whatever the
        medians say."""
        return self.quality_ok and self.order_kind == "interleaved"

    @property
    def pair_wins(self) -> dict[str, int] | None:
        """Wins/losses/ties counted from same-length, interleaved samples
        in their recorded run order. ``None`` — never a fabricated zero —
        when pairing is not possible (unequal n or not interleaved)."""
        if self.order_kind != "interleaved" or self.baseline.n != self.trial.n:
            return None
        wins = losses = ties = 0
        for b, t in zip(self.baseline.raw_samples, self.trial.raw_samples, strict=True):
            if b == t:
                ties += 1
                continue
            trial_won = (t < b) if self.lower_is_better else (t > b)
            wins, losses = (wins + 1, losses) if trial_won else (wins, losses + 1)
        return {"wins": wins, "losses": losses, "ties": ties, "n_pairs": len(self.baseline.raw_samples)}

    def summary(self) -> dict[str, Any]:
        return {
            "schema": active("experiment-manifest"),
            "manifest_id": self.manifest_id,
            "created_at": self.created_at,
            "hypothesis": self.hypothesis,
            "lower_is_better": self.lower_is_better,
            "changed_variables": list(self.changed_variables),
            "run_order_kind": self.order_kind,
            "quality_ok": self.quality_ok,
            "gate_eligible": self.gate_eligible,
            "direction": self.direction,
            "delta": self.delta,
            "baseline_median": self.baseline.median,
            "trial_median": self.trial.median,
            "n": {"baseline": self.baseline.n, "trial": self.trial.n},
            "pair_wins": self.pair_wins,
        }

    def to_dict(self) -> dict[str, Any]:
        body = self.summary()
        body["baseline"] = self.baseline.to_dict()
        body["trial"] = self.trial.to_dict()
        body["content_sha256"] = digest(
            {"hypothesis": self.hypothesis, "baseline": body["baseline"], "trial": body["trial"],
             "run_order": list(self.run_order)}
        )
        return body
