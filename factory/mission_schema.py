"""Strict, closed-schema model mission definitions."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from factory.config import FactoryError


class MissionState(StrEnum):
    PROPOSED = "proposed"
    PREFLIGHT_BLOCKED = "preflight_blocked"
    READY = "ready"
    RUNNING = "running"
    EVALUATING = "evaluating"
    PASSED = "passed"
    FAILED = "failed"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class EvidenceKind(StrEnum):
    REAL = "real"
    SMOKE = "smoke"
    UNIT = "unit"
    MEASUREMENT = "measurement"
    MOCK = "mock"
    PLACEHOLDER = "placeholder"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class Repository:
    path: Path
    code_sha: str


@dataclass(frozen=True)
class DatasetIdentity:
    id: str
    path: str
    source: str
    revision: str
    license: str
    sha256: str
    identity_verified: bool


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]


@dataclass(frozen=True)
class Evaluation:
    argv: tuple[str, ...]
    report: str
    max_age_seconds: int
    contract_revision: str


@dataclass(frozen=True)
class Resources:
    ram_mb: int
    disk_mb: int
    gpu: str
    exclusive_gpu: bool
    max_parallel_jobs: int


@dataclass(frozen=True)
class MetricGate:
    name: str
    path: str
    op: str
    threshold: float


@dataclass(frozen=True)
class Output:
    kind: str
    source: str
    destination: str


@dataclass(frozen=True)
class ApprovalPolicy:
    reviewer_required: bool
    shipper_required: bool


@dataclass(frozen=True)
class Mission:
    schema_version: int
    id: str
    repository: Repository
    datasets: tuple[DatasetIdentity, ...]
    train: Command
    evaluation: Evaluation
    resources: Resources
    denied_dependencies: tuple[str, ...]
    metrics: tuple[MetricGate, ...]
    outputs: tuple[Output, ...]
    protected_artifacts: tuple[str, ...]
    approval_policy: ApprovalPolicy
    evidence_kind: EvidenceKind

    def canonical(self) -> dict[str, Any]:
        doc = asdict(self)
        doc["repository"]["path"] = str(self.repository.path)
        doc["evidence_kind"] = self.evidence_kind.value
        for key in ("datasets", "denied_dependencies", "metrics", "outputs"):
            doc[key] = list(doc[key])
        doc["train"]["argv"] = list(self.train.argv)
        doc["evaluation"]["argv"] = list(self.evaluation.argv)
        doc["protected_artifacts"] = list(self.protected_artifacts)
        return doc


LEGAL_TRANSITIONS: dict[MissionState, set[MissionState]] = {
    MissionState.PROPOSED: {MissionState.PREFLIGHT_BLOCKED, MissionState.READY},
    MissionState.PREFLIGHT_BLOCKED: {MissionState.READY, MissionState.CANCELLED},
    MissionState.READY: {MissionState.RUNNING, MissionState.CANCELLED},
    MissionState.RUNNING: {
        MissionState.EVALUATING,
        MissionState.FAILED,
        MissionState.CANCELLED,
    },
    MissionState.EVALUATING: {
        MissionState.PASSED,
        MissionState.FAILED,
        MissionState.CANCELLED,
    },
    MissionState.PASSED: {
        MissionState.PROMOTED,
        MissionState.REJECTED,
        MissionState.CANCELLED,
    },
    MissionState.FAILED: {MissionState.REJECTED, MissionState.CANCELLED},
    MissionState.PROMOTED: set(),
    MissionState.REJECTED: set(),
    MissionState.CANCELLED: set(),
}

_HEX = set("0123456789abcdef")
_OPS = {">=", "<=", ">", "<"}
_MISSION_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")


def _object(value: Any, where: str, required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FactoryError(f"{where}: expected object")
    missing = required - value.keys()
    unknown = value.keys() - required
    if missing:
        raise FactoryError(f"{where}: missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise FactoryError(f"{where}: unknown fields: {', '.join(sorted(unknown))}")
    return value


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FactoryError(f"{where}: expected non-empty string")
    return value


def _relative(value: Any, where: str) -> str:
    text = _string(value, where)
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or ".." in windows.parts
        or "\\" in text
    ):
        raise FactoryError(f"{where}: expected safe repository-relative path")
    return text


def _mission_id(value: Any) -> str:
    text = _string(value, "mission.id")
    if _MISSION_ID.fullmatch(text) is None:
        raise FactoryError(
            "mission.id: expected restricted slug "
            "(1-64 lowercase letters, digits, or interior hyphens)"
        )
    return text


def _argv(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise FactoryError(f"{where}: argv must be a non-empty string list")
    if not all(isinstance(item, str) and item for item in value):
        raise FactoryError(f"{where}: argv must be a non-empty string list")
    return tuple(value)


def _positive_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FactoryError(f"{where}: expected positive integer")
    return value


def _finite_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FactoryError(f"{where}: expected finite number")
    result = float(value)
    if not math.isfinite(result):
        raise FactoryError(f"{where}: expected finite number")
    return result


def _sha(value: Any, where: str, *, lengths: set[int]) -> str:
    text = _string(value, where).lower()
    if len(text) not in lengths or any(ch not in _HEX for ch in text):
        raise FactoryError(f"{where}: expected hexadecimal SHA")
    return text


def load_mission(path: Path) -> Mission:
    """Load one strict mission JSON document; every object is closed."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FactoryError(f"{path}: cannot load mission: {exc}") from exc
    top = _object(
        raw,
        "mission",
        {
            "schema_version",
            "id",
            "repository",
            "datasets",
            "train",
            "evaluation",
            "resources",
            "denied_dependencies",
            "metrics",
            "outputs",
            "protected_artifacts",
            "approval_policy",
            "evidence_kind",
        },
    )
    if top["schema_version"] != 1:
        raise FactoryError("mission.schema_version: only version 1 is supported")
    repo = _object(top["repository"], "mission.repository", {"path", "code_sha"})
    repository_path = Path(_string(repo["path"], "mission.repository.path")).expanduser()
    if not repository_path.is_absolute():
        repository_path = Path(path).resolve().parent / repository_path
    repository = Repository(
        repository_path.resolve(),
        _sha(repo["code_sha"], "mission.repository.code_sha", lengths={40, 64}),
    )
    if not isinstance(top["datasets"], list) or not top["datasets"]:
        raise FactoryError("mission.datasets: at least one real dataset is required")
    datasets: list[DatasetIdentity] = []
    for index, value in enumerate(top["datasets"]):
        where = f"mission.datasets[{index}]"
        item = _object(
            value,
            where,
            {
                "id",
                "path",
                "source",
                "revision",
                "license",
                "sha256",
                "identity_verified",
            },
        )
        if not isinstance(item["identity_verified"], bool):
            raise FactoryError(f"{where}.identity_verified: expected Boolean")
        datasets.append(
            DatasetIdentity(
                _string(item["id"], f"{where}.id"),
                _relative(item["path"], f"{where}.path"),
                _string(item["source"], f"{where}.source"),
                _string(item["revision"], f"{where}.revision"),
                _string(item["license"], f"{where}.license"),
                _sha(item["sha256"], f"{where}.sha256", lengths={64}),
                item["identity_verified"],
            )
        )
    train = _object(top["train"], "mission.train", {"argv"})
    evaluation_raw = _object(
        top["evaluation"],
        "mission.evaluation",
        {"argv", "report", "max_age_seconds", "contract_revision"},
    )
    resources_raw = _object(
        top["resources"],
        "mission.resources",
        {"ram_mb", "disk_mb", "gpu", "exclusive_gpu", "max_parallel_jobs"},
    )
    if resources_raw["gpu"] not in {"none", "required"}:
        raise FactoryError("mission.resources.gpu: expected 'none' or 'required'")
    if not isinstance(resources_raw["exclusive_gpu"], bool):
        raise FactoryError("mission.resources.exclusive_gpu: expected Boolean")
    denied = top["denied_dependencies"]
    if not isinstance(denied, list) or not all(
        isinstance(item, str) and item for item in denied
    ):
        raise FactoryError("mission.denied_dependencies: expected string list")
    metrics_raw = top["metrics"]
    if not isinstance(metrics_raw, list) or not metrics_raw:
        raise FactoryError("mission.metrics: at least one gate is required")
    metrics: list[MetricGate] = []
    for index, value in enumerate(metrics_raw):
        where = f"mission.metrics[{index}]"
        item = _object(value, where, {"name", "path", "op", "threshold"})
        if item["op"] not in _OPS:
            raise FactoryError(f"{where}.op: expected one of {sorted(_OPS)}")
        metrics.append(
            MetricGate(
                _string(item["name"], f"{where}.name"),
                _string(item["path"], f"{where}.path"),
                item["op"],
                _finite_number(item["threshold"], f"{where}.threshold"),
            )
        )
    outputs_raw = top["outputs"]
    if not isinstance(outputs_raw, list) or not outputs_raw:
        raise FactoryError("mission.outputs: at least one output is required")
    outputs: list[Output] = []
    for index, value in enumerate(outputs_raw):
        where = f"mission.outputs[{index}]"
        item = _object(value, where, {"kind", "source", "destination"})
        if item["kind"] not in {"model", "checkpoint", "tokenizer", "config"}:
            raise FactoryError(f"{where}.kind: unknown artifact kind")
        outputs.append(
            Output(
                item["kind"],
                _relative(item["source"], f"{where}.source"),
                _relative(item["destination"], f"{where}.destination"),
            )
        )
    missing_artifacts = {"model", "checkpoint", "tokenizer", "config"} - {
        item.kind for item in outputs
    }
    if missing_artifacts:
        raise FactoryError(
            "mission.outputs: missing artifact kinds: "
            + ", ".join(sorted(missing_artifacts))
        )
    if len({item.source for item in outputs}) != len(outputs):
        raise FactoryError("mission.outputs: duplicate artifact source")
    if len({item.destination for item in outputs}) != len(outputs):
        raise FactoryError("mission.outputs: duplicate artifact destination")
    protected = top["protected_artifacts"]
    if not isinstance(protected, list) or not all(
        isinstance(item, str) for item in protected
    ):
        raise FactoryError("mission.protected_artifacts: expected path list")
    approval = _object(
        top["approval_policy"],
        "mission.approval_policy",
        {"reviewer_required", "shipper_required"},
    )
    if not all(isinstance(approval[key], bool) for key in approval):
        raise FactoryError("mission.approval_policy: values must be Boolean")
    try:
        evidence = EvidenceKind(top["evidence_kind"])
    except (TypeError, ValueError) as exc:
        raise FactoryError("mission.evidence_kind: unknown evidence kind") from exc
    return Mission(
        1,
        _mission_id(top["id"]),
        repository,
        tuple(datasets),
        Command(_argv(train["argv"], "mission.train.argv")),
        Evaluation(
            _argv(evaluation_raw["argv"], "mission.evaluation.argv"),
            _relative(evaluation_raw["report"], "mission.evaluation.report"),
            _positive_int(
                evaluation_raw["max_age_seconds"],
                "mission.evaluation.max_age_seconds",
            ),
            _string(
                evaluation_raw["contract_revision"],
                "mission.evaluation.contract_revision",
            ),
        ),
        Resources(
            _positive_int(resources_raw["ram_mb"], "mission.resources.ram_mb"),
            _positive_int(resources_raw["disk_mb"], "mission.resources.disk_mb"),
            resources_raw["gpu"],
            resources_raw["exclusive_gpu"],
            _positive_int(
                resources_raw["max_parallel_jobs"],
                "mission.resources.max_parallel_jobs",
            ),
        ),
        tuple(denied),
        tuple(metrics),
        tuple(outputs),
        tuple(_relative(item, "mission.protected_artifacts[]") for item in protected),
        ApprovalPolicy(approval["reviewer_required"], approval["shipper_required"]),
        evidence,
    )
