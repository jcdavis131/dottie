"""AdvancedIF-style rubric rewards (research sequence stage 1).

A versioned rubric is a list of weighted criteria. A pluggable verifier scores
each criterion; every score is persisted as an audit record. Task success is a
hard gate: rubric quality cannot rescue a failed (or regressed) task.

This module does not call a model. Tests inject a deterministic fake verifier.
The scored quality maps onto :mod:`dottie_loop.reward` the same way a 1–10
verifier score does, after the gate is applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import digest, new_id, now_iso
from dottie_loop.schema import active

if TYPE_CHECKING:
    from collections.abc import Callable

CRITERION_KINDS = (
    "task_success",
    "instruction_follow",
    "multi_turn",
    "system_constraint",
    "format",
    "safety",
    "other",
)
#: Criteria that inspect dialogue history or a system prompt / policy.
COMPLEX_KINDS = frozenset({"multi_turn", "system_constraint"})


@dataclass(frozen=True)
class RubricCriterion:
    criterion_id: str
    kind: str
    text: str
    weight: float = 1.0
    required: bool = False

    def __post_init__(self) -> None:
        if self.kind not in CRITERION_KINDS:
            raise InvalidInputError(
                f"unknown criterion kind {self.kind!r}", field="kind"
            )
        if self.weight <= 0:
            raise InvalidInputError("criterion weight must be positive", field="weight")
        if not self.criterion_id or not self.text.strip():
            raise InvalidInputError("criterion needs an id and text", field="criterion_id")


@dataclass
class Rubric:
    rubric_id: str
    version: str
    name: str
    criteria: list[RubricCriterion]
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.criteria:
            raise InvalidInputError("rubric needs at least one criterion", field="criteria")
        ids = [c.criterion_id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise InvalidInputError("criterion ids must be unique", field="criteria")
        if not _semver(self.version):
            raise InvalidInputError(
                "rubric version must look like <major>.<minor>.<patch>", field="version"
            )

    def digest(self) -> str:
        return digest(
            {
                "rubric_id": self.rubric_id,
                "version": self.version,
                "name": self.name,
                "criteria": [
                    {
                        "criterion_id": c.criterion_id,
                        "kind": c.kind,
                        "text": c.text,
                        "weight": c.weight,
                        "required": c.required,
                    }
                    for c in self.criteria
                ],
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": active("rubric"),
            "rubric_id": self.rubric_id,
            "version": self.version,
            "name": self.name,
            "notes": self.notes,
            "digest": self.digest(),
            "criteria": [
                {
                    "criterion_id": c.criterion_id,
                    "kind": c.kind,
                    "text": c.text,
                    "weight": c.weight,
                    "required": c.required,
                }
                for c in self.criteria
            ],
        }


@dataclass
class Transcript:
    """What the verifier sees: turns, optional system prompt, named constraints."""

    turns: list[dict[str, str]]
    system: str | None = None
    constraints: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turns": list(self.turns),
            "system": self.system,
            "constraints": list(self.constraints),
            "artifacts": dict(self.artifacts),
        }


@dataclass(frozen=True)
class CriterionVerdict:
    score: float
    rationale: str
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise InvalidInputError("criterion score must be in [0, 1]", field="score")


class RubricVerifier(Protocol):
    """Callable/pluggable verifier. Implementations must be deterministic given inputs."""

    def score_criterion(
        self, criterion: RubricCriterion, transcript: Transcript
    ) -> CriterionVerdict: ...


class ScriptedVerifier:
    """Deterministic fake verifier: scores come from a table keyed by criterion id."""

    def __init__(self, scores: dict[str, float], *, rationale: str = "scripted") -> None:
        self.scores = dict(scores)
        self.rationale = rationale
        self.calls: list[str] = []

    def score_criterion(
        self, criterion: RubricCriterion, transcript: Transcript
    ) -> CriterionVerdict:
        self.calls.append(criterion.criterion_id)
        if criterion.criterion_id not in self.scores:
            raise InvalidInputError(
                f"scripted verifier has no score for {criterion.criterion_id!r}",
                field="scores",
            )
        return CriterionVerdict(
            score=float(self.scores[criterion.criterion_id]),
            rationale=self.rationale,
            evidence=[f"transcript_turns={len(transcript.turns)}"],
        )

    def __call__(
        self, criterion: RubricCriterion, transcript: Transcript
    ) -> CriterionVerdict:
        return self.score_criterion(criterion, transcript)


def evaluate_rubric(
    rubric: Rubric,
    transcript: Transcript,
    verifier: RubricVerifier | Callable[[RubricCriterion, Transcript], CriterionVerdict],
    *,
    task_ok: bool | None,
    regression: bool = False,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Score every criterion, persist an audit, then apply the hard task-success gate.

    ``ungated_score`` is the weighted mean of criterion scores. ``gated_score`` is
    0 when ``task_ok`` is false or a regression is recorded; None when task
    success is unknown. Required criteria that score 0 fail the rubric itself,
    but still cannot override a task failure (the gate wins).
    """
    audits: list[dict[str, Any]] = []
    required_failed: list[str] = []
    weighted = 0.0
    weight_sum = 0.0
    for criterion in rubric.criteria:
        verdict = _invoke_verifier(verifier, criterion, transcript)
        audits.append(
            {
                "criterion_id": criterion.criterion_id,
                "kind": criterion.kind,
                "weight": criterion.weight,
                "required": criterion.required,
                "score": verdict.score,
                "rationale": verdict.rationale,
                "evidence": list(verdict.evidence),
            }
        )
        weighted += criterion.weight * verdict.score
        weight_sum += criterion.weight
        if criterion.required and verdict.score <= 0.0:
            required_failed.append(criterion.criterion_id)

    ungated = round(weighted / weight_sum, 6) if weight_sum else None
    task_success = task_ok is True and not regression
    if task_ok is None:
        gated: float | None = None
        gate = "unknown"
    elif not task_success:
        gated = 0.0
        gate = "task_failed" if not regression else "regression"
    else:
        gated = ungated
        gate = "open"

    return {
        "schema": active("rubric-eval"),
        "eval_id": new_id("rubric_"),
        "trace_id": trace_id,
        "rubric_id": rubric.rubric_id,
        "rubric_version": rubric.version,
        "rubric_digest": rubric.digest(),
        "task_ok": task_ok,
        "regression": bool(regression),
        "task_success": task_success,
        "gate": gate,
        "ungated_score": ungated,
        "gated_score": gated,
        "required_failed": required_failed,
        "audits": audits,
        "complex_kinds_scored": sorted(
            {a["kind"] for a in audits if a["kind"] in COMPLEX_KINDS}
        ),
        "computed_at": now_iso(),
    }


def slice_scores(evals: list[dict[str, Any]]) -> dict[str, float]:
    """Mean gated criterion score by kind — suitable for EvalBundle.slice_results."""
    buckets: dict[str, list[float]] = {}
    for ev in evals:
        gate = 1.0 if ev.get("task_success") else 0.0
        for a in ev.get("audits") or []:
            buckets.setdefault(a["kind"], []).append(float(a["score"]) * gate)
    return {k: round(sum(v) / len(v), 6) for k, v in sorted(buckets.items()) if v}


def quality_for_reward(
    rubric_eval: dict[str, Any],
) -> tuple[float | None, list[str]]:
    """Map a rubric eval onto the §22 verifier scale (1–10).

    Task failure / regression → 1.0 (zero quality credit). Unknown task → None.
    """
    if rubric_eval.get("task_ok") is None:
        return None, ["quality:unknown(no valid task_ok); rubric withheld"]
    if not rubric_eval.get("task_success"):
        why = "regression" if rubric_eval.get("regression") else "task not successful"
        return 1.0, [f"quality:no_credit({why}); rubric cannot override"]
    raw = rubric_eval.get("gated_score")
    if raw is None:
        return None, ["quality:unknown"]
    if not 0.0 <= float(raw) <= 1.0:
        raise InvalidInputError("gated_score must be in [0, 1]", field="gated_score")
    score_10 = round(1.0 + 9.0 * float(raw), 6)
    return score_10, [
        f"quality:rubric {float(raw):.4f}/1 ({rubric_eval.get('rubric_version', 'unversioned')})"
    ]


def _invoke_verifier(
    verifier: RubricVerifier | Callable[[RubricCriterion, Transcript], CriterionVerdict],
    criterion: RubricCriterion,
    transcript: Transcript,
) -> CriterionVerdict:
    if callable(verifier) and not hasattr(verifier, "score_criterion"):
        out = verifier(criterion, transcript)
    else:
        out = verifier.score_criterion(criterion, transcript)
    if not isinstance(out, CriterionVerdict):
        raise InvalidInputError("verifier must return a CriterionVerdict", field="verifier")
    return out


def _semver(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 3 and all(p.isdigit() for p in parts)


__all__ = [
    "COMPLEX_KINDS",
    "CRITERION_KINDS",
    "CriterionVerdict",
    "Rubric",
    "RubricCriterion",
    "RubricVerifier",
    "ScriptedVerifier",
    "Transcript",
    "evaluate_rubric",
    "quality_for_reward",
    "slice_scores",
]
