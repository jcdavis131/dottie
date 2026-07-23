# Solo personal project, no connection to employer, built with public/free-tier only
"""Offline-fixture tests for dottie.kg — no network, no real substrate touched.

Run ONLY this file (the wider suite is owned by other lanes right now):

    .venv\\Scripts\\python.exe -m pytest tests/test_kg.py -q
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dottie.kg import ingest, taxonomy
from dottie.kg.build import LIVE_LEDGER, build_graph, refuse_live_ledger
from dottie.kg.query import hint_efficacy
from dottie.kg.store import GraphStore

# ---------------------------------------------------------------------------
# fixtures (everything synthetic, everything offline)
# ---------------------------------------------------------------------------


@pytest.fixture()
def metrics_file(tmp_path: Path) -> Path:
    lines = [
        {"ts": 1.0, "event": "model_built", "preset": "nano", "params": 138},
        {"ts": 2.0, "event": "phase_enter", "preset": "nano", "phase": 0,
         "name": "p0_logic", "seq": 256},
        {"ts": 3.0, "event": "step", "step": 1, "lm": 9.0},
        {"ts": 4.0, "event": "step", "step": 2, "lm": 8.5},
        {"ts": 5.0, "event": "checkpoint", "step": 15},
        {"ts": 6.0, "event": "done", "step": 15},
    ]
    p = tmp_path / "metrics_test.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    return p


@pytest.fixture()
def ledger_file(tmp_path: Path) -> Path:
    p = tmp_path / "ledger_fixture.sqlite3"
    con = sqlite3.connect(str(p))
    con.execute(
        "CREATE TABLE experiments (id TEXT PRIMARY KEY, state TEXT NOT NULL,"
        " created_ts REAL NOT NULL, updated_ts REAL NOT NULL,"
        " hypothesis TEXT NOT NULL, implementation TEXT, workspace TEXT,"
        " train_metrics TEXT, eval_verdict TEXT, writeup TEXT, failure TEXT,"
        " attempts INTEGER NOT NULL DEFAULT 0)")
    con.execute(
        "CREATE TABLE baseline (singleton INTEGER PRIMARY KEY,"
        " metric_name TEXT NOT NULL, metric_value REAL NOT NULL,"
        " higher_is_better INTEGER NOT NULL, architecture TEXT NOT NULL,"
        " experiment_id TEXT, updated_ts REAL NOT NULL,"
        " notes TEXT NOT NULL DEFAULT '', metric_sem REAL, metric_sem_n INTEGER,"
        " per_seed TEXT)")
    con.execute(
        "INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("exp1", "failed_validation", 1.0, 2.0,
         json.dumps({"hypothesis_name": "E1", "search_domain": "attention"}),
         json.dumps({"module_name": "M1", "validation": {
             "ok": False, "level": "dry_run", "attempts": 5,
             "per_level": {"dry_run": {
                 "status": "fail",
                 "detail": "RuntimeError: einsum(): output subscript n bad"}},
             "history": [
                 {"attempt": 0, "ok": False, "level": "dry_run",
                  "status": "fail",
                  "detail": "RuntimeError: einsum(): output subscript n bad"},
                 {"attempt": 1, "ok": False, "level": "dry_run",
                  "status": "fail",
                  "detail": "RuntimeError: einsum(): still bad"}]}}),
         None, None, None, None,
         "validation failed at 'dry_run' after 5 self-correction attempt(s): "
         "...[head truncated]... tail without the class signature", 5))
    con.execute(
        "INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("exp2", "rejected", 1.0, 2.0,
         json.dumps({"hypothesis_name": "E2"}),
         json.dumps({"module_name": "M2",
                     "validation": {"ok": True, "attempts": 2, "history": [
                         {"attempt": 0, "ok": False, "level": "dry_run",
                          "status": "fail",
                          "detail": "RuntimeError: einsum(): wrong operands"},
                         {"attempt": 1, "ok": False, "level": "static",
                          "status": "fail",
                          "detail": "F821 Undefined name `attn`"},
                         {"attempt": 2, "ok": True, "level": "dry_run",
                          "status": "pass", "detail": "forward ok"}]}}),
         None, None,
         json.dumps({"promote": False, "metric": "proxy_loss",
                     "baseline_value": 1.0, "new_value": 1.2, "delta": 0.2}),
         None, None, 2))
    con.execute(
        "INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("exp3", "failed_training", 1.0, 2.0,
         json.dumps({"hypothesis_name": "E3"}), None, None, None, None, None,
         "candidate not integrable: The size of tensor a "
         "must match the size of tensor b", 0))
    con.execute(
        "INSERT INTO baseline VALUES (1,'proxy_loss',5.7,0,'nano',NULL,1.0,"
        "'fixture',0.1,3,NULL)")
    con.commit()
    con.close()
    return p


@pytest.fixture()
def live_status_file(tmp_path: Path) -> Path:
    doc = {
        "published_utc": "2026-07-23T00:00:00Z", "source": "local",
        "hostname": "testbox",
        "pipeline": {"preset": "mini", "mode": "train", "disk_free_gb": 5.0,
                     "trainer": {"metrics_path": "/reports/x.jsonl",
                                 "n_points": 6,
                                 "last": {"preset": "mini", "step": 50,
                                          "phase": 5, "lm_loss": 0.14,
                                          "tok_s": 4000},
                                 "series": {
                                     "step": [10, 20, 30, 40, 50, 50],
                                     "lm_loss": [0.5, 0.2, 0.15, 0.14, 0.14,
                                                 5.0]}}},
        "hub": {
            "sites": [{"name": "hub", "url": "https://example.invalid",
                       "http": 200, "ms": 100, "up": True}],
            "site_history": {"hub": [{"t": 1, "up": True, "ms": 100},
                                     {"t": 2, "up": True, "ms": 300}]},
            "fleet": {"containers": [
                {"Name": "dottie-factory-trainer-1", "CPUPerc": "98%",
                 "MemPerc": "13%"}]},
        },
        "recent_events": [
            {"event_type": "ok", "message": "trainer ok", "level": "ok"},
            {"event_type": "warn", "message": "trainer stale", "level": "warn"}],
        "research": {
            "baseline": {"metric_name": "factory_lm_loss",
                         "metric_value": 5.73733, "metric_sem": 0.099},
            "sota_history": [{"id": "exp2", "name": "E2 promoted", "metric": 5.6,
                              "metric_name": "factory_lm_loss",
                              "baseline_value": 5.7, "updated_ts": 3.0}]},
    }
    p = tmp_path / "live_status_fixture.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture()
def steer_file(tmp_path: Path) -> Path:
    lines = [
        {"id": "c1", "body": "fleet: restart dottie-factory-trainer-1", "ts": 1},
        {"id": "c2", "type": "ack", "ack_of": "c1",
         "body": "\U0001f916 ack c1: done", "status": "done", "ts": 2},
    ]
    p = tmp_path / "steer_audit_fixture.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines),
                 encoding="utf-8")
    return p


@pytest.fixture()
def incidents_fixture(tmp_path: Path) -> tuple[Path, Path]:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    (docs_root / "DOC.md").write_text(
        "# handoff\n"
        "the trainer fell over at step 42 because\n"
        "disk vanished under it; parked safely.\n", encoding="utf-8")
    seed = {
        "incidents": [
            {"key": "t1", "title": "trainer fell over", "class": "disk",
             "severity": "critical", "doc": "DOC.md",
             "anchor": "fell over at step 42 because disk vanished",
             "container": "dottie-factory-trainer-1", "phase": "p4_long",
             "checkpoint": "step_42", "resolution": "parked safely"},
            {"key": "t2", "title": "phantom", "class": "disk",
             "severity": "minor", "doc": "DOC.md",
             "anchor": "this text is nowhere in the doc"},
        ],
        "policies": [
            {"key": "pol1", "title": "hold on crash", "doc": "DOC.md",
             "anchor": "parked safely", "rule": "hold",
             "governs": ["phase:p9"]}],
    }
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    return seed_path, docs_root


@pytest.fixture()
def built(tmp_path: Path, metrics_file: Path, ledger_file: Path,
          live_status_file: Path, steer_file: Path,
          incidents_fixture: tuple[Path, Path]):
    seed_path, docs_root = incidents_fixture
    out = tmp_path / "graph.sqlite3"
    report = build_graph(out=out, ledger=ledger_file, metrics=[metrics_file],
                         live_status=live_status_file, steer=steer_file,
                         incidents_seed=seed_path, docs_root=docs_root)
    store = GraphStore(out, readonly=True)
    yield report, store
    store.close()


# ---------------------------------------------------------------------------
# taxonomy
# ---------------------------------------------------------------------------

def test_taxonomy_classify() -> None:
    assert taxonomy.primary_class("RuntimeError: einsum(): bad eq") == "einsum"
    assert taxonomy.primary_class(
        "The size of tensor a must match the size of tensor b") == "shape_algebra"
    assert taxonomy.primary_class("something entirely novel") == "unclassified"
    both = taxonomy.classify("einsum() and NameError: name 'x'")
    assert both == ["einsum", "name_error"]


def test_failing_level() -> None:
    assert taxonomy.failing_level(
        "validation failed at 'dry_run' after 5 attempts") == "dry_run"
    assert taxonomy.failing_level("candidate not integrable: boom") == "training"
    assert taxonomy.failing_level("???") == "unknown"


# ---------------------------------------------------------------------------
# safety guard
# ---------------------------------------------------------------------------

def test_refuse_live_ledger(tmp_path: Path) -> None:
    # The guard must fire on the live ledger PATH IDENTITY without opening it.
    with pytest.raises(ValueError, match="LIVE research ledger"):
        refuse_live_ledger(LIVE_LEDGER)
    # A copy elsewhere is fine (no exception).
    refuse_live_ledger(tmp_path / "ledger_copy.sqlite3")


# ---------------------------------------------------------------------------
# ingesters (via one full offline build)
# ---------------------------------------------------------------------------

def test_build_counts(built) -> None:
    report, store = built
    assert report["sources"]["ledger"]["experiments"] == 3
    assert report["sources"]["steer"] == {"directives": 1, "acks": 1}
    assert report["sources"]["incidents"]["incidents"] == 2
    assert report["sources"]["incidents"]["unverified"] == 1
    counts = store.counts()
    assert counts["nodes_by_type"]["experiment"] == 3
    assert counts["nodes_by_type"]["incident"] == 2
    assert counts["nodes_by_type"]["site"] == 1
    assert counts["nodes_by_type"]["container"] >= 1
    assert counts["total_edges"] > 20


def test_trainer_event_chain(built) -> None:
    _, store = built
    done = [n for n in store.nodes_by_type("event")
            if n["props"].get("event") == "done"]
    assert len(done) == 1
    chain = store.chain_back(done[0]["id"], limit=5)
    kinds = [n["props"].get("event") for n in chain]
    # nearest predecessor first: checkpoint, then phase_enter, then model_built
    assert kinds == ["checkpoint", "phase_enter", "model_built"]


def test_series_anomalies_mined(built) -> None:
    _, store = built
    kinds = {n["props"].get("kind") for n in store.nodes_by_type("event")
             if ":series_" in n["id"]}
    assert kinds == {"step_reemitted", "loss_spike"}


def test_ledger_classification_reads_per_level_detail(built) -> None:
    # exp1's failure column is head-truncated with NO einsum signature; the
    # signature lives only in implementation.validation.per_level. It must
    # still classify as einsum.
    _, store = built
    edges = store.edges_to("failure_class:einsum")
    srcs = {e["src"] for e in edges if e["type"] == "classified_as"}
    assert "experiment:exp1" in srcs


def test_resolved_by_correction_edge(built) -> None:
    _, store = built
    edges = store.edges_to("outcome:validation_resolved_class_unlogged")
    assert [e["src"] for e in edges] == ["experiment:exp2"]
    assert edges[0]["props"]["attempts"] == 2


def test_promotion_joins_ledger_experiment(built) -> None:
    # The live-status sota_history row for exp2 must land on the SAME node id
    # the ledger ingester created — the cross-source join is the point.
    _, store = built
    edges = store.edges_from("promotion:exp2")
    assert any(e["dst"] == "experiment:exp2" and e["type"] == "promoted"
               for e in edges)
    assert store.node("experiment:exp2")["props"]["state"] == "rejected"


def test_incident_anchor_verification(built) -> None:
    _, store = built
    ok = store.node("incident:t1")
    bad = store.node("incident:t2")
    assert ok["props"]["anchor_verified"] is True
    assert ok["source_ref"] == "DOC.md:L2"  # anchor starts on line 2
    assert bad["props"]["anchor_verified"] is False
    assert bad["source_ref"] == "DOC.md"    # cited to the doc, no line claim
    # linked context
    dsts = {e["dst"] for e in store.edges_from("incident:t1")}
    assert {"container:dottie-factory-trainer-1", "phase:p4_long",
            "checkpoint:step_42", "fix:t1"} <= dsts


def test_steer_ack_links_directive(built) -> None:
    _, store = built
    edges = store.edges_from("steer_ack:c2")
    assert any(e["dst"] == "steer_directive:c1" and e["type"] == "acks"
               for e in edges)


def test_steer_missing_is_honest(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "g.sqlite3")
    out = ingest.ingest_steer(store, tmp_path / "nope.jsonl")
    assert out == {"directives": 0, "acks": 0, "skipped_missing": 1}
    store.close()


def test_find_anchor_wraps_lines() -> None:
    text = "alpha beta\n  gamma   delta\nepsilon\n"
    found, line = ingest.find_anchor(text, "beta gamma delta")
    assert found and line == 1
    found2, _ = ingest.find_anchor(text, "beta epsilon")
    assert not found2


# ---------------------------------------------------------------------------
# query layer
# ---------------------------------------------------------------------------

def test_hint_efficacy_query(built) -> None:
    _, store = built
    out = hint_efficacy(store, "einsum")
    # exp1 and exp2 both HIT einsum during correction; only exp2 cleared it.
    assert out["n_encounters"] == 2
    assert out["n_cleared"] == 1
    assert out["cleared_by"] == ["experiment:exp2"]
    assert out["clearance_rate"] == 0.5
    assert out["n_died_matching"] == 1
    assert out["died"][0]["id"] == "experiment:exp1"
    assert "hint_id" in out["caveat"]  # the re-derivation gap is named
    assert hint_efficacy(store, "no_such_class")["error"]


def test_struggled_with_trajectories(built) -> None:
    _, store = built
    # exp1: einsum twice, never cleared (final ok False, no later other class)
    e1 = [e for e in store.edges_from("experiment:exp1")
          if e["type"] == "struggled_with"]
    assert len(e1) == 1
    assert e1[0]["dst"] == "failure_class:einsum"
    assert e1[0]["props"]["cleared"] is False
    assert e1[0]["props"]["attempt_indices"] == [0, 1]
    # exp2: einsum cleared (trajectory ends ok=True); F821 lands unclassified
    e2 = {e["dst"]: e["props"] for e in store.edges_from("experiment:exp2")
          if e["type"] == "struggled_with"}
    assert e2["failure_class:einsum"]["cleared"] is True
    assert e2["failure_class:unclassified"]["cleared"] is True


def test_refine_candidates(built) -> None:
    from dottie.kg.query import refine_candidates
    _, store = built
    cands = refine_candidates(store, min_count=1)
    # the F821 cluster from exp2's history must surface as a proposal candidate
    assert any("FN Undefined name" in c["signature"] or "F821" in c["signature"]
               for c in cands)
    for c in cands:
        assert c["confidence"] in ("HIGH", "MEDIUM", "LOW")
