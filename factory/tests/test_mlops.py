from __future__ import annotations

import json

import pytest

from factory import mlops
from factory.config import Factory, FactoryError


def test_preflight_names_missing_needs(ws: Factory):
    assert mlops.preflight(ws, ws.job("j1")) == []
    problems = mlops.preflight(ws, ws.job("j2"))
    assert problems == ["missing r1/does-not-exist.py"]
    assert "preflight FAILED" in mlops.render_preflight("j2", problems)


def test_preflight_missing_repo(ws: Factory):
    job = dict(ws.job("j1"), repo="r1")
    (ws.workspace / "r1").rename(ws.workspace / "gone")
    assert "not checked out" in mlops.preflight(ws, job)[0]


def test_gate_states(ws: Factory):
    job = ws.job("j1")
    assert mlops.gate(ws, job)["outcome"] == "no_report"
    report = ws.workspace / "r1" / "out" / "report.json"
    report.parent.mkdir()
    report.write_text(json.dumps({"m": {"value": "nan-string"}}))
    assert mlops.gate(ws, job)["outcome"] == "no_metric"
    report.write_text(json.dumps({"m": {"value": 0.7}}))
    d = mlops.gate(ws, job)
    assert d["outcome"] == "pass" and d["value"] == 0.7
    report.write_text(json.dumps({"m": {"value": 0.2}}))
    assert mlops.gate(ws, job)["outcome"] == "fail"


def test_smoke_run_skips_gate_and_logs(ws: Factory):
    r = mlops.run(ws, ws.job("j1"), smoke=True)
    assert r["rc"] == 0 and r["gate"] == "skipped" and r["smoke"]
    log = ws.runs_dir / "j1" / f"{r['stamp']}.log"
    assert log.read_text().startswith("$ {python} write_report.py --smoke")
    assert "wrote report" in log.read_text()
    assert (ws.runs_dir / "j1" / f"{r['stamp']}.json").is_file()


def test_full_run_passes_gate_then_promote_prints_steps(ws: Factory):
    r = mlops.run(ws, ws.job("j1"))
    assert r["gate"] == "pass" and r["gate_detail"]["value"] == 0.9
    text = mlops.promote(ws, ws.job("j1"))
    assert "copy out/report.json somewhere" in text and "factory done c" in text
    assert "gate=pass" in mlops.list_jobs(ws)


def test_failing_gate_blocks_promotion(ws: Factory):
    q = json.loads(ws.queue_path.read_text())
    q["jobs"][0]["run"] = "{python} write_report.py --bad"
    ws.queue_path.write_text(json.dumps(q))
    r = mlops.run(ws, ws.job("j1"))
    assert r["gate"] == "fail"
    with pytest.raises(FactoryError, match="only a pass can promote"):
        mlops.promote(ws, ws.job("j1"))


def test_promote_needs_a_full_run(ws: Factory):
    with pytest.raises(FactoryError, match="no full run"):
        mlops.promote(ws, ws.job("j1"))
    mlops.run(ws, ws.job("j1"), smoke=True)
    with pytest.raises(FactoryError, match="no full run"):
        mlops.promote(ws, ws.job("j1"))


def test_nonzero_rc_is_fail_even_with_old_report(ws: Factory):
    mlops.run(ws, ws.job("j1"))  # leaves a passing report on disk
    q = json.loads(ws.queue_path.read_text())
    q["jobs"][0]["run"] = '{python} -c "import sys; sys.exit(2)"'
    ws.queue_path.write_text(json.dumps(q))
    r = mlops.run(ws, ws.job("j1"))
    assert r["rc"] == 2 and r["gate"] == "fail"


def test_preflight_failure_is_recorded_not_run(ws: Factory):
    r = mlops.run(ws, ws.job("j2"))
    assert r["gate"] == "preflight_failed" and r["rc"] is None and r["problems"]
    assert not (ws.workspace / "r1" / "out").exists()


def test_next_job_skips_passed_and_unready(ws: Factory):
    assert mlops.next_job(ws)["id"] == "j1"
    mlops.run(ws, ws.job("j1"))
    assert mlops.next_job(ws) is None  # j1 passed, j2 fails preflight


def test_env_from_job_reaches_command(ws: Factory):
    q = json.loads(ws.queue_path.read_text())
    q["jobs"][0]["run"] = (
        "{python} -c \"import os, sys; sys.exit(0 if os.environ.get('FACTORY_T') == 'yes' else 9)\""
    )
    q["jobs"][0]["env"] = {"FACTORY_T": "yes"}
    ws.queue_path.write_text(json.dumps(q))
    assert mlops.run(ws, ws.job("j1"))["rc"] == 0


def test_cuda_status_is_a_string():
    assert isinstance(mlops.cuda_status(), str)


def test_next_job_skips_known_miss_until_code_or_command_changes(ws: Factory):
    import subprocess

    repo = ws.workspace / "r1"
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        cwd=repo,
        check=True,
    )
    q = json.loads(ws.queue_path.read_text())
    q["jobs"][0]["run"] = "{python} write_report.py --bad"
    ws.queue_path.write_text(json.dumps(q))
    assert mlops.run(ws, ws.job("j1"))["gate"] == "fail"
    assert (
        mlops.next_job(ws) is None
    )  # same head, same command: a retry is a known miss
    q["jobs"][0]["run"] = "{python} write_report.py"
    ws.queue_path.write_text(json.dumps(q))
    assert mlops.next_job(ws)["id"] == "j1"  # the command changed


def test_opt_lane_gate_rejects_fast_but_wrong(ws: Factory):
    job = dict(ws.job("j1"))
    job["gate"] = {
        "report": "out/opt.json",
        "metric": "factory.speed_credit",
        "op": ">=",
        "threshold": 0.5,
        "baseline": 0.4,
    }
    report = ws.workspace / "r1" / "out" / "opt.json"
    report.parent.mkdir()
    report.write_text(
        json.dumps(
            {"factory": {"correctness": 0, "speed_credit": 0.99, "speed_percentile": 0.99}}
        )
    )
    d = mlops.gate_opt_lane(ws, job)
    assert d["outcome"] == "fail" and d["metric"] == "factory.correctness" and d["value"] == 0
    report.write_text(
        json.dumps({"factory": {"correctness": 1, "speed_credit": 0.9, "speed_percentile": 0.9}})
    )
    d = mlops.gate_opt_lane(ws, job)
    assert d["outcome"] == "pass" and d["metric"] == "factory.speed_credit" and d["value"] == 0.9
    assert mlops.gate_opt_lane(ws, dict(job, gate={**job["gate"], "report": "out/missing.json"}))[
        "outcome"
    ] == "no_report"
