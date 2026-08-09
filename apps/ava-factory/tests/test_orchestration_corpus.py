"""Tests for scripts/build_orchestration_corpus.py.

Hermetic: builds go into tmp_path with fixture inputs — the real workflow
journal path is never required, and nothing is written into
apps/ava-factory/data during tests. The committed corpus check is skipped
when the data files are absent so CI stays green pre-build.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_AVA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AVA / "scripts"))

# The corpus builder imports the scout-cli harness heuristics (which pull in
# typer) at module level; the codeact-sandbox CI env deliberately installs
# neither, so skip this module there rather than erroring at collection.
pytest.importorskip("typer", reason="corpus builder requires scout-cli harness deps")

import build_orchestration_corpus as bc

# ---------------------------------------------------------------- helpers

def _build(out, ultra_dir, journal_dir=None, battery_n=5, seed=None, corrections=None):
    argv = ["build", "--out", str(out), "--ultra-dir", str(ultra_dir), "--battery-n", str(battery_n)]
    if journal_dir is not None:
        argv += ["--journal-dir", str(journal_dir)]
    if seed is not None:
        argv += ["--seed", str(seed)]
    if corrections is not None:
        argv += ["--corrections", str(corrections)]
    assert bc.main(argv) == 0
    return _load(out / "corpus.jsonl")


def _load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _empty_ultra(tmp_path):
    d = tmp_path / "no-ultra"
    d.mkdir(exist_ok=True)
    return d


def _write_ultra_fixture(tmp_path):
    """Two re-runs of the same run family, identical rows, timestamp suffixes."""
    ultra = tmp_path / "ultra-runs"
    rows = [
        {"nodeId": "langchain.run.observe", "agentId": "researcher", "attempt": 1,
         "latency_ms": 30, "latency": 30, "tokens": 2, "tokens_est": 2,
         "status": "ok", "errorClass": None, "layer": 2},
        {"nodeId": "langchain.run.decide_act", "agentId": "scout-prime-coordinator", "attempt": 1,
         "latency_ms": 1, "latency": 1, "tokens": 6, "tokens_est": 6,
         "status": "ok", "errorClass": None, "layer": 0},
    ]
    checkpoint = {"goal_preview": "launch the loop end-to-end", "intent": "agentic_loop"}
    for run_id in ("agents-x-run-abc-111111", "agents-x-run-abc-222222"):
        run_dir = ultra / run_id
        run_dir.mkdir(parents=True)
        with (run_dir / "timeline.jsonl").open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        (run_dir / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    return ultra


# A deliberately fake model-id string for the leak test — NOT a real product name.
_FAKE_MODEL_ID = "prov-model-zz9-20260101"
# Not a credential: sentinel free text the zero-text guarantee must strip.
_SECRET_TEXT = "secret journal free text that must never cross into the corpus"  # noqa: S105


def _write_journal_fixture(tmp_path):
    jdir = tmp_path / "wf_fixture-001"
    jdir.mkdir()
    journal = [
        {"type": "started", "agentId": "aga", "key": "recon"},
        {"type": "result", "agentId": "aga", "key": "recon",
         "result": {"conventions": ["c"], "key_files": ["a.py"], "hooks": [],
                    "summary": _SECRET_TEXT + " " + "x" * 200}},
        {"type": "started", "agentId": "agb", "key": "validate"},
        {"type": "result", "agentId": "agb", "key": "validate",
         "result": {"all_green": False, "results": [_SECRET_TEXT],
                    "fixups_applied": "free text despite the numeric-sounding name " + "y" * 300}},
    ]
    with (jdir / "journal.jsonl").open("w", encoding="utf-8") as fh:
        for obj in journal:
            fh.write(json.dumps(obj) + "\n")
    for aid, out_toks in (("aga", 100), ("agb", 250)):
        lines = [
            {"timestamp": "2026-08-09T01:00:00.000Z", "type": "user",
             "cwd": "/somewhere/private", "gitBranch": "private-branch-name",
             "message": {"role": "user", "content": _SECRET_TEXT}},
            {"timestamp": "2026-08-09T01:05:00.000Z", "type": "assistant",
             "message": {"role": "assistant", "model": _FAKE_MODEL_ID,
                         "usage": {"output_tokens": out_toks, "input_tokens": 5},
                         "content": [{"type": "tool_use", "name": "Read", "input": {}},
                                     {"type": "text", "text": _SECRET_TEXT}]}},
        ]
        with (jdir / f"agent-{aid}.jsonl").open("w", encoding="utf-8") as fh:
            for obj in lines:
                fh.write(json.dumps(obj) + "\n")
        (jdir / f"agent-{aid}.meta.json").write_text(
            json.dumps({"agentType": "workflow-subagent", "spawnDepth": 1}), encoding="utf-8")
    return jdir


def _walk_strings(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v, path)
    elif isinstance(obj, str):
        yield path, obj


# ---------------------------------------------------------------- (1) determinism

def test_battery_determinism_byte_identical(tmp_path):
    ultra = _empty_ultra(tmp_path)
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    _build(out_a, ultra, battery_n=50)
    _build(out_b, ultra, battery_n=50)
    assert (out_a / "corpus.jsonl").read_bytes() == (out_b / "corpus.jsonl").read_bytes()
    assert len(_load(out_a / "corpus.jsonl")) == 50


# ---------------------------------------------------------------- (2) keyword guarantee

def test_every_battery_goal_hits_a_keyword(tmp_path):
    records = _build(tmp_path / "out", _empty_ultra(tmp_path), battery_n=200)
    battery = [r for r in records if r["source"] == "synthetic_battery"]
    assert battery
    for rec in battery:
        goal = rec["features"]["goal_text"]
        assert max(bc._score_intent(goal, k) for k in bc.INTENT_KEYWORDS) > 0, goal


# ---------------------------------------------------------------- (3) schema

_REQUIRED_KEYS = {
    "schema_version", "record_id", "source", "provenance", "provenance_fields",
    "features", "label_tier", "label_agents_n", "reward", "latency_ms",
    "tokens_est", "status", "errorClass", "split_key", "split_bucket",
}
_FEATURE_KEYS = {
    "goal_text", "n_words", "n_chain_signals", "has_code_terms", "latency_ms",
    "tokens_est", "attempt", "layer", "phase", "n_tool_calls", "duration_s",
    "output_tokens",
}


def test_schema_all_records(tmp_path):
    ultra = _write_ultra_fixture(tmp_path)
    jdir = _write_journal_fixture(tmp_path)
    records = _build(tmp_path / "out", ultra, journal_dir=jdir, battery_n=40)
    assert records
    seen_ids = set()
    for rec in records:
        assert _REQUIRED_KEYS <= set(rec.keys())
        assert rec["schema_version"] == 1
        assert rec["record_id"] not in seen_ids
        seen_ids.add(rec["record_id"])
        assert rec["source"] in {"ultra_timeline", "workflow_journal", "synthetic_battery"}
        assert rec["provenance"] in {"measured", "simulated"}
        pf = rec["provenance_fields"]
        assert set(pf) == {"latency_ms", "tokens_est", "status", "label_tier"}
        assert all(pf[k] in {"measured", "simulated"} for k in ("latency_ms", "tokens_est", "status"))
        assert pf["label_tier"] in bc.LABEL_TIER_PROVENANCE
        assert _FEATURE_KEYS <= set(rec["features"].keys())
        assert rec["label_tier"] in bc.TIER_VOCAB
        assert isinstance(rec["label_agents_n"], int) and rec["label_agents_n"] >= 1
        assert -1.0 <= rec["reward"] <= 1.0
        assert 0 <= rec["split_bucket"] <= 9
        expect = int(hashlib.sha256(rec["split_key"].encode()).hexdigest(), 16) % 10
        assert rec["split_bucket"] == expect


# ---------------------------------------------------------------- (4) ultra mining

def test_ultra_fixture_split_key_and_provenance(tmp_path):
    ultra = _write_ultra_fixture(tmp_path)
    records = _build(tmp_path / "out", ultra, battery_n=5)
    ultra_recs = [r for r in records if r["source"] == "ultra_timeline"]
    assert len(ultra_recs) == 4  # 2 runs x 2 rows
    # Timestamp-suffix stripping groups re-runs into one split group.
    assert {r["split_key"] for r in ultra_recs} == {"agents-x-run-abc"}
    for rec in ultra_recs:
        assert rec["label_tier"] == "agentic_epic"
        assert rec["features"]["goal_text"] == "launch the loop end-to-end"
        # tokens are scripted constants -> record-level provenance simulated
        assert rec["provenance"] == "simulated"
    decide = [r for r in ultra_recs if r["latency_ms"] == 1]
    other = [r for r in ultra_recs if r["latency_ms"] != 1]
    assert len(decide) == 2 and len(other) == 2
    for rec in decide:
        assert rec["provenance_fields"]["latency_ms"] == "measured"
    for rec in other:
        assert rec["provenance_fields"]["latency_ms"] == "simulated"


# ---------------------------------------------------------------- (4b) harness runs: outcome labels + corrections

def _write_harness_run_fixture(tmp_path, run_id, *, escalate=False, timeline=True):
    """One harness-runner run dir (checkpoint version harness-run/*).

    Mirrors the runner store layout: perf_counter latencies, measured-0 tokens
    (no external model), both field spellings per timeline row. With
    escalate=True the run ends in the ladder's terminal escalate: a lone
    attempt-1 WRITE failure, recovery_action "escalate", never auto-retried.
    """
    ultra = tmp_path / "ultra-runs"
    run_dir = ultra / run_id
    run_dir.mkdir(parents=True)
    nodes = [
        {"nodeId": "plan.decompose", "status": "ok", "attempts": 1, "errorClass": None,
         "artifact_chars": 120, "recovery_action": None},
    ]
    rows = [
        {"nodeId": "plan.decompose", "agentId": "planner", "attempt": 1,
         "latency": 3.2, "latency_ms": 3.2, "tokens": 0, "tokens_est": 0,
         "status": "ok", "errorClass": None, "ts": "2026-08-09T00:00:00Z", "runId": run_id},
    ]
    if escalate:
        nodes.append({"nodeId": "exec.write", "status": "failed", "attempts": 1,
                      "errorClass": "TOOL_FAILURE", "artifact_chars": 0,
                      "recovery_action": "escalate"})
        rows.append({"nodeId": "exec.write", "agentId": "executor", "attempt": 1,
                     "latency": 5.0, "latency_ms": 5.0, "tokens": 0, "tokens_est": 0,
                     "status": "fail", "errorClass": "TOOL_FAILURE",
                     "ts": "2026-08-09T00:00:01Z", "runId": run_id})
    checkpoint = {
        "runId": run_id, "dag_version": 1, "nodes": nodes,
        "version": "harness-run/0.1",
        "provenance": {"driver": "dag", "executors": ["deterministic"],
                       "latency": "measured perf_counter",
                       "tokens": "measured 0 — deterministic executors, no external calls",
                       "goal": "send the invoice for latency budgets",
                       "tier": "action_operator", "intent": "complex_action",
                       "complexity": "medium"},
    }
    (run_dir / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    if timeline:
        with (run_dir / "timeline.jsonl").open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
    return ultra


def test_harness_escalated_run_gets_outcome_adjusted_label(tmp_path):
    run_id = "harness-run-20260809T000000000000Z"
    ultra = _write_harness_run_fixture(tmp_path, run_id, escalate=True)
    records = _build(tmp_path / "out", ultra, battery_n=5)
    recs = [r for r in records if r["source"] == "ultra_timeline"]
    assert len(recs) == 2
    for rec in recs:
        # ladder escalated -> executed tier measured-insufficient -> strongest tier
        assert rec["label_tier"] == "agentic_epic"
        assert rec["provenance_fields"]["label_tier"] == "measured-outcome"
        assert rec["provenance"] == "measured"
        assert rec["split_key"] == run_id
    fail_row = next(r for r in recs if r["status"] == "fail")
    assert fail_row["errorClass"] == "TOOL_FAILURE"
    assert fail_row["reward"] < 0


def test_harness_run_without_escalation_keeps_behavior_label(tmp_path):
    run_id = "harness-run-20260809T000001000000Z"
    ultra = _write_harness_run_fixture(tmp_path, run_id, escalate=False)
    records = _build(tmp_path / "out", ultra, battery_n=5)
    recs = [r for r in records if r["source"] == "ultra_timeline"]
    assert len(recs) == 1
    assert recs[0]["label_tier"] == "action_operator"  # executed routing, unchanged
    assert recs[0]["provenance_fields"]["label_tier"] == "measured-behavior"
    assert recs[0]["provenance"] == "measured"


def test_harness_run_missing_timeline_never_fails_mining(tmp_path):
    run_id = "harness-run-20260809T000002000000Z"
    ultra = _write_harness_run_fixture(tmp_path, run_id, escalate=True, timeline=False)
    records = _build(tmp_path / "out", ultra, battery_n=5)
    # No timeline -> no rows to mine; the build still succeeds.
    assert [r for r in records if r["source"] == "ultra_timeline"] == []
    assert len(records) == 5


def test_corrupt_timeline_does_not_invent_escalation(tmp_path):
    # The checkpoint's complete node summary says the failure was retried
    # ("patch", attempts 2), but the timeline lost its attempt-2 row to a torn
    # line — the lone attempt-1 failure left in the timeline must NOT be read
    # as a terminal escalate: the authoritative summary wins.
    run_id = "harness-run-20260809T000005000000Z"
    ultra = _write_harness_run_fixture(tmp_path, run_id, escalate=False)
    run_dir = ultra / run_id
    checkpoint = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
    checkpoint["nodes"].append({"nodeId": "exec.retry", "status": "failed", "attempts": 2,
                                "errorClass": "TOOL_FAILURE", "artifact_chars": 0,
                                "recovery_action": "patch"})
    (run_dir / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    with (run_dir / "timeline.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"nodeId": "exec.retry", "agentId": "executor", "attempt": 1,
                             "latency": 4.0, "latency_ms": 4.0, "tokens": 0, "tokens_est": 0,
                             "status": "fail", "errorClass": "TOOL_FAILURE",
                             "ts": "2026-08-09T00:00:02Z", "runId": run_id}) + "\n")
        fh.write('{"nodeId": "exec.retry", "attempt": 2, "status"')  # torn line
    records = _build(tmp_path / "out", ultra, battery_n=5)
    recs = [r for r in records if r["source"] == "ultra_timeline"]
    assert len(recs) == 2  # plan row + attempt-1 fail row; torn line dropped
    for rec in recs:
        assert rec["label_tier"] == "action_operator"
        assert rec["provenance_fields"]["label_tier"] == "measured-behavior"


def test_operator_correction_wins_over_outcome_adjustment(tmp_path):
    run_id = "harness-run-20260809T000003000000Z"
    ultra = _write_harness_run_fixture(tmp_path, run_id, escalate=True)
    corr = tmp_path / "label_corrections.jsonl"
    corr.write_text(json.dumps({
        "run_id": run_id, "tier": "deep_research",
        "reason": "run was a research probe, escalation was environmental",
        "corrected_by": "operator", "date": "2026-08-09",
    }) + "\n", encoding="utf-8")
    records = _build(tmp_path / "out", ultra, battery_n=5, corrections=corr)
    recs = [r for r in records if r["source"] == "ultra_timeline"]
    assert len(recs) == 2
    for rec in recs:
        assert rec["label_tier"] == "deep_research"
        assert rec["provenance_fields"]["label_tier"] == "operator-corrected"
    meta = json.loads((tmp_path / "out" / "corpus_meta.json").read_text(encoding="utf-8"))
    assert meta["label_corrections"]["n_corrections"] == 1
    assert meta["label_corrections"]["n_records_corrected"] == 2


def test_invalid_correction_tier_fails_loudly(tmp_path):
    run_id = "harness-run-20260809T000004000000Z"
    ultra = _write_harness_run_fixture(tmp_path, run_id, escalate=True)
    corr = tmp_path / "label_corrections.jsonl"
    corr.write_text(json.dumps({
        "run_id": run_id, "tier": "mega_epic", "reason": "typo",
        "corrected_by": "operator", "date": "2026-08-09",
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mega_epic"):
        bc.main(["build", "--out", str(tmp_path / "out"), "--ultra-dir", str(ultra),
                 "--battery-n", "5", "--corrections", str(corr)])


def test_meta_label_tier_counts(tmp_path):
    # Pick a run id that lands in the hold-out (bucket 8/9) so the escalated
    # run's rows count toward measured_holdout_by_label_tier.
    run_id = None
    for i in range(10000):
        cand = f"harness-run-fixture-{i:05d}"
        if bc.split_bucket(cand) >= 8:
            run_id = cand
            break
    assert run_id is not None
    ultra = _write_harness_run_fixture(tmp_path, run_id, escalate=True)
    records = _build(tmp_path / "out", ultra, battery_n=20)
    meta = json.loads((tmp_path / "out" / "corpus_meta.json").read_text(encoding="utf-8"))
    counts = meta["counts"]
    assert counts["by_label_tier"] == {"measured-outcome": 2, "simulated": 20}
    assert counts["measured_holdout_by_label_tier"] == {"measured-outcome": 2}
    assert sum(counts["by_label_tier"].values()) == counts["total"] == len(records)


# ---------------------------------------------------------------- (5) reward semantics

def test_reward_semantics():
    # failure dominates: 0.6 weight on S means speed can never buy it back
    assert bc.node_reward("failed", 1, 1.0, 1) < 0
    assert bc.agent_reward("failed", 1, 10.0, 10) < 0
    # ok, first attempt, fast and cheap
    assert bc.node_reward("ok", 1, 1.0, 2) > 0.5
    # 'blocked' is NOT a failure (matches harness timeline.py:28 set): S == 0
    assert bc.status_score("blocked", 1) == 0.0
    r_blocked = bc.node_reward("blocked", 1, 1.0, 2)
    assert 0.0 <= r_blocked < 0.5  # only the latency/token terms remain
    # attempt discount on ok
    assert bc.status_score("ok", 3) == pytest.approx(1.0 / 3.0)


# ---------------------------------------------------------------- (6) zero-text rule

def test_zero_text_enforcement(tmp_path):
    jdir = _write_journal_fixture(tmp_path)
    out = tmp_path / "out"
    records = _build(out, _empty_ultra(tmp_path), journal_dir=jdir, battery_n=5)
    wf = [r for r in records if r["source"] == "workflow_journal"]
    assert len(wf) == 2
    for rec in wf:
        assert rec["features"]["goal_text"] == ""
        for path, s in _walk_strings(rec):
            if path.endswith(".record_id") or path.endswith(".split_key"):
                continue
            assert len(s) <= 64, (path, s)
    # the one genuine measured negative: validate agent with all_green false
    validate = next(r for r in wf if r["features"]["phase"] == "validate")
    assert validate["status"] == "failed"
    assert validate["reward"] < 0
    assert validate["provenance"] == "measured"
    recon = next(r for r in wf if r["features"]["phase"] == "recon")
    assert recon["status"] == "ok"
    assert recon["features"]["n_tool_calls"] == 1
    assert recon["features"]["output_tokens"] == 100
    assert recon["features"]["duration_s"] == pytest.approx(300.0)
    # nothing from the journal's free text, paths, or model id may leak
    raw = (out / "corpus.jsonl").read_text(encoding="utf-8")
    assert _FAKE_MODEL_ID not in raw
    assert _SECRET_TEXT not in raw
    assert "private-branch-name" not in raw
    assert "/somewhere/private" not in raw


def test_journal_skipped_when_not_provided(tmp_path):
    out = tmp_path / "out"
    _build(out, _empty_ultra(tmp_path), battery_n=5)
    meta = json.loads((out / "corpus_meta.json").read_text(encoding="utf-8"))
    src = meta["sources"]["workflow_journal"]
    assert src["included"] is False
    assert src["reason"] == "journal dir not provided"


# ---------------------------------------------------------------- (7) stats

def test_stats_subcommand_prints_counts(tmp_path, capsys):
    out = tmp_path / "out"
    _build(out, _empty_ultra(tmp_path), battery_n=10)
    capsys.readouterr()
    assert bc.main(["stats", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "total: 10" in printed
    assert "by_provenance:" in printed
    assert "by_source:" in printed
    assert "by_tier:" in printed
    assert "by_split:" in printed


# ---------------------------------------------------------------- committed corpus

_COMMITTED = _AVA / "data" / "orchestration"


@pytest.mark.skipif(not (_COMMITTED / "corpus.jsonl").exists(),
                    reason="committed corpus not built yet")
def test_committed_corpus_matches_meta():
    records = _load(_COMMITTED / "corpus.jsonl")
    meta = json.loads((_COMMITTED / "corpus_meta.json").read_text(encoding="utf-8"))
    counts = meta["counts"]
    assert counts["total"] == len(records)
    by_source = {}
    for rec in records:
        by_source[rec["source"]] = by_source.get(rec["source"], 0) + 1
    assert counts["by_source"] == by_source
    assert meta["tier_vocab"] == bc.TIER_VOCAB
    for rec in records:
        assert rec["schema_version"] == 1
        assert rec["label_tier"] in bc.TIER_VOCAB
