"""Regression tests for second-pass mission safety findings."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import factory.mission as mission_module
import factory.mission_ledger as ledger_module
import factory.mission_process as process_module
from factory.config import FactoryError
from factory.mission import (
    Ledger,
    MissionState,
    evaluate_attempt,
    load_mission,
    preflight_mission,
    promote_attempt,
    run_attempt,
)
from factory.mission_paths import contained_path


def test_capacity_uses_minimum_active_and_candidate_limits(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    first = load_mission(mission_path)
    second_doc = json.loads(mission_path.read_text())
    second_doc["id"] = "fixture-real-mission-two"
    second_doc["resources"]["max_parallel_jobs"] = 3
    second_path = tmp_path / "mission-two.json"
    second_path.write_text(json.dumps(second_doc))
    second = load_mission(second_path)
    ledger = Ledger(tmp_path / "capacity-min.sqlite3")
    for mission, path in ((first, mission_path), (second, second_path)):
        ledger.propose(mission, path)
        ledger.transition(mission.id, MissionState.READY)

    assert ledger.claim(first.id)
    assert ledger.claim(second.id) is None


def test_dependency_groups_and_poetry_groups_are_denied(
    mission_fixture, tmp_path: Path
):
    repo, _mission_path = mission_fixture
    (repo / "pyproject.toml").write_text(
        "[dependency-groups]\n"
        'quality = ["WandB.Core>=1"]\n'
        "[tool.poetry.group.training.dependencies]\n"
        'ML_Flow = "^2.0"\n',
        encoding="utf-8",
    )

    assert mission_module._declared_dependencies(repo) >= {"wandb-core", "ml-flow"}


def test_malformed_dependency_manifest_blocks_preflight(
    mission_fixture, tmp_path: Path
):
    repo, mission_path = mission_fixture
    (repo / "pyproject.toml").write_text("[project\nbroken = true", encoding="utf-8")
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "malformed-dependencies.sqlite3")
    ledger.propose(mission, mission_path)

    blockers = preflight_mission(mission, ledger)

    assert any("dependency declarations could not be verified" in item for item in blockers)


def test_launched_process_identity_remains_in_audit(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "audit.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    runtime = ledger.attempt(attempt)
    assert runtime["process_pid"] is None
    assert runtime["train_pid"]
    assert runtime["train_identity"]
    evaluate_attempt(mission, ledger, attempt)
    runtime = ledger.attempt(attempt)
    assert runtime["eval_pid"]
    assert runtime["eval_identity"]


def test_generic_runtime_update_cannot_rewrite_process_audit(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "immutable-process-audit.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")

    with pytest.raises(FactoryError, match="invalid attempt runtime fields"):
        ledger.set_runtime(attempt, train_pid=1, train_identity="rewritten")


def test_cancel_between_launch_and_registration_terminates_launch(
    mission_fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger_path = tmp_path / "cancel-race.sqlite3"
    ledger = Ledger(ledger_path)
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    reached_registration = threading.Event()
    release_registration = threading.Event()
    launched: list[subprocess.Popen] = []
    real_register = ledger_module.Ledger.register_process
    real_popen = process_module.subprocess.Popen

    def delayed_register(self, *args):
        reached_registration.set()
        assert release_registration.wait(10)
        return real_register(self, *args)

    def capture_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(ledger_module.Ledger, "register_process", delayed_register)
    monkeypatch.setattr(process_module.subprocess, "Popen", capture_popen)
    errors: list[BaseException] = []

    def launch() -> None:
        try:
            run_attempt(mission, Ledger(ledger_path), tmp_path / "runs")
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=launch)
    worker.start()
    assert reached_registration.wait(10)
    ledger.cancel(mission.id)
    release_registration.set()
    worker.join(10)

    assert not errors
    assert launched and launched[0].poll() is not None
    assert ledger.status(mission.id)["state"] == "cancelled"


@pytest.mark.parametrize("mode", ["recover", "collision", "indeterminate"])
def test_promotion_recovers_or_rolls_back_after_first_publication_crash(
    mode, mission_fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    assert mode in {"recover", "collision", "indeterminate"}
    repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger_path = tmp_path / "recovery.sqlite3"
    ledger = Ledger(ledger_path)
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    evaluate_attempt(mission, ledger, attempt)
    code = (
        "import os,sys\n"
        "from pathlib import Path\n"
        "import factory.mission as m\n"
        "mission=m.load_mission(Path(sys.argv[1]))\n"
        "ledger=m.Ledger(Path(sys.argv[2]))\n"
        "real_link=os.link\n"
        "def crash(source,destination):\n"
        "    real_link(source,destination)\n"
        "    os._exit(73)\n"
        "m.os.link=crash\n"
        "m.promote_attempt(mission,ledger,sys.argv[3],approve=True,"
        "reviewer='reviewer-fixture',shipper='shipper-fixture')\n"
    )
    crashed = subprocess.run(
        [sys.executable, "-c", code, str(mission_path), str(ledger_path), attempt],
        cwd=Path(__file__).parents[2],
        check=False,
    )
    assert crashed.returncode == 73
    assert ledger.pending_promotion(mission.id) is not None
    collision = repo / "release/checkpoint.bin"
    if mode == "indeterminate":
        def fail_identity(_left: Path, _right: Path) -> bool:
            raise FactoryError("filesystem identity could not be verified")

        monkeypatch.setattr(mission_module, "same_file", fail_identity)
        with pytest.raises(FactoryError, match="ownership is indeterminate"):
            promote_attempt(
                mission,
                ledger,
                attempt,
                approve=True,
                reviewer="reviewer-fixture",
                shipper="shipper-fixture",
            )
        assert ledger.pending_promotion(mission.id) is not None
        assert (repo / "release/model.bin").exists()
        return
    if mode == "collision":
        collision.write_bytes(b"external")
        with pytest.raises(FactoryError, match="collision"):
            promote_attempt(
                mission,
                ledger,
                attempt,
                approve=True,
                reviewer="reviewer-fixture",
                shipper="shipper-fixture",
            )
        assert collision.read_bytes() == b"external"
        assert not (repo / "release/model.bin").exists()
        assert ledger.status(mission.id)["state"] == "passed"
        assert ledger.pending_promotion(mission.id) is None
        return

    promoted = promote_attempt(
        mission,
        ledger,
        attempt,
        approve=True,
        reviewer="reviewer-fixture",
        shipper="shipper-fixture",
    )

    assert len(promoted) == 4
    assert all(path.is_file() for path in promoted)
    assert ledger.status(mission.id)["state"] == "promoted"
    assert ledger.pending_promotion(mission.id) is None
    assert (repo / "release/model.bin").read_bytes() == b"model"


def test_promotion_rejects_symlinked_output_source(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "symlink.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    evaluate_attempt(mission, ledger, attempt)
    scratch = Path(ledger.attempt(attempt)["scratch_path"])
    source = scratch / "out/model.bin"
    source.unlink()
    try:
        source.symlink_to(scratch / "out/config.json")
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(FactoryError, match=r"symlink|reparse"):
        promote_attempt(
            mission,
            ledger,
            attempt,
            approve=True,
            reviewer="reviewer-fixture",
            shipper="shipper-fixture",
        )


def test_containment_rejects_symlink_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "root"
    root.mkdir()
    artifact = root / "artifact.bin"
    artifact.write_bytes(b"artifact")
    real_lstat = Path.lstat

    def symlink_lstat(path: Path):
        details = real_lstat(path)
        if path == artifact:
            values = list(details)
            values[0] = stat.S_IFLNK | 0o777
            return os.stat_result(values)
        return details

    monkeypatch.setattr(Path, "lstat", symlink_lstat)
    with pytest.raises(FactoryError, match="symlink"):
        contained_path(root, artifact, require_file=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_containment_rejects_windows_junction(tmp_path: Path):
    root = tmp_path / "root"
    target = tmp_path / "target"
    root.mkdir()
    target.mkdir()
    junction = root / "junction"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"junction creation unavailable: {created.stderr}")
    with pytest.raises(FactoryError, match="reparse"):
        contained_path(root, junction / "artifact.bin")


def test_ledger_exposes_no_unbound_approval_methods(tmp_path: Path):
    ledger = Ledger(tmp_path / "approval.sqlite3")
    assert not hasattr(ledger, "approve")
    assert not hasattr(ledger, "approve_promotion")
    assert not hasattr(ledger, "finalize_promotion")
