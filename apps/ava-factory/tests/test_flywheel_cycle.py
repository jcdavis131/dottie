"""Tests for scripts/flywheel_cycle.py — the P2 flywheel bridge.

Hermetic: never touches the real runner store, the repo bundles tree, or the
real reports — collect and gate parsing are unit-tested against tmp_path, and
the end-to-end exit-code tests drive main() against a fixture repo tree with
subprocess.run monkeypatched to a recorder. No real training cycle ever runs
here (the trainer and miner are only ever fake subprocess calls).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import flywheel_cycle as fc

_REPO = Path(__file__).resolve().parents[3]
_REAL_COPY_ARTIFACTS = (
    _REPO / "apps" / "dottie-harness-api" / "lib" / "copy_artifacts.py"
)

# ---------------------------------------------------------------- helpers


class _SubprocessRecorder:
    """Stands in for subprocess.run: records argv, optionally fails one cmd."""

    def __init__(self, fail_substring: str | None = None, stderr: str = ""):
        self.calls: list[list[str]] = []
        self.fail_substring = fail_substring
        self.stderr = stderr

    def __call__(self, cmd, **kwargs):
        argv = [str(c) for c in cmd]
        self.calls.append(argv)
        rc = 0
        if self.fail_substring is not None and any(
            self.fail_substring in a for a in argv
        ):
            rc = 1
        return subprocess.CompletedProcess(
            argv, rc, stdout="[fake] ok\n", stderr=self.stderr if rc else ""
        )

    def scripts(self) -> list[str]:
        return [Path(argv[1]).name for argv in self.calls]


def _fake_repo(tmp_path: Path, *, gate_passed=False, reason="fixture: gate closed"):
    """A minimal repo tree with committed-artifact stand-ins.

    Uses the REAL copy_artifacts.py (copied in, its path resolution is
    __file__-relative) so the sync step exercises genuine reuse.
    """
    repo = tmp_path / "repo"
    ava = repo / "apps" / "ava-factory"
    pkg = repo / "apps" / "dottie-harness-api"
    (ava / "scripts").mkdir(parents=True)
    (ava / "data" / "orchestration").mkdir(parents=True)
    (ava / "reports" / "orchestrator").mkdir(parents=True)
    (pkg / "lib").mkdir(parents=True)
    (pkg / "scripts").mkdir(parents=True)
    shutil.copyfile(_REAL_COPY_ARTIFACTS, pkg / "lib" / "copy_artifacts.py")
    eval_report = {
        "schema_version": 1,
        "built_at": "2026-08-09T00:00:00+00:00",
        "corpus_source": "fixture",
        "trainer": "fixture",
        "champion": {
            "name": "fx",
            "model_version": "orch-mlp-v1-fx",
            "risk_calibration": {"deciles": [], "brier": 0.1},
        },
        "gate": {"gate_passed": gate_passed, "reason": reason},
        "notes": [],
    }
    (ava / "reports" / "orchestrator" / "eval_report.json").write_text(
        json.dumps(eval_report), encoding="utf-8"
    )
    (ava / "reports" / "orchestrator" / "champion_weights.json").write_text(
        f'{{"schema_version": 1, "gate_passed": {json.dumps(gate_passed)}}}',
        encoding="utf-8",
    )
    (ava / "data" / "orchestration" / "corpus_meta.json").write_text(
        json.dumps(
            {"counts": {"total": 3, "by_provenance": {"measured": 1, "simulated": 2}}}
        ),
        encoding="utf-8",
    )
    return repo


def _wire(monkeypatch, tmp_path: Path, repo: Path, recorder) -> None:
    monkeypatch.setattr(fc, "_REPO", repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # runner store absent
    monkeypatch.setattr(fc.subprocess, "run", recorder)


def _summary(repo: Path) -> dict:
    path = repo / "apps" / "ava-factory" / "reports" / "flywheel" / "cycle-summary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _steps(summary: dict) -> dict[str, dict]:
    return {s["name"]: s for s in summary["steps"]}


# ---------------------------------------------------------------- collect


def test_collect_copies_new_and_skips_existing(tmp_path):
    src = tmp_path / "runner-store"
    dst = tmp_path / "repo-store"
    for name in ("harness-run-a", "harness-run-b"):
        d = src / name
        d.mkdir(parents=True)
        (d / "timeline.jsonl").write_text('{"nodeId": "x"}\n', encoding="utf-8")
        (d / "checkpoint.json").write_text("{}", encoding="utf-8")
    (src / "stray-file.txt").write_text("not a run dir", encoding="utf-8")
    (dst / "harness-run-a").mkdir(parents=True)  # already landed -> skipped

    out = fc.collect_runs(src, dst)

    assert out["status"] == "ok"
    assert out["copied"] == 1
    assert out["skipped"] == 1
    copied = dst / "harness-run-b"
    assert (copied / "timeline.jsonl").read_text(encoding="utf-8").startswith(
        '{"nodeId"'
    )
    assert (copied / "checkpoint.json").exists()
    # skipped dir untouched, stray files never copied
    assert not (dst / "harness-run-a" / "timeline.jsonl").exists()
    assert not (dst / "stray-file.txt").exists()


def test_collect_interrupted_copy_is_restaged_not_frozen(tmp_path):
    """A cycle killed mid-copy must not freeze a half-copied run dir: copies
    land via a staging name renamed into place, and stale staging dirs from a
    crashed cycle are removed and re-copied whole."""
    src = tmp_path / "runner-store"
    run = src / "harness-run-a"
    run.mkdir(parents=True)
    (run / "timeline.jsonl").write_text('{"nodeId": "x"}\n', encoding="utf-8")
    (run / "checkpoint.json").write_text("{}", encoding="utf-8")
    dst = tmp_path / "repo-store"
    stale = dst / "harness-run-a.tmp-collect"  # previous cycle died mid-copy
    stale.mkdir(parents=True)
    (stale / "timeline.jsonl").write_text('{"trunc', encoding="utf-8")

    out = fc.collect_runs(src, dst)

    assert out["status"] == "ok"
    assert out["copied"] == 1
    assert not stale.exists()
    landed = dst / "harness-run-a"
    assert (landed / "timeline.jsonl").read_text("utf-8") == '{"nodeId": "x"}\n'
    assert (landed / "checkpoint.json").exists()  # whole run, not the truncation
    # no staging dirs linger for the miner to pick up as run dirs
    assert list(dst.glob("*.tmp-collect")) == []


def test_collect_missing_source_is_recorded_noop(tmp_path):
    out = fc.collect_runs(tmp_path / "does-not-exist", tmp_path / "repo-store")
    assert out["status"] == "ok"
    assert out["copied"] == 0
    assert out["skipped"] == 0
    assert "absent" in out["note"]
    assert not (tmp_path / "repo-store").exists()  # true no-op


# ---------------------------------------------------------------- gate


def test_gate_promoted_only_on_strict_true(tmp_path):
    p = tmp_path / "eval_report.json"
    p.write_text(
        json.dumps({"gate": {"gate_passed": True, "reason": "beats both"}}),
        encoding="utf-8",
    )
    out = fc.resolve_gate(p)
    assert out["promoted"] is True
    assert out["gate_passed"] is True
    assert out["reason"] == "beats both"


@pytest.mark.parametrize("value", [False, "true", "True", 1, 0, None, [], {}])
def test_gate_non_true_values_resolve_not_promoted(tmp_path, value):
    p = tmp_path / "eval_report.json"
    p.write_text(
        json.dumps({"gate": {"gate_passed": value, "reason": "r"}}), encoding="utf-8"
    )
    out = fc.resolve_gate(p)
    assert out["promoted"] is False


def test_gate_missing_file_not_promoted(tmp_path):
    out = fc.resolve_gate(tmp_path / "absent" / "eval_report.json")
    assert out["promoted"] is False
    assert "missing" in out["reason"]


def test_gate_garbage_json_not_promoted(tmp_path):
    p = tmp_path / "eval_report.json"
    p.write_text("{not json at all", encoding="utf-8")
    out = fc.resolve_gate(p)
    assert out["promoted"] is False
    assert "unreadable" in out["reason"]


@pytest.mark.parametrize(
    "doc", [{}, {"gate": None}, {"gate": "passed"}, {"gate": [True]}, [1, 2]]
)
def test_gate_missing_or_odd_gate_section_not_promoted(tmp_path, doc):
    p = tmp_path / "eval_report.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    out = fc.resolve_gate(p)
    assert out["promoted"] is False
    assert "fail closed" in out["reason"]


# ---------------------------------------------------------------- full cycle


def test_cycle_not_promoted_is_success_and_syncs_meta_only(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path, gate_passed=False)
    recorder = _SubprocessRecorder()
    _wire(monkeypatch, tmp_path, repo, recorder)

    rc = fc.main(["--journal-dir", str(tmp_path / "journal"), "--epochs", "5"])

    assert rc == 0
    assert recorder.scripts() == [
        "build_orchestration_corpus.py",
        "orchestrator_hillclimb.py",
        "build_dashboard.py",
    ]
    mine_cmd, train_cmd, _ = recorder.calls
    assert "--journal-dir" in mine_cmd
    assert str(tmp_path / "journal") in mine_cmd
    assert train_cmd[train_cmd.index("--epochs") + 1] == "5"

    summary = _summary(repo)
    assert summary["ok"] is True
    assert summary["promoted"] is False
    assert summary["gate"] == {
        "gate_passed": False,
        "reason": "fixture: gate closed",
    }
    assert summary["deploy_required"] is True  # meta went absent -> present
    assert summary["corpus_counts"]["total"] == 3
    steps = _steps(summary)
    assert [s["name"] for s in summary["steps"]] == [
        "collect", "mine", "train", "gate", "sync", "dashboard",
    ]
    assert all(s["status"] == "ok" for s in summary["steps"])
    assert steps["sync"]["mode"] == "meta_only"

    lib = repo / "apps" / "dottie-harness-api" / "lib"
    # real copy_artifacts transform ran (risk_calibration dropped for a note)
    vendored = json.loads((lib / "meta" / "eval_summary.json").read_text("utf-8"))
    assert "risk_calibration_note" in vendored["champion"]
    assert (lib / "meta" / "corpus_meta.json").exists()
    # weights are NEVER touched on the not-promoted path
    assert not (lib / "weights" / "champion_weights.json").exists()


def test_cycle_second_run_without_changes_clears_deploy_required(
    tmp_path, monkeypatch
):
    repo = _fake_repo(tmp_path, gate_passed=False)
    recorder = _SubprocessRecorder()
    _wire(monkeypatch, tmp_path, repo, recorder)

    assert fc.main([]) == 0
    assert _summary(repo)["deploy_required"] is True  # first sync lands the meta
    assert fc.main([]) == 0
    second = _summary(repo)
    assert second["ok"] is True
    assert second["deploy_required"] is False  # sha256 unchanged -> no deploy
    assert _steps(second)["sync"]["meta_changed"] == []


def test_cycle_promoted_vendors_weights(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path, gate_passed=True, reason="beats both baselines")
    recorder = _SubprocessRecorder()
    _wire(monkeypatch, tmp_path, repo, recorder)

    rc = fc.main([])

    assert rc == 0
    summary = _summary(repo)
    assert summary["promoted"] is True
    assert summary["deploy_required"] is True
    assert _steps(summary)["sync"]["mode"] == "full_vendor"
    src = (
        repo / "apps" / "ava-factory" / "reports" / "orchestrator"
        / "champion_weights.json"
    )
    dst = (
        repo / "apps" / "dottie-harness-api" / "lib" / "weights"
        / "champion_weights.json"
    )
    assert dst.read_bytes() == src.read_bytes()  # verbatim vendor


def test_cycle_promoted_stale_lib_weights_missing_source_fails_closed(
    tmp_path, monkeypatch
):
    """Gate passes but the trained weights are missing, while a STALE champion
    from a previous promotion is still vendored in lib/weights: copy_artifacts
    no-ops on the missing source, so a mere existence check on the dest would
    fail OPEN and report the stale weights as a fresh promoted vendor."""
    repo = _fake_repo(tmp_path, gate_passed=True, reason="beats both")
    lib_weights = repo / "apps" / "dottie-harness-api" / "lib" / "weights"
    lib_weights.mkdir(parents=True)
    stale = lib_weights / "champion_weights.json"
    stale.write_text('{"stale_previous_champion": true}', encoding="utf-8")
    (
        repo / "apps" / "ava-factory" / "reports" / "orchestrator"
        / "champion_weights.json"
    ).unlink()  # trained weights never landed this cycle
    recorder = _SubprocessRecorder()
    _wire(monkeypatch, tmp_path, repo, recorder)

    rc = fc.main([])

    assert rc == 1
    summary = _summary(repo)
    assert summary["ok"] is False
    steps = _steps(summary)
    assert steps["sync"]["status"] == "failed"
    assert "refusing to report a deployable state" in steps["sync"]["error"]
    # stale weights untouched (never overwritten by garbage), dashboard not run
    assert json.loads(stale.read_text("utf-8")) == {"stale_previous_champion": True}
    assert "build_dashboard.py" not in recorder.scripts()


def test_cycle_promoted_synced_flags_are_measured(tmp_path, monkeypatch):
    """On the promoted path the synced flags record what actually copied —
    a missing corpus_meta.json must be reported False, not fabricated True."""
    repo = _fake_repo(tmp_path, gate_passed=True, reason="beats both")
    (
        repo / "apps" / "ava-factory" / "data" / "orchestration"
        / "corpus_meta.json"
    ).unlink()
    recorder = _SubprocessRecorder()
    _wire(monkeypatch, tmp_path, repo, recorder)

    rc = fc.main([])

    assert rc == 0  # weights + eval summary landed; meta absence is legitimate
    summary = _summary(repo)
    assert summary["promoted"] is True
    sync = _steps(summary)["sync"]
    assert sync["status"] == "ok"
    assert sync["synced"] == {
        "weights/champion_weights.json": True,
        "meta/eval_summary.json": True,
        "meta/corpus_meta.json": False,
    }
    assert summary["corpus_counts"] is None
    lib = repo / "apps" / "dottie-harness-api" / "lib"
    assert not (lib / "meta" / "corpus_meta.json").exists()


def test_cycle_mine_failure_aborts_with_stderr_tail(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    recorder = _SubprocessRecorder(
        fail_substring="build_orchestration_corpus",
        stderr=(
            "Traceback (most recent call last):\n"
            '  ...\nValueError: corrections line 3: duplicate run_id "harness-run-x"\n'
        ),
    )
    _wire(monkeypatch, tmp_path, repo, recorder)

    rc = fc.main([])

    assert rc == 1
    assert recorder.scripts() == ["build_orchestration_corpus.py"]  # train never ran
    summary = _summary(repo)
    assert summary["ok"] is False
    assert summary["promoted"] is False
    assert summary["deploy_required"] is False
    # the fixture's pre-existing corpus_meta.json is STALE relative to this
    # cycle (mine failed) — its counts must not be reported as this cycle's
    assert summary["corpus_counts"] is None
    steps = _steps(summary)
    assert steps["collect"]["status"] == "ok"
    assert steps["mine"]["status"] == "failed"
    assert "ValueError: corrections line 3" in steps["mine"]["stderr_tail"]
    assert "train" not in steps and "gate" not in steps and "sync" not in steps
    assert "not reached" in summary["gate"]["reason"]
    # nothing was synced on a failed cycle
    assert not (repo / "apps" / "dottie-harness-api" / "lib" / "meta").exists()


def test_cycle_dashboard_failure_exits_nonzero(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    recorder = _SubprocessRecorder(
        fail_substring="build_dashboard", stderr="FileNotFoundError: scoreboard.json"
    )
    _wire(monkeypatch, tmp_path, repo, recorder)

    rc = fc.main([])

    assert rc == 1
    summary = _summary(repo)
    assert summary["ok"] is False
    steps = _steps(summary)
    assert steps["dashboard"]["status"] == "failed"
    assert "scoreboard" in steps["dashboard"]["stderr_tail"]


def test_skip_train_skips_only_the_train_step(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path, gate_passed=False)
    recorder = _SubprocessRecorder()
    _wire(monkeypatch, tmp_path, repo, recorder)

    rc = fc.main(["--skip-train"])

    assert rc == 0
    assert recorder.scripts() == [
        "build_orchestration_corpus.py",
        "build_dashboard.py",
    ]
    summary = _summary(repo)
    assert summary["ok"] is True
    steps = _steps(summary)
    assert steps["train"]["status"] == "skipped"
    assert steps["gate"]["status"] == "ok"  # gate still read the existing report


def test_dry_run_executes_nothing(tmp_path, monkeypatch, capsys):
    repo = _fake_repo(tmp_path)
    recorder = _SubprocessRecorder()
    _wire(monkeypatch, tmp_path, repo, recorder)

    rc = fc.main(["--dry-run"])

    assert rc == 0
    assert recorder.calls == []  # no subprocess ran
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "build_orchestration_corpus.py" in out
    # no writes anywhere: no summary, no repo store, no vendored artifacts
    assert not (
        repo / "apps" / "ava-factory" / "reports" / "flywheel"
    ).exists()
    assert not (repo / "bundles").exists()
    assert not (repo / "apps" / "dottie-harness-api" / "lib" / "meta").exists()
