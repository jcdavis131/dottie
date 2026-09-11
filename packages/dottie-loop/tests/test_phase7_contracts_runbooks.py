"""Phase 7 acceptance: §37A migrations, §21.1 telemetry + heartbeats, §36 Runbook D as data
and as `privacy hold|delete`, Runbook A cancellation, §04/§34 component inventory."""

from __future__ import annotations

import json

import pytest

from dottie_loop import (
    components,
    dataset,
    errors,
    incidents,
    schema,
    timeline,
    training,
)
from dottie_loop.cli import EXIT_BLOCKED, EXIT_INVALID, EXIT_OK, main
from dottie_loop.execution import Kernel
from dottie_loop.plan import PlanStep


def _run(capsys, *argv):
    rc = main([str(a) for a in argv])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return rc, json.loads(lines[-1])


# --- §37A migrations -----------------------------------------------------------------------


def test_migration_is_deterministic_new_records_with_manifest():
    old = [{"schema": "pair-reward-1.0.0", "trace_id": "t1", "total": 1.0}, {"schema": "pair-reward-1.0.0", "trace_id": "t2", "total": 0.5}]
    snapshot = json.dumps(old, sort_keys=True)

    def up(rec):
        rec["components"] = {"task_ok": rec.pop("total")}
        return rec

    a = schema.migrate(old, record_type="pair-reward", target="pair-reward-1.1.0", migrator=up, id_field="trace_id")
    b = schema.migrate(old, record_type="pair-reward", target="pair-reward-1.1.0", migrator=up, id_field="trace_id")
    assert json.dumps(old, sort_keys=True) == snapshot  # inputs untouched
    assert [r["trace_id"] for r in a["records"]] == ["t1", "t2"] and a["records"][0]["schema"] == "pair-reward-1.1.0" and a["records"][0]["migrated_from"] == "pair-reward-1.0.0"
    assert a["manifest"]["before_hash"] == b["manifest"]["before_hash"] and a["manifest"]["after_hash"] == b["manifest"]["after_hash"]
    assert a["manifest"]["counts"] == {"in": 2, "out": 2} and a["manifest"]["from_schemas"] == ["pair-reward-1.0.0"]
    schema.check_compatible(a["records"][0]["schema"], "pair-reward")  # a minor bump stays readable
    with pytest.raises(errors.InvalidInputError):
        schema.migrate(old, record_type="pair-reward", target="eval-bundle-2.0.0", migrator=up, id_field="trace_id")
    with pytest.raises(errors.InvalidInputError):  # ids must be preserved
        schema.migrate(old, record_type="pair-reward", target="pair-reward-1.1.0", migrator=lambda r: {**r, "trace_id": "renamed"}, id_field="trace_id")
    with pytest.raises(errors.InvalidInputError):
        schema.migrate([{"schema": "pair-reward-1.0.0"}], record_type="pair-reward", target="pair-reward-1.1.0", migrator=up, id_field="trace_id")


# --- §21.1 telemetry + heartbeats ----------------------------------------------------------


def _telemetry(**over):
    base = {"run_id": "run_1", "step": 10, "tokens_seen": 1000, "loss_total": 2.1, "loss_components": {"sft": 2.1}, "lr": 1e-4, "grad_norm": 0.9, "throughput": 100.0, "memory_gb": 7.5, "data_shard": "shard-0", "selected_distribution": {"a": 6, "b": 4}, "kl": 0.01, "reward_components": {}, "checkpoint_write_s": 1.2, "evaluator_status": "ok"}
    base.update(over)
    return base


def test_telemetry_maps_to_hard_stops_and_heartbeats_detect_hangs():
    assert training.stop_condition_for(_telemetry()) is None
    assert training.stop_condition_for(_telemetry(loss_total=float("nan"))) == "nan_or_inf_loss"
    assert training.stop_condition_for(_telemetry(loss_total=float("inf"))) == "nan_or_inf_loss"
    assert training.stop_condition_for(_telemetry(shard_error="EIO")) == "unreadable_shard"
    assert training.stop_condition_for(_telemetry(samples_expected=11)) == "sample_accounting_mismatch"
    assert training.stop_condition_for(_telemetry(secret_detector_hits=1)) == "secret_detector_hit"
    assert training.stop_condition_for(_telemetry(), manifest_shards={"shard-1"}) == "data_drift_beyond_manifest"
    assert training.stop_condition_for(_telemetry(checkpoint_hash_ok=False)) == "checkpoint_corruption"
    assert training.stop_condition_for(_telemetry(evaluator_status="unavailable")) == "evaluation_unavailable"
    for cond in training.HARD_STOP_CONDITIONS:
        assert training.hard_stop(cond)["action"] == "hard_stop"
    with pytest.raises(errors.InvalidInputError):
        training.validate_telemetry({"run_id": "x"})
    hb = training.HeartbeatMonitor(interval_s=10.0)
    assert hb.hang(now=5.0)["hung"] is False and hb.hang(now=31.0)["hung"] is True  # never beat
    hb.beat(31.0)
    assert hb.hang(now=60.0)["hung"] is False and hb.hang(now=61.5)["hung"] is True and hb.hang(61.5)["silent_s"] == 30.5
    with pytest.raises(errors.InvalidInputError):
        hb.beat(1.0)


# --- Runbook D ------------------------------------------------------------------------------


def test_playbooks_are_ordered_data_and_open_incidents_at_their_severity(capsys):
    for kind, pb in incidents.PLAYBOOKS.items():
        p = incidents.playbook(kind)
        assert [s["n"] for s in p["steps"]] == list(range(1, len(pb["steps"]) + 1)) and p["never"]
    with pytest.raises(errors.InvalidInputError):
        incidents.playbook("improvise")
    inc = incidents.open_from_playbook("credential_exposure", source="leaks scan", observed_impact="token in a log line")
    assert inc.severity == "SEV-0" and inc.status == "detect"
    rc, env = _run(capsys, "incident", "playbook", "--kind", "provider_rate_block")
    assert rc == EXIT_OK and env["data"]["steps"][0]["step"].startswith("treat the 429")
    assert _run(capsys, "incident", "playbook", "--kind", "nope")[0] == EXIT_INVALID


def test_privacy_hold_and_delete_over_a_persisted_lineage(capsys, tmp_path):
    ln = dataset.Lineage()
    ln.register_trace("trc_1", "del-u1")
    ln.register_trace("trc_2", "del-u2")
    ln.register_manifest({"dataset_id": "ds_1", "trace_ids": ["trc_1", "trc_2"], "status": "approved"})
    ln.register_train_run("run_1", "ds_1", checkpoint="ckpt-A")
    lineage = tmp_path / "lineage.json"
    ln.save(lineage)
    assert dataset.Lineage.load(lineage).to_dict() == ln.to_dict()
    # a deletion hold blocks export/training BEFORE the deletion completes (Runbook D step 2)
    rc, env = _run(capsys, "privacy", "hold", "--lineage", lineage, "--key", "del-u1", "--operator", "cam")
    assert rc == EXIT_OK and env["data"]["kind"] == "deletion" and "del-u1" not in json.dumps(env)
    assert not dataset.Lineage.load(lineage).exportable("trc_1") and dataset.Lineage.load(lineage).exportable("trc_2")
    rc, env = _run(capsys, "privacy", "delete", "--lineage", lineage, "--key", "del-u1", "--operator", "cam", "--out", tmp_path / "receipt.json")
    r = env["data"]
    assert rc == EXIT_OK and r["counts"] == {"traces_tombstoned": 1, "manifests_invalidated": 1, "train_runs_contaminated": 1} and r["affected_checkpoints"] == ["ckpt-A"]
    assert "del-u1" not in (tmp_path / "receipt.json").read_text() and "trc_1" not in json.dumps(r)  # no private content, no trace ids
    after = dataset.Lineage.load(lineage)
    assert after.traces["trc_1"]["tombstoned"] and not after.promotable("ckpt-A") and len(after.receipts) == 1
    # a legal hold blocks deletion: exit 2, receipt says held, nothing tombstoned
    rc, env = _run(capsys, "privacy", "hold", "--lineage", lineage, "--key", "del-u2", "--kind", "legal", "--operator", "counsel")
    assert rc == EXIT_OK
    rc, env = _run(capsys, "privacy", "delete", "--lineage", lineage, "--key", "del-u2", "--operator", "cam")
    assert rc == EXIT_BLOCKED and env["error"]["details"]["receipt"]["status"] == "held" and not dataset.Lineage.load(lineage).traces["trc_2"]["tombstoned"]
    with pytest.raises(errors.InvalidInputError):
        ln.hold("k", kind="forever", by="x")


# --- Runbook A cancellation ----------------------------------------------------------------


def test_cancellation_records_actor_reason_and_unknown_external_effects(tmp_path):
    store = timeline.RunStore(tmp_path, "run_c")
    k = Kernel(store=store, goal_id="g")
    with pytest.raises(errors.InvalidInputError):
        k.cancel(actor="", reason="", in_flight=[], external_effects_pending=[])
    rec = k.cancel(actor="cam", reason="wrong destination", in_flight=["step-2"], external_effects_pending=["slack:#ops send"])
    assert rec["external_effects"] == {"slack:#ops send": "unknown_until_checked"} and rec["evidence_retained"] and rec["implies_rollback"] is False
    ev = store.events()[-1]
    assert ev["status"] == "cancelled" and ev["tool_receipts"][0]["cancelled_by"] == "cam" and all(f in ev for f in timeline.SEVEN_FIELDS)
    with pytest.raises(errors.LoopError) as ei:  # no new dispatch after cancel
        k.admit(PlanStep(id="s", idx=0, role="worker"), set())
    assert ei.value.code == "cancelled"


# --- §04 / §34 ------------------------------------------------------------------------------


def test_component_inventory_reports_the_tree_not_the_spec_column(capsys, tmp_path):
    (tmp_path / "apps" / "scout-cli").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "forge_runner.py").write_text("")
    inv = components.inventory(tmp_path)
    by = {r["component"]: r for r in inv["components"]}
    assert by["scout_cli"]["present"] and by["scout_cli"]["kind"] == "dir" and by["forge"]["present"] and by["forge"]["kind"] == "file"
    assert by["pair_capture"]["present"] is False and by["pair_capture"]["spec_status_2026_09_10"] == "BRANCH"  # the spec said BRANCH; the tree says absent
    assert inv["present"] == 2 and len(inv["absent"]) == len(components.COMPONENTS) - 2
    rc, env = _run(capsys, "spec", "components", "--root", tmp_path)
    assert rc == EXIT_OK and env["data"]["absent"] == inv["absent"]
