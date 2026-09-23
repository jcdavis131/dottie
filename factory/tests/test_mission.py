"""Deterministic unit evidence for mission controls; never model evidence."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from factory.cli import main
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
from factory.mission_process import run_capture, terminate_process_tree


def test_mission_rejects_unknown_fields_and_incomplete_identity(mission_fixture):
    _repo, mission_path = mission_fixture
    doc = json.loads(mission_path.read_text())
    doc["surprise"] = True
    mission_path.write_text(json.dumps(doc))
    with pytest.raises(FactoryError, match="unknown fields"):
        load_mission(mission_path)
    del doc["surprise"]
    del doc["datasets"][0]["license"]
    mission_path.write_text(json.dumps(doc))
    with pytest.raises(FactoryError, match="missing fields"):
        load_mission(mission_path)


def test_mission_rejects_nested_unknown_fields_and_wrong_scalar_types(mission_fixture):
    _repo, mission_path = mission_fixture
    doc = json.loads(mission_path.read_text())
    doc["resources"]["surprise"] = True
    mission_path.write_text(json.dumps(doc))
    with pytest.raises(FactoryError, match="unknown fields"):
        load_mission(mission_path)

    del doc["resources"]["surprise"]
    doc["metrics"][0]["threshold"] = True
    mission_path.write_text(json.dumps(doc))
    with pytest.raises(FactoryError, match="expected finite number"):
        load_mission(mission_path)


@pytest.mark.parametrize(
    "mission_id",
    [
        "../escape",
        "/absolute",
        r"C:\absolute",
        "nested/path",
        r"nested\path",
        "UPPERCASE",
        "two words",
        ".hidden",
        "trailing-",
    ],
)
def test_mission_rejects_non_slug_ids(mission_fixture, mission_id):
    _repo, mission_path = mission_fixture
    doc = json.loads(mission_path.read_text())
    doc["id"] = mission_id
    mission_path.write_text(json.dumps(doc))

    with pytest.raises(FactoryError, match="restricted slug"):
        load_mission(mission_path)


def test_ledger_transitions_and_atomic_claim(mission_fixture, tmp_path: Path):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    with pytest.raises(FactoryError, match="illegal transition"):
        ledger.transition(mission.id, MissionState.RUNNING)
    ledger.transition(mission.id, MissionState.READY)
    winner = ledger.claim(mission.id)
    assert winner
    assert ledger.claim(mission.id) is None
    assert ledger.status(mission.id)["state"] == "running"


def test_unknown_transition_fails_as_factory_error(mission_fixture, tmp_path: Path):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)

    with pytest.raises(FactoryError, match="transition"):
        ledger.transition(mission.id, "teleported")  # type: ignore[arg-type]


def test_concurrent_claim_has_exactly_one_attempt(mission_fixture, tmp_path: Path):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger_path = tmp_path / "ledger.sqlite3"
    ledger = Ledger(ledger_path)
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    barrier = threading.Barrier(8)
    results: list[str | None] = []

    def contend() -> None:
        contender = Ledger(ledger_path)
        barrier.wait()
        results.append(contender.claim(mission.id))

    threads = [threading.Thread(target=contend) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(result is not None for result in results) == 1
    with sqlite3.connect(ledger_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM transitions WHERE to_state='running'")
            .fetchone()[0]
            == 1
        )


def test_concurrent_process_claim_has_exactly_one_winner(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger_path = tmp_path / "process-ledger.sqlite3"
    ledger = Ledger(ledger_path)
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    gate = tmp_path / "claimers.go"
    code = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from factory.mission import Ledger\n"
        "ledger,mission,ready,gate=sys.argv[1:]\n"
        "Path(ready).write_text('ready')\n"
        "while not Path(gate).exists(): time.sleep(0.005)\n"
        "print(Ledger(Path(ledger)).claim(mission) or '')\n"
    )
    processes = []
    for index in range(6):
        ready = tmp_path / f"claimer-{index}.ready"
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    code,
                    str(ledger_path),
                    mission.id,
                    str(ready),
                    str(gate),
                ],
                cwd=Path(__file__).parents[2],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if len(list(tmp_path.glob("claimer-*.ready"))) == len(processes):
            break
        time.sleep(0.01)
    else:
        pytest.fail("subprocess claimers did not reach the contention barrier")
    gate.write_text("go", encoding="utf-8")
    outputs = [process.communicate(timeout=15) for process in processes]
    assert all(process.returncode == 0 for process in processes), outputs
    assert sum(bool(stdout.strip()) for stdout, _stderr in outputs) == 1
    with sqlite3.connect(ledger_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_capacity_claim_allows_one_of_two_ready_missions(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    first = load_mission(mission_path)
    second_doc = json.loads(mission_path.read_text())
    second_doc["id"] = "fixture-real-mission-two"
    second_path = tmp_path / "mission-two.json"
    second_path.write_text(json.dumps(second_doc))
    second = load_mission(second_path)
    ledger_path = tmp_path / "capacity.sqlite3"
    ledger = Ledger(ledger_path)
    for mission, path in ((first, mission_path), (second, second_path)):
        ledger.propose(mission, path)
        ledger.transition(mission.id, MissionState.READY)
    barrier = threading.Barrier(2)
    results: list[str | None] = []

    def contend(mission_id: str) -> None:
        contender = Ledger(ledger_path)
        barrier.wait()
        results.append(contender.claim(mission_id))

    threads = [
        threading.Thread(target=contend, args=(first.id,)),
        threading.Thread(target=contend, args=(second.id,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(result is not None for result in results) == 1
    assert ledger.running_count() == 1


def test_preflight_dirty_tree_and_safe_end_to_end(mission_fixture, tmp_path: Path):
    repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    assert preflight_mission(mission, ledger) == []
    (repo / "dirty.txt").write_text("dirty", encoding="utf-8")
    assert any("dirty" in item for item in preflight_mission(mission, ledger))
    (repo / "dirty.txt").unlink()

    ledger.transition(mission.id, MissionState.READY)
    attempt_id = run_attempt(mission, ledger, tmp_path / "runs")
    assert ledger.status(mission.id)["state"] == "evaluating"
    assert evaluate_attempt(mission, ledger, attempt_id)["passed"] is True
    provenance = ledger.status(mission.id)["provenance"]
    assert provenance["evidence_kind"] == "real"
    with pytest.raises(FactoryError, match="explicit"):
        promote_attempt(mission, ledger, attempt_id, approve=False)
    promote_attempt(
        mission,
        ledger,
        attempt_id,
        approve=True,
        reviewer="reviewer-fixture",
        shipper="shipper-fixture",
    )
    assert (repo / "release" / "model.bin").read_bytes() == b"model"
    status = ledger.status(mission.id)
    assert status["state"] == "promoted"
    _provenance, provenance_hash = ledger.provenance(attempt_id)
    assert {approval["role"] for approval in status["approvals"]} == {
        "reviewer",
        "shipper",
    }
    assert {
        approval["provenance_hash"] for approval in status["approvals"]
    } == {provenance_hash}


def test_preflight_refuses_clean_sha_drift(mission_fixture, tmp_path: Path):
    repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "drift",
        ],
        cwd=repo,
        check=True,
    )

    blockers = preflight_mission(mission, ledger)

    assert any("code SHA drift" in blocker for blocker in blockers)


def test_preflight_rejects_placeholder_identity_fields(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    doc = json.loads(mission_path.read_text())
    doc["datasets"][0]["license"] = "N/A"
    doc["datasets"][0]["revision"] = "TODO: pin source"
    doc["evaluation"]["contract_revision"] = "placeholder-v1"
    mission_path.write_text(json.dumps(doc))
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)

    blockers = preflight_mission(mission, ledger)

    assert any("license is unverified" in blocker for blocker in blockers)
    assert any("source revision is unverified" in blocker for blocker in blockers)
    assert any("contract revision is unverified" in blocker for blocker in blockers)


def test_denied_dependency_matching_uses_declared_package_name(
    mission_fixture, tmp_path: Path
):
    repo, mission_path = mission_fixture
    requirements = repo / "requirements.txt"
    requirements.write_text("wandb-core==1.0\n", encoding="utf-8")
    subprocess.run(["git", "add", "requirements.txt"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "dependency fixture",
        ],
        cwd=repo,
        check=True,
    )
    doc = json.loads(mission_path.read_text())
    doc["repository"]["code_sha"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    mission_path.write_text(json.dumps(doc))
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    assert not any(
        "denied dependency" in blocker
        for blocker in preflight_mission(mission, ledger)
    )

    requirements.write_text("wandb>=0.16\n", encoding="utf-8")
    assert any(
        "denied dependency is declared: wandb" in blocker
        for blocker in preflight_mission(mission, ledger)
    )


def test_training_exit_and_snapshot_drift_fail_closed(
    mission_fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, mission_path = mission_fixture
    (repo / "train.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
    subprocess.run(["git", "add", "train.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "failing trainer"],
        cwd=repo,
        check=True,
    )
    doc = json.loads(mission_path.read_text())
    doc["repository"]["code_sha"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    mission_path.write_text(json.dumps(doc))
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "exit-ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "exit-runs")
    assert ledger.attempt(attempt)["train_exit_code"] == 9
    assert ledger.status(mission.id)["state"] == "failed"

    ledger = Ledger(tmp_path / "drift-ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    implementation = sys.modules[run_attempt.__module__]
    original_copytree = implementation.shutil.copytree

    def drifting_copytree(*args, **kwargs):
        copied = original_copytree(*args, **kwargs)
        (repo / "drift.txt").write_text("changed during copy", encoding="utf-8")
        return copied

    monkeypatch.setattr(implementation.shutil, "copytree", drifting_copytree)
    with pytest.raises(FactoryError, match="source drift"):
        run_attempt(mission, ledger, tmp_path / "drift-runs")
    assert ledger.status(mission.id)["state"] == "failed"


def test_snapshot_rejects_copied_dataset_hash_drift(
    mission_fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    implementation = sys.modules[run_attempt.__module__]
    original_copytree = implementation.shutil.copytree

    def corrupting_copytree(*args, **kwargs):
        copied = Path(original_copytree(*args, **kwargs))
        if Path(args[0]) == mission.repository.path:
            (copied / "data/input.csv").write_text("corrupted", encoding="utf-8")
        return copied

    monkeypatch.setattr(implementation.shutil, "copytree", corrupting_copytree)
    with pytest.raises(FactoryError, match="snapshot dataset hash mismatch"):
        run_attempt(mission, ledger, tmp_path / "runs")
    assert ledger.status(mission.id)["state"] == "failed"


def test_post_snapshot_setup_exception_fails_active_attempt(
    mission_fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    implementation = sys.modules[run_attempt.__module__]
    original_atomic_json = implementation._atomic_json

    def fail_environment(path, value):
        if path.name == "environment.json":
            raise OSError("injected environment persistence failure")
        return original_atomic_json(path, value)

    monkeypatch.setattr(implementation, "_atomic_json", fail_environment)
    with pytest.raises(OSError, match="injected"):
        run_attempt(mission, ledger, tmp_path / "runs")
    assert ledger.status(mission.id)["state"] == "failed"


def test_launch_recording_failure_terminates_exact_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import factory.mission_process as process_module

    launched: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def capture_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        launched.append(process)
        return process

    class BrokenLedger:
        def register_process(self, *args):
            raise OSError("injected ledger write failure")

    monkeypatch.setattr(process_module.subprocess, "Popen", capture_popen)
    with pytest.raises(OSError, match="injected"):
        run_capture(
            (sys.executable, "-c", "import time; time.sleep(60)"),
            tmp_path,
            tmp_path / "stdout.log",
            tmp_path / "stderr.log",
            BrokenLedger(),
            "mission",
            "attempt",
            "train",
        )
    assert launched
    assert launched[0].poll() is not None


def test_cancel_terminates_only_recorded_sleeping_process(mission_fixture, tmp_path: Path):
    repo, mission_path = mission_fixture
    (repo / "train.py").write_text(
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "Path('child.pid').write_text(str(child.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "train.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "sleeping trainer"],
        cwd=repo,
        check=True,
    )
    doc = json.loads(mission_path.read_text())
    doc["repository"]["code_sha"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    mission_path.write_text(json.dumps(doc))
    mission = load_mission(mission_path)
    ledger_path = tmp_path / "cancel-ledger.sqlite3"
    ledger = Ledger(ledger_path)
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    errors: list[BaseException] = []

    def launch() -> None:
        try:
            run_attempt(mission, Ledger(ledger_path), tmp_path / "cancel-runs")
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=launch)
    worker.start()
    deadline = time.monotonic() + 10
    pid = None
    child_pid = None
    while time.monotonic() < deadline:
        attempt_id = ledger.status(mission.id)["active_attempt_id"]
        if attempt_id:
            attempt = ledger.attempt(attempt_id)
            pid = attempt.get("process_pid")
            if attempt.get("scratch_path"):
                child_pid_path = Path(attempt["scratch_path"]) / "child.pid"
                if child_pid_path.is_file():
                    child_pid = int(child_pid_path.read_text())
        if pid and child_pid:
            break
        time.sleep(0.02)
    assert pid and child_pid
    Ledger(ledger_path).cancel(mission.id)
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert ledger.status(mission.id)["state"] == "cancelled"
    assert not errors
    for terminated_pid in (pid, child_pid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(terminated_pid, 0)
            except OSError:
                break
            time.sleep(0.02)
        else:
            pytest.fail(f"process {terminated_pid} survived tree cancellation")


def test_phase_gap_cancel_uses_state_when_process_is_clear(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    runtime = ledger.attempt(attempt)
    assert runtime["process_pid"] is None
    assert runtime["process_identity"] is None

    ledger.cancel(mission.id)

    assert ledger.status(mission.id)["state"] == "cancelled"


def test_cancellation_refuses_reused_or_mismatched_process_identity():
    with pytest.raises(FactoryError, match="no longer exact"):
        terminate_process_tree(os.getpid(), "definitely-not-this-process")


def test_evaluator_exit_propagates_and_resume_is_new_attempt(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    first = run_attempt(mission, ledger, tmp_path / "runs")
    scratch = Path(ledger.attempt(first)["scratch_path"])
    (scratch / "evaluate.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
    result = evaluate_attempt(mission, ledger, first)
    assert result["exit_code"] == 7
    assert ledger.status(mission.id)["state"] == "failed"
    second = ledger.resume(mission.id)
    assert second != first
    assert ledger.attempt(second)["parent_attempt_id"] == first
    changed = json.loads(mission_path.read_text())
    changed["train"]["argv"].append("--changed")
    mission_path.write_text(json.dumps(changed))
    with pytest.raises(FactoryError, match="lineage integrity"):
        run_attempt(load_mission(mission_path), ledger, tmp_path / "runs")


def test_evaluation_claim_rejects_cross_mission_and_concurrent_attempt(
    mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    first = load_mission(mission_path)
    second_doc = json.loads(mission_path.read_text())
    second_doc["id"] = "fixture-real-mission-two"
    second_path = tmp_path / "mission-two.json"
    second_path.write_text(json.dumps(second_doc))
    second = load_mission(second_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(first, mission_path)
    ledger.transition(first.id, MissionState.READY)
    attempt = run_attempt(first, ledger, tmp_path / "runs")
    ledger.propose(second, second_path)

    with pytest.raises(FactoryError, match="does not belong"):
        ledger.claim_evaluation(second.id, attempt)
    ledger.claim_evaluation(first.id, attempt)
    with pytest.raises(FactoryError, match="already claimed"):
        ledger.claim_evaluation(first.id, attempt)


def test_evaluation_exception_fails_active_attempt(
    mission_fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    implementation = sys.modules[evaluate_attempt.__module__]

    def fail_evaluation(*args, **kwargs):
        raise OSError("injected evaluation failure")

    monkeypatch.setattr(implementation, "run_capture", fail_evaluation)
    with pytest.raises(OSError, match="injected"):
        evaluate_attempt(mission, ledger, attempt)
    assert ledger.status(mission.id)["state"] == "failed"


def test_provenance_is_append_only_per_attempt(mission_fixture, tmp_path: Path):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    evaluate_attempt(mission, ledger, attempt)
    provenance, _digest = ledger.provenance(attempt)

    with pytest.raises(FactoryError, match="provenance is immutable"):
        ledger.add_provenance(attempt, provenance)


@pytest.mark.parametrize("metric", [float("nan"), True])
def test_invalid_metrics_fail(metric, mission_fixture, tmp_path: Path):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / f"metric-{type(metric).__name__}.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "metric-runs")
    scratch = Path(ledger.attempt(attempt)["scratch_path"])
    metric_expression = "float('nan')" if isinstance(metric, float) else repr(metric)
    (scratch / "evaluate.py").write_text(
        "import json\nfrom pathlib import Path\n"
        f"Path('out/report.json').write_text(json.dumps({{'contract_revision': "
        f"'fixture-contract-v1', 'metrics': {{'score': {metric_expression}}}}}))\n",
        encoding="utf-8",
    )
    result = evaluate_attempt(mission, ledger, attempt)
    assert result["passed"] is False
    assert any("non-finite" in problem for problem in result["problems"])


def test_stale_report_fails(mission_fixture, tmp_path: Path):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "stale.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "stale-runs")
    scratch = Path(ledger.attempt(attempt)["scratch_path"])
    old = time.time() - 120
    (scratch / "evaluate.py").write_text(
        "import json, os, time\nfrom pathlib import Path\n"
        "p=Path('out/report.json')\n"
        "p.write_text(json.dumps({'contract_revision':'fixture-contract-v1',"
        "'metrics':{'score':0.9}}))\n"
        f"os.utime(p, ({old}, {old}))\n",
        encoding="utf-8",
    )
    result = evaluate_attempt(mission, ledger, attempt)
    assert "canonical evaluation report is stale" in result["problems"]


def test_promotion_preconditions_leave_no_partial_writes(mission_fixture, tmp_path: Path):
    repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "promote-ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "promote-runs")
    evaluate_attempt(mission, ledger, attempt)
    (repo / "release").mkdir()
    (repo / "release/model.bin").write_bytes(b"existing")
    with pytest.raises(FactoryError, match="overwrite"):
        promote_attempt(
            mission,
            ledger,
            attempt,
            approve=True,
            reviewer="reviewer-fixture",
            shipper="shipper-fixture",
        )
    assert ledger.status(mission.id)["approvals"] == []
    assert not (repo / "release/checkpoint.bin").exists()
    (repo / "release/model.bin").unlink()
    with pytest.raises(FactoryError, match="distinct"):
        promote_attempt(
            mission, ledger, attempt, approve=True, reviewer="same", shipper="same"
        )

    scratch = Path(ledger.attempt(attempt)["scratch_path"])
    model = scratch / "out/model.bin"
    model.write_bytes(b"tampered")
    with pytest.raises(FactoryError, match="artifact integrity"):
        promote_attempt(
            mission, ledger, attempt, approve=True,
            reviewer="reviewer-fixture", shipper="shipper-fixture"
        )
    model.write_bytes(b"model")
    (scratch.parent / "provenance.json").write_text("{}")
    with pytest.raises(FactoryError, match="provenance integrity"):
        promote_attempt(
            mission, ledger, attempt, approve=True,
            reviewer="reviewer-fixture", shipper="shipper-fixture"
        )
    assert ledger.status(mission.id)["approvals"] == []


def test_mid_promotion_failure_rolls_back_only_created_outputs(
    mission_fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    evaluate_attempt(mission, ledger, attempt)
    implementation = sys.modules[promote_attempt.__module__]
    real_link = implementation.os.link
    links = 0

    def fail_second_materialization(source, destination):
        nonlocal links
        if Path(destination).name in {
            "model.bin",
            "checkpoint.bin",
            "tokenizer.json",
            "config.json",
        }:
            links += 1
            if links == 2:
                raise OSError("injected materialization failure")
        return real_link(source, destination)

    monkeypatch.setattr(implementation.os, "link", fail_second_materialization)
    with pytest.raises(OSError, match="injected"):
        promote_attempt(
            mission,
            ledger,
            attempt,
            approve=True,
            reviewer="reviewer-fixture",
            shipper="shipper-fixture",
        )
    assert not any((repo / output.destination).exists() for output in mission.outputs)
    assert ledger.status(mission.id)["approvals"] == []
    assert ledger.status(mission.id)["state"] == "passed"


def test_external_destination_collision_is_never_overwritten(
    mission_fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    evaluate_attempt(mission, ledger, attempt)
    implementation = sys.modules[promote_attempt.__module__]
    real_copy_stage = implementation._copy_stage
    collision = repo / mission.outputs[0].destination
    injected = False

    def inject_collision(source, destination, expected_hash):
        nonlocal injected
        if not injected:
            collision.parent.mkdir(parents=True, exist_ok=True)
            collision.write_bytes(b"external")
            injected = True
        return real_copy_stage(source, destination, expected_hash)

    monkeypatch.setattr(implementation, "_copy_stage", inject_collision)
    with pytest.raises(FactoryError, match=r"collision|overwrite"):
        promote_attempt(
            mission,
            ledger,
            attempt,
            approve=True,
            reviewer="reviewer-fixture",
            shipper="shipper-fixture",
        )
    assert collision.read_bytes() == b"external"
    assert ledger.status(mission.id)["approvals"] == []


def test_promotion_rechecks_bound_runtime_evidence(mission_fixture, tmp_path: Path):
    _repo, mission_path = mission_fixture
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    evaluate_attempt(mission, ledger, attempt)
    scratch = Path(ledger.attempt(attempt)["scratch_path"])
    (scratch.parent / "train.stdout.log").write_text("tampered", encoding="utf-8")

    with pytest.raises(FactoryError, match="runtime evidence integrity"):
        promote_attempt(
            mission,
            ledger,
            attempt,
            approve=True,
            reviewer="reviewer-fixture",
            shipper="shipper-fixture",
        )
    assert ledger.status(mission.id)["approvals"] == []


def test_cli_blocked_gridiron_preflight_and_lifecycle(mission_fixture, tmp_path: Path, ws, capsys):
    _repo, mission_path = mission_fixture
    ledger = tmp_path / "cli.sqlite3"
    common = ["mission", "--ledger", str(ledger), "--runs-root", str(tmp_path / "runs")]
    assert main([*common, "propose", str(mission_path)], factory=ws) == 0
    assert main([*common, "preflight", str(mission_path)], factory=ws) == 0
    assert main([*common, "run", str(mission_path)], factory=ws) == 0
    assert main([*common, "evaluate", str(mission_path)], factory=ws) == 0
    assert main([*common, "promote", str(mission_path)], factory=ws) == 1
    assert main([*common, "status", "fixture-real-mission"], factory=ws) == 0
    assert main([*common, "cancel", "fixture-real-mission"], factory=ws) == 0
    assert main([*common, "resume", "fixture-real-mission"], factory=ws) == 0

    blocked_path = Path(__file__).parents[1] / "missions" / "gridiron-real-blocked.json"
    blocked_ledger = tmp_path / "blocked.sqlite3"
    blocked_common = ["mission", "--ledger", str(blocked_ledger)]
    assert main([*blocked_common, "propose", str(blocked_path)], factory=ws) == 0
    assert main([*blocked_common, "preflight", str(blocked_path)], factory=ws) == 1
    joined = capsys.readouterr().out
    assert "exact license is unverified" in joined
    assert "immutable source revision is unverified" in joined
    assert "SHA-256 is unverified" in joined
    assert "metric contract revision is unverified" in joined
    assert "evaluation command path is missing" in joined
    assert "GPU" in joined
    assert "promoted" not in joined.lower()


@pytest.mark.parametrize(
    "evidence_kind",
    ["smoke", "unit", "measurement", "mock", "placeholder", "synthetic"],
)
def test_non_real_evidence_never_promotes(
    evidence_kind, mission_fixture, tmp_path: Path
):
    _repo, mission_path = mission_fixture
    doc = json.loads(mission_path.read_text())
    doc["evidence_kind"] = evidence_kind
    mission_path.write_text(json.dumps(doc))
    mission = load_mission(mission_path)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.propose(mission, mission_path)
    ledger.transition(mission.id, MissionState.READY)
    attempt = run_attempt(mission, ledger, tmp_path / "runs")
    evaluate_attempt(mission, ledger, attempt)
    with pytest.raises(FactoryError, match="real evidence"):
        promote_attempt(
            mission,
            ledger,
            attempt,
            approve=True,
            reviewer="reviewer-fixture",
            shipper="shipper-fixture",
        )


def test_cli_evaluator_failure_returns_nonzero(mission_fixture, tmp_path: Path, ws):
    _repo, mission_path = mission_fixture
    ledger_path = tmp_path / "cli-failure.sqlite3"
    runs_root = tmp_path / "runs"
    common = [
        "mission",
        "--ledger",
        str(ledger_path),
        "--runs-root",
        str(runs_root),
    ]
    assert main([*common, "propose", str(mission_path)], factory=ws) == 0
    assert main([*common, "preflight", str(mission_path)], factory=ws) == 0
    assert main([*common, "run", str(mission_path)], factory=ws) == 0
    ledger = Ledger(ledger_path)
    attempt_id = ledger.status("fixture-real-mission")["active_attempt_id"]
    scratch = Path(ledger.attempt(attempt_id)["scratch_path"])
    (scratch / "evaluate.py").write_text("raise SystemExit(17)\n", encoding="utf-8")

    assert main([*common, "evaluate", str(mission_path)], factory=ws) == 1
