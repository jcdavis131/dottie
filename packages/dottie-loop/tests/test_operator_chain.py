"""Phase 3: the operator drives the whole loop from the CLI (spec §36 Runbooks A–C,
Appendix B decisions 3–12), plus the §08 router contract (RT-03 goldens) and the §13
skill lifecycle.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from dottie_loop import errors, router, skills
from dottie_loop.cli import EXIT_BLOCKED, EXIT_OK, main

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run(capsys, *argv):
    rc = main([str(a) for a in argv])
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, out
    return rc, json.loads(lines[0])


def _write(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj))
    return path


# --- the chain: run --capture → feedback → dataset → approve → preflight → gates → approval → promote → release → rollback


def test_operator_chain_end_to_end(capsys, tmp_path):
    store = tmp_path / "store"
    (tmp_path / "hello.txt").write_text("hello")
    run_ids = []
    for i in range(12):
        spec = _write(tmp_path / f"spec{i}.json", {"intent_text": f"check the hello file number {i} in module alpha beta gamma {i}", "idempotency_key": f"k{i}", "capture": True, "steps": [{"id": "f", "kind": "file", "path": "hello.txt", "expect_substring": "hello"}]})
        rc, env = _run(capsys, "loop", "run", "--spec", spec, "--store", store, "--root", tmp_path, "--subject", "cam", "--capture")
        assert rc == EXIT_OK and env["data"]["status"] == "completed" and env["data"]["trace_id"]
        run_ids.append(env["data"]["run_id"])
    # feedback: accept on one run, reject on another; the reward is recomputed and persisted
    rc, env = _run(capsys, "feedback", "record", "--store", store, "--run-id", run_ids[0], "--signal", "accept")
    assert rc == EXIT_OK and env["data"]["reward"]["components"]["accept"] == 1.0
    rc, env = _run(capsys, "feedback", "record", "--store", store, "--run-id", run_ids[1], "--signal", "edit", "--edit-fraction", "0.8")
    assert rc == EXIT_OK and env["data"]["reward"]["components"]["accept"] == 0.25
    rc, env = _run(capsys, "feedback", "record", "--store", store, "--run-id", "nope", "--signal", "accept")
    assert rc == 3
    # dataset release hard-blocks without consent, then releases with it
    traces = store / "traces" / "pair.jsonl"
    hashed = json.loads(traces.read_text().splitlines()[0])["hashed_user_id"]
    rc, env = _run(capsys, "dataset", "release", "--traces", traces, "--out", tmp_path / "ds0")
    assert rc == EXIT_BLOCKED and "no eligible records" in env["error"]["message"]  # zero-eligible is a hard block, not an empty release
    ledger = _write(tmp_path / "ledger.json", {hashed: {"capture_training": True, "version": "c1"}})
    rc, env = _run(capsys, "dataset", "release", "--traces", traces, "--out", tmp_path / "ds", "--consent-ledger", ledger, "--commit", "abc1234")
    assert rc == EXIT_OK, env
    manifest_path = tmp_path / "ds" / "manifest.json"
    counts = env["data"]["counts"]
    assert counts["raw"] == sum(counts[b] for b in ("excluded_consent", "excluded_privacy", "invalid", "quarantined", "deduplicated", "train", "validation", "test"))
    assert counts["deduplicated"] >= 2  # the superseding feedback records dedupe against their originals
    # preflight refuses an unapproved manifest, then passes after approval
    run_json = _write(tmp_path / "train.json", {"objective": "sft", "parent_checkpoint": "ckpt-0", "dataset_manifest": env["data"]["manifest"]["dataset_id"], "code_commit": "abc1234", "tokenizer_hash": "tok", "model": {"architecture": "tiny", "parameters": 1, "context": 128}, "optimizer": {"name": "adamw", "lr": 0.001, "schedule": "cosine", "weight_decay": 0.1}, "batch": {"micro": 2, "grad_accum": 2, "global": 4, "packing": "concat"}, "hardware": {"runner": "box", "gpu": "x", "vram_gb": 8, "cuda": "12"}, "budgets": {"max_steps": 10, "max_hours": 1, "max_cost": 1}})
    checks = _write(tmp_path / "checks.json", {"split_overlap_zero": True, "tokenizer_roundtrip_ok": True, "checkpoint_loads": True, "hardware_ok": True, "storage_gb_free": 100, "storage_gb_needed": 1, "metrics_sink_writable": True, "cancellation_tested": True, "baseline_eval_fresh": True})
    rc, env = _run(capsys, "train", "preflight", "--run", run_json, "--manifest", manifest_path, "--checks", checks)
    assert rc == EXIT_BLOCKED and "manifest_approved_and_hashes_resolve" in env["error"]["details"]["failed"]
    rc, env = _run(capsys, "dataset", "approve", "--manifest", manifest_path, "--reviewer", "independent")
    assert rc == EXIT_OK and env["data"]["status"] == "approved"
    rc, env = _run(capsys, "train", "preflight", "--run", run_json, "--manifest", manifest_path, "--checks", checks)
    assert rc == EXIT_OK and env["data"]["ok"]
    # evaluation gates
    bundle = _write(tmp_path / "bundle.json", {"candidate": {"id": "ch", "sha256": "chal"}, "incumbent": {"id": "inc", "sha256": "inc"}, "benchmark_version": "b1", "hidden_set_snapshot": "h1", "primary_metric": "task_ok", "candidate_primary": 0.8, "incumbent_primary": 0.75, "ci_low": 0.01, "ci_high": 0.09, "n_items": 200, "slice_results": {"bugfix": 0.8}, "slice_floors": {"bugfix": 0.6}, "regressions": {"safety": 0}, "safety_findings": [], "efficiency": {"candidate_cost": 1, "incumbent_cost": 1, "approved_ratio": 1.2}, "overlap_report": {"manifest_ok": True, "split_ok": True, "leakage": False, "privacy_unresolved": False}, "synthetic": False, "mock": False, "evaluator_commit": "abc", "evaluated_at": _iso(datetime.now(UTC)), "baseline_evaluated_at": _iso(datetime.now(UTC))})
    rc, env = _run(capsys, "eval", "gates", "--bundle", bundle, "--out", tmp_path / "gates.json")
    assert rc == EXIT_OK and env["data"]["verdict"] == "pass"
    # promotion without approval is BLOCKED, not hold
    canary = _write(tmp_path / "canary.json", {"status": "complete", "challenger_metric": 0.8, "baseline_metric": 0.79})
    rc, env = _run(capsys, "promote", "decide", "--gates", tmp_path / "gates.json", "--canary", canary)
    assert rc == EXIT_BLOCKED and env["error"]["details"]["decision"]["outcome"] == "block"
    # explicit one-time approval, persisted across processes
    approvals = tmp_path / "approvals.json"
    rc, env = _run(capsys, "approval", "issue", "--store", approvals, "--approver", "cam", "--action", "promote", "--payload", '{"artifact": "chal"}', "--destination", "production", "--goal-id", "loop")
    assert rc == EXIT_OK
    apr = env["data"]["approval_id"]
    rc, env = _run(capsys, "approval", "consume", "--store", approvals, "--approval-id", apr, "--action", "promote", "--payload", '{"artifact": "chal"}', "--destination", "production", "--goal-id", "loop")
    assert rc == EXIT_OK and env["data"]["consumed_at"]
    rc, env = _run(capsys, "approval", "consume", "--store", approvals, "--approval-id", apr, "--action", "promote", "--payload", '{"artifact": "chal"}', "--destination", "production", "--goal-id", "loop")
    assert rc == 1 and env["error"]["code"] == "approval_required" and json.loads(approvals.read_text())["replay_attempts"] == 1
    rc, env = _run(capsys, "promote", "decide", "--gates", tmp_path / "gates.json", "--canary", canary, "--approval-consumed")
    assert rc == EXIT_OK and env["data"]["outcome"] == "promote"
    # release: served hash must match; then a rollback drill
    common = ["--artifact-id", "ch", "--artifact-sha", "chal", "--source-commit", "abc", "--eval-bundle", "b1", "--approval-id", apr, "--deployment-id", "dep1", "--rollback-target", "inc"]
    rc, env = _run(capsys, "release", "record", *common, "--served-sha", "zzz", "--out", tmp_path / "rel-bad.json")
    assert rc == EXIT_BLOCKED and env["error"]["details"]["release"]["status"] == "mismatch"
    rc, env = _run(capsys, "release", "record", *common, "--served-sha", "chal", "--out", tmp_path / "rel.json")
    assert rc == EXIT_OK and env["data"]["status"] == "active"
    rc, env = _run(capsys, "release", "rollback", "--release", tmp_path / "rel.json", "--served-sha", "inc", "--reason", "drill", "--out", tmp_path / "rb.json")
    assert rc == EXIT_OK and env["data"]["status"] == "rolled_back" and env["data"]["incident"]["severity"] == "SEV-1"
    rc, env = _run(capsys, "release", "rollback", "--release", tmp_path / "rel.json", "--served-sha", "wrong", "--reason", "drill", "--out", tmp_path / "rb2.json")
    assert rc == EXIT_BLOCKED


# --- §08 router contract, RT-03 golden fixtures --------------------------------------------------------


GOLDENS = [
    ("run the heartbeat health check", "read_only", "T0", "deterministic"),
    ("summarize this paragraph", "read_only", "T1", "llm_assist"),
    ("compare Stripe vs Lemon Squeezy with fresh sources", "read_only", "T2", "deep_research"),
    ("send the weekly report to #ops", "external_send", "T3", "action_operator"),
    ("migrate the platform end to end over the next month", "write_local", "T4", "agentic_epic"),
]


@pytest.mark.parametrize(("text", "effect", "tier", "intent"), GOLDENS)
def test_rt03_router_goldens_are_deterministic(text, effect, tier, intent):
    f = router.RoutingFeatures(intent_text=text, side_effect_class=effect)
    a = router.route(f)
    b = router.route(f)
    assert a["tier"] == tier and a["intent"] == intent and a["authority"] == "heuristic" and a["learned"] is None
    assert (a["tier"], a["agents"], a["budget"]) == (b["tier"], b["agents"], b["budget"])
    assert a["risk"]["provenance"] == "static_priors" and a["tier_name"] == router.TIER_NAMES[tier]


def test_router_decision_order_and_learned_advice():
    f = router.RoutingFeatures(intent_text="compare Stripe vs Lemon Squeezy with fresh sources")
    # 4. missing/invalid artifact -> learned null; gate false -> heuristic authoritative on disagreement
    assert router.route(f, learned_artifact={"model": "orch-mlp-v1-v4"})["learned"] is None
    r = router.route(f, learned_artifact={"model": "orch-mlp-v1-v4", "tier": "T1", "confidence": 0.9, "provenance": "eval_report.json", "gate_passed": False})
    assert r["tier"] == "T2" and r["authority"] == "heuristic" and r["learned"]["gate_passed"] is False
    r = router.route(f, learned_artifact={"model": "orch-mlp-v1-v4", "tier": "T1", "confidence": 0.9, "provenance": "eval_report.json", "gate_passed": True})
    assert r["tier"] == "T1" and r["authority"] == "learned"
    r = router.route(f, learned_artifact={"model": "m", "tier": "T4", "confidence": 0.9, "provenance": "p", "gate_passed": True})
    assert r["tier"] == "T2" and r["authority"] == "heuristic"  # a learned model cannot escalate on its own
    # 5. low confidence prefers the cheaper tier
    low = router.route(router.RoutingFeatures(intent_text="do the thing", ambiguity=0.9))
    assert low["tier"] == "T0" and low["heuristic"]["downgraded"] == "confidence below threshold"
    # 6. escalation only with a recorded insufficiency
    with pytest.raises(errors.InvalidInputError):
        router.route(f, insufficiency={"note": "felt weak"})
    esc = router.route(f, insufficiency={"recorded_at": _iso(NOW), "error_class": "verification_failed"})
    assert esc["tier"] == "T3" and esc["escalated_from_insufficiency"]
    # 1. policy exclusions and hard constraints; forbidden features
    with pytest.raises(errors.PolicyDeniedError):
        router.route(f, policy_exclusions={"T2"})
    with pytest.raises(errors.PolicyDeniedError):
        router.route(router.RoutingFeatures(intent_text="x", privacy_class="P3"))
    with pytest.raises(errors.PolicyDeniedError):
        router.RoutingFeatures(intent_text="x", extra={"religion": "y"})
    assert router.route(router.RoutingFeatures(intent_text="summarize this", model_available=False))["tier"] == "T0"
    assert router.route(router.RoutingFeatures(intent_text="compare sources", cost_budget_tokens=500))["budget"]["tokens"] == 500
    legacy = router.from_production_routing({"intent": "deep_research", "moma_tier": "deep_research", "heuristic_score": 0.75, "recommended_agents": ["deep-researcher"], "provenance": "request_derived_heuristic"})
    assert legacy["tier"] == "T2" and legacy["learned"] is None
    with pytest.raises(errors.InvalidInputError):
        router.from_production_routing({"moma_tier": "warp"})


# --- §13 skill lifecycle ----------------------------------------------------------------------------------


SKILL_MD = """---
name: anydoc
description: Unified Document IR + single GFM serializer
triggers:
- anydoc
- extract
j_space_target: S2
half_life: 300
dependencies: []
connectors: [git-repo, "notion"]
provider: none
version: 1.0.0
---

# anydoc
"""


def test_skill_frontmatter_and_lifecycle_gates():
    fm = skills.parse_frontmatter(SKILL_MD)
    assert fm["triggers"] == ["anydoc", "extract"] and fm["connectors"] == ["git-repo", "notion"] and fm["half_life"] == 300 and fm["dependencies"] == []
    pkg = skills.validate_package(fm, has_describe=True, has_run=True)
    assert pkg["name"] == "anydoc" and pkg["version"] == "1.0.0"
    with pytest.raises(errors.InvalidInputError):
        skills.validate_package(fm, has_describe=True, has_run=False)
    with pytest.raises(errors.InvalidInputError):
        skills.parse_frontmatter("no frontmatter here")
    with pytest.raises(errors.InvalidInputError):
        skills.validate_package({**fm, "name": "Bad Name"}, has_describe=True, has_run=True)
    rec = skills.SkillRecord(package=pkg, instructions="do the thing", references={"ref.md": "..."})
    assert rec.disclose("router") == {"name": "anydoc", "description": pkg["description"]}  # progressive disclosure
    assert "instructions" in rec.disclose("selected") and "references" in rec.disclose("workflow")
    with pytest.raises(errors.UnexecutableError):
        rec.advance("benchmarked", {})  # one stage at a time
    with pytest.raises(errors.UnexecutableError):
        rec.advance("validated", {"frontmatter_schema": True})  # missing evidence named
    rec.advance("validated", dict.fromkeys(skills.REQUIRED_EVIDENCE["validated"], True))
    with pytest.raises(errors.PolicyDeniedError):
        rec.advance("benchmarked", {**dict.fromkeys(skills.REQUIRED_EVIDENCE["benchmarked"], True), "mock": True})
    rec.advance("benchmarked", dict.fromkeys(skills.REQUIRED_EVIDENCE["benchmarked"], True))
    rec.advance("shadow", dict.fromkeys(skills.REQUIRED_EVIDENCE["shadow"], True))
    with pytest.raises(errors.PolicyDeniedError):
        rec.advance("canary", dict.fromkeys(skills.REQUIRED_EVIDENCE["canary"], True))  # needs approval id
    rec.advance("canary", {**dict.fromkeys(skills.REQUIRED_EVIDENCE["canary"], True), "approval_id": "apr_1"})
    rb = rec.rollback("threshold breached")
    assert rb["rollback"] == "pin incumbent" and rec.stage == "shadow"
    rep = skills.benchmark_report(dict.fromkeys(skills.BENCHMARK_DIMENSIONS, 1.0), real_data=False, source="fixtures")
    assert rep["complete"] and rep["capability_claim"] == "none"
    assert skills.benchmark_report({"task_success": 0.9}, real_data=True, source="consented traces")["missing"]


def test_cli_module_entry_still_single_json_line(tmp_path):
    import subprocess

    proc = subprocess.run([sys.executable, "-m", "dottie_loop", "spec", "status"], capture_output=True, text=True, check=False)
    assert proc.returncode == 0 and len([ln for ln in proc.stdout.splitlines() if ln.strip()]) == 1
