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

import build_orchestration_corpus as bc

# ---------------------------------------------------------------- helpers

def _build(out, ultra_dir, journal_dir=None, battery_n=5, seed=None):
    argv = ["build", "--out", str(out), "--ultra-dir", str(ultra_dir), "--battery-n", str(battery_n)]
    if journal_dir is not None:
        argv += ["--journal-dir", str(journal_dir)]
    if seed is not None:
        argv += ["--seed", str(seed)]
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
        assert all(v in {"measured", "simulated"} for v in pf.values())
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
