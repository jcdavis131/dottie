"""AIRA2-inspired experiment architecture (research sequence stage 3).

Fixed train / search / validation split metadata, Hidden Consistent Evaluation
(the agent never sees labels; scores come from an external consistent scorer),
an async resource-aware job abstraction with lineage, and an interactive-debug
result shape.

GPU work goes through the existing :class:`dottie_loop.closed_loop.LeaseFile`.
This module does not add a second GPU lock and will not acquire a GPU without
that lease file — the single-GPU lease safety in ``closed_loop`` is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from dottie_loop.errors import BlockedError, InvalidInputError
from dottie_loop.hashing import digest, new_id, now_iso
from dottie_loop.schema import active

if TYPE_CHECKING:
    from dottie_loop.closed_loop import Lease, LeaseFile

SPLITS = ("train", "search", "validation")
RESOURCES = ("cpu", "disk", "gpu")
JOB_STATES = ("pending", "leased", "running", "succeeded", "failed", "debug")
DEBUG_STATES = ("open", "hypothesized", "fix_attempted", "resolved")
HIDDEN_LEAK_KEYS = frozenset(
    {"gold", "label", "labels", "answer", "expected", "target", "score_detail"}
)


@dataclass
class ExperimentSplit:
    """Frozen train / search / validation membership. Isolation is required."""

    experiment_id: str
    train: list[str]
    search: list[str]
    validation: list[str]
    strategy: str = "fixed"
    seed: str = "aira2"
    notes: str = ""

    def __post_init__(self) -> None:
        for name in SPLITS:
            ids = getattr(self, name)
            if len(ids) != len(set(ids)):
                raise InvalidInputError(f"{name} ids must be unique", field=name)
        overlap = self.overlap()
        if any(overlap.values()):
            raise InvalidInputError(
                f"split isolation failed: {overlap}", field="splits"
            )
        if not self.train or not self.search or not self.validation:
            raise InvalidInputError(
                "train, search and validation must each be non-empty", field="splits"
            )

    def overlap(self) -> dict[str, list[str]]:
        sets = {n: set(getattr(self, n)) for n in SPLITS}
        out: dict[str, list[str]] = {}
        names = list(SPLITS)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                hit = sorted(sets[a] & sets[b])
                if hit:
                    out[f"{a}&{b}"] = hit
        return out

    def digest(self) -> str:
        return digest(
            {
                "experiment_id": self.experiment_id,
                "train": sorted(self.train),
                "search": sorted(self.search),
                "validation": sorted(self.validation),
                "strategy": self.strategy,
                "seed": self.seed,
            }
        )

    def assign(self, item_id: str) -> str:
        for name in SPLITS:
            if item_id in getattr(self, name):
                return name
        raise InvalidInputError(f"{item_id!r} is not in any split", field="item_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": active("experiment-split"),
            "experiment_id": self.experiment_id,
            "train": list(self.train),
            "search": list(self.search),
            "validation": list(self.validation),
            "strategy": self.strategy,
            "seed": self.seed,
            "notes": self.notes,
            "digest": self.digest(),
            "counts": {n: len(getattr(self, n)) for n in SPLITS},
        }


@dataclass
class HiddenItem:
    item_id: str
    prompt: str
    gold: Any
    split: Literal["train", "search", "validation"]
    constraints: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


class ConsistentScorer(Protocol):
    """External scorer. The agent never calls this; the evaluator does."""

    version: str

    def score(self, item_id: str, gold: Any, prediction: Any) -> float: ...


class ScriptedScorer:
    """Deterministic scorer: exact match → 1.0, else a table or 0.0."""

    def __init__(self, version: str = "scripted-1", table: dict[str, float] | None = None) -> None:
        self.version = version
        self.table = dict(table or {})

    def score(self, item_id: str, gold: Any, prediction: Any) -> float:
        if item_id in self.table:
            return float(self.table[item_id])
        return 1.0 if prediction == gold else 0.0


@dataclass
class HiddenEvalPack:
    """Held-out items whose labels stay on the evaluator side of the API."""

    pack_id: str
    items: list[HiddenItem]
    scorer_version: str

    def __post_init__(self) -> None:
        ids = [i.item_id for i in self.items]
        if not ids:
            raise InvalidInputError("hidden eval pack is empty", field="items")
        if len(ids) != len(set(ids)):
            raise InvalidInputError("hidden item ids must be unique", field="items")
        leaked = [k for i in self.items for k in i.meta if k in HIDDEN_LEAK_KEYS]
        if leaked:
            raise InvalidInputError(
                f"item meta must not carry label keys {sorted(set(leaked))}",
                field="meta",
            )

    def agent_view(self, item_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """What an agent may see: prompt and constraints, never gold or scores."""
        wanted = set(item_ids) if item_ids is not None else None
        view: list[dict[str, Any]] = []
        for item in self.items:
            if wanted is not None and item.item_id not in wanted:
                continue
            view.append(
                {
                    "item_id": item.item_id,
                    "prompt": item.prompt,
                    "constraints": list(item.constraints),
                    "split": item.split,
                }
            )
        _assert_no_leak(view)
        return view

    def score(
        self,
        predictions: dict[str, Any],
        scorer: ConsistentScorer,
        *,
        split: str | None = None,
    ) -> dict[str, Any]:
        """Score from the outside. Scorer version is recorded; labels stay here."""
        if getattr(scorer, "version", None) != self.scorer_version:
            raise InvalidInputError(
                "scorer version does not match the pack (consistent eval required)",
                field="scorer_version",
            )
        rows: list[dict[str, Any]] = []
        items = [i for i in self.items if split is None or i.split == split]
        missing = [i.item_id for i in items if i.item_id not in predictions]
        if missing:
            raise InvalidInputError(
                f"predictions missing {missing}", field="predictions"
            )
        for item in items:
            s = float(scorer.score(item.item_id, item.gold, predictions[item.item_id]))
            if not 0.0 <= s <= 1.0:
                raise InvalidInputError("scorer must return [0, 1]", field="score")
            rows.append({"item_id": item.item_id, "split": item.split, "score": s})
        mean = round(sum(r["score"] for r in rows) / len(rows), 6) if rows else None
        record = {
            "schema": active("hidden-eval"),
            "pack_id": self.pack_id,
            "scorer_version": self.scorer_version,
            "split": split,
            "n": len(rows),
            "mean": mean,
            "rows": rows,
            "agent_view_digest": digest(self.agent_view([r["item_id"] for r in rows])),
            "scored_at": now_iso(),
        }
        _assert_no_leak(record)
        return record


def _assert_no_leak(obj: Any) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in HIDDEN_LEAK_KEYS:
                raise InvalidInputError(
                    f"hidden eval leak: {k!r} is not visible to agents", field=k
                )
            _assert_no_leak(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_no_leak(v)


@dataclass
class DebugResult:
    """Interactive-debug representation: traceback, hypothesis, fix attempt."""

    job_id: str
    traceback: str
    hypothesis: str | None = None
    fix_attempt: str | None = None
    status: str = "open"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.status not in DEBUG_STATES:
            raise InvalidInputError(f"unknown debug status {self.status!r}", field="status")
        if not self.traceback.strip():
            raise InvalidInputError("debug result needs a traceback", field="traceback")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": active("debug-result"),
            "job_id": self.job_id,
            "traceback": self.traceback,
            "hypothesis": self.hypothesis,
            "fix_attempt": self.fix_attempt,
            "status": self.status,
            "notes": self.notes,
            "at": now_iso(),
        }


@dataclass
class ExperimentJob:
    experiment_id: str
    split: str
    resource: str
    payload: dict[str, Any]
    parent_job_id: str | None = None
    job_id: str = field(default_factory=lambda: new_id("xjob_"))
    status: str = "pending"
    owner: str | None = None
    lineage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.split not in SPLITS:
            raise InvalidInputError(f"split must be one of {SPLITS}", field="split")
        if self.resource not in RESOURCES:
            raise InvalidInputError(f"resource must be one of {RESOURCES}", field="resource")
        if self.status not in JOB_STATES:
            raise InvalidInputError(f"status must be one of {JOB_STATES}", field="status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": active("experiment-job"),
            "job_id": self.job_id,
            "experiment_id": self.experiment_id,
            "split": self.split,
            "resource": self.resource,
            "payload": dict(self.payload),
            "parent_job_id": self.parent_job_id,
            "status": self.status,
            "owner": self.owner,
            "lineage": dict(self.lineage),
        }


class ResourceBroker:
    """Resource-aware leases. GPU always delegates to ``closed_loop.LeaseFile``."""

    def __init__(self, gpu_lease: LeaseFile | None = None) -> None:
        self._gpu = gpu_lease
        self._held: dict[str, str] = {}

    def acquire(self, resource: str, owner: str, **lease_kw: Any) -> dict[str, Any]:
        if resource not in RESOURCES:
            raise InvalidInputError(f"unknown resource {resource!r}", field="resource")
        if resource == "gpu":
            if self._gpu is None:
                raise BlockedError(
                    "gpu lease file required; single-GPU safety is not bypassed",
                    "lease",
                )
            lease = self._gpu.acquire(owner, **lease_kw)
            return {"resource": "gpu", "owner": lease.owner, "expires_at": lease.expires_at}
        if resource in self._held:
            raise BlockedError(
                f"{resource} lease held by {self._held[resource]}", "lease"
            )
        self._held[resource] = owner
        return {"resource": resource, "owner": owner, "expires_at": None}

    def heartbeat(self, resource: str, owner: str, **lease_kw: Any) -> dict[str, Any]:
        if resource == "gpu":
            if self._gpu is None:
                raise BlockedError("gpu lease file required", "lease")
            lease = self._gpu.heartbeat(owner, **lease_kw)
            return {"resource": "gpu", "owner": lease.owner, "expires_at": lease.expires_at}
        if self._held.get(resource) != owner:
            raise BlockedError("heartbeat from a non-owner", "lease")
        return {"resource": resource, "owner": owner, "expires_at": None}

    def release(self, resource: str, owner: str, **lease_kw: Any) -> dict[str, Any]:
        if resource == "gpu":
            if self._gpu is None:
                raise BlockedError("gpu lease file required", "lease")
            return {"resource": "gpu", **self._gpu.release(owner, **lease_kw)}
        if self._held.get(resource) != owner:
            raise BlockedError("release from a non-owner", "lease")
        del self._held[resource]
        return {"resource": resource, "released": owner}

    def gpu_lease(self) -> Lease | None:
        return None if self._gpu is None else self._gpu.read()


class ExperimentQueue:
    """Submit / claim / complete. Claim of a GPU job acquires the GPU lease."""

    def __init__(self, broker: ResourceBroker) -> None:
        self.broker = broker
        self.jobs: dict[str, ExperimentJob] = {}

    def submit(self, job: ExperimentJob) -> ExperimentJob:
        if job.job_id in self.jobs:
            raise InvalidInputError("duplicate job_id", field="job_id")
        job.status = "pending"
        job.lineage.setdefault("submitted_at", now_iso())
        self.jobs[job.job_id] = job
        return job

    def claim(self, owner: str, *, resource: str | None = None, **lease_kw: Any) -> ExperimentJob | None:
        for job in self.jobs.values():
            if job.status != "pending":
                continue
            if resource is not None and job.resource != resource:
                continue
            self.broker.acquire(job.resource, owner, **lease_kw)
            job.status = "leased"
            job.owner = owner
            job.lineage["leased_at"] = now_iso()
            job.lineage["lease_owner"] = owner
            return job
        return None

    def start(self, job_id: str, owner: str) -> ExperimentJob:
        job = self._owned(job_id, owner)
        if job.status != "leased":
            raise BlockedError("job is not leased", "job")
        job.status = "running"
        job.lineage["started_at"] = now_iso()
        return job

    def complete(
        self,
        job_id: str,
        owner: str,
        *,
        result: dict[str, Any] | None = None,
        hidden_eval: dict[str, Any] | None = None,
    ) -> ExperimentJob:
        job = self._owned(job_id, owner)
        job.status = "succeeded"
        job.lineage["completed_at"] = now_iso()
        if result is not None:
            job.lineage["result"] = result
        if hidden_eval is not None:
            _assert_no_leak(hidden_eval)
            job.lineage["hidden_eval"] = {
                "pack_id": hidden_eval.get("pack_id"),
                "mean": hidden_eval.get("mean"),
                "n": hidden_eval.get("n"),
                "scorer_version": hidden_eval.get("scorer_version"),
            }
        self.broker.release(job.resource, owner)
        return job

    def fail(
        self,
        job_id: str,
        owner: str,
        debug: DebugResult,
    ) -> ExperimentJob:
        job = self._owned(job_id, owner)
        if debug.job_id != job.job_id:
            raise InvalidInputError("debug result job_id does not match", field="job_id")
        job.status = "debug" if debug.status != "resolved" else "failed"
        job.lineage["debug"] = debug.to_dict()
        job.lineage["failed_at"] = now_iso()
        self.broker.release(job.resource, owner)
        return job

    def _owned(self, job_id: str, owner: str) -> ExperimentJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise InvalidInputError("unknown job", field="job_id")
        if job.owner != owner:
            raise BlockedError("job not owned by caller", "job")
        return job


def attach_lineage(
    job: ExperimentJob,
    *,
    rubric_eval_id: str | None = None,
    opt_report_id: str | None = None,
    split_digest: str | None = None,
    parent_job_id: str | None = None,
) -> ExperimentJob:
    if rubric_eval_id:
        job.lineage["rubric_eval_id"] = rubric_eval_id
    if opt_report_id:
        job.lineage["opt_report_id"] = opt_report_id
    if split_digest:
        job.lineage["split_digest"] = split_digest
    if parent_job_id:
        job.parent_job_id = parent_job_id
        job.lineage["parent_job_id"] = parent_job_id
    return job


__all__ = [
    "DEBUG_STATES",
    "HIDDEN_LEAK_KEYS",
    "JOB_STATES",
    "RESOURCES",
    "SPLITS",
    "ConsistentScorer",
    "DebugResult",
    "ExperimentJob",
    "ExperimentQueue",
    "ExperimentSplit",
    "HiddenEvalPack",
    "HiddenItem",
    "ResourceBroker",
    "ScriptedScorer",
    "attach_lineage",
]
