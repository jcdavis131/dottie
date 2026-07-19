# Solo personal project, no connection to employer, built with public/free-tier only
"""Climb orchestrator tests — real echo/scripted iterations through the REAL engine +
flywheel, paired promotion-gate logic (incl. the win-overall-lose-family trap), honest
insufficient verdicts, EG-trend reuse of the factory machinery, log schema, CLI smoke."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import dottie.engine as engine_mod
from dottie import climb, resolve
from dottie.climb import ClimbConfig
from dottie.tasks import FAMILIES
from tests.conftest import UNROUTABLE_OLLAMA

APP_ROOT = Path(__file__).resolve().parent.parent  # apps/dottie


# ---------------------------------------------------------------------------
# (1) Echo-backend full iteration, for real: verifiers bite -> overall 0.0 recorded
#     honestly; flywheel export + mint actually run over the new traces.
# ---------------------------------------------------------------------------

def test_echo_mixed_iteration_measured_and_logged(data_dir):
    rec = climb.run_iteration(ClimbConfig(families="mixed", n=5, backend="echo"), data_dir)
    sb = rec["scoreboard"]
    assert sb["overall"]["n"] == 5
    assert sb["overall"]["success_rate"] == 0.0        # every verifier honestly scored echo 0
    assert set(sb["per_family"]) == set(FAMILIES)      # mixed n=5 covered all five families
    for fam in FAMILIES:
        assert sb["per_family"][fam] == {
            "n": 1, "success_rate": 0.0, "mean_r_task": 0.0,
            "mean_rl_return": sb["per_family"][fam]["mean_rl_return"],
        }
    # Per-task rows are the real measured values, not summaries of nothing.
    assert [t["family"] for t in rec["tasks"]] == list(FAMILIES)
    assert all(t["r_task"] == 0.0 for t in rec["tasks"])
    assert all(isinstance(t["rl_return"], float) for t in rec["tasks"])
    assert all(t["reached_final"] for t in rec["tasks"])
    assert sb["cost"]["wall_s_total"] > 0.0
    assert sb["cost"]["steps_total"] == 10             # echo: exactly 2 real code steps/task
    assert sb["cost"]["chars_code_total"] > 0
    assert "NOT token" in sb["cost"]["token_note"]     # cost proxy honestly labeled

    # Flywheel stages REALLY ran on the traces this iteration produced.
    exp = rec["flywheel"]["export_rft"]
    assert exp["status"] == "ok"
    assert exp["source_traces"] == 5
    assert exp["records_written"] >= 1 and Path(exp["out"]).exists()
    mint = rec["flywheel"]["mint"]
    assert mint["status"] == "ok"
    assert mint["events_captured"] == 5
    assert mint["stats"]["minted"] >= 1
    assert list(Path(mint["store_dir"]).glob("*.jsonl")), "minted shards must be on disk"

    # Not requested -> honestly recorded as skipped, never invented.
    assert rec["evaluate"] is None and rec["train_step"] is None

    # Identity: plumbing backend labeled; git SHA really resolved (this repo exists).
    assert rec["policy_identity"] == {
        "backend": "echo", "plumbing_only": True,
        "note": "deterministic CI plumbing policy; never a capability claim",
    }
    assert re.fullmatch(r"[0-9a-f]{40}", rec["git"]["sha"])

    # Exactly one log record, identical identity to the returned one.
    logged = climb.read_log(data_dir)
    assert len(logged) == 1
    assert logged[0]["iteration_id"] == rec["iteration_id"]
    assert logged[0]["scoreboard"] == sb


def test_climb_log_jsonl_schema(data_dir):
    climb.run_iteration(ClimbConfig(families="compute", n=2, backend="echo"), data_dir)
    lines = climb.climb_log_path(data_dir).read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert {
        "schema_version", "iteration_id", "ts", "config", "git", "policy_identity",
        "tasks", "scoreboard", "flywheel", "evaluate", "train_step", "iteration_wall_s",
    } <= set(row)
    assert row["schema_version"] == climb.CLIMB_SCHEMA_VERSION
    assert row["config"] == {
        "families": "compute", "n": 2, "seed_base": 0, "backend": "echo", "max_steps": 8,
        "use_skills": False, "evaluate": None, "train_step": False, "compute": None,
        "tolerance": 0.05,
    }
    for t in row["tasks"]:
        assert {"task_id", "family", "seed", "r_task", "rl_return", "r_exec", "r_codeuse",
                "terminated", "reached_final", "n_steps", "wall_s", "sandbox_ms",
                "chars_code", "chars_final"} <= set(t)
    assert {"overall", "per_family", "cost", "success_definition"} <= set(row["scoreboard"])
    assert "sha" in row["git"]


# ---------------------------------------------------------------------------
# (2) Scripted-solver iteration (labeled plumbing brain, REAL sandbox execution)
#     -> nonzero success -> paired promote verdict against the echo iteration.
# ---------------------------------------------------------------------------

class _ComputeSolver:
    """Scripted compute-family solver (the tasks tests' pattern): one real code block built
    from the prompt, FINAL parsed from the REAL observation. plumbing_only — machinery
    verification, never a model-capability claim."""

    name = "scripted-solver"
    plumbing_only = True

    def __init__(self) -> None:
        self._step = 0

    def __call__(self, transcript: str) -> str:
        self._step += 1
        if self._step == 1:
            nums = re.search(r"Data list: (\[[^\]]*\])", transcript).group(1)
            return ("```python\n"
                    f"nums = {nums}\n"
                    "sum(x * x for x in nums if x % 2 == 0) - "
                    "sum(x for x in nums if x % 2 == 1)\n```")
        if self._step == 2:
            got = re.findall(r"=> (\S+)", transcript)[-1].strip("'\"")
            return f"FINAL: computed in the sandbox; the result is {got}."
        return ""


def test_scripted_iteration_promotes_over_echo_paired(data_dir, monkeypatch):
    echo_rec = climb.run_iteration(
        ClimbConfig(families="compute", n=3, backend="echo"), data_dir)
    monkeypatch.setattr(engine_mod, "get_policy", lambda backend, **kw: _ComputeSolver())
    scripted_rec = climb.run_iteration(
        ClimbConfig(families="compute", n=3, backend="scripted"), data_dir)

    assert scripted_rec["scoreboard"]["overall"]["success_rate"] == 1.0  # real solves
    assert all(t["r_task"] == 1.0 for t in scripted_rec["tasks"])
    # An injected backend's identity is honestly not resolvable — labeled, not guessed.
    assert "not resolvable" in scripted_rec["policy_identity"]["note"]

    v = climb.compare_iterations(echo_rec, scripted_rec)
    assert v["verdict"] == "promote"
    assert v["paired"] is True
    assert v["overall"] == {"prev": 0.0, "curr": 1.0, "delta": 1.0}
    assert v["per_family"]["compute"]["delta"] == 1.0
    assert v["per_family"]["compute"]["regressed_beyond_tolerance"] is False
    assert v["paired_tasks"] == {"n": 3, "wins": 3, "losses": 0, "ties": 0}
    assert v["mean_rl_return"]["delta"] > 0
    assert v["reasons"] == []

    # The reverse direction is a regression -> hold, with the true reasons.
    rv = climb.compare_iterations(scripted_rec, echo_rec)
    assert rv["verdict"] == "hold"
    assert rv["per_family"]["compute"]["regressed_beyond_tolerance"] is True
    assert any("did not improve" in r for r in rv["reasons"])
    assert any("regression beyond tolerance" in r for r in rv["reasons"])


# ---------------------------------------------------------------------------
# (3) Promotion-gate unit tests on synthetic scoreboards (gating MATH under test;
#     the inputs are labeled synthetic, the gate never sees them as capability claims).
# ---------------------------------------------------------------------------

def _rec(family_scores, *, seed_base=0, families="mixed", iteration_id="synth"):
    tasks = []
    for fam, scores in family_scores.items():
        for i, s in enumerate(scores):
            tasks.append({"family": fam, "seed": seed_base + i,
                          "r_task": float(s), "rl_return": float(s)})
    return {
        "iteration_id": iteration_id,
        "config": {"families": families, "n": len(tasks), "seed_base": seed_base},
        "tasks": tasks,
        "scoreboard": climb.build_scoreboard(tasks),
    }


def test_win_overall_lose_family_is_hold():
    """The rank-invariance trap: overall improves (+0.25) but one family collapses -> hold."""
    prev = _rec({"compute": [1, 0, 0], "extract": [1]})       # overall 0.5
    curr = _rec({"compute": [1, 1, 1], "extract": [0]})       # overall 0.75, extract -1.0
    v = climb.compare_iterations(prev, curr, tolerance=0.05)
    assert v["overall"]["delta"] == 0.25
    assert v["verdict"] == "hold"
    assert v["per_family"]["extract"]["regressed_beyond_tolerance"] is True
    assert v["per_family"]["compute"]["regressed_beyond_tolerance"] is False
    assert len(v["reasons"]) == 1 and "extract" in v["reasons"][0]
    # With a tolerance wide enough to absorb the regression, the same data promotes —
    # the knob really gates.
    assert climb.compare_iterations(prev, curr, tolerance=1.0)["verdict"] == "promote"


def test_promote_requires_strict_overall_improvement():
    prev = _rec({"compute": [1, 0], "extract": [1, 0]})
    same = _rec({"compute": [1, 0], "extract": [1, 0]})
    v = climb.compare_iterations(prev, same)
    assert v["verdict"] == "hold" and "did not improve" in v["reasons"][0]
    better = _rec({"compute": [1, 1], "extract": [1, 0]})
    assert climb.compare_iterations(prev, better)["verdict"] == "promote"


def test_insufficient_verdicts_never_promote_or_hold():
    a = _rec({"compute": [1, 0]})
    # Missing side(s).
    assert climb.compare_iterations(None, a)["verdict"] == "insufficient"
    assert climb.compare_iterations(a, None)["verdict"] == "insufficient"
    # Unpaired seeds base -> no paired comparison exists.
    b = _rec({"compute": [1, 1]}, seed_base=7)
    v = climb.compare_iterations(a, b)
    assert v["verdict"] == "insufficient" and "seed_base" in v["reason"]
    # Different n -> unpaired.
    c = _rec({"compute": [1, 1, 1]})
    assert climb.compare_iterations(a, c)["verdict"] == "insufficient"
    # No measured scoreboard -> insufficient, never a fabricated verdict.
    broken = {**a, "scoreboard": {}}
    assert climb.compare_iterations(broken, a)["verdict"] == "insufficient"


# ---------------------------------------------------------------------------
# EG trend — reuses the factory's success->error transform + eg_trend ladder rule.
# ---------------------------------------------------------------------------

def _rec_at(compute, success_rate, iteration_id="synth"):
    return {"iteration_id": iteration_id,
            "config": {"families": "mixed", "n": 4, "seed_base": 0, "compute": compute},
            "scoreboard": {"overall": {"success_rate": success_rate}}}


BASELINE = [(1.0, 0.2), (2.0, 0.35), (4.0, 0.5)]  # synthetic baseline curve (math test)


def test_eg_trend_insufficient_without_compute_labels(data_dir):
    rec = climb.run_iteration(ClimbConfig(families="compute", n=1, backend="echo"), data_dir)
    v = climb.eg_trend_verdict([rec], BASELINE)
    assert v["verdict"] == "insufficient" and "compute points" in v["reason"]
    # Two iterations at the SAME compute point are still one point — insufficient.
    v2 = climb.eg_trend_verdict([_rec_at(2.0, 0.3), _rec_at(2.0, 0.4)], BASELINE)
    assert v2["verdict"] == "insufficient"


def test_eg_trend_insufficient_without_baseline_curve():
    v = climb.eg_trend_verdict([_rec_at(1.0, 0.3), _rec_at(4.0, 0.6)], [])
    assert v["verdict"] == "insufficient" and "baseline" in v["reason"]


def test_eg_trend_reuses_factory_machinery_on_synthetic_ladder():
    """Synthetic-math test of the reused factory gate (same spirit as codeact_eg_gate's own
    tests): candidate beats the baseline error curve at both compute points -> promote."""
    v = climb.eg_trend_verdict([_rec_at(1.0, 0.3), _rec_at(4.0, 0.6)], BASELINE)
    assert v["verdict"] == "promote"
    assert v["mode"] == "climb_iterations_vs_baseline"
    assert v["all_rungs_gt_1"] is True and v["largest_rung_not_worst"] is True
    assert v["compute_points"] == [1.0, 4.0]
    assert all(eg > 1.0 for eg in v["egs"].values())
    # A candidate losing at the large compute point -> hold (rank-invariance rule, reused).
    v2 = climb.eg_trend_verdict([_rec_at(1.0, 0.3), _rec_at(4.0, 0.4)], BASELINE)
    assert v2["verdict"] == "hold"


def test_eg_trend_undefined_math_is_insufficient():
    """A perfect success rate puts the error at/below the floor: EG is undefined there, and
    the verdict says so instead of inventing one."""
    v = climb.eg_trend_verdict([_rec_at(1.0, 1.0), _rec_at(4.0, 1.0)], BASELINE)
    assert v["verdict"] == "insufficient" and "EG undefined" in v["reason"]


# ---------------------------------------------------------------------------
# Honest degradation: missing siblings / checkpoints are recorded, not faked.
# ---------------------------------------------------------------------------

def test_missing_prereqs_recorded_as_unavailable_not_fabricated(data_dir, monkeypatch,
                                                               tmp_path):
    monkeypatch.setenv("DOTTIE_ROOT", str(tmp_path))          # no siblings, not a git repo
    monkeypatch.setattr(resolve, "ava_ckpt_candidates", lambda: [])   # no trainee ckpt
    rec = climb.run_iteration(
        ClimbConfig(families="compute", n=1, backend="echo", train_step=True), data_dir)
    # The tasks still ran for real (factory resolved via its default checkout)...
    assert rec["scoreboard"]["overall"]["n"] == 1
    # ...while every absent prerequisite is an honest recorded refusal with the true reason.
    assert rec["flywheel"]["export_rft"]["status"] == "unavailable"
    assert "RFT ETL" in rec["flywheel"]["export_rft"]["reason"]
    assert rec["flywheel"]["mint"]["status"] == "unavailable"
    assert rec["train_step"]["status"] == "unavailable"
    assert "checkpoint" in rec["train_step"]["reason"]
    assert rec["git"]["sha"] is None and "note" in rec["git"]


def test_evaluate_mock_passthrough_runs_real_harness(data_dir):
    rec = climb.run_iteration(
        ClimbConfig(families="compute", n=1, backend="echo", evaluate="mock"), data_dir)
    ev = rec["evaluate"]
    assert ev["status"] == "ok"
    assert ev["meta"]["mode"] == "mock"
    assert ev["meta"]["total"] > 0                    # the harness's own real report meta
    assert Path(ev["report_json"]).exists()


# ---------------------------------------------------------------------------
# (5) CLI smoke — subprocess, echo backend, tiny n.
# ---------------------------------------------------------------------------

def test_cli_climb_smoke_and_report(tmp_path):
    dd = tmp_path / "dd"
    p = subprocess.run(
        [sys.executable, "-m", "dottie", "climb", "--families", "compute", "--n", "2",
         "--backend", "echo", "--iterations", "2", "--data-dir", str(dd)],
        cwd=APP_ROOT, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr
    assert "climb iteration" in p.stdout and "OVERALL" in p.stdout
    assert "plumbing_only" in p.stdout                # echo labeled in the scoreboard header
    # Echo vs echo on the same seeds: no improvement -> honest HOLD, never a fake promote.
    assert "verdict vs previous: HOLD" in p.stdout
    assert len(climb.read_log(dd)) == 2

    r = subprocess.run(
        [sys.executable, "-m", "dottie", "climb-report", "--data-dir", str(dd)],
        cwd=APP_ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "echo" in r.stdout and "HOLD" in r.stdout
    assert "compute" in r.stdout


def test_cli_climb_report_empty_log_is_honest(tmp_path, capsys):
    from dottie.__main__ import main

    assert main(["climb-report", "--data-dir", str(tmp_path)]) == 0
    assert "no climb iterations recorded" in capsys.readouterr().out


def test_cli_climb_exits_2_on_backend_unavailable_not_on_low_scores(tmp_path, monkeypatch,
                                                                    capsys):
    from dottie.__main__ import main

    monkeypatch.setenv("DOTTIE_OLLAMA_URL", UNROUTABLE_OLLAMA)
    rc = main(["climb", "--families", "compute", "--n", "1", "--backend", "ollama",
               "--data-dir", str(tmp_path / "d")])
    assert rc == 2                                    # infrastructure failure -> nonzero
    assert "unavailable" in capsys.readouterr().err
    assert climb.read_log(tmp_path / "d") == []       # no iteration record was invented
