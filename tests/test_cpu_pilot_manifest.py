# Solo personal project, no connection to employer, built with public/free-tier only
"""Validate the CPU-pilot evidence manifest (runs/cpu_pilot/MANIFEST.json).

Structure-only checks, deliberately:
  * NO assertions on loss *values* — the series must merely be real floats
    parsed from the trainer's metrics jsonl (anti-fabrication discipline says
    we never encode an expected loss number that was not measured).
  * Referenced non-binary artifacts (tokenizer json, shard .idx.json sidecars,
    metrics jsonl, config dir) must actually exist on disk. Binary checkpoints
    (.pt) and packed .bin shards are gitignored, so their existence is only
    checked when the manifest was produced on this machine (sha fields present
    implies the run happened here; we still guard with a skip if the files
    were cleaned).

Skips (not fails) when runs/cpu_pilot/MANIFEST.json is absent — the pilot is
an artifact of running scripts/cpu_pilot_e2e.py, not of checking out the repo.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO / "runs" / "cpu_pilot" / "MANIFEST.json"

RUN_KEYS = ("pretrain", "branch_agentic")


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not MANIFEST_PATH.exists():
        pytest.skip(f"no pilot manifest at {MANIFEST_PATH}; run scripts/cpu_pilot_e2e.py")
    return json.loads(MANIFEST_PATH.read_text())


def test_scale_and_capability_labels(manifest):
    assert manifest["scale"] == "smoke_cpu_pilot"
    assert manifest["capability_claim"] == "none"
    assert manifest["status"] == "success", (
        f"pilot manifest records a failed run: {manifest.get('error')!r}")


def test_all_stages_present_with_real_timings(manifest):
    stages = manifest["stages"]
    for name in ("corpus", "tokenizer", "pack", "register", "pretrain", "branch"):
        assert name in stages, f"missing stage {name!r}"
        secs = stages[name]["seconds"]
        assert isinstance(secs, (int, float)) and secs >= 0


def test_corpus_stage_is_nonempty(manifest):
    c = manifest["stages"]["corpus"]
    assert c["bytes"] > 0 and c["docs"] > 0
    assert c["generators"], "no generators recorded"
    for name, g in c["generators"].items():
        assert g["bytes"] > 0 and g["docs"] > 0, f"generator {name} produced nothing"
        assert isinstance(g["sha256"], str) and len(g["sha256"]) == 64


def test_tokenizer_artifact_exists_with_sha(manifest):
    t = manifest["stages"]["tokenizer"]
    assert isinstance(t["sha256"], str) and len(t["sha256"]) == 64
    assert t["vocab_size"] >= 6  # at minimum the pinned specials
    assert Path(t["path"]).exists(), f"tokenizer artifact missing: {t['path']}"


def test_packed_shard_sidecars_exist(manifest):
    p = manifest["stages"]["pack"]
    assert p["total_tokens"] > 0
    assert p["shards"], "no packed shards recorded"
    # idx sidecars are gitignored (regenerable alongside the shard .bin files), so on a fresh
    # clone the MANIFEST exists but the sidecars don't — skip rather than fail, consistent with
    # the module's skip-when-artifacts-absent philosophy. When present (a real run), validate
    # their cross-file consistency fully.
    if not Path(p["shards"][0]["idx"]).exists():
        pytest.skip("packed idx sidecars absent (fresh clone — gitignored, regenerable)")
    for s in p["shards"]:
        assert s["tokens"] > 0
        idx = Path(s["idx"])
        assert idx.exists(), f"idx sidecar missing: {idx}"
        meta = json.loads(idx.read_text())
        assert meta["tokens"] == s["tokens"]
        assert meta["tokenizer_sha"] == p["tokenizer_sha"]


def _check_loss_series(run: dict) -> None:
    steps = run["logged_steps"]
    for series_key in ("lm_loss_series", "total_loss_series"):
        series = run[series_key]
        assert isinstance(series, list) and series, f"{series_key} empty"
        assert len(series) == len(steps), f"{series_key} length != logged_steps"
        for v in series:
            assert isinstance(v, float), f"{series_key} has non-float {v!r}"
            assert math.isfinite(v), f"{series_key} has non-finite {v!r}"
    # steps strictly increasing ints — a real, ordered log, not a paste
    assert all(isinstance(s, int) for s in steps)
    assert all(b > a for a, b in zip(steps, steps[1:])), "logged_steps not increasing"


@pytest.mark.parametrize("run_key", RUN_KEYS)
def test_run_loss_series_is_real(manifest, run_key):
    run = manifest["runs"][run_key]
    _check_loss_series(run)
    assert run["wall_seconds"] > 0
    assert isinstance(run["final_ckpt_sha256"], str) and len(run["final_ckpt_sha256"]) == 64


@pytest.mark.parametrize("run_key", RUN_KEYS)
def test_run_metrics_file_exists_and_matches(manifest, run_key):
    """Manifest loss series must MATCH the raw metrics jsonl — steps AND values.

    (Adversarial-verifier finding: the original version compared only step indices, so a
    fabricated loss series of the right length would have passed while the assertion message
    claimed value-level matching. Now the lm/total series are compared numerically too.)"""
    run = manifest["runs"][run_key]
    mpath = Path(run["metrics_file"])
    assert mpath.exists(), f"metrics jsonl missing: {mpath}"
    records = [json.loads(l) for l in mpath.read_text().splitlines() if l.strip()]
    steps = [r for r in records if r.get("event") == "step"]
    assert [r["step"] for r in steps] == run["logged_steps"], "step indices diverge from jsonl"
    for series_key, jsonl_key in (("lm_loss_series", "lm"), ("total_loss_series", "total")):
        manifest_vals = run[series_key]
        jsonl_vals = [r[jsonl_key] for r in steps]
        assert len(manifest_vals) == len(jsonl_vals)
        for i, (mv, jv) in enumerate(zip(manifest_vals, jsonl_vals)):
            assert math.isclose(mv, jv, rel_tol=1e-6, abs_tol=1e-9), (
                f"{series_key}[{i}] = {mv} != jsonl {jsonl_key} {jv} — manifest does not "
                f"match the raw log"
            )


def test_branch_forked_from_pretrain_ckpt(manifest):
    pre = manifest["runs"]["pretrain"]
    br = manifest["runs"]["branch_agentic"]
    fork = br.get("branch_forked")
    assert fork, "branch run has no branch_forked event"
    assert fork["branch"] == "agentic"
    assert fork["init"] == pre["final_ckpt"], (
        "branch did not init from the pretrain final checkpoint")
    assert fork["frozen"] == ["system1", "system2"]
    assert isinstance(fork["trainable"], int) and fork["trainable"] > 0


def test_checkpoints_not_committable():
    """Guard: *.pt under runs/cpu_pilot must be gitignored; MANIFEST.json must not."""
    gi = (REPO / ".gitignore").read_text()
    assert "!runs/cpu_pilot/MANIFEST.json" in gi
    assert "*.pt" in gi
