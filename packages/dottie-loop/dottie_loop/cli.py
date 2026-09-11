"""``python -m dottie_loop`` — the CLI surface contract (spec §06 CLI row).

Stable exit codes, JSON mode, dry-run, explicit destructive flags, stderr
diagnostics, and no interactive prompt anywhere::

    0  ok
    1  error (typed; see the JSON envelope on stdout)
    2  blocked (a named dependency or stale/missing evidence)
    3  invalid input

Commands::

    goal submit  --store DIR --surface cli --subject ID --json '{...}'
    goal status  --store DIR --goal-id ID
    plan validate --file plan.json
    loop evaluate --sources metrics.json [--baseline baseline.json] [--last-terminal-at T]
                  [--promote] [--approve-prod] [--out decisions.jsonl]
    loop run     --spec run.json --store DIR --root DIR --subject ID [--capture]
    reward compute --file inputs.json
    capture status
    forge runners --root DIR
    forge submit  --root DIR --file jobspec.json --allow owner/name
    feedback record --store DIR --run-id ID --signal accept|reject|edit|apply|dismiss [--edit-fraction F]
    dataset release --traces pair.jsonl --out DIR [--consent-ledger L] [--benchmarks B]
    dataset approve --manifest DIR/manifest.json --reviewer NAME
    train preflight --run train.json --manifest manifest.json --checks checks.json
    eval gates --bundle bundle.json [--out gates.json]
    approval issue|consume --store approvals.json ...
    promote decide --gates gates.json [--canary canary.json] [--approval-consumed]
    release record ... --served-sha H --out release.json
    release rollback --release release.json --served-sha H --reason R --out rollback.json
    bench smoke
    retention expire --records R.jsonl [--holds H.json] [--deletions D.json] [--out R2.jsonl]
    incident drill --results r.json | playbook --kind K
    privacy hold|delete --lineage L.json --key K --operator O
    spec status | schemas | traceability --dir DIR | components --root . | acceptance | done
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dottie_loop import SPEC_BASELINE, SPEC_VERSION, __version__
from dottie_loop.errors import (
    BlockedError,
    InvalidInputError,
    LoopError,
    StaleEvidenceError,
    error_envelope,
    ok_envelope,
)

EXIT_OK, EXIT_ERROR, EXIT_BLOCKED, EXIT_INVALID = 0, 1, 2, 3


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --- commands ------------------------------------------------------------------------------


def cmd_goal_submit(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.intake import GoalStore

    store = GoalStore(Path(a.store))
    ack, created = store.submit(a.json, authenticated_subject=a.subject, surface=a.surface)
    return {**ack, "created": created}


def cmd_goal_status(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.intake import GoalStore

    store = GoalStore(Path(a.store))
    return {"goal_id": a.goal_id, "status": store.status(a.goal_id), "transitions": store.transitions(a.goal_id)}


def cmd_plan_validate(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.plan import PlanGraph, PlanStep, validate_plan

    raw = _read_json(a.file)
    steps = [PlanStep(**s) for s in raw.pop("steps", [])]
    raw.pop("schema", None)
    plan = PlanGraph(steps=steps, **raw)
    return validate_plan(plan)


def cmd_loop_evaluate(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.closed_loop import (
        evaluate_trigger,
        load_sources,
        promote_guard,
        write_decision,
    )

    sources = load_sources(Path(a.sources))
    baseline = _read_json(a.baseline) if a.baseline else {}
    decision = evaluate_trigger(sources, baseline=baseline, lease=None, last_terminal_at=a.last_terminal_at)
    if a.out:
        write_decision(decision, Path(a.out))
    guard = promote_guard(promote=a.promote, approve_prod=a.approve_prod, decision=decision)
    out = {"decision": decision, "promotion": guard}
    if decision["decision"] == "blocked":
        raise BlockedError("loop evaluation blocked: " + "; ".join(decision["blockers"]), "metrics", **out)
    return out


def cmd_loop_run(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.driver import RunSpec, run_goal

    spec = RunSpec.from_dict(_read_json(a.spec))
    result = run_goal(spec, store_root=Path(a.store), root=Path(a.root), subject=a.subject, surface=a.surface, capture_flag=a.capture)
    if result.get("status") == "blocked":
        raise BlockedError("goal blocked: " + str(result.get("dependency") or result.get("outcome", {}).get("error_class")), str(result.get("dependency") or "policy"), **result)
    return result


def cmd_reward_compute(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.reward import RewardInputs, compute_reward

    return compute_reward(RewardInputs(**_read_json(a.file)))


def cmd_capture_status(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.capture import ENV_FLAG, capture_enabled

    return {"enabled": capture_enabled(flag=a.capture), "env_flag": ENV_FLAG, "default": "off"}


def cmd_forge_runners(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.forge import ForgeQueue

    q = ForgeQueue(Path(a.root), repo_allowlist=a.allow or [])
    rs = [r.to_dict() for r in q.runners()]
    if not rs:
        raise BlockedError("no Forge runner is registered", "forge_runner", runners=[])
    return {"runners": rs}


def cmd_forge_submit(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.forge import ForgeQueue, JobSpec

    q = ForgeQueue(Path(a.root), repo_allowlist=a.allow or [])
    raw = _read_json(a.file)
    raw.pop("schema", None)
    spec = JobSpec(**raw)
    if a.dry_run:
        from dottie_loop.forge import validate_job

        validate_job(spec, q.repo_allowlist)
        return {"dry_run": True, "job_id": spec.job_id, "valid": True}
    p = q.submit(spec)
    return {"job_id": spec.job_id, "queued": str(p), "status": "accepted", "note": "queued, not executed"}


def cmd_bench_smoke(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.bench import (
        Step,
        Workflow,
        build_report,
        golden_check,
        run_workflow,
    )
    from dottie_loop.plan import PlanGraph, PlanStep, validate_plan
    from dottie_loop.reward import RewardInputs, compute_reward

    def plan_ok() -> dict[str, Any]:
        p = PlanGraph(goal_id="g", steps=[PlanStep(id="s1", idx=0, role="check", final=True)])
        return validate_plan(p)

    def reward_ok() -> dict[str, Any]:
        return compute_reward(RewardInputs(trace_id="t", task_ok=True, feedback="accept"))

    wfs = [
        run_workflow(Workflow("plan-validate", [Step("validate", plan_ok, lambda o: o["ok"])])),
        run_workflow(Workflow("reward-compute", [Step("compute", reward_ok, lambda o: o["total"] == 1.25)])),
    ]
    goldens = [golden_check(reward_ok(), "pair-reward", ["trace_id", "components", "weights", "total"])]
    return build_report(wfs, goldens, harness_commit=a.commit or "unknown")


def _load_traces(path: Path) -> list[dict[str, Any]]:
    from dottie_loop.feedback import load_traces

    return load_traces(path)


def cmd_feedback_record(a: argparse.Namespace) -> dict[str, Any]:
    """Gap 02 (real feedback UX) for the CLI surface: attach a signal to a captured run."""
    from dottie_loop.feedback import record_feedback

    return record_feedback(Path(a.store), run_id=a.run_id, signal=a.signal, surface="cli", edit_fraction=a.edit_fraction, subject=a.subject)


def cmd_retention_expire(a: argparse.Namespace) -> dict[str, Any]:
    """§17 expiry job: deterministic, idempotent, observable; holds and deletion requests honoured."""
    from dottie_loop.retention import expire

    records = _load_traces(Path(a.records))
    holds = set(json.loads(Path(a.holds).read_text(encoding="utf-8"))) if a.holds else set()
    deletions = set(json.loads(Path(a.deletions).read_text(encoding="utf-8"))) if a.deletions else set()
    receipt = expire(records, legal_holds=holds, deletion_requests=deletions)
    out = Path(a.out) if a.out else Path(a.records)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    tmp.replace(out)
    Path(str(out) + ".receipt.json").write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="utf-8")
    return {"receipt": receipt, "out": str(out)}


def cmd_incident_drill(a: argparse.Namespace) -> dict[str, Any]:
    """§33 restore drill: every item must be proven; a missing item is a failed drill (exit 2)."""
    from dottie_loop.incidents import dr_drill_checklist

    results = json.loads(Path(a.results).read_text(encoding="utf-8"))
    if not isinstance(results, dict):
        raise InvalidInputError("results must be an object of item -> bool", field="results")
    verdict = dr_drill_checklist(results)
    if a.out:
        Path(a.out).write_text(json.dumps(verdict, indent=1, sort_keys=True), encoding="utf-8")
    if not verdict["ok"]:
        raise BlockedError("restore drill failed: " + ", ".join(verdict["failed"]), "dr_drill", verdict=verdict)
    return verdict


def cmd_dataset_release(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.dataset import Source, run_pipeline, write_release

    traces = _load_traces(a.traces)
    ledger = _read_json(a.consent_ledger) if a.consent_ledger else {}
    bench = _read_json(a.benchmarks) if a.benchmarks else []
    src = Source(id=a.source_id, license=a.license, consent_version=a.consent_version, records=traces)
    res = run_pipeline([src], consent_ledger=ledger, deletion_holds=set(a.hold or []), benchmark_items=bench, pipeline_commit=a.commit or "unknown")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "qa_report.json").write_text(json.dumps(res.report, indent=1, sort_keys=True), encoding="utf-8")
    if not res.ok:
        raise BlockedError("dataset QA hard-blocked: " + "; ".join(res.report["failures"]), "qa", report=res.report)
    manifest = write_release(res, out)
    return {"manifest": manifest, "counts": res.report["counts"], "out": str(out)}


def cmd_dataset_approve(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.dataset import approve_manifest

    mpath = Path(a.manifest)
    approved = approve_manifest(_read_json(str(mpath)), reviewer=a.reviewer, out_dir=mpath.parent)
    mpath.write_text(json.dumps(approved, indent=1, sort_keys=True), encoding="utf-8")
    return {"dataset_id": approved["dataset_id"], "status": approved["status"], "approved_by": approved["approved_by"], "manifest_hash": approved["manifest_hash"]}


def cmd_train_preflight(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.training import PreflightInputs, TrainRun, preflight

    raw = _read_json(a.run)
    raw.pop("schema", None)
    run = TrainRun(**raw)
    checks = _read_json(a.checks)
    pf = preflight(run, PreflightInputs(manifest=_read_json(a.manifest), **checks))
    if not pf["ok"]:
        raise BlockedError("preflight failed: " + ", ".join(pf["failed"]), "preflight", **pf)
    return pf


def cmd_eval_gates(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.evaluation import EvalBundle, evaluate_gates

    raw = _read_json(a.bundle)
    raw.pop("schema", None)
    result = evaluate_gates(EvalBundle(**raw))
    if a.out:
        Path(a.out).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


def cmd_approval_issue(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.approvals import ApprovalStore

    store = ApprovalStore.load(Path(a.store))
    rec = store.issue(approver_subject=a.approver, approver_role=a.role, action_type=a.action, payload=json.loads(a.payload), destination=a.destination, goal_id=a.goal_id, ttl_seconds=a.ttl)
    store.save(Path(a.store))
    return rec.to_dict()


def cmd_approval_consume(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.approvals import ApprovalStore

    store = ApprovalStore.load(Path(a.store))
    try:
        rec = store.verify_and_consume(a.approval_id, action_type=a.action, payload=json.loads(a.payload), destination=a.destination, goal_id=a.goal_id)
    finally:
        store.save(Path(a.store))  # replay attempts are recorded even when refused
    return rec.to_dict()


def cmd_promote_decide(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.evaluation import promotion_decision

    gates = _read_json(a.gates)
    canary = _read_json(a.canary) if a.canary else None
    decision = promotion_decision(gates, canary=canary, approval_valid=bool(a.approval_consumed), production_threshold_crossed=bool(a.threshold_crossed))
    if decision["outcome"] == "block":
        raise BlockedError("promotion blocked: " + decision["reason"], "promotion", decision=decision)
    return decision


def cmd_release_record(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.evaluation import release_record

    rec = release_record(artifact={"type": a.artifact_type, "id": a.artifact_id, "sha256": a.artifact_sha}, source_commit=a.source_commit, eval_bundle=a.eval_bundle, canary_decision=a.canary_decision, approval_id=a.approval_id, deployment_id=a.deployment_id, previous_release=a.previous_release, rollback_target=a.rollback_target, served_observed_hash=a.served_sha)
    Path(a.out).write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    if not rec["served_verification"]["pass"]:
        raise BlockedError("served artifact hash does not match the approved artifact", "served_verification", release=rec)
    return rec


def cmd_release_rollback(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.evaluation import rollback

    rel = _read_json(a.release)
    out = rollback(rel, served_after_hash=a.served_sha, reason=a.reason)
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    if out["status"] != "rolled_back":
        raise BlockedError("rollback did not restore the pinned incumbent", "rollback", **out)
    return out


def now_iso_str() -> str:
    from dottie_loop.hashing import now_iso

    return now_iso()


def cmd_spec_schemas(_a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.schema import ACTIVE_SCHEMAS

    return {"active": dict(ACTIVE_SCHEMAS), "rule": "readers accept known minor additions and reject unknown majors; writers emit one active version per record type"}


def cmd_spec_traceability(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.traceability import from_directory, validate_graph

    graph = from_directory(Path(a.dir))
    verdict = validate_graph(graph, require_rollback=not a.no_rollback)
    if a.out:
        Path(a.out).write_text(json.dumps({"graph": graph, "verdict": verdict}, indent=1, sort_keys=True), encoding="utf-8")
    if not verdict["complete"]:
        raise BlockedError("traceability graph incomplete: " + ", ".join(verdict["unresolved_edges"] + verdict["edges_missing_human_authority"]), "traceability", verdict=verdict)
    return {"verdict": verdict, "nodes": sorted(graph["nodes"])}


def cmd_spec_components(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.components import inventory

    return inventory(Path(a.root))


def cmd_privacy_hold(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.dataset import Lineage

    ln = Lineage.load(Path(a.lineage))
    rec = ln.hold(a.key, kind=a.kind, by=a.operator)
    ln.save(Path(a.lineage))
    return rec


def cmd_privacy_delete(a: argparse.Namespace) -> dict[str, Any]:
    """Runbook D privacy deletion over a persisted lineage; the receipt never restates private content."""
    from dottie_loop.dataset import Lineage

    ln = Lineage.load(Path(a.lineage))
    receipt = ln.delete(a.key, operator=a.operator)
    ln.save(Path(a.lineage))
    if a.out:
        Path(a.out).write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="utf-8")
    if receipt["status"] != "complete":
        raise BlockedError("deletion not completed: " + "; ".join(receipt.get("exceptions_under_hold", [])), "legal_hold", receipt=receipt)
    return receipt


def cmd_incident_playbook(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.incidents import playbook

    return playbook(a.kind)


def cmd_spec_acceptance(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.acceptance import coverage

    cov = coverage(Path(a.tests))
    if cov["missing"]:
        raise BlockedError("acceptance IDs without a named test: " + ", ".join(cov["missing"]), "tests", missing=cov["missing"])
    return cov


def cmd_spec_done(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.acceptance import definition_of_done

    ev = json.loads(Path(a.operator_evidence).read_text(encoding="utf-8")) if a.operator_evidence else None
    if ev is not None and not isinstance(ev, dict):
        raise InvalidInputError("operator evidence must be an object of D-id -> {proven, ref}", field="operator_evidence")
    dod = definition_of_done(Path(a.tests), ev)
    if a.out:
        Path(a.out).write_text(json.dumps(dod, indent=1, sort_keys=True), encoding="utf-8")
    if not dod["complete"]:
        raise BlockedError(f"definition of done not met: {len(dod['pending'])} item(s) pending: " + ", ".join(dod["pending"]), "operator_evidence", counts=dod["counts"], pending=dod["pending"])
    return dod


def cmd_spec_status(_a: argparse.Namespace) -> dict[str, Any]:
    return {
        "package": "dottie_loop",
        "version": __version__,
        "spec_version": SPEC_VERSION,
        "spec_baseline": SPEC_BASELINE,
        "capability_claim": "none",
        "note": "contracts and gates only; no model is called by this package",
    }


# --- parser -----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dottie-loop", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("goal").add_subparsers(dest="sub", required=True)
    s = g.add_parser("submit")
    s.add_argument("--store", required=True)
    s.add_argument("--surface", default="cli")
    s.add_argument("--subject", required=True, help="authenticated subject id")
    s.add_argument("--json", required=True, help="GoalEnvelope request payload")
    s.set_defaults(fn=cmd_goal_submit)
    s = g.add_parser("status")
    s.add_argument("--store", required=True)
    s.add_argument("--goal-id", required=True)
    s.set_defaults(fn=cmd_goal_status)

    pl = sub.add_parser("plan").add_subparsers(dest="sub", required=True)
    s = pl.add_parser("validate")
    s.add_argument("--file", required=True)
    s.set_defaults(fn=cmd_plan_validate)

    lo = sub.add_parser("loop").add_subparsers(dest="sub", required=True)
    s = lo.add_parser("evaluate")
    s.add_argument("--sources", required=True)
    s.add_argument("--baseline")
    s.add_argument("--last-terminal-at")
    s.add_argument("--out")
    s.add_argument("--promote", action="store_true")
    s.add_argument("--approve-prod", action="store_true")
    s.set_defaults(fn=cmd_loop_evaluate)
    s = lo.add_parser("run", help="one goal end to end: intake -> plan -> execute -> verify -> checkpoint")
    s.add_argument("--spec", required=True, help="RunSpec JSON: intent_text, steps[{kind: argv|file, ...}], capture")
    s.add_argument("--store", required=True)
    s.add_argument("--root", default=".", help="sandbox root every step is confined to")
    s.add_argument("--subject", required=True)
    s.add_argument("--surface", default="cli")
    s.add_argument("--capture", action="store_true", help="explicit opt-in switch (with spec.capture consent)")
    s.set_defaults(fn=cmd_loop_run)

    rw = sub.add_parser("reward").add_subparsers(dest="sub", required=True)
    s = rw.add_parser("compute")
    s.add_argument("--file", required=True)
    s.set_defaults(fn=cmd_reward_compute)

    ca = sub.add_parser("capture").add_subparsers(dest="sub", required=True)
    s = ca.add_parser("status")
    s.add_argument("--capture", action="store_true", help="explicit opt-in flag")
    s.set_defaults(fn=cmd_capture_status)

    fo = sub.add_parser("forge").add_subparsers(dest="sub", required=True)
    s = fo.add_parser("runners")
    s.add_argument("--root", required=True)
    s.add_argument("--allow", action="append")
    s.set_defaults(fn=cmd_forge_runners)
    s = fo.add_parser("submit")
    s.add_argument("--root", required=True)
    s.add_argument("--file", required=True)
    s.add_argument("--allow", action="append", help="repo allowlist entry owner/name")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_forge_submit)

    be = sub.add_parser("bench").add_subparsers(dest="sub", required=True)
    s = be.add_parser("smoke")
    s.add_argument("--commit")
    s.set_defaults(fn=cmd_bench_smoke)

    fb = sub.add_parser("feedback").add_subparsers(dest="sub", required=True)
    s = fb.add_parser("record", help="attach accept|reject|edit|apply|dismiss to a captured run and recompute its reward")
    s.add_argument("--store", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--signal", required=True)
    s.add_argument("--edit-fraction", type=float)
    s.add_argument("--subject", help="who gave the feedback (hashed by the caller if it is an identity)")
    s.set_defaults(fn=cmd_feedback_record)

    ds = sub.add_parser("dataset").add_subparsers(dest="sub", required=True)
    s = ds.add_parser("release", help="run the hard-block QA chain over captured traces and write shards + manifest")
    s.add_argument("--traces", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--consent-ledger", help="JSON {hashed_user_id: {capture_training, version}}")
    s.add_argument("--benchmarks", help="JSON list of benchmark prompts for decontamination")
    s.add_argument("--hold", action="append", help="deletion-hold key (repeatable)")
    s.add_argument("--source-id", default="pair-session")
    s.add_argument("--license", default="private-opt-in")
    s.add_argument("--consent-version", default="c1")
    s.add_argument("--commit")
    s.set_defaults(fn=cmd_dataset_release)
    s = ds.add_parser("approve", help="independent reviewer signs the exact manifest (hashes must resolve)")
    s.add_argument("--manifest", required=True)
    s.add_argument("--reviewer", required=True)
    s.set_defaults(fn=cmd_dataset_approve)

    tr = sub.add_parser("train").add_subparsers(dest="sub", required=True)
    s = tr.add_parser("preflight", help="the ten preflight checks; exits 2 naming every failure")
    s.add_argument("--run", required=True, help="TrainRun JSON")
    s.add_argument("--manifest", required=True, help="approved DatasetManifest JSON")
    s.add_argument("--checks", required=True, help="JSON of PreflightInputs minus manifest")
    s.set_defaults(fn=cmd_train_preflight)

    ev = sub.add_parser("eval").add_subparsers(dest="sub", required=True)
    s = ev.add_parser("gates", help="the seven §24 gates over an EvalBundle JSON")
    s.add_argument("--bundle", required=True)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_eval_gates)

    apv = sub.add_parser("approval").add_subparsers(dest="sub", required=True)
    s = apv.add_parser("issue")
    s.add_argument("--store", required=True, help="approvals JSON file")
    s.add_argument("--approver", required=True)
    s.add_argument("--role", default="owner")
    s.add_argument("--action", required=True)
    s.add_argument("--payload", required=True, help="canonical action payload JSON")
    s.add_argument("--destination", required=True)
    s.add_argument("--goal-id", required=True)
    s.add_argument("--ttl", type=int, default=900)
    s.set_defaults(fn=cmd_approval_issue)
    s = apv.add_parser("consume")
    s.add_argument("--store", required=True)
    s.add_argument("--approval-id", required=True)
    s.add_argument("--action", required=True)
    s.add_argument("--payload", required=True)
    s.add_argument("--destination", required=True)
    s.add_argument("--goal-id", required=True)
    s.set_defaults(fn=cmd_approval_consume)

    pr = sub.add_parser("promote").add_subparsers(dest="sub", required=True)
    s = pr.add_parser("decide", help="promote|hold|reject|rollback|block from gates + canary + approval state")
    s.add_argument("--gates", required=True, help="output of `eval gates --out`")
    s.add_argument("--canary", help="canary JSON {status, challenger_metric, baseline_metric}")
    s.add_argument("--approval-consumed", action="store_true", help="a promote approval was consumed for this exact artifact")
    s.add_argument("--threshold-crossed", action="store_true")
    s.set_defaults(fn=cmd_promote_decide)

    rl = sub.add_parser("release").add_subparsers(dest="sub", required=True)
    s = rl.add_parser("record", help="ReleaseRecord with served-hash verification; exits 2 on mismatch")
    s.add_argument("--artifact-type", default="model")
    s.add_argument("--artifact-id", required=True)
    s.add_argument("--artifact-sha", required=True)
    s.add_argument("--served-sha", required=True, help="hash fetched directly from production after aliasing")
    s.add_argument("--source-commit", required=True)
    s.add_argument("--eval-bundle", required=True)
    s.add_argument("--canary-decision", default="pass")
    s.add_argument("--approval-id", required=True)
    s.add_argument("--deployment-id", required=True)
    s.add_argument("--previous-release")
    s.add_argument("--rollback-target", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_release_record)
    s = rl.add_parser("rollback", help="move to the pinned incumbent, verify, freeze challenger, open SEV-1")
    s.add_argument("--release", required=True, help="ReleaseRecord JSON")
    s.add_argument("--served-sha", required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_release_rollback)

    rt = sub.add_parser("retention").add_subparsers(dest="sub", required=True)
    s = rt.add_parser("expire", help="§17 expiry job over a JSONL of {record_id, data_class, created_at, deletion_key?}")
    s.add_argument("--records", required=True)
    s.add_argument("--holds", help="JSON list of legal-hold record ids / deletion keys")
    s.add_argument("--deletions", help="JSON list of deletion-request keys")
    s.add_argument("--out", help="rewrite target (default: in place, atomically); a .receipt.json is written beside it")
    s.set_defaults(fn=cmd_retention_expire)

    inc = sub.add_parser("incident").add_subparsers(dest="sub", required=True)
    s = inc.add_parser("drill", help="§33 restore drill checklist; exits 2 unless every item is proven")
    s.add_argument("--results", required=True, help="JSON object item -> bool")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_incident_drill)
    s = inc.add_parser("playbook", help="§36 Runbook D steps for privacy_deletion | credential_exposure | prompt_injection | provider_rate_block")
    s.add_argument("--kind", required=True)
    s.set_defaults(fn=cmd_incident_playbook)

    pv = sub.add_parser("privacy").add_subparsers(dest="sub", required=True)
    s = pv.add_parser("hold", help="place a deletion hold (blocks export/training) or a legal hold (blocks deletion) on a deletion key")
    s.add_argument("--lineage", required=True, help="lineage JSON file (created if missing)")
    s.add_argument("--key", required=True, help="the subject's deletion key")
    s.add_argument("--kind", default="deletion", choices=["deletion", "legal"])
    s.add_argument("--operator", required=True)
    s.set_defaults(fn=cmd_privacy_hold)
    s = pv.add_parser("delete", help="Runbook D: tombstone traces, invalidate datasets, contaminate runs; exit 2 under a legal hold")
    s.add_argument("--lineage", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--operator", required=True)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_privacy_delete)

    sp = sub.add_parser("spec").add_subparsers(dest="sub", required=True)
    s = sp.add_parser("status")
    s.set_defaults(fn=cmd_spec_status)
    s = sp.add_parser("schemas", help="the one active version per record type")
    s.set_defaults(fn=cmd_spec_schemas)
    s = sp.add_parser("traceability", help="§39 final proof: assemble the chain's records into one graph and validate every arrow")
    s.add_argument("--dir", required=True, help="directory holding trace.json, reward.json, manifest.json, train.json, bundle.json, canary.json, approval.json, release.json, served.json, monitoring.json, rollback.json ...")
    s.add_argument("--out")
    s.add_argument("--no-rollback", action="store_true", help="do not require the rollback drill edge")
    s.set_defaults(fn=cmd_spec_traceability)
    s = sp.add_parser("acceptance", help="§38: which RT/ML IDs have a named test; exit 2 if any is missing")
    s.add_argument("--tests", default=str(Path(__file__).resolve().parent.parent / "tests"))
    s.set_defaults(fn=cmd_spec_acceptance)
    s = sp.add_parser("done", help="§39: the thirty done items; exit 2 until every operator item carries explicit evidence")
    s.add_argument("--tests", default=str(Path(__file__).resolve().parent.parent / "tests"))
    s.add_argument("--operator-evidence", help="JSON object D-id -> {proven: true, ref: '...'}")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_spec_done)
    s = sp.add_parser("components", help="§04/§34: which authoritative artifacts are actually in the tree")
    s.add_argument("--root", default=".")
    s.set_defaults(fn=cmd_spec_components)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = args.fn(args)
    except (BlockedError, StaleEvidenceError) as e:
        _emit({**error_envelope(e), "status": "blocked"})
        sys.stderr.write(f"blocked: {e.message}\n")
        return EXIT_BLOCKED
    except InvalidInputError as e:
        _emit(error_envelope(e))
        sys.stderr.write(f"invalid: {e.message}\n")
        return EXIT_INVALID
    except LoopError as e:
        _emit(error_envelope(e))
        sys.stderr.write(f"error: {e.message}\n")
        return EXIT_ERROR
    _emit(ok_envelope(data))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
