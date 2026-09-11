"""Acceptance matrix B — learning loop (spec §38 ML-01 … ML-17) plus RT-12/13/14/16
and the §22 anti-hacking tests.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from dottie_loop import (
    bench,
    capture,
    closed_loop,
    dataset,
    errors,
    evaluation,
    forge,
    reward,
    training,
)
from dottie_loop.hashing import now_iso

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _trace(i: int, user: str = "u1", session: str | None = None, text: str | None = None, **over):
    rec = capture.PairSessionTrace(
        session_id=session or f"s{i}",
        hashed_user_id=user,
        surface="cli",
        agent_id="dottie",
        goal={"intent": f"fix bug {i}", "task_family": "bugfix"},
        turns=[{"role": "user", "text": text or f"please fix bug number {i} in module alpha beta gamma delta {i}"}],
        outcome={"task_ok": True, "verifier": "pass"},
        consent_version="c1",
        lineage={"deletion_key": f"del-{user}", "source_hashes": []},
        captured_at=_iso(NOW + timedelta(minutes=i)),
        checkpoints=[{"nodeId": "n", "agentId": "dottie", "attempt": 1, "latency_ms": 5, "tokens_est": 0, "status": "completed", "errorClass": None}],
    ).to_dict()
    rec.update(over)
    return rec


LEDGER = {"u1": {"capture_training": True, "version": "c1"}, "u2": {"capture_training": True, "version": "c1"}}


# --- RT-12 capture off by default; RT-13 redaction before persistence ------------------------


def test_rt12_capture_off_by_default_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(capture.ENV_FLAG, raising=False)
    assert capture.capture_enabled() is False
    w = capture.CaptureWriter(tmp_path / "traces.jsonl", enabled=capture.capture_enabled(), salt="s")
    assert w.write(_trace(1)) is None
    assert not (tmp_path / "traces.jsonl").exists() and w.writes == 0
    assert capture.capture_enabled(env={capture.ENV_FLAG: "1"}) is True
    assert capture.capture_enabled(flag=True) is True


def test_rt13_sentinel_secret_email_ip_and_long_token_are_redacted(tmp_path):
    w = capture.CaptureWriter(tmp_path / "t.jsonl", enabled=True, salt="salt")
    sentinel_key = "sk-" + "TESTSENTINEL0123456789abcdef"
    long_tok = "".join(chr(65 + (i * 7) % 26) + str(i % 10) for i in range(24))
    rec = _trace(1, text=f"contact cam@example.com from 10.1.2.3 with Bearer {sentinel_key} and {long_tok} plus authorization token: abcdef123456")
    out = w.write(rec)
    body = json.dumps(out)
    assert "cam@example.com" not in body and "10.1.2.3" not in body
    assert sentinel_key not in body and long_tok not in body and "abcdef123456" not in body
    assert out["redaction_report"]["email"] == 1 and out["redaction_report"]["ip"] == 1
    disk = (tmp_path / "t.jsonl").read_text()
    assert sentinel_key not in disk and "cam@example.com" not in disk
    assert w.hash_identity("cam@example.com") != "cam@example.com" and len(w.hash_identity("x")) == 32


def test_capture_validation_and_honest_sink_error(tmp_path):
    w = capture.CaptureWriter(tmp_path / "t.jsonl", enabled=True, salt="s")
    with pytest.raises(errors.PolicyDeniedError):
        w.write(_trace(1, hashed_user_id="cam@example.com"))
    with pytest.raises(errors.PolicyDeniedError):
        w.write(_trace(1, data_class="P3"))
    with pytest.raises(errors.InvalidInputError):
        w.write(_trace(1, feedback=[{"signal": "loved_it"}]))
    with pytest.raises(errors.InvalidInputError):
        w.write(_trace(1, checkpoints=[{"nodeId": "n"}]))
    assert w.write(_trace(1)) is not None  # creates t.jsonl, which the next writer treats as a directory
    bad = capture.CaptureWriter(tmp_path / "t.jsonl" / "sub" / "x.jsonl", enabled=True, salt="s")  # parent is a file
    with pytest.raises(errors.TransientDependencyError):
        bad.write(_trace(2))


def test_export_eligibility_names_every_reason():
    rec = _trace(1)
    assert capture.export_eligibility(rec, consent_ledger=LEDGER, deletion_holds=set())["eligible"]
    r = capture.export_eligibility({**rec, "outcome": {}}, consent_ledger={}, deletion_holds={"del-u1"}, detector_fired=True)
    assert not r["eligible"]
    assert any("consent" in x for x in r["reasons"]) and any("outcome" in x for x in r["reasons"])
    assert any("detector" in x for x in r["reasons"]) and any("deletion" in x for x in r["reasons"])


# --- §22 reward anti-hacking (ML-06) ------------------------------------------------------------------


def _r(**kw):
    base = {"trace_id": "t", "task_ok": True}
    base.update(kw)
    return reward.compute_reward(reward.RewardInputs(**base))


def test_ml06_reward_anti_hacking_rules():
    correct = _r(feedback=None)
    accepted_failing = _r(task_ok=False, feedback="accept")
    assert accepted_failing["total"] < correct["total"]  # accepted-but-failing ranks below correct
    fast_fail = _r(task_ok=False, latency_ms=10, latency_baseline_ms=1000)
    slow_ok = _r(task_ok=True, latency_ms=5000, latency_baseline_ms=1000)
    assert fast_fail["total"] < slow_ok["total"]  # fast failure does not outrank slow success
    assert _r(verifier_score=8.0)["components"]["quality"] == _r(verifier_score=8.0)["components"]["quality"]  # length never enters
    silence = _r(feedback=None)
    assert silence["components"]["accept"] is None and "accept" in silence["components_missing"]  # silence neutral
    assert _r(regression=True)["components"]["task_ok"] == 0.0  # regression zeros task
    assert _r(feedback="accept", edit_fraction=0.9)["components"]["accept"] == reward.HEAVY_EDIT_ACCEPT_CREDIT  # heavy edit
    missing = _r(latency_ms=None, verifier_score=None, tokens_used=None)
    assert missing["components"]["time"] is None and missing["components"]["quality"] is None  # missing stays missing
    full = _r(feedback="accept", latency_ms=1000, latency_baseline_ms=1000, verifier_score=10.0, tokens_used=0, token_budget=100)
    assert full["total"] == 1.65 and reward.replay_total(full) == full["total"]  # weights reproduce total exactly
    assert _r(task_ok=None)["components"]["task_ok"] is None  # free-form without verifier stays null
    assert _r(feedback="reject")["components"]["accept"] == 0.0
    with pytest.raises(errors.InvalidInputError):
        _r(feedback="thumbs")
    with pytest.raises(errors.InvalidInputError):
        _r(verifier_score=11)


def test_preference_pairs_need_comparable_context_and_supported_ordering():
    a = _r(trace_id="a", task_ok=True)
    b = _r(trace_id="b", task_ok=False)
    pair = reward.form_preference_pair("ctx", "ctx", a, b)
    assert pair == {"chosen": "a", "rejected": "b", "basis": "task_outcome", "confidence": 1.0}
    assert reward.form_preference_pair("ctx1", "ctx2", a, b) is None
    assert reward.form_preference_pair("ctx", "ctx", a, b, tool_availability_a=["x"], tool_availability_b=[]) is None
    assert reward.form_preference_pair("ctx", "ctx", a, _r(trace_id="c", task_ok=True)) is None  # tie / unknown


# --- ML-01..05 dataset pipeline; ML-02 hard block; ML-03 accounting; ML-04 isolation -------------


def _sources(n=12, extra=None):
    recs = [_trace(i, user="u1" if i % 2 else "u2") for i in range(n)] + (extra or [])
    return [dataset.Source(id="pair-session", license="private-opt-in", consent_version="c1", records=recs)]


def test_ml01_to_ml05_release_reconciles_and_hard_blocks(tmp_path):
    secretish = _trace(90, text="here is the key " + "sk-" + "ABCDEFGHIJKLMNOP1234" + " for you")
    no_consent = _trace(91, user="u9")
    dup = _trace(92, text="please fix bug number 3 in module alpha beta gamma delta 3")
    res = dataset.run_pipeline(_sources(extra=[secretish, no_consent, dup]), consent_ledger=LEDGER, deletion_holds=set(), benchmark_items=["totally unrelated benchmark prompt"])
    c = res.report["counts"]
    assert res.ok, res.report["failures"]
    assert c["raw"] == 15 and c["excluded_privacy"] == 1 and c["excluded_consent"] == 1 and c["deduplicated"] == 1
    assert c["raw"] == sum(c[b] for b in dataset.BUCKETS)  # ML-03 exact equality
    assert c["train"] + c["validation"] + c["test"] == 12
    assert res.report["overlap"] == {"session_overlap": [], "exact_overlap": []}  # ML-04
    m = dataset.write_release(res, tmp_path / "ds")
    assert not dataset.consumer_accepts(m)  # unapproved manifest is rejected by consumers
    approved = dataset.approve_manifest(m, reviewer="independent", out_dir=tmp_path / "ds")
    assert dataset.consumer_accepts(approved) and approved["approved_by"] == "independent"
    # ML-05 lossless: every packed record decodes to its source text tokens
    for name, recs in res.shards.items():
        for r in recs:
            assert r["n_tokens"] == len(r["tokens"]) and r["n_tokens"] > 0, name


def test_ml02_injected_failure_prevents_manifest_and_training(tmp_path):
    bench_text = "please fix bug number 4 in module alpha beta gamma delta 4"
    res = dataset.run_pipeline(_sources(), consent_ledger=LEDGER, deletion_holds=set(), benchmark_items=[bench_text])
    assert not res.ok and res.manifest is None and any("contamination" in f for f in res.report["failures"])
    with pytest.raises(errors.UnexecutableError):
        dataset.write_release(res, tmp_path / "ds")
    bad_license = [dataset.Source(id="scraped", license="unknown", consent_version=None, records=[_trace(1)])]
    res2 = dataset.run_pipeline(bad_license, consent_ledger=LEDGER, deletion_holds=set(), benchmark_items=[])
    assert not res2.ok and any("license" in f for f in res2.report["failures"])  # ML-01


# --- RT-14 / ML-14 deletion propagates through lineage --------------------------------------------


def test_rt14_deletion_invalidates_dataset_and_blocks_promotion(tmp_path):
    src = _sources()
    res = dataset.run_pipeline(src, consent_ledger=LEDGER, deletion_holds=set(), benchmark_items=[])
    manifest = dataset.write_release(res, tmp_path / "ds")
    lin = dataset.Lineage()
    for r in src[0].records:
        lin.register_trace(r["trace_id"], r["lineage"]["deletion_key"])
    lin.register_manifest(manifest)
    lin.register_train_run("run1", manifest["dataset_id"], checkpoint="ckpt-A")
    assert lin.promotable("ckpt-A")
    receipt = lin.delete("del-u1", operator="cam")
    assert receipt["counts"]["traces_tombstoned"] > 0 and receipt["counts"]["manifests_invalidated"] == 1
    assert not lin.promotable("ckpt-A") and lin.manifests[manifest["dataset_id"]]["status"] == "invalidated"
    assert "del-u1" not in json.dumps(receipt)  # receipt never repeats private content
    with pytest.raises(errors.PolicyDeniedError):
        dataset.approve_manifest(lin.manifests[manifest["dataset_id"]], reviewer="r")


# --- ML-07 training preflight / reproducibility -----------------------------------------------------


def _run():
    return training.TrainRun(objective="sft", parent_checkpoint="ckpt-0", dataset_manifest="ds-1", code_commit="abc1234", tokenizer_hash="tok", model={"architecture": "tiny", "parameters": 14_000_000, "context": 1024}, optimizer={"name": "adamw", "lr": 3e-4, "schedule": "cosine", "weight_decay": 0.1}, batch={"micro": 4, "grad_accum": 8, "global": 32, "packing": "concat"}, hardware={"runner": "alienware", "gpu": "rtx", "vram_gb": 8, "cuda": "12.8"}, budgets={"max_steps": 100, "max_hours": 1, "max_cost": 0})


def test_ml07_preflight_names_every_failure_and_resume_rule():
    run = _run()
    run.budgets["max_cost"] = 1
    manifest = {"dataset_id": "ds-1", "status": "approved", "approved_by": "r", "shards": [{"sha256": "x"}]}
    good = training.PreflightInputs(manifest=manifest, split_overlap_zero=True, tokenizer_roundtrip_ok=True, checkpoint_loads=True, hardware_ok=True, storage_gb_free=100, storage_gb_needed=10, metrics_sink_writable=True, cancellation_tested=True, baseline_eval_fresh=True)
    assert training.preflight(run, good)["ok"]
    bad = training.PreflightInputs(manifest={**manifest, "status": "candidate"}, split_overlap_zero=False, tokenizer_roundtrip_ok=True, checkpoint_loads=True, hardware_ok=False, storage_gb_free=10, storage_gb_needed=10, metrics_sink_writable=True, cancellation_tested=False, baseline_eval_fresh=False)
    pf = training.preflight(run, bad)
    assert not pf["ok"] and set(pf["failed"]) == {"manifest_approved_and_hashes_resolve", "split_overlap_zero", "hardware_satisfies_requirements", "storage_fits_with_margin", "cancellation_and_checkpoint_on_signal_tested", "baseline_eval_bundle_fresh"}
    with pytest.raises(errors.InvalidInputError):
        training.validate_train_run(_run())  # max_cost 0 is not explicit
    digest0 = run.config_digest()
    assert training.resume_run(run, checkpoint_verified=True, recorded_config_digest=digest0)["resumed"] == run.run_id
    with pytest.raises(errors.BlockedError):
        training.resume_run(run, checkpoint_verified=False, recorded_config_digest=digest0)
    forked = training.oom_retry(run, new_micro=2)
    assert forked.forked_from == run.run_id and forked.batch["global"] == 16 and forked.batch["revised_from"] == 32
    with pytest.raises(errors.BlockedError):
        training.oom_retry(forked, new_micro=1)
    assert training.hard_stop("nan_or_inf_loss")["action"] == "hard_stop"
    with pytest.raises(errors.InvalidInputError):
        training.hard_stop("felt_wrong")


# --- ML-09..ML-13 evaluation gates, ML-11 anti-mock, ML-12 freshness -----------------------------------


def _bundle(**over):
    base = {"candidate": {"id": "ch", "sha256": "c" * 8}, "incumbent": {"id": "inc", "sha256": "i" * 8}, "benchmark_version": "b1", "hidden_set_snapshot": "h1", "primary_metric": "task_ok", "candidate_primary": 0.80, "incumbent_primary": 0.75, "ci_low": 0.01, "ci_high": 0.09, "n_items": 200, "slice_results": {"bugfix": 0.8, "research": 0.7}, "slice_floors": {"bugfix": 0.6, "research": 0.6}, "regressions": {"safety": 0, "authorization": 0, "protected_tests": 0}, "safety_findings": [], "efficiency": {"candidate_cost": 1.0, "incumbent_cost": 1.0, "approved_ratio": 1.2}, "overlap_report": {"manifest_ok": True, "split_ok": True, "leakage": False, "privacy_unresolved": False}, "synthetic": False, "mock": False, "evaluator_commit": "abc", "evaluated_at": _iso(NOW - timedelta(hours=1)), "baseline_evaluated_at": _iso(NOW - timedelta(hours=2))}
    base.update(over)
    return evaluation.EvalBundle(**base)


def test_ml09_to_ml13_gates_and_decisions():
    g = evaluation.evaluate_gates(_bundle(), now=NOW)
    assert g["verdict"] == "pass" and g["failed"] == []
    assert evaluation.evaluate_gates(_bundle(ci_low=-0.01), now=NOW)["failed"] == ["task_win"]  # uncertainty reported
    assert evaluation.evaluate_gates(_bundle(regressions={"safety": 1, "authorization": 0, "protected_tests": 0}), now=NOW)["failed"] == ["no_critical_regression"]  # ML-10
    assert evaluation.evaluate_gates(_bundle(slice_results={"bugfix": 0.8, "research": 0.5}), now=NOW)["failed"] == ["slice_floor"]
    assert evaluation.evaluate_gates(_bundle(synthetic=True), now=NOW)["failed"] == ["anti_mock"]  # ML-11
    assert evaluation.evaluate_gates(_bundle(evaluated_at=_iso(NOW - timedelta(days=21))), now=NOW)["failed"] == ["freshness"]  # ML-12
    assert evaluation.evaluate_gates(_bundle(efficiency={"candidate_cost": 2.0, "incumbent_cost": 1.0, "approved_ratio": 1.2}), now=NOW)["failed"] == ["efficiency_bound"]
    canary = {"status": "complete", "challenger_metric": 0.80, "baseline_metric": 0.79, "incumbent_id": "inc", "challenger_id": "ch"}  # ML-13
    assert evaluation.promotion_decision(g, canary=canary, approval_valid=True)["outcome"] == "promote"
    assert evaluation.promotion_decision(g, canary=canary, approval_valid=False)["outcome"] == "block"  # ML-14
    assert evaluation.promotion_decision(g, canary=None, approval_valid=True)["outcome"] == "hold"
    assert evaluation.promotion_decision(g, canary={**canary, "challenger_metric": 0.70}, approval_valid=True)["outcome"] == "reject"
    assert evaluation.promotion_decision(evaluation.evaluate_gates(_bundle(mock=True), now=NOW), canary=canary, approval_valid=True)["outcome"] == "block"
    assert evaluation.promotion_decision(evaluation.evaluate_gates(_bundle(ci_low=-1), now=NOW), canary=canary, approval_valid=True)["outcome"] == "reject"
    assert evaluation.promotion_decision(g, canary=canary, approval_valid=True, production_threshold_crossed=True)["outcome"] == "rollback"
    assert evaluation.canary_plan_valid({})["missing"] == list(evaluation.CANARY_REQUIREMENTS)


# --- ML-15 served artifact matches; ML-16 rollback tested ----------------------------------------------


def test_ml15_ml16_release_record_and_rollback():
    with pytest.raises(errors.ApprovalRequiredError):
        evaluation.release_record(artifact={"type": "model", "id": "ch", "sha256": "abc"}, source_commit="c", eval_bundle="e", canary_decision="pass", approval_id=None, deployment_id="d", previous_release=None, rollback_target="inc-hash", served_observed_hash="abc")
    rel = evaluation.release_record(artifact={"type": "model", "id": "ch", "sha256": "abc"}, source_commit="c", eval_bundle="e", canary_decision="pass", approval_id="apr_1", deployment_id="d", previous_release=None, rollback_target="inc-hash", served_observed_hash="abc")
    assert rel["served_verification"]["pass"] and rel["status"] == "active"
    mismatch = evaluation.release_record(artifact={"type": "model", "id": "ch", "sha256": "abc"}, source_commit="c", eval_bundle="e", canary_decision="pass", approval_id="apr_1", deployment_id="d", previous_release=None, rollback_target="inc-hash", served_observed_hash="zzz")
    assert mismatch["status"] == "mismatch"
    rb = evaluation.rollback(rel, served_after_hash="inc-hash", reason="correctness regression")
    assert rb["status"] == "rolled_back" and rb["incident"]["severity"] == "SEV-1" and rb["challenger_frozen"] == "ch"
    assert rb["incident"]["suspected_cause"] is None and rb["incident"]["confirmed_cause"] is None
    assert evaluation.rollback(rel, served_after_hash="wrong", reason="x")["status"] == "rollback_failed"


# --- §26 closed loop: freshness, cooldown, lease, approval guard ---------------------------------------


def _sources_metrics(age_h=1.0, traces=600, verifier=7.5, ok=0.85, ev=0.70, prov="measured"):
    t = _iso(NOW - timedelta(hours=age_h))
    return {
        "verifier": closed_loop.MetricSource("verifier", verifier, t, prov, "v1"),
        "agent_ok": closed_loop.MetricSource("agent_ok", ok, t, prov, "v1"),
        "eval": closed_loop.MetricSource("eval", ev, t, prov, "v1"),
        "traces": closed_loop.MetricSource("traces", traces, t, prov, "v1"),
    }


def test_closed_loop_trigger_blocked_and_no_change(tmp_path):
    base = {"agent_ok": 0.95, "eval": 0.75}
    d = closed_loop.evaluate_trigger(_sources_metrics(), baseline=base, lease=None, last_terminal_at=None, now=NOW)
    assert d["decision"] == "trigger" and d["predicates"]["enough_new_traces"]
    stale = closed_loop.evaluate_trigger(_sources_metrics(age_h=21 * 24), baseline=base, lease=None, last_terminal_at=None, now=NOW)
    assert stale["decision"] == "blocked" and all("stale" in b for b in stale["blockers"])  # the observed live state
    synth = closed_loop.evaluate_trigger(_sources_metrics(prov="synthetic"), baseline=base, lease=None, last_terminal_at=None, now=NOW)
    assert synth["decision"] == "blocked" and any("synthetic" in b for b in synth["blockers"])
    few = closed_loop.evaluate_trigger(_sources_metrics(traces=12), baseline=base, lease=None, last_terminal_at=None, now=NOW)
    assert few["decision"] == "blocked" and any("500" in b for b in few["blockers"])
    healthy = closed_loop.evaluate_trigger(_sources_metrics(verifier=9.0, ok=0.96, ev=0.76), baseline=base, lease=None, last_terminal_at=None, now=NOW)
    assert healthy["decision"] == "no_change" and healthy["blockers"] == []
    lease = closed_loop.Lease(owner="box", started_at=_iso(NOW), heartbeat_at=_iso(NOW), expires_at=_iso(NOW + timedelta(hours=1)))
    assert closed_loop.evaluate_trigger(_sources_metrics(), baseline=base, lease=lease, last_terminal_at=None, now=NOW)["decision"] == "blocked"
    cool = closed_loop.evaluate_trigger(_sources_metrics(), baseline=base, lease=None, last_terminal_at=_iso(NOW - timedelta(hours=23)), now=NOW)
    assert cool["decision"] == "blocked" and any("cooldown" in b for b in cool["blockers"])
    missing = {k: v for k, v in _sources_metrics().items() if k != "eval"}
    assert "eval: missing" in closed_loop.evaluate_trigger(missing, baseline=base, lease=None, last_terminal_at=None, now=NOW)["blockers"]
    closed_loop.write_decision(healthy, tmp_path / "d.jsonl")
    closed_loop.write_decision(d, tmp_path / "d.jsonl")
    assert len((tmp_path / "d.jsonl").read_text().splitlines()) == 2  # emitted even on no change


def test_closed_loop_promote_guard_never_changes_production():
    d = closed_loop.evaluate_trigger(_sources_metrics(), baseline={"agent_ok": 0.95, "eval": 0.75}, lease=None, last_terminal_at=None, now=NOW)
    g = closed_loop.promote_guard(promote=True, approve_prod=False, decision=d)
    assert g["production_change"] is False and g["record"] is None and "without --approve-prod" in g["reason"]
    g2 = closed_loop.promote_guard(promote=True, approve_prod=True, decision=d)
    assert g2["production_change"] is False and g2["record"]["kind"] == "promotion_packet"
    assert closed_loop.promote_guard(promote=False, approve_prod=True, decision=d)["record"] is None


# --- ML-08 Forge runner is real and healthy -------------------------------------------------------------


def _spec(**over):
    base = {"repo": "jcdavis131/dottie", "ref": "abc1234", "argv": ["python3", "-c", "print('FORGE_METRIC loss=0.5')"], "cwd": ".", "requirements": {"cuda": False, "vram_gb": 0, "torch": False}, "inputs": [], "outputs": [], "timeout_seconds": 30, "submitted_by": "hatch"}
    base.update(over)
    return forge.JobSpec(**base)


def test_ml08_forge_queue_claim_execute_and_runner_blocker(tmp_path):
    q = forge.ForgeQueue(tmp_path / "forge", repo_allowlist=["jcdavis131/dottie"])
    with pytest.raises(errors.BlockedError):
        q.require_runner()  # the spec's immediate blocker, typed
    with pytest.raises(errors.PolicyDeniedError):
        q.submit(_spec(repo="evil/repo"))
    with pytest.raises(errors.InvalidInputError):
        q.submit(_spec(ref="main"))
    with pytest.raises(errors.InvalidInputError):
        q.submit(_spec(cwd="../up"))
    q.submit(_spec())
    gpu_job = _spec(requirements={"cuda": True, "vram_gb": 6, "torch": True})
    q.submit(gpu_job)
    runner = forge.RunnerRecord(hostname="cpu-box", gpu="none", vram_gb=0, cuda=None, torch=None, platform="linux")
    q.advertise(runner)
    assert q.require_runner().hostname == "cpu-box"
    claimed = q.claim(runner)
    assert claimed is not None and claimed.requirements["cuda"] is False
    assert q.claim(runner) is None  # nothing else claimable; second claim of the same job impossible
    assert q.result(gpu_job.job_id)["status"] == "mismatch"  # rejected before clone/execute
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    res = q.execute(claimed, checkout, runner)
    assert res["status"] == "ok" and res["metrics"] == {"loss": 0.5}
    assert (tmp_path / "forge" / "jobs" / "done" / f"{claimed.job_id}.json").exists()
    assert forge.parse_metrics("FORGE_METRIC a=1\nnoise\nFORGE_METRIC b = 2.5e-1\n") == {"a": 1.0, "b": 0.25}


def test_forge_input_hash_mismatch_and_required_output(tmp_path):
    q = forge.ForgeQueue(tmp_path / "forge", repo_allowlist=["jcdavis131/dottie"])
    runner = forge.RunnerRecord(hostname="r", gpu="none", vram_gb=0, cuda=None, torch=None, platform="linux")
    checkout = tmp_path / "co"
    checkout.mkdir()
    (checkout / "data.txt").write_text("x")
    spec = _spec(inputs=[{"path": "data.txt", "sha256": "0" * 64}])
    q.submit(spec)
    q.advertise(runner)
    assert q.execute(q.claim(runner), checkout, runner)["status"] == "input_mismatch"
    spec2 = _spec(outputs=[{"path": "model.bin", "required": True}])
    q.submit(spec2)
    assert q.execute(q.claim(runner), checkout, runner)["status"] == "failed"
    old = forge.RunnerRecord(hostname="r", gpu="none", vram_gb=0, cuda=None, torch=None, platform="linux", heartbeat_at=_iso(NOW - timedelta(hours=2)))
    q.advertise(old)
    spec3 = _spec()
    q.submit(spec3)
    q.claim(old, now=_iso(NOW))
    assert q.orphans(_iso(NOW)) == [spec3.job_id]


# --- §23 benchmark builder ---------------------------------------------------------------------------------


def test_bench_report_accounting_and_anti_mock():
    wf_ok = bench.run_workflow(bench.Workflow("a", [bench.Step("s", lambda: 1, lambda o: o == 1)]))
    wf_fail = bench.run_workflow(bench.Workflow("b", [bench.Step("boom", lambda: 1 / 0), bench.Step("after", lambda: 2)]))
    wf_syn = bench.run_workflow(bench.Workflow("grpo-collector", [bench.Step("s", lambda: {"synthetic": True})], synthetic=True))
    assert wf_fail["steps"][0]["status"] == "failed" and wf_fail["steps"][1]["status"] == "skipped"
    rep = bench.build_report([wf_ok, wf_fail, wf_syn], [bench.golden_check({"schema": "pair-reward-1.0.0", "total": 1}, "pair-reward", ["total", "weights"])])
    assert rep["accounting_ok"] and rep["workflows"] == {"total": 3, "ok": 2, "failed": 1, "evidence_eligible": 2, "excluded_synthetic": ["grpo-collector"]}
    assert rep["harness_score"] == 0.5 and rep["capability_claim"] == "none"
    assert rep["goldens"]["valid"] == 0 and rep["goldens"]["invalid"][0]["problems"] == ["missing weights"]
    broken = bench.build_report([{**wf_ok, "steps": [{"step": "s", "status": "??", "latency_ms": 0}]}], [])
    assert not broken["accounting_ok"] and broken["harness_score"] is None and "abort" in broken


# --- ML-17 one closed loop completes end to end (traceability graph) ----------------------------------------


def test_ml17_traceability_chain_resolves(tmp_path):
    """trace → reward → dataset → train run → eval → canary → approval → release → rollback."""
    from dottie_loop.approvals import ApprovalStore

    w = capture.CaptureWriter(tmp_path / "traces.jsonl", enabled=True, salt="s")
    traces = [w.write(_trace(i)) for i in range(12)]
    rewards = [reward.compute_reward(reward.RewardInputs(trace_id=t["trace_id"], task_ok=True, feedback="accept")) for t in traces]
    assert all(r["trace_id"] in {t["trace_id"] for t in traces} for r in rewards)
    src = [dataset.Source(id="pair-session", license="private-opt-in", consent_version="c1", records=traces)]
    res = dataset.run_pipeline(src, consent_ledger=LEDGER, deletion_holds=set(), benchmark_items=[])
    manifest = dataset.approve_manifest(dataset.write_release(res, tmp_path / "ds"), reviewer="independent", out_dir=tmp_path / "ds")
    run = _run()
    run.budgets["max_cost"] = 1
    run.dataset_manifest = manifest["dataset_id"]
    pf = training.preflight(run, training.PreflightInputs(manifest=manifest, split_overlap_zero=True, tokenizer_roundtrip_ok=True, checkpoint_loads=True, hardware_ok=True, storage_gb_free=100, storage_gb_needed=1, metrics_sink_writable=True, cancellation_tested=True, baseline_eval_fresh=True))
    assert pf["ok"]
    gates = evaluation.evaluate_gates(_bundle(candidate={"id": run.run_id, "sha256": "chal"}), now=NOW)
    st = ApprovalStore()
    apr = st.issue(approver_subject="cam", approver_role="owner", action_type="promote", payload={"artifact": "chal"}, destination="production", goal_id="loop", now=NOW)
    st.verify_and_consume(apr.approval_id, action_type="promote", payload={"artifact": "chal"}, destination="production", goal_id="loop", now=NOW)
    decision = evaluation.promotion_decision(gates, canary={"status": "complete", "challenger_metric": 0.8, "baseline_metric": 0.79}, approval_valid=True)
    assert decision["outcome"] == "promote"
    rel = evaluation.release_record(artifact={"type": "model", "id": run.run_id, "sha256": "chal"}, source_commit="abc", eval_bundle=gates["bundle_id"], canary_decision="pass", approval_id=apr.approval_id, deployment_id="dep1", previous_release=None, rollback_target="inc", served_observed_hash="chal")
    assert rel["status"] == "active"
    assert evaluation.rollback(rel, served_after_hash="inc", reason="drill")["status"] == "rolled_back"
    chain = [traces[0]["trace_id"], rewards[0]["trace_id"], manifest["dataset_id"], run.dataset_manifest, gates["bundle_id"], rel["eval_bundle"], apr.approval_id, rel["approval_id"]]
    assert all(chain) and rel["eval_bundle"] == gates["bundle_id"] and run.dataset_manifest == manifest["dataset_id"]
    assert now_iso().endswith("Z")
