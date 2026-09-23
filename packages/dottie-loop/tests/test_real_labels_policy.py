"""The amended data policy: provenance tiers, verifiers, dedupe/decontamination,
the production-gated eval, the human spot-check, and the CPU MLP trainer.

Named after what each test pins, so a red test says which rule broke.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from dottie_loop import (
    backends,
    provenance,
    router_artifacts,
    router_training,
    traces,
    verifiers,
)
from dottie_loop.errors import InvalidInputError, PolicyDeniedError

BENCH = Path(provenance.__file__).parent / "benchmarks" / "router_bench_v1.jsonl"
BUILDER = Path(provenance.__file__).parents[1] / "scripts" / "build_router_bench.py"


# --- provenance ---------------------------------------------------------------------------


def test_normalised_goal_hash_folds_case_space_and_punctuation():
    a = provenance.goal_norm_sha256("Convert 5 miles to km.")
    assert a == provenance.goal_norm_sha256("  convert 5  MILES to km ")
    assert a != provenance.goal_norm_sha256("Convert 6 miles to km.")
    assert backends.goal_features("Convert 5 miles to km.")["goal_norm_sha256"] == a


def test_row_provenance_and_unknown_tiers():
    assert provenance.row_provenance({"source": "production"}) == "production"  # pre-provenance line
    assert provenance.row_provenance({"source": "test"}) == "test"
    assert provenance.row_provenance({"source": "production", "provenance": "teacher"}) == "teacher"
    assert provenance.TRAINABLE == {"production", "benchmark-verified"}
    assert provenance.WEIGHTS == {"production": 1.0, "benchmark-verified": 0.7}
    with pytest.raises(ValueError):
        provenance.check_tier("made-up")


def test_trace_lines_carry_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTTIE_TRACE_DIR", str(tmp_path))
    rec = traces.record_route({"moma_tier": "llm"}, surface="t", goal="g", features=backends.goal_features("g"),
                              provenance="benchmark-verified")
    traces.record_outcome(rec["trace_id"], {"ok": True}, surface="t", provenance="benchmark-verified")
    rows, bad = traces.read_traces(sorted(tmp_path.glob("route-*.jsonl")))
    assert bad == 0 and {r["provenance"] for r in rows} == {"benchmark-verified"}
    joined = traces.join_outcomes(rows)
    assert joined[0]["outcome_provenance"] == "benchmark-verified"
    with pytest.raises(ValueError):
        traces.record_route({}, surface="t", goal="g", features={}, provenance="vibes")


# --- verifiers ----------------------------------------------------------------------------


@pytest.mark.parametrize(("result", "spec", "want"), [
    ({"answer": "Mice."}, {"type": "exact", "expected": "mice"}, True),
    ({"answer": "mouses"}, {"type": "exact", "expected": "mice"}, False),
    ({"answer": "ff"}, {"type": "exact", "expected": "FF", "accept": ["ff"]}, True),
    ({"answer": "Ashish Vaswani [1]"}, {"type": "contains", "expected": "vaswani"}, True),
    ({"answer": "id 1706.03762v7"}, {"type": "regex", "pattern": r"\b1706\.03762(v\d+)?\b"}, True),
    ({"answer": "1706.0376"}, {"type": "regex", "pattern": r"\b1706\.03762\b"}, False),
    ({"answer": "about 8.0467 km"}, {"type": "numeric", "expected": 8.04672, "rel_tol": 1e-4}, True),
    ({"answer": "1,234"}, {"type": "numeric", "expected": 1234}, True),
    ({"answer": "9"}, {"type": "numeric", "expected": 8, "abs_tol": 0.5}, False),
    ({"answer": "no digits"}, {"type": "numeric", "expected": 1}, False),
    ({"answer": '```json\n{"a": 1, "b": "x"}\n```'},
     {"type": "json_schema", "schema": {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}}, True),
    ({"answer": '{"a": "1"}'},
     {"type": "json_schema", "schema": {"type": "object", "properties": {"a": {"type": "integer"}}}}, False),
    ({"answer": "[1, 2]"}, {"type": "json_schema", "schema": {"type": "array"}, "expected": [1, 2]}, True),
    ({"answer": "x", "meta": {"exit_code": 0}, "text": '{"ok": true}'},
     {"type": "exit_code", "expected_output": r'"ok":\s*true'}, True),
    ({"answer": "x", "meta": {"exit_code": 2}}, {"type": "exit_code"}, False),
])
def test_verifier_registry(result, spec, want):
    assert verifiers.verify(result, spec)["passed"] is want


def test_unknown_or_malformed_spec_fails_closed():
    assert verifiers.verify({"answer": "x"}, {"type": "vibes"})["passed"] is False
    assert verifiers.verify({"answer": "x"}, {"type": "exact"})["passed"] is False  # no expected
    assert verifiers.validate_spec({"type": "exact"}) == ["exact: missing 'expected'"]


def test_unit_tests_verifier_runs_isolated_with_timeout():
    spec = {"type": "unit_tests", "tests": "assert add(2, 3) == 5", "timeout_s": 5}
    assert verifiers.verify({"answer": "```python\ndef add(a, b):\n    return a + b\n```"}, spec)["passed"]
    assert not verifiers.verify({"answer": "def add(a, b):\n    return a - b"}, spec)["passed"]
    hang = verifiers.verify({"answer": "def add(a, b):\n    while True: pass"}, {**spec, "timeout_s": 1})
    assert hang["passed"] is False and "timed out" in hang["detail"]


def test_citations_verifier_needs_sources_citation_and_the_fact():
    src = [{"id": "1706.03762", "title": "Attention Is All You Need"}]
    spec = {"type": "citations", "min_sources": 1, "answer_check": {"type": "regex", "pattern": r"1706\.03762"}}
    assert verifiers.verify({"answer": "1706.03762 [1]", "sources": src}, spec)["passed"]
    assert not verifiers.verify({"answer": "1706.03762", "sources": []}, spec)["passed"]  # no source
    assert not verifiers.verify({"answer": "1512.03385 [1]", "sources": src}, spec)["passed"]  # wrong fact
    two = [*src, {"id": "1512.03385", "title": "Deep Residual Learning"}]
    assert not verifiers.verify({"answer": "it is 1706.03762", "sources": two}, {**spec, "min_sources": 2})["passed"]
    assert verifiers.verify({"answer": "1706.03762 [1], see also [2]", "sources": two}, {**spec, "min_sources": 2})["passed"]


# --- the committed benchmark --------------------------------------------------------------


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_router_bench", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_benchmark_is_deduped_valid_and_reproducible():
    rows = [json.loads(line) for line in BENCH.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert 150 <= len(rows) <= 300
    assert len({r["id"] for r in rows}) == len(rows)
    assert len({provenance.goal_norm_sha256(r["goal"]) for r in rows}) == len(rows)
    for r in rows:
        assert not verifiers.validate_spec(verifiers.verifier_for(r)), r["id"]
    assert {r["tier_hint"] for r in rows} == {"deterministic", "llm", "deep_research"}
    builder = _load_builder()
    assert "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in builder.build()) == \
        BENCH.read_text(encoding="utf-8")


def test_benchmark_is_not_contaminated_by_repo_eval_sets():
    builder = _load_builder()
    external = builder.eval_set_hashes()
    assert len(external) > 1000  # the scan found the eval sets; an empty scan would pass vacuously
    rows = [json.loads(line) for line in BENCH.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert not {provenance.goal_norm_sha256(r["goal"]) for r in rows} & external


def test_benchmark_code_references_pass_their_own_tests():
    rows = [json.loads(line) for line in BENCH.read_text(encoding="utf-8").splitlines() if line.strip()]
    code = [r for r in rows if r["task_type"] == "code"]
    assert len(code) >= 15
    for r in code:
        assert verifiers.verify({"answer": r["reference"]}, r["verifier"])["passed"], r["id"]


# --- pack: provenance, labels, dedupe, decontamination ------------------------------------


def _prod_rows(n_goals: int, prefix: str = "real goal") -> list[dict]:
    out = []
    for i in range(n_goals):
        goal = f"{prefix} {i} " + ("compare sources" if i % 2 else "ship the loop")
        feats = backends.goal_features(goal)
        tier = "deep_research" if i % 2 else "llm"
        tid = f"rt_p{prefix[:2]}{i:04d}"
        failed = 1 if i % 4 != 3 else 0
        out.append({"schema": traces.TRACE_SCHEMA, "kind": "route", "trace_id": tid, "source": "production",
                    "provenance": "production", "surface": "scout.harness.run", "goal_sha256": feats["goal_sha256"],
                    "features": feats, "goal_text": goal,
                    "decision": {"tier": tier, "heuristic_tier": tier, "authority": "heuristic"}})
        out.append({"schema": traces.TRACE_SCHEMA, "kind": "outcome", "trace_id": tid, "source": "production",
                    "provenance": "production",
                    "outcome": {"run_id": f"r{prefix[:2]}{i}", "ok": True, "executor": "real", "n_nodes": 4,
                                "ok_nodes": 4 - failed, "failed_nodes": failed, "escalated": False}})
    return out


def _bench_rows(goals: list[tuple[str, str, str]], *, prov: str = "benchmark-verified", status: str = "labeled",
                executor: str = "real", heuristic: str = "llm") -> list[dict]:
    """(bench id, goal text, minimal tier) -> probe route + outcome lines (no goal text: hashes only)."""
    out = []
    for bid, goal, tier in goals:
        feats = backends.goal_features(goal)
        tid = f"rt_b{bid}"
        out.append({"schema": traces.TRACE_SCHEMA, "kind": "route", "trace_id": tid, "source": "production",
                    "provenance": prov, "surface": "scout.router.probe", "goal_sha256": feats["goal_sha256"],
                    "features": feats, "decision": {"tier": heuristic, "heuristic_tier": heuristic, "authority": "heuristic"}})
        out.append({"schema": traces.TRACE_SCHEMA, "kind": "outcome", "trace_id": tid, "source": "production",
                    "provenance": prov,
                    "outcome": {"run_id": f"probe-{bid}", "ok": True, "executor": executor, "verified": status.startswith("labeled"),
                                "probe": {"status": status, "minimal_tier": tier if status.startswith("labeled") else None,
                                          "attempts": []},
                                "bench": {"id": bid}, "tokens": {"total": 0}, "n_nodes": 1, "ok_nodes": 1, "failed_nodes": 0}})
    return out


def _bench_goals(n: int, offset: int = 0) -> list[tuple[str, str, str]]:
    return [(f"b{i:03d}", f"benchmark question number {i} " + ("heartbeat" if i % 2 else "paper"),
             "deterministic" if i % 2 else "deep_research") for i in range(offset, offset + n)]


def _write(tmp_path: Path, rows: list[dict], name: str = "in") -> Path:
    p = tmp_path / name / "route-20260923.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def _bench_file(tmp_path: Path, goals: list[tuple[str, str, str]]) -> Path:
    p = tmp_path / "bench.jsonl"
    p.write_text("\n".join(json.dumps({"id": b, "goal": g, "task_type": "t"}) for b, g, _ in goals) + "\n",
                 encoding="utf-8")
    return p


def test_pack_trains_production_and_benchmark_with_weights_and_a_disjoint_benchmark_holdout(tmp_path):
    goals = _bench_goals(20)
    rows = _prod_rows(10) + _bench_rows(goals)
    m = router_training.pack([_write(tmp_path, rows)], tmp_path / "pack", seed=1, bench_files=[_bench_file(tmp_path, goals)])
    assert m["provenance"] == {"production": 10, "benchmark-verified": 20}
    assert m["weights"] == {"benchmark-verified": 0.7, "production": 1.0}
    assert m["rows"]["holdout"] > 0 and m["rows"]["holdout_benchmark"] > 0
    assert m["all_rows_production"] is False and m["consent"]["champion"] is False
    prov = [json.loads(line) for line in (tmp_path / "pack" / "provenance.jsonl").read_text().splitlines()]
    assert {p["split"] for p in prov if p["provenance"] == "production"} <= {"train", "holdout"}
    assert {p["split"] for p in prov if p["provenance"] == "benchmark-verified"} <= {"train", "holdout_benchmark"}
    assert all(p["bench_text"].startswith("benchmark question") for p in prov if p["provenance"] == "benchmark-verified")
    assert {p["label_source"] for p in prov if p["provenance"] == "benchmark-verified"} == \
        {"tier:probe_minimal_sufficient,action:completed"}
    integrity = router_training.verify_pack(tmp_path / "pack")
    assert integrity["split_ok"] and integrity["untrainable_rows"] == 0 and integrity["production_rows"] == 10
    router_training.refuse_synthetic_pack(tmp_path / "pack")  # real rows only: no raise


def test_pack_refuses_teacher_synthetic_outcome_real_and_unreal_executors(tmp_path):
    goals = _bench_goals(6)
    rows = (_bench_rows(goals[:2]) + _bench_rows([("t1", "teacher goal one", "llm")], prov="teacher")
            + _bench_rows([("s1", "synthetic goal one", "llm")], prov="synthetic")
            + _bench_rows([("o1", "recorded future one", "llm")], prov="outcome-real")
            + _bench_rows(goals[2:4], status="unavailable", executor="unavailable")
            + _bench_rows(goals[4:5], status="insufficient"))
    m = router_training.pack([_write(tmp_path, rows)], tmp_path / "pack", seed=1)
    rej = m["rejected"]
    for tier in ("teacher", "synthetic", "outcome-real"):
        assert rej[f"refused: provenance {tier} never trains a router"] == 1
    assert rej["refused: executor 'unavailable' is not real work"] == 2
    assert rej["no label: probe status insufficient"] == 1
    assert m["provenance"] == {"benchmark-verified": 2}


def test_upper_bound_labels_need_explicit_opt_in(tmp_path):
    goals = _bench_goals(8)
    rows = _bench_rows(goals[:4]) + _bench_rows(goals[4:], status="labeled_upper_bound")
    m = router_training.pack([_write(tmp_path, rows)], tmp_path / "p1", seed=1)
    assert m["provenance"] == {"benchmark-verified": 4} and any("upper bound" in k for k in m["rejected"])
    m2 = router_training.pack([_write(tmp_path, rows, "b")], tmp_path / "p2", seed=1, allow_upper_bound=True)
    assert m2["provenance"] == {"benchmark-verified": 8}
    assert "tier:probe_upper_bound,action:completed" in m2["labels"]["label_sources"]


def test_decontamination_against_holdouts_and_external_eval_sets(tmp_path):
    prod = _prod_rows(10)
    held = router_training.split_by_goal(
        {provenance.goal_norm_sha256(r["goal_text"]): 1 for r in prod if r["kind"] == "route"}, 1)
    held_text = next(r["goal_text"] for r in prod if r["kind"] == "route" and provenance.goal_norm_sha256(r["goal_text"]) in held)
    goals = _bench_goals(12)
    # the same goal as a production holdout goal, reworded only in case and punctuation
    clash = ("x1", held_text.upper() + "!", "deterministic")
    external_goal = goals[0][1]
    ext = tmp_path / "external.jsonl"
    ext.write_text(json.dumps({"prompt": external_goal.title()}) + "\n", encoding="utf-8")
    m = router_training.pack([_write(tmp_path, prod + _bench_rows([*goals, clash]))], tmp_path / "pack", seed=1,
                             eval_sets=[ext])
    assert m["rejected"].get("decontaminated: goal is in an eval holdout of another provenance") == 1
    prov = [json.loads(line) for line in (tmp_path / "pack" / "provenance.jsonl").read_text().splitlines()]
    train_keys = {p["norm_key"] for p in prov if p["split"] == "train"}
    assert provenance.goal_norm_sha256(external_goal) not in train_keys
    assert not train_keys & {p["norm_key"] for p in prov if p["split"] != "train"}


def test_normalised_duplicates_dedupe_and_contradictions_drop(tmp_path):
    rows = _bench_rows([("a", "What is 2 * 21?", "deterministic"), ("b", "what is 2 * 21", "deterministic"),
                        ("c", "Convert 5 miles to km.", "deterministic"), ("d", "convert 5 miles to km", "llm"),
                        ("e", "an unrelated benchmark goal", "llm"), ("f", "another unrelated goal", "deep_research")])
    m = router_training.pack([_write(tmp_path, rows)], tmp_path / "pack", seed=1)
    assert m["rejected"]["duplicate"] == 1 and m["rejected"]["conflicting labels"] == 2
    assert m["goals"]["total"] == 3


# --- the gate: refusal reasons ------------------------------------------------------------


def _ckpt(tmp_path: Path) -> Path:
    ck = tmp_path / "ckpt"
    ck.mkdir(exist_ok=True)
    (ck / "pointer.pt").write_bytes(b"placeholder; the eval reads predictions")
    return ck


def _eval(tmp_path: Path, predict, **kw):
    ck = _ckpt(tmp_path)
    items = router_training.eval_items(tmp_path / "pack")
    return router_training.evaluate(tmp_path / "pack", ck, {it["id"]: predict(it) for it in items},
                                    predictions_source="test", **kw)


def test_gate_refuses_a_benchmark_only_pack_with_named_reasons(tmp_path):
    router_training.pack([_write(tmp_path, _bench_rows(_bench_goals(30)))], tmp_path / "pack", seed=1)
    s = _eval(tmp_path, lambda it: it["label"])
    assert s["gate_passed"] is False
    assert any(r.startswith("too few production rows: 0 < 50") for r in s["refusals"])
    assert "production holdout is empty: nothing measures real use" in s["refusals"]
    assert s["metrics"]["benchmark"]["candidate_tier_accuracy"] == 1.0
    assert s["promotion"]["outcome"] == "block"


def test_gate_refuses_below_min_production_rows_even_for_a_perfect_candidate(tmp_path):
    router_training.pack([_write(tmp_path, _prod_rows(40))], tmp_path / "pack", seed=3)
    s = _eval(tmp_path, lambda it: it["label"])
    assert s["gate_passed"] is False and s["refusals"] == ["too few production rows: 40 < 50 "
                                                           "(benchmark rows can train candidates but cannot stand in for real use)"]
    assert _eval(tmp_path, lambda it: it["label"], min_production_rows=40)["gate_passed"] is True


def test_gate_refuses_a_benchmark_regression(tmp_path):
    goals = _bench_goals(30)
    router_training.pack([_write(tmp_path, _prod_rows(60) + _bench_rows(goals, heuristic="deterministic"))],
                         tmp_path / "pack", seed=3)
    # perfect on production, always wrong on the benchmark holdout where the heuristic is sometimes right
    s = _eval(tmp_path, lambda it: it["label"] if it["provenance"] == "production" else "agentic_epic")
    assert s["gate_passed"] is False
    assert any(r.startswith("regresses on the benchmark holdout") for r in s["refusals"])
    ok = _eval(tmp_path, lambda it: it["label"])
    assert ok["gate_passed"] is True and ok["refusals"] == []


def test_gate_refuses_when_the_candidate_does_not_beat_the_heuristic_on_production(tmp_path):
    router_training.pack([_write(tmp_path, _prod_rows(60))], tmp_path / "pack", seed=3)
    s = _eval(tmp_path, lambda it: it["heuristic"])
    assert s["gate_passed"] is False and any("production holdout gates failed" in r for r in s["refusals"])


# --- the human spot-check -----------------------------------------------------------------


def test_promote_requires_a_complete_spotcheck_on_the_same_bytes(tmp_path):
    router_training.pack([_write(tmp_path, _prod_rows(60))], tmp_path / "pack", seed=3)
    s = _eval(tmp_path, lambda it: it["label"])
    ck = tmp_path / "ckpt"
    router_training.write_eval_summary(ck, s)
    with pytest.raises(PolicyDeniedError, match="no spot-check"):
        router_artifacts.write_stamp(ck, reviewed=True, reviewer="cam")
    sheet = router_artifacts.spotcheck_sample(tmp_path / "pack", ck, n=10, seed=4)
    assert len(sheet["items"]) == 10 and all(it["mark"] is None for it in sheet["items"])
    assert router_artifacts.spotcheck_path(ck) == tmp_path / "ckpt.spotcheck.json"  # beside, not inside
    with pytest.raises(PolicyDeniedError, match="incomplete"):
        router_artifacts.write_stamp(ck, reviewed=True, reviewer="cam")
    with pytest.raises(InvalidInputError):
        router_artifacts.spotcheck_mark(ck, {"not-an-id": "ok"}, reviewer="cam")
    with pytest.raises(InvalidInputError):
        router_artifacts.spotcheck_mark(ck, {sheet["items"][0]["id"]: "meh"}, reviewer="cam")
    ids = [it["id"] for it in sheet["items"]]
    router_artifacts.spotcheck_mark(ck, {i: "bad" if n < 2 else "ok" for n, i in enumerate(ids)}, reviewer="cam")
    with pytest.raises(PolicyDeniedError, match="2/10 bad"):
        router_artifacts.write_stamp(ck, reviewed=True, reviewer="cam")
    router_artifacts.spotcheck_mark(ck, {ids[0]: "ok"}, reviewer="cam")  # 1/10 bad is within 10%
    stamp = router_artifacts.write_stamp(ck, reviewed=True, reviewer="cam")
    assert stamp["spotcheck"] == {"path": str(tmp_path / "ckpt.spotcheck.json"), "reviewer": "cam", "n": 10, "bad": 1}
    (ck / "pointer.pt").write_bytes(b"retrained")
    with pytest.raises(PolicyDeniedError, match="different artifact bytes"):
        router_artifacts.write_stamp(ck, reviewed=True, reviewer="cam")


# --- the CPU MLP trainer ------------------------------------------------------------------


def test_mlp_trains_on_cpu_from_a_pack_and_evaluates_through_the_frozen_contract(tmp_path):
    pytest.importorskip("numpy")
    from dottie_loop import mlp_infer, mlp_train

    goals = [(f"d{i}", f"heartbeat monitor tick number {i}", "deterministic") for i in range(15)] + \
            [(f"r{i}", f"survey the literature on topic {i} with sources", "deep_research") for i in range(15)]
    router_training.pack([_write(tmp_path, _bench_rows(goals))], tmp_path / "pack", seed=1,
                         bench_files=[_bench_file(tmp_path, goals)])
    out = tmp_path / "weights.json"
    rep = mlp_train.train_pack(tmp_path / "pack", out, epochs=150, seed=0, n_buckets=512)
    assert rep["rows"] > 10 and rep["skipped"]["no_text"] == 0
    assert rep["history"][-1]["train_accuracy"] == 1.0 and rep["history"][-1]["loss"] < rep["history"][0]["loss"]
    doc = json.loads(out.read_text())
    assert doc["schema_version"] == 1 and doc["gate_passed"] is False
    model = mlp_infer.load_weights(out)  # the router's own loader accepts it
    assert mlp_infer.predict(model, "heartbeat monitor tick number 99")["tier"] == "deterministic"
    assert router_training.is_mlp_weights(out)
    items = router_training.eval_items(tmp_path / "pack")
    preds = router_training.checkpoint_predictions(out, items)
    assert set(preds) == {it["id"] for it in items}
    s = router_training.evaluate(tmp_path / "pack", out, preds, predictions_source="checkpoint")
    assert s["gate_passed"] is False and s["metrics"]["benchmark"]["candidate_tier_accuracy"] == 1.0


def test_mlp_trainer_skips_rows_without_text(tmp_path):
    pytest.importorskip("numpy")
    from dottie_loop import mlp_train

    goals = _bench_goals(12)
    router_training.pack([_write(tmp_path, _bench_rows(goals))], tmp_path / "pack", seed=1)  # no bench file: no text
    rows, skipped = mlp_train.training_rows(tmp_path / "pack")
    assert rows == [] and skipped["no_text"] > 0
    with pytest.raises(InvalidInputError):
        mlp_train.train_pack(tmp_path / "pack", tmp_path / "w.json")
