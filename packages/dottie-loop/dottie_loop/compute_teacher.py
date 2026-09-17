"""Compute-as-Teacher offline synthesis (research sequence stage 4).

A teacher trace records *how* compute was spent (search steps, proof steps,
verifier outcomes), not only the final answer. This module packs those traces
into an offline shard the closed-loop / factory trainer can consume later.
There is no live teacher at train time and no training run here.

Fail-closed: missing teacher artifacts, empty traces, or a schema mismatch
produce a typed error or a blocked pack — never an imputed success. A long
trace cannot raise quality when the attached task failed. Raw tool secrets
are refused (reuse :mod:`dottie_loop.capture` redaction + consent).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dottie_loop.capture import export_eligibility, redact_obj, redact_record
from dottie_loop.errors import InvalidInputError, PolicyDeniedError, UnexecutableError
from dottie_loop.hashing import digest, new_id, now_iso
from dottie_loop.schema import active, check_compatible, parse_schema

STEP_KINDS = ("search", "proof", "test", "tool", "other")
STEP_OUTCOMES = ("pass", "fail", "unknown", "skipped")
ATTACH_SCHEMAS = frozenset({"rubric-eval", "opt-lane-report"})
ARTIFACT_KINDS = ("search_tree", "proof_log", "unit_tests", "tool_trace")


@dataclass(frozen=True)
class ComputeStep:
    step_id: str
    kind: str
    outcome: str
    parent_id: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise InvalidInputError(f"unknown compute-step kind {self.kind!r}", field="kind")
        if self.outcome not in STEP_OUTCOMES:
            raise InvalidInputError(f"unknown compute-step outcome {self.outcome!r}", field="outcome")
        if not self.step_id.strip():
            raise InvalidInputError("compute step needs an id", field="step_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "outcome": self.outcome,
            "parent_id": self.parent_id,
            "detail": self.detail,
        }


@dataclass
class ComputeTrace:
    """Content-addressed teacher trace: steps, branching, verifier outcomes."""

    trace_id: str
    steps: list[ComputeStep]
    verifier_outcomes: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.trace_id.strip():
            raise InvalidInputError("compute trace needs a trace_id", field="trace_id")
        if not self.steps:
            raise InvalidInputError("compute trace has no steps", field="steps")
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise InvalidInputError("compute step ids must be unique", field="steps")
        known = set(ids)
        for step in self.steps:
            if step.parent_id is not None and step.parent_id not in known:
                raise InvalidInputError(
                    f"parent_id {step.parent_id!r} is not a step on this trace",
                    field="parent_id",
                )

    def branching(self) -> dict[str, Any]:
        children: dict[str | None, list[str]] = {}
        for step in self.steps:
            children.setdefault(step.parent_id, []).append(step.step_id)
        branch_nodes = {k: v for k, v in children.items() if k is not None and len(v) > 1}
        return {
            "n_steps": len(self.steps),
            "n_branch_nodes": len(branch_nodes),
            "max_fanout": max((len(v) for v in children.values()), default=0),
        }

    def digest(self) -> str:
        return digest(
            {
                "trace_id": self.trace_id,
                "steps": [s.to_dict() for s in self.steps],
                "verifier_outcomes": list(self.verifier_outcomes),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": active("compute-trace"),
            "trace_id": self.trace_id,
            "digest": self.digest(),
            "steps": [s.to_dict() for s in self.steps],
            "verifier_outcomes": list(self.verifier_outcomes),
            "branching": self.branching(),
            "notes": self.notes,
        }


@dataclass
class TeacherConfig:
    """Operator hooks for the offline pack. Defaults fail closed."""

    require_artifacts: bool = True
    require_consent: bool = True
    require_redaction: bool = True
    allow_empty: bool = False
    allow_live_teacher: bool = False


@dataclass
class TeacherRecord:
    """A packed teacher artifact bound to one compute trace."""

    teacher_id: str
    compute_trace_id: str
    artifact_kind: str
    artifact_digest: str
    task_ok: bool | None = None

    def __post_init__(self) -> None:
        if self.artifact_kind not in ARTIFACT_KINDS:
            raise InvalidInputError(
                f"unknown teacher artifact kind {self.artifact_kind!r}", field="artifact_kind"
            )
        if not self.teacher_id.strip() or not self.compute_trace_id.strip():
            raise InvalidInputError("teacher record needs teacher_id and compute_trace_id", field="teacher_id")
        if not self.artifact_digest.strip():
            raise InvalidInputError("teacher artifact digest is required", field="artifact_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": active("teacher-record"),
            "teacher_id": self.teacher_id,
            "compute_trace_id": self.compute_trace_id,
            "artifact_kind": self.artifact_kind,
            "artifact_digest": self.artifact_digest,
            "task_ok": self.task_ok,
        }


def parse_trace(raw: dict[str, Any]) -> ComputeTrace:
    """Load a compute-trace dict. Unknown/wrong schema fails closed."""
    if not isinstance(raw, dict):
        raise InvalidInputError("compute trace must be an object", field="trace")
    if "schema" in raw:
        check_compatible(raw["schema"], "compute-trace")
    steps_raw = raw.get("steps")
    if not steps_raw:
        raise InvalidInputError("compute trace has no steps", field="steps")
    steps = [s if isinstance(s, ComputeStep) else ComputeStep(**_step_kwargs(s)) for s in steps_raw]
    return ComputeTrace(
        trace_id=str(raw.get("trace_id") or ""),
        steps=steps,
        verifier_outcomes=list(raw.get("verifier_outcomes") or []),
        notes=str(raw.get("notes") or ""),
    )


def _step_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {"step_id", "kind", "outcome", "parent_id", "detail"}
    return {k: raw[k] for k in raw if k in allowed}


def attach_teacher(
    record: dict[str, Any],
    teacher: TeacherRecord | dict[str, Any],
) -> dict[str, Any]:
    """Bind a teacher record to a rubric-eval or opt-lane-report.

    Attachment is allowed only when ``task_ok`` is true. A failed task cannot
    earn teacher credit from a long compute trace.
    """
    schema = record.get("schema")
    if not isinstance(schema, str):
        raise InvalidInputError("attach target needs a schema", field="schema")
    rec_name, *_ = parse_schema(schema)
    if rec_name not in ATTACH_SCHEMAS:
        raise InvalidInputError(
            f"teacher records attach only to {sorted(ATTACH_SCHEMAS)}", field="schema"
        )
    if record.get("task_ok") is not True:
        raise InvalidInputError(
            "teacher record may attach only when task_ok is true", field="task_ok"
        )
    teacher_d = teacher.to_dict() if isinstance(teacher, TeacherRecord) else dict(teacher)
    if teacher_d.get("schema"):
        check_compatible(teacher_d["schema"], "teacher-record")
    if teacher_d.get("task_ok") is False:
        raise InvalidInputError(
            "teacher record task_ok is false; cannot attach", field="task_ok"
        )
    out = dict(record)
    out["teacher_record"] = {
        "teacher_id": teacher_d.get("teacher_id"),
        "compute_trace_id": teacher_d.get("compute_trace_id"),
        "artifact_digest": teacher_d.get("artifact_digest"),
    }
    out["quality_from_compute"] = False
    return out


def load_teacher_artifacts(path: Path | None) -> list[dict[str, Any]]:
    """Read teacher artifacts from disk. Missing path or empty file fails closed."""
    if path is None:
        raise InvalidInputError("teacher artifacts path is required", field="artifacts")
    p = Path(path)
    if not p.is_file():
        raise UnexecutableError(f"teacher artifacts missing: {p}", field="artifacts")
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        raise InvalidInputError("teacher artifacts file is empty", field="artifacts")
    data = json.loads(text)
    if isinstance(data, dict) and "artifacts" in data:
        data = data["artifacts"]
    if not isinstance(data, list) or not data:
        raise InvalidInputError("teacher artifacts must be a non-empty list", field="artifacts")
    return [dict(a) for a in data]


def synthesize_offline(
    traces: list[ComputeTrace | dict[str, Any]],
    *,
    artifacts: list[dict[str, Any]] | None,
    consent_ledger: dict[str, dict[str, Any]],
    source_records: list[dict[str, Any]],
    deletion_holds: set[str] | None = None,
    config: TeacherConfig | None = None,
    attach: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pack offline teacher traces. Does not train, promote, or call a model.

    ``factory.ready`` is true only when at least one consented, redacted trace
    survived. A missing artifact, empty input, or schema mismatch fails closed.
    """
    cfg = config or TeacherConfig()
    if cfg.allow_live_teacher:
        raise PolicyDeniedError("live teacher at train time is out of scope", field="allow_live_teacher")
    if not traces and not cfg.allow_empty:
        raise InvalidInputError("compute-teacher pack has no traces", field="traces")

    parsed: list[ComputeTrace] = []
    for raw in traces:
        parsed.append(raw if isinstance(raw, ComputeTrace) else parse_trace(raw))
    if not parsed and not cfg.allow_empty:
        raise InvalidInputError("compute-teacher pack has no traces", field="steps")

    arts = list(artifacts or [])
    if cfg.require_artifacts and not arts:
        raise InvalidInputError("teacher artifacts are required", field="artifacts")
    for art in arts:
        if art.get("schema"):
            check_compatible(art["schema"], "teacher-record")
        TeacherRecord(
            teacher_id=str(art.get("teacher_id") or ""),
            compute_trace_id=str(art.get("compute_trace_id") or ""),
            artifact_kind=str(art.get("artifact_kind") or ""),
            artifact_digest=str(art.get("artifact_digest") or ""),
            task_ok=art.get("task_ok"),
        )

    by_trace = {a.get("compute_trace_id"): a for a in arts}
    holds = deletion_holds or set()
    packed: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    eligible_traces: list[ComputeTrace] = []
    eligible_arts: list[dict[str, Any]] = []
    records_by_id = {str(r.get("trace_id")): r for r in source_records}

    for trace in parsed:
        art = by_trace.get(trace.trace_id)
        if cfg.require_artifacts and art is None:
            raise InvalidInputError(
                f"no teacher artifact for compute trace {trace.trace_id!r}",
                field="artifacts",
            )
        rec = records_by_id.get(trace.trace_id)
        if rec is None:
            raise InvalidInputError(
                f"no source record for compute trace {trace.trace_id!r}",
                field="source_records",
            )
        if cfg.require_consent:
            elig = export_eligibility(rec, consent_ledger=consent_ledger, deletion_holds=holds)
            if not elig["eligible"]:
                refused.append({"trace_id": trace.trace_id, "reasons": elig["reasons"]})
                continue
        _red, rep = redact_record(rec)
        if cfg.require_redaction and (rep.get("secret") or rep.get("keyish")):
            raise PolicyDeniedError(
                "teacher pack refused: secret/keyish detector hit on tool output",
                field="redaction",
            )
        if cfg.require_redaction:
            _scrubbed, step_rep = redact_obj(
                {
                    "steps": [s.to_dict() for s in trace.steps],
                    "notes": trace.notes,
                    "verifier_outcomes": list(trace.verifier_outcomes),
                }
            )
            if step_rep.get("secret") or step_rep.get("keyish"):
                raise PolicyDeniedError(
                    "teacher pack refused: secret/keyish detector hit on compute-trace content",
                    field="redaction",
                )
        eligible_traces.append(trace)
        if art is not None:
            eligible_arts.append(art)
        packed.append(
            {
                "trace_id": rec.get("trace_id"),
                "compute_trace_id": trace.digest(),
                "source": rec.get("_source") or rec.get("session_id"),
                "teacher_id": None if art is None else art.get("teacher_id"),
                "n_steps": len(trace.steps),
                "branching": trace.branching(),
            }
        )

    if not packed and not cfg.allow_empty:
        raise InvalidInputError(
            "no eligible compute traces survived consent/redaction", field="traces"
        )

    attachment = None
    if attach is not None:
        first_art = eligible_arts[0] if eligible_arts else {}
        anchor = eligible_traces[0] if eligible_traces else parsed[0]
        teacher = TeacherRecord(
            teacher_id=str(first_art.get("teacher_id") or new_id("teach_")),
            compute_trace_id=anchor.digest(),
            artifact_kind=str(first_art.get("artifact_kind") or "search_tree"),
            artifact_digest=str(first_art.get("artifact_digest") or anchor.digest()),
            task_ok=True,
        )
        attachment = attach_teacher(attach, teacher)

    pack = {
        "schema": active("teacher-pack"),
        "pack_id": new_id("cat_"),
        "traces": [t.to_dict() for t in eligible_traces],
        "artifacts": eligible_arts,
        "shards": packed,
        "refused": refused,
        "attachment": None
        if attachment is None
        else {
            "schema": attachment.get("schema"),
            "id": attachment.get("eval_id") or attachment.get("report_id"),
            "teacher_record": attachment.get("teacher_record"),
        },
        "factory": {
            "ready": bool(packed),
            "live_teacher": False,
            "n_traces": len(packed),
            "training": False,
        },
        "capability_claim": "none",
        "training": False,
        "promotion": "manual",
        "computed_at": now_iso(),
    }
    pack["digest"] = digest(
        {"traces": [t.digest() for t in eligible_traces], "shards": packed, "artifacts": eligible_arts}
    )
    return pack


def factory_ready(pack: dict[str, Any]) -> dict[str, Any]:
    """Factory-readable gate. Missing/empty/mismatched packs fail closed."""
    if not pack:
        return {"outcome": "fail", "metric": "factory.ready", "value": None, "reason": "teacher pack missing"}
    try:
        check_compatible(pack.get("schema"), "teacher-pack")
    except InvalidInputError as e:
        return {
            "outcome": "no_metric",
            "metric": "factory.ready",
            "value": None,
            "reason": f"schema mismatch: {e.message}",
        }
    factory = pack.get("factory") or {}
    n = factory.get("n_traces")
    ready = factory.get("ready") is True and isinstance(n, int) and n > 0 and bool(pack.get("shards"))
    if factory.get("live_teacher") or factory.get("training") or pack.get("training"):
        return {
            "outcome": "fail",
            "metric": "factory.ready",
            "value": False,
            "reason": "pack claims a live teacher or a training run; this scaffold does not",
        }
    return {
        "outcome": "pass" if ready else "fail",
        "metric": "factory.ready",
        "value": ready,
        "n_traces": n,
        "reason": "offline teacher pack ready" if ready else "teacher pack not ready",
    }


__all__ = [
    "ARTIFACT_KINDS",
    "ATTACH_SCHEMAS",
    "ComputeStep",
    "ComputeTrace",
    "TeacherConfig",
    "TeacherRecord",
    "attach_teacher",
    "factory_ready",
    "load_teacher_artifacts",
    "parse_trace",
    "synthesize_offline",
]
