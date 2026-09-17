"""Auditable, fail-closed model missions backed by a local SQLite ledger."""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from factory.config import FactoryError, sha256_of
from factory.mission_ledger import Ledger
from factory.mission_paths import contained_path, same_file
from factory.mission_process import (
    available_ram_mb,
    run_capture,
)
from factory.mission_schema import (
    EvidenceKind,
    Mission,
    MissionState,
    Resources,
    load_mission,
)


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _command_problems(repo: Path, argv: tuple[str, ...], name: str) -> list[str]:
    problems: list[str] = []
    executable = Path(argv[0])
    if executable.is_absolute():
        if not executable.is_file():
            problems.append(f"{name} executable does not exist: {executable}")
    elif shutil.which(argv[0]) is None:
        problems.append(f"{name} executable is not on PATH: {argv[0]}")
    if len(argv) > 1 and argv[1].endswith(".py"):
        script = repo / argv[1]
        if not script.is_file():
            problems.append(f"{name} command path is missing: {argv[1]}")
    return problems


_PLACEHOLDER = re.compile(
    r"^(?:tbd|todo|n/?a|none|unknown|unverified|missing|placeholder|"
    r"fixme|pending|not[-_ ]?(?:available|applicable|set|verified))"
    r"(?:\b|[-_:])",
    re.IGNORECASE,
)


def _is_placeholder(value: str) -> bool:
    return _PLACEHOLDER.match(value.strip()) is not None


def _package_name(value: str) -> str:
    candidate = re.split(r"[\s<>=!~;\[]", value.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", candidate).casefold()


def _declared_dependencies(repo: Path) -> set[str]:
    declared: set[str] = set()
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise FactoryError(
                f"dependency declarations could not be verified: {pyproject}: {exc}"
            ) from exc
        project = document.get("project", {})
        for dependency in project.get("dependencies", []):
            if isinstance(dependency, str):
                declared.add(_package_name(dependency))
        for group in project.get("optional-dependencies", {}).values():
            if isinstance(group, list):
                declared.update(
                    _package_name(item) for item in group if isinstance(item, str)
                )
        for group in document.get("dependency-groups", {}).values():
            if isinstance(group, list):
                declared.update(
                    _package_name(item) for item in group if isinstance(item, str)
                )
        poetry = document.get("tool", {}).get("poetry", {})
        for group in (
            poetry.get("dependencies", {}),
            poetry.get("dev-dependencies", {}),
        ):
            if isinstance(group, dict):
                declared.update(_package_name(item) for item in group)
        poetry_groups = poetry.get("group", {})
        if isinstance(poetry_groups, dict):
            for group in poetry_groups.values():
                dependencies = (
                    group.get("dependencies", {}) if isinstance(group, dict) else {}
                )
                if isinstance(dependencies, dict):
                    declared.update(_package_name(item) for item in dependencies)
    for name in ("requirements.txt", "requirements-dev.txt"):
        path = repo / name
        if not path.is_file():
            continue
        for raw_line in path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            line = raw_line.partition("#")[0].strip()
            if line and not line.startswith(("-", "http:", "https:", "git+")):
                declared.add(_package_name(line))
    return declared


def _gpu_problems(resources: Resources) -> list[str]:
    if resources.gpu == "none":
        return []
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return ["GPU is required but nvidia-smi is unavailable"]
    probe = subprocess.run(
        [
            executable,
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return ["GPU state could not be verified"]
    active = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    if resources.exclusive_gpu and active:
        return [f"exclusive GPU requested but active compute jobs exist: {active}"]
    return []


def preflight_mission(mission: Mission, ledger: Ledger) -> list[str]:
    """Return every blocker; absence of blockers is the only ready condition."""
    ledger.assert_mission(mission)
    blockers: list[str] = []
    repo = mission.repository.path
    repo_exists = repo.is_dir()
    if not repo_exists:
        blockers.append(f"repository does not exist: {repo}")
    else:
        head = _git(repo, "rev-parse", "HEAD")
        if head.returncode != 0:
            blockers.append("repository is not a readable Git checkout")
        elif head.stdout.strip().lower() != mission.repository.code_sha:
            blockers.append(
                f"code SHA drift: expected {mission.repository.code_sha}, "
                f"found {head.stdout.strip()}"
            )
        dirty = _git(repo, "status", "--porcelain", "--untracked-files=all")
        if dirty.returncode != 0 or dirty.stdout.strip():
            blockers.append("repository is dirty; exact clean code SHA required")
    for command_name, argv in (
        ("train", mission.train.argv),
        ("evaluation", mission.evaluation.argv),
    ):
        blockers.extend(_command_problems(repo, argv, command_name))
    if _is_placeholder(mission.evaluation.contract_revision):
        blockers.append("canonical metric contract revision is unverified")
    for dataset in mission.datasets:
        path = repo / dataset.path
        if not dataset.identity_verified:
            blockers.append(f"dataset {dataset.id}: immutable identity is unverified")
        if _is_placeholder(dataset.license):
            blockers.append(f"dataset {dataset.id}: exact license is unverified")
        if _is_placeholder(dataset.revision):
            blockers.append(
                f"dataset {dataset.id}: immutable source revision is unverified"
            )
        if dataset.sha256 == "0" * 64:
            blockers.append(f"dataset {dataset.id}: SHA-256 is unverified")
        if not path.is_file():
            blockers.append(f"dataset {dataset.id}: file is missing at {dataset.path}")
        elif sha256_of(path) != dataset.sha256:
            blockers.append(f"dataset {dataset.id}: SHA-256 mismatch")
    try:
        dependencies = _declared_dependencies(repo)
    except FactoryError as exc:
        blockers.append(str(exc))
    else:
        for denied in mission.denied_dependencies:
            if _package_name(denied) in dependencies:
                blockers.append(f"denied dependency is declared: {denied}")
    available_ram = available_ram_mb()
    if available_ram is None:
        blockers.append("available RAM could not be verified")
    elif available_ram < mission.resources.ram_mb:
        blockers.append(
            f"insufficient RAM: {available_ram} MiB available, "
            f"{mission.resources.ram_mb} MiB required"
        )
    if repo_exists:
        free_disk = shutil.disk_usage(repo).free // (1024 * 1024)
        if free_disk < mission.resources.disk_mb:
            blockers.append(
                f"insufficient disk: {free_disk} MiB free, "
                f"{mission.resources.disk_mb} MiB required"
            )
    blockers.extend(_gpu_problems(mission.resources))
    if ledger.running_count() >= mission.resources.max_parallel_jobs:
        blockers.append("conflicting factory mission is already running")
    protected = set(mission.protected_artifacts)
    for output in mission.outputs:
        if output.destination in protected:
            blockers.append(f"output would overwrite protected artifact: {output.destination}")
        if not repo_exists:
            continue
        destination = repo / output.destination
        try:
            contained_path(repo, destination)
        except FactoryError as exc:
            blockers.append(f"unsafe output destination: {exc}")
        if destination.exists():
            blockers.append(f"output destination already exists: {output.destination}")
    return blockers


def preflight_and_record(mission: Mission, ledger: Ledger) -> list[str]:
    blockers = preflight_mission(mission, ledger)
    target = (
        MissionState.PREFLIGHT_BLOCKED if blockers else MissionState.READY
    )
    current = MissionState(ledger.status(mission.id)["state"])
    if current == MissionState.PREFLIGHT_BLOCKED and not blockers:
        ledger.transition(mission.id, MissionState.READY, reason="preflight passed")
    elif current == MissionState.PROPOSED:
        ledger.transition(
            mission.id,
            target,
            reason="; ".join(blockers) if blockers else "preflight passed",
        )
    elif current not in {target, MissionState.PREFLIGHT_BLOCKED}:
        raise FactoryError(f"cannot preflight mission in state {current.value}")
    return blockers


def _hash_paths(root: Path, paths: tuple[str, ...]) -> dict[str, str | None]:
    return {
        relative: sha256_of(root / relative) if (root / relative).is_file() else None
        for relative in paths
    }


def _source_state(mission: Mission) -> tuple[str, str]:
    head = _git(mission.repository.path, "rev-parse", "HEAD")
    dirty = _git(
        mission.repository.path, "status", "--porcelain", "--untracked-files=all"
    )
    if head.returncode != 0 or dirty.returncode != 0:
        raise FactoryError("source drift check could not read repository state")
    return head.stdout.strip().lower(), dirty.stdout.strip()


def _require_stable_source(mission: Mission) -> tuple[str, str]:
    state = _source_state(mission)
    if state != (mission.repository.code_sha, ""):
        raise FactoryError("source drift: exact clean approved SHA required")
    return state


def run_attempt(mission: Mission, ledger: Ledger, runs_root: Path) -> str:
    """Atomically claim, copy the clean tree, and execute training without a shell."""
    ledger.assert_mission(mission)
    attempt_id = ledger.claim(mission.id)
    if attempt_id is None:
        raise FactoryError("mission is not ready or was claimed by another operator")
    scratch = Path(runs_root) / mission.id / attempt_id / "scratch"
    try:
        before = _require_stable_source(mission)
        scratch.parent.mkdir(parents=True, exist_ok=False)
        shutil.copytree(
            mission.repository.path,
            scratch,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "venv",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                "*.pyc",
            ),
        )
        after = _require_stable_source(mission)
        if after != before:
            raise FactoryError("source drift during snapshot creation")
        for dataset in mission.datasets:
            copied = scratch / dataset.path
            if not copied.is_file() or sha256_of(copied) != dataset.sha256:
                raise FactoryError(
                    f"snapshot dataset hash mismatch: {dataset.id}"
                )
    except BaseException as exc:
        ledger.transition(
            mission.id,
            MissionState.FAILED,
            attempt_id=attempt_id,
            reason=str(exc),
        )
        raise
    try:
        ledger.set_runtime(attempt_id, scratch_path=str(scratch))
        environment = {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "argv": list(mission.train.argv),
            "code_sha": mission.repository.code_sha,
        }
        _atomic_json(scratch.parent / "environment.json", environment)
        protected_before = _hash_paths(
            mission.repository.path, mission.protected_artifacts
        )
        _atomic_json(scratch.parent / "protected-before.json", protected_before)
        rc, seconds = run_capture(
            mission.train.argv,
            scratch,
            scratch.parent / "train.stdout.log",
            scratch.parent / "train.stderr.log",
            ledger,
            mission.id,
            attempt_id,
            "train",
        )
        protected_after = _hash_paths(
            mission.repository.path, mission.protected_artifacts
        )
        _atomic_json(scratch.parent / "protected-after.json", protected_after)
        ledger.set_runtime(
            attempt_id, train_exit_code=rc, train_seconds=round(seconds, 6)
        )
    except BaseException as exc:
        ledger.fail_active(mission.id, attempt_id, str(exc))
        raise
    if protected_before != protected_after:
        ledger.transition(
            mission.id,
            MissionState.FAILED,
            attempt_id=attempt_id,
            reason="protected artifacts changed during training",
        )
        raise FactoryError("protected artifacts changed during training")
    if ledger.status(mission.id)["state"] == MissionState.CANCELLED.value:
        return attempt_id
    target = MissionState.EVALUATING if rc == 0 else MissionState.FAILED
    ledger.transition(
        mission.id,
        target,
        attempt_id=attempt_id,
        reason=f"training exit code {rc}",
    )
    return attempt_id


def _lookup(document: Any, dotted: str) -> Any:
    current = document
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _passes(value: float, op: str, threshold: float) -> bool:
    if op == ">=":
        return value >= threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == "<":
        return value < threshold
    raise FactoryError(f"unknown metric operator {op!r}")


def evaluate_attempt(
    mission: Mission, ledger: Ledger, attempt_id: str
) -> dict[str, Any]:
    ledger.assert_mission(mission)
    ledger.claim_evaluation(mission.id, attempt_id)
    try:
        return _evaluate_claimed_attempt(mission, ledger, attempt_id)
    except BaseException as exc:
        ledger.fail_active(mission.id, attempt_id, str(exc))
        raise


def _evaluate_claimed_attempt(
    mission: Mission, ledger: Ledger, attempt_id: str
) -> dict[str, Any]:
    attempt = ledger.attempt(attempt_id)
    scratch = Path(attempt["scratch_path"])
    report = scratch / mission.evaluation.report
    with contextlib.suppress(FileNotFoundError):
        report.unlink()
    started_wall = time.time()
    rc, seconds = run_capture(
        mission.evaluation.argv,
        scratch,
        scratch.parent / "evaluate.stdout.log",
        scratch.parent / "evaluate.stderr.log",
        ledger,
        mission.id,
        attempt_id,
        "eval",
    )
    ledger.set_runtime(
        attempt_id, eval_exit_code=rc, eval_seconds=round(seconds, 6)
    )
    result: dict[str, Any] = {
        "attempt_id": attempt_id,
        "exit_code": rc,
        "seconds": round(seconds, 6),
        "metrics": {},
        "passed": False,
        "problems": [],
    }
    if rc != 0:
        result["problems"].append(f"evaluator exited {rc}")
    elif not report.is_file():
        result["problems"].append("canonical evaluation report is missing")
    else:
        age = time.time() - report.stat().st_mtime
        if report.stat().st_mtime < started_wall - 1 or age > mission.evaluation.max_age_seconds:
            result["problems"].append("canonical evaluation report is stale")
        try:
            document = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["problems"].append(f"canonical evaluation report is invalid: {exc}")
            document = {}
        for gate in mission.metrics:
            value = _lookup(document, gate.path)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
            ):
                result["problems"].append(
                    f"metric {gate.name} is missing or non-finite"
                )
                continue
            numeric = float(value)
            result["metrics"][gate.name] = numeric
            if not _passes(numeric, gate.op, gate.threshold):
                result["problems"].append(
                    f"metric {gate.name}={numeric} misses {gate.op} {gate.threshold}"
                )
        if document.get("contract_revision") != mission.evaluation.contract_revision:
            result["problems"].append("canonical metric contract revision is stale")
    artifact_hashes: dict[str, str] = {}
    for output in mission.outputs:
        source = scratch / output.source
        if not source.is_file():
            result["problems"].append(f"declared output is missing: {output.source}")
        else:
            artifact_hashes[output.source] = sha256_of(source)
    evidence_paths = {
        "environment": scratch.parent / "environment.json",
        "protected_before": scratch.parent / "protected-before.json",
        "protected_after": scratch.parent / "protected-after.json",
        "train_stdout": scratch.parent / "train.stdout.log",
        "train_stderr": scratch.parent / "train.stderr.log",
        "evaluation_stdout": scratch.parent / "evaluate.stdout.log",
        "evaluation_stderr": scratch.parent / "evaluate.stderr.log",
        "evaluation_report": report,
    }
    evidence_hashes: dict[str, str] = {}
    for name, path in evidence_paths.items():
        if not path.is_file():
            result["problems"].append(f"runtime evidence is missing: {name}")
        else:
            evidence_hashes[name] = sha256_of(path)
    result["passed"] = not result["problems"]
    runtime = ledger.attempt(attempt_id)
    runtime_evidence = {
        key: runtime[key]
        for key in (
            "scratch_path",
            "process_pid",
            "process_identity",
            "train_pid",
            "train_identity",
            "eval_pid",
            "eval_identity",
            "train_exit_code",
            "train_seconds",
            "eval_exit_code",
            "eval_seconds",
        )
    }
    provenance = {
        "attempt_id": attempt_id,
        "mission_id": mission.id,
        "mission_hash": hashlib.sha256(
            _json_text(mission.canonical()).encode()
        ).hexdigest(),
        "code_sha": mission.repository.code_sha,
        "datasets": [asdict(item) for item in mission.datasets],
        "train_argv": list(mission.train.argv),
        "evaluation_argv": list(mission.evaluation.argv),
        "metrics": result["metrics"],
        "metric_contract": [asdict(item) for item in mission.metrics],
        "metric_contract_revision": mission.evaluation.contract_revision,
        "artifact_manifest": [asdict(item) for item in mission.outputs],
        "artifact_hashes": artifact_hashes,
        "evidence_hashes": evidence_hashes,
        "runtime_evidence": runtime_evidence,
        "runtime_evidence_hash": hashlib.sha256(
            _json_text(runtime_evidence).encode()
        ).hexdigest(),
        "protected_artifact_hashes": _hash_paths(
            mission.repository.path, mission.protected_artifacts
        ),
        "evidence_kind": mission.evidence_kind.value,
        "evaluation_exit_code": rc,
        "passed": result["passed"],
    }
    ledger.add_provenance(attempt_id, provenance)
    _atomic_json(scratch.parent / "provenance.json", provenance)
    ledger.transition(
        mission.id,
        MissionState.PASSED if result["passed"] else MissionState.FAILED,
        attempt_id=attempt_id,
        reason="evaluation passed" if result["passed"] else "; ".join(result["problems"]),
    )
    return result


def promote_attempt(
    mission: Mission,
    ledger: Ledger,
    attempt_id: str,
    *,
    approve: bool,
    reviewer: str | None = None,
    shipper: str | None = None,
) -> list[Path]:
    """Journal intent, publish owned outputs, then atomically record approval."""
    ledger.assert_mission(mission)
    if not approve:
        raise FactoryError("promotion requires explicit --approve")
    pending = ledger.pending_promotion(mission.id)
    if pending is not None:
        if (
            reviewer is None
            or shipper is None
            or pending["reviewer"] != reviewer.strip()
            or pending["shipper"] != shipper.strip()
        ):
            raise FactoryError("pending promotion actors do not match journal")
        return _recover_promotion(mission, ledger, pending)
    status = ledger.status(mission.id)
    if (
        status["state"] != MissionState.PASSED.value
        or status["active_attempt_id"] != attempt_id
    ):
        raise FactoryError("only the active passed attempt can promote")
    if mission.evidence_kind is not EvidenceKind.REAL:
        raise FactoryError("promotion requires real evidence, never mock/smoke/synthetic")
    if reviewer is None:
        raise FactoryError("reviewer approval is required")
    if shipper is None:
        raise FactoryError("shipper approval is required")
    if reviewer.strip().casefold() == shipper.strip().casefold():
        raise FactoryError("reviewer and shipper must be distinct actors")
    provenance, provenance_hash = ledger.provenance(attempt_id)
    if not provenance["passed"] or provenance["evaluation_exit_code"] != 0:
        raise FactoryError("canonical evaluation evidence is not passing")
    attempt = ledger.attempt(attempt_id)
    scratch = Path(attempt["scratch_path"])
    provenance_path = scratch.parent / "provenance.json"
    try:
        provenance_file = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FactoryError(f"provenance integrity check failed: {exc}") from exc
    if (
        hashlib.sha256(_json_text(provenance_file).encode()).hexdigest()
        != provenance_hash
    ):
        raise FactoryError("provenance integrity check failed")
    for relative, expected in provenance["artifact_hashes"].items():
        source = scratch / relative
        try:
            contained_path(scratch, source, require_file=True)
        except FactoryError as exc:
            if source.exists() or source.is_symlink():
                raise
            raise FactoryError(f"artifact integrity check failed: {relative}") from exc
        if sha256_of(source) != expected:
            raise FactoryError(f"artifact integrity check failed: {relative}")
    current_protected = _hash_paths(
        mission.repository.path, mission.protected_artifacts
    )
    if current_protected != provenance["protected_artifact_hashes"]:
        raise FactoryError("protected artifact integrity changed since evaluation")
    evidence_paths = {
        "environment": scratch.parent / "environment.json",
        "protected_before": scratch.parent / "protected-before.json",
        "protected_after": scratch.parent / "protected-after.json",
        "train_stdout": scratch.parent / "train.stdout.log",
        "train_stderr": scratch.parent / "train.stderr.log",
        "evaluation_stdout": scratch.parent / "evaluate.stdout.log",
        "evaluation_stderr": scratch.parent / "evaluate.stderr.log",
        "evaluation_report": scratch / mission.evaluation.report,
    }
    for name, expected in provenance["evidence_hashes"].items():
        path = evidence_paths.get(name)
        if path is None or not path.is_file() or sha256_of(path) != expected:
            raise FactoryError(f"runtime evidence integrity check failed: {name}")
    runtime = ledger.attempt(attempt_id)
    runtime_evidence = {
        key: runtime[key]
        for key in (
            "scratch_path",
            "process_pid",
            "process_identity",
            "train_pid",
            "train_identity",
            "eval_pid",
            "eval_identity",
            "train_exit_code",
            "train_seconds",
            "eval_exit_code",
            "eval_seconds",
        )
    }
    if (
        hashlib.sha256(_json_text(runtime_evidence).encode()).hexdigest()
        != provenance["runtime_evidence_hash"]
        or runtime_evidence != provenance["runtime_evidence"]
    ):
        raise FactoryError("runtime evidence integrity check failed")
    transaction_token = uuid.uuid4().hex
    outputs: list[dict[str, str]] = []
    for index, output in enumerate(mission.outputs):
        source = contained_path(
            scratch, scratch / output.source, require_file=True
        )
        destination = contained_path(
            mission.repository.path,
            mission.repository.path / output.destination,
        )
        stage = destination.parent / f".promotion-{transaction_token}-{index}.tmp"
        contained_path(mission.repository.path, stage)
        outputs.append(
            {
                "source_path": str(source),
                "destination_path": str(destination),
                "stage_path": str(stage),
                "expected_hash": provenance["artifact_hashes"][output.source],
            }
        )
    transaction_id = ledger._begin_promotion(
        mission.id,
        attempt_id,
        reviewer,
        shipper,
        provenance_hash,
        outputs,
    )
    pending = ledger.pending_promotion(mission.id)
    if pending is None or pending["id"] != transaction_id:
        raise FactoryError("promotion journal durability check failed")
    return _recover_promotion(mission, ledger, pending)


def _copy_stage(source: Path, stage: Path, expected_hash: str) -> None:
    stage.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as reader, stage.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
    except FileExistsError:
        pass
    if not stage.is_file() or sha256_of(stage) != expected_hash:
        raise FactoryError(f"promotion stage integrity failed: {stage}")


def _recover_promotion(
    mission: Mission,
    ledger: Ledger,
    transaction: dict[str, Any],
) -> list[Path]:
    """Complete a pending journal only through verifiably owned hard links."""
    destinations: list[Path] = []
    cleanup_stages = False
    try:
        for output in transaction["outputs"]:
            source = contained_path(
                Path(ledger.attempt(transaction["attempt_id"])["scratch_path"]),
                Path(output["source_path"]),
                require_file=True,
            )
            destination = contained_path(
                mission.repository.path, Path(output["destination_path"])
            )
            stage = contained_path(
                mission.repository.path, Path(output["stage_path"])
            )
            expected = output["expected_hash"]
            if sha256_of(source) != expected:
                raise FactoryError(f"promotion source integrity failed: {source}")
            _copy_stage(source, stage, expected)
            contained_path(mission.repository.path, destination)
            contained_path(mission.repository.path, stage, require_file=True)
            if destination.exists():
                if not same_file(destination, stage):
                    raise FactoryError(
                        f"destination collision; refusing artifact overwrite: {destination}"
                    )
            else:
                try:
                    os.link(stage, destination)
                except FileExistsError as exc:
                    raise FactoryError(
                        f"destination collision; refusing artifact overwrite: {destination}"
                    ) from exc
            if (
                not same_file(destination, stage)
                or sha256_of(destination) != expected
            ):
                raise FactoryError(f"published artifact integrity failed: {destination}")
            destinations.append(destination)
        ledger._finalize_promotion(transaction["id"])
        cleanup_stages = True
        return destinations
    except BaseException as original:
        ownership: list[tuple[Path, bool]] = []
        for output in transaction["outputs"]:
            destination = Path(output["destination_path"])
            stage = Path(output["stage_path"])
            try:
                ownership.append((destination, same_file(destination, stage)))
            except FactoryError as exc:
                raise FactoryError(
                    "promotion ownership is indeterminate; "
                    "journal and stages remain pending for recovery"
                ) from exc
        for destination, owned in ownership:
            if owned:
                destination.unlink(missing_ok=True)
        ledger._rollback_promotion(transaction["id"])
        cleanup_stages = True
        raise original
    finally:
        if cleanup_stages:
            for output in transaction["outputs"]:
                stage = Path(output["stage_path"])
                with contextlib.suppress(FileNotFoundError):
                    stage.unlink()


__all__ = [
    "EvidenceKind",
    "Ledger",
    "Mission",
    "MissionState",
    "evaluate_attempt",
    "load_mission",
    "preflight_and_record",
    "preflight_mission",
    "promote_attempt",
    "run_attempt",
]
