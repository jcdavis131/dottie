"""The one router: route_goal, its backends, traces, stamps and the training loop.

The golden file ``fixtures/moma_route_goldens.json`` was generated from scout's
PRE-unification classifier (origin/main c79225d, bigbang/plugins/harness/cli.py)
before any code moved. route_goal must reproduce every field of it with the
default backends: unifying the router must not change a single decision.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from dottie_loop import backends, router, router_artifacts, router_training, traces
from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.jev import load_decision_io

FIXTURES = Path(__file__).parent / "fixtures"
GOLDENS = json.loads((FIXTURES / "moma_route_goldens.json").read_text(encoding="utf-8"))["cases"]
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTTIE_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("DOTTIE_ROUTER_STAMPS", str(tmp_path / "stamps"))
    monkeypatch.delenv("DOTTIE_OS_URL", raising=False)
    monkeypatch.delenv("DOTTIE_TRACE_TEXT", raising=False)
    monkeypatch.delenv("DOTTIE_TRACE_SOURCE", raising=False)


# --- one policy, identical decisions --------------------------------------------------------


@pytest.mark.parametrize("case", GOLDENS, ids=lambda c: c["goal"][:40] or "<empty>")
def test_route_goal_reproduces_pre_unification_decisions(case):
    d = router.route_goal(case["goal"], trace=False)
    for key in ("intent", "intent_scores", "complexity", "moma_tier", "moma_cap", "confidence", "routed_agents"):
        assert d[key] == case[key], (key, case["goal"])
    assert d["authority"] == "heuristic"
    assert d["heuristic_tier"] == case["moma_tier"]
    assert d["spec_tier"] == router.LEGACY_TIER[case["moma_tier"]]
    assert d["advisory"]["heuristic"]["authoritative"] is True
    assert d["advisory"]["system_one"]["enabled"] is False
    assert "confidence" not in d["advisory"]["system_one"]


def test_moma_route_is_the_heuristic_backend():
    for case in GOLDENS:
        assert backends.HeuristicBackend().answer(case["goal"])["tier"] == case["moma_tier"]


def test_hard_constraint_and_escalation_and_exclusion():
    d = router.route_goal("mcp:srv__echo", trace=False,
                          hard_constraint={"tier": "action_operator", "intent": "complex_action", "confidence": 1.0, "reason": "mcp"})
    assert (d["moma_tier"], d["intent"], d["confidence"]) == ("action_operator", "complex_action", 1.0)
    with pytest.raises(InvalidInputError):
        router.route_goal("hello", trace=False, insufficiency={"note": "felt weak"})
    up = router.route_goal("hello", trace=False, insufficiency={"recorded_at": "2026-09-23T00:00:00Z", "error_class": "verification_failed"})
    assert up["moma_tier"] == "deep_research" and up["escalated_from_insufficiency"] is True
    with pytest.raises(PolicyDeniedError):
        router.route_goal("compare stripe vs lemon", trace=False, policy_exclusions={"T2"})


class _Fixed:
    def __init__(self, name, tier, *, gate=False, sha="a" * 64):
        self.name, self.tier, self.gate, self.sha = name, tier, gate, sha

    def answer(self, goal):
        return {"backend": self.name, "enabled": True, "available": True, "tier": self.tier,
                "gate_passed": self.gate, "artifact_sha256": self.sha, "reason": "fixed test answer"}


def _stamp(tmp_path, sha):
    d = tmp_path / "stamps"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sha}.json").write_text(json.dumps({"artifact_sha256": sha, "reviewed": True, "gate_passed": True}), encoding="utf-8")


def test_learned_answer_is_advisory_until_gate_and_stamp(tmp_path):
    goal = "compare Stripe vs Lemon Squeezy Aug 2026"  # heuristic: deep_research (T2)
    ungated = router.route_goal(goal, trace=False, backends=[_Fixed("learned_mlp", "llm")])
    assert ungated["moma_tier"] == "deep_research" and ungated["authority"] == "heuristic"
    assert ungated["advisory"]["learned_mlp"]["authoritative"] is False
    gated_unstamped = router.route_goal(goal, trace=False, backends=[_Fixed("learned_mlp", "llm", gate=True)])
    assert gated_unstamped["moma_tier"] == "deep_research"
    assert gated_unstamped["advisory"]["learned_mlp"]["stamped"] is False
    _stamp(tmp_path, "a" * 64)
    taken = router.route_goal(goal, trace=False, backends=[_Fixed("learned_mlp", "llm", gate=True)])
    assert taken["moma_tier"] == "llm" and taken["authority"] == "learned_mlp"
    assert taken["advisory"]["heuristic"]["authoritative"] is False
    # an authoritative answer may only pick an equal-or-cheaper tier
    pricier = router.route_goal(goal, trace=False, backends=[_Fixed("system_one", "agentic_epic", gate=True)])
    assert pricier["moma_tier"] == "deep_research" and pricier["authority"] == "heuristic"


def test_malformed_stamp_is_no_stamp(tmp_path):
    d = tmp_path / "stamps"
    d.mkdir()
    (d / f"{'b' * 64}.json").write_text(json.dumps({"artifact_sha256": "b" * 64, "reviewed": False, "gate_passed": True}), encoding="utf-8")
    assert router_artifacts.read_stamp("b" * 64) is None
    assert router_artifacts.read_stamp("../etc/passwd") is None


# --- System One over /decide -------------------------------------------------------------------


def _serve(predictor=None, info=None):
    import importlib.util
    import sys

    jev = REPO / "apps" / "jev-v0"
    sys.path.insert(0, str(jev))
    spec = importlib.util.spec_from_file_location("serve_decide_under_test", jev / "serve_decide.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mode = "untrained" if predictor is None else "pointer-lora"
    srv = mod.DecideServer("127.0.0.1", 0, model="test", mode=mode, predictor=predictor, checkpoint_info=info or {})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_system_one_off_by_default_and_never_raises():
    off = backends.SystemOneBackend().answer("hello")
    assert off["enabled"] is False and off["available"] is False
    dead = backends.SystemOneBackend(url="http://127.0.0.1:9", timeout=0.3).answer("hello")
    assert dead["available"] is False and "unreachable" in dead["reason"]
    bad = backends.SystemOneBackend(url="file:///etc/passwd").answer("hello")
    assert bad["available"] is False


def test_system_one_untrained_is_no_signal():
    srv, url = _serve()
    try:
        ans = backends.SystemOneBackend(url=url).answer("compare Stripe vs Lemon Squeezy Aug 2026")
    finally:
        srv.shutdown()
    assert ans["available"] is True and ans["mode"] == "untrained"
    assert ans["signal"] is False and ans["tier"] is None
    assert ans["shape_concentration"]["tier"] == pytest.approx(0.2)
    assert "confidence" not in ans


class _Peaked:
    def probabilities(self, state, question):
        keys = load_decision_io().option_keys(question)
        return {k: (0.9 if i == 0 else 0.1 / (len(keys) - 1)) for i, k in enumerate(keys)}


def test_system_one_trained_answer_is_advisory_and_uses_shape_concentration():
    srv, url = _serve(_Peaked(), {"checkpoint_sha256": "c" * 64, "gate_passed": False})
    try:
        d = router.route_goal("compare Stripe vs Lemon Squeezy Aug 2026", trace=False,
                              backends=[backends.SystemOneBackend(url=url)])
    finally:
        srv.shutdown()
    s1 = d["advisory"]["system_one"]
    assert s1["signal"] is True and s1["tier"] == "deterministic" and s1["mode"] == "pointer-lora"
    assert s1["shape_concentration"]["tier"] == pytest.approx(0.9)
    assert s1["authoritative"] is False and d["moma_tier"] == "deep_research"


def test_decide_request_is_schema_valid():
    io = load_decision_io()
    body = backends.SystemOneBackend(url="http://127.0.0.1:1").request_body("ship it")
    req = io.validate_request(body)
    assert set(req["questions"]) == {"tier", "action", "safe", "severity"}
    assert "goal_text" not in req["state"]  # text leaves the process only on opt-in


# --- the MLP backend -----------------------------------------------------------------------------


def test_mlp_internal_matches_shared_module_on_the_real_weights():
    pytest.importorskip("numpy")
    weights = REPO / "apps" / "ava-factory" / "reports" / "orchestrator" / "champion_weights.json"
    infer = REPO / "apps" / "ava-factory" / "orchestrator_infer.py"
    if not weights.is_file() or not infer.is_file():
        pytest.skip("ava-factory artifacts absent in this checkout")
    goal = "build a data pipeline and test the api endpoints for the harness"
    shared = backends.LearnedMLPBackend(weights, infer).answer(goal)
    internal = backends.LearnedMLPBackend(weights, REPO / "nonexistent.py").answer(goal)
    assert shared["infer_impl"] == "shared_module" and internal["infer_impl"] == "internal"
    assert shared["tier"] == internal["tier"]
    for t, p in shared["tier_probs"].items():
        assert internal["tier_probs"][t] == pytest.approx(p, abs=1e-9)
    assert shared["gate_passed"] is False  # the recorded candidate never passed its gate
    d = router.route_goal(goal, trace=False, backends=[backends.LearnedMLPBackend(weights, infer)])
    assert d["advisory"]["learned_mlp"]["authoritative"] is False and d["authority"] == "heuristic"


def test_mlp_missing_weights_is_unavailable(tmp_path):
    ans = backends.LearnedMLPBackend(tmp_path / "absent.json").answer("hello")
    assert ans["available"] is False and "not found" in ans["reason"]


# --- traces ---------------------------------------------------------------------------------------


def test_traces_under_pytest_never_default_to_the_real_path(monkeypatch):
    monkeypatch.delenv("DOTTIE_TRACE_DIR", raising=False)
    assert traces.trace_dir() is None
    d = router.route_goal("hello")
    assert d["trace"] == {"trace_id": d["trace"]["trace_id"], "path": None}


def test_trace_route_and_outcome_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTTIE_TRACE_SOURCE", "production")  # a test can never claim production
    d = router.route_goal("heartbeat tick", surface="test.surface")
    traces.record_outcome(d["trace"]["trace_id"], {"ok": True, "n_nodes": 3}, surface="test.surface")
    rows, bad = traces.read_traces(sorted((tmp_path / "traces").glob("route-*.jsonl")))
    assert bad == 0 and [r["kind"] for r in rows] == ["route", "outcome"]
    assert all(r["source"] == "test" for r in rows)
    assert rows[0]["decision"]["tier"] == "deterministic"
    assert "goal_text" not in rows[0] and len(rows[0]["goal_sha256"]) == 64
    assert "heartbeat" not in json.dumps(rows[0]["features"])


# --- training loop: pack -> eval -> promote --------------------------------------------------


def _trace_rows(n_goals=10):
    out = []
    for i in range(n_goals):
        goal = f"goal number {i} " + ("compare sources" if i % 2 else "ship the loop")
        feats = backends.goal_features(goal)
        tier = "deep_research" if i % 2 else "llm"
        tid = f"rt_{i:04d}"
        failed = 1 if i % 4 != 3 else 0
        out.append({"schema": traces.TRACE_SCHEMA, "kind": "route", "trace_id": tid, "at": "2026-09-23T00:00:00Z",
                    "source": "production", "surface": "scout.harness.run", "goal_sha256": feats["goal_sha256"],
                    "features": feats, "backends": {}, "goal_text": goal,
                    "decision": {"tier": tier, "heuristic_tier": tier, "authority": "heuristic"}})
        out.append({"schema": traces.TRACE_SCHEMA, "kind": "outcome", "trace_id": tid, "at": "2026-09-23T00:00:01Z",
                    "source": "production", "surface": "scout.harness.run",
                    "outcome": {"run_id": f"run-{i}", "ok": True, "executor": "real", "n_nodes": 4, "ok_nodes": 4 - failed,
                                "failed_nodes": failed, "escalated": False, "recovery_actions": [], "truncated": False}})
    out.append({**out[0], "trace_id": "rt_test", "source": "test"})
    return out


def _write_traces(tmp_path, rows):
    p = tmp_path / "in" / "route-20260923.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_pack_writes_strict_records_refuses_test_rows_and_holds_out_whole_goals(tmp_path):
    src = _write_traces(tmp_path, _trace_rows())
    m = router_training.pack([src], tmp_path / "pack", seed=1)
    assert m["consent"]["champion"] is False and m["all_rows_production"] is True
    assert any("not production" in k for k in m["rejected"])
    assert m["rows"]["holdout_frac"] >= 0.20
    io = load_decision_io()
    for name in ("train.jsonl", "holdout.jsonl"):
        for line in (tmp_path / "pack" / name).read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            assert io.validate_record(rec) == rec  # strict: no extra keys survive
    integrity = router_training.verify_pack(tmp_path / "pack")
    assert integrity["manifest_ok"] and integrity["split_ok"] and integrity["non_production_rows"] == 0
    labels = m["labels"]
    assert labels["tier"] and set(labels["action"]) <= {"execute", "escalate", "halt", "other"}


def test_pack_refuses_when_only_test_rows(tmp_path):
    rows = [dict(r, source="test") for r in _trace_rows(4)]
    with pytest.raises(InvalidInputError):
        router_training.pack([_write_traces(tmp_path, rows)], tmp_path / "pack")


def test_observed_labels():
    base = {"decision": {"tier": "llm"}}
    ok = router_training.observed_labels({**base, "outcome": {"ok": True, "n_nodes": 3, "ok_nodes": 3, "failed_nodes": 0}}, {})
    assert ok[0]["tier"]["choice"] == "llm" and ok[0]["action"]["choice"] == "execute"
    bad = router_training.observed_labels({**base, "outcome": {"ok": True, "n_nodes": 4, "ok_nodes": 3, "failed_nodes": 1}}, {})
    assert bad[0]["tier"]["choice"] == "deep_research" and bad[0]["action"]["choice"] == "escalate"
    assert bad[0]["severity"]["score"] == 0.25
    fixed = router_training.observed_labels({**base, "outcome": {"run_id": "r1", "ok": True, "n_nodes": 3, "ok_nodes": 3, "failed_nodes": 0}}, {"r1": "deterministic"})
    assert fixed[0]["tier"]["choice"] == "deterministic" and "operator_correction" in fixed[1]
    assert router_training.observed_labels({**base, "outcome": {"ok": True, "n_nodes": 3, "truncated": True}}, {}) is None
    assert router_training.observed_labels({**base, "outcome": None}, {}) is None


def _eval(tmp_path, predict):
    src = _write_traces(tmp_path, _trace_rows(60))
    router_training.pack([src], tmp_path / "pack", seed=3)
    ck = tmp_path / "ckpt"
    ck.mkdir()
    (ck / "pointer.pt").write_bytes(b"not a real checkpoint; the eval reads predictions")
    items = router_training._tier_items(tmp_path / "pack")
    preds = {it["id"]: predict(it) for it in items}
    return ck, router_training.evaluate(tmp_path / "pack", ck, preds, predictions_source="test")


def test_eval_gate_fails_when_candidate_does_not_beat_heuristic(tmp_path):
    ck, s = _eval(tmp_path, lambda it: it["heuristic"])
    assert s["gate_passed"] is False and "task_win" in s["gates"]["failed"]
    assert s["promotion"]["outcome"] == "reject"
    router_training.write_eval_summary(ck, s)
    with pytest.raises(PolicyDeniedError):
        router_artifacts.write_stamp(ck, reviewed=True, reviewer="cam")


def test_eval_pass_then_promote_is_a_separate_human_step(tmp_path):
    ck, s = _eval(tmp_path, lambda it: it["label"])
    assert s["metrics"]["candidate_tier_accuracy"] == 1.0
    assert s["gate_passed"] is True and s["stamped"] is False
    assert s["promotion"]["outcome"] == "hold"  # canary + approval still pending
    router_training.write_eval_summary(ck, s)
    assert router_artifacts.read_stamp(s["artifact_sha256"]) is None  # eval never stamps
    with pytest.raises(PolicyDeniedError):
        router_artifacts.write_stamp(ck, reviewed=False, reviewer="cam")
    stamp = router_artifacts.write_stamp(ck, reviewed=True, reviewer="cam")
    assert router_artifacts.read_stamp(stamp["artifact_sha256"])["reviewer"] == "cam"
    (ck / "pointer.pt").write_bytes(b"retrained bytes")  # new bytes are not the reviewed bytes
    with pytest.raises(PolicyDeniedError):
        router_artifacts.write_stamp(ck, reviewed=True, reviewer="cam")


def test_artifact_identity_matches_jev_checkpoint_identity(tmp_path):
    (tmp_path / "lora").mkdir()
    (tmp_path / "lora" / "a.bin").write_bytes(b"x")
    (tmp_path / "pointer.pt").write_bytes(b"y")
    before = router_artifacts.artifact_identity(tmp_path)
    (tmp_path / "eval_summary.json").write_text("{}", encoding="utf-8")
    assert router_artifacts.artifact_identity(tmp_path) == before
    assert load_decision_io().checkpoint_identity(tmp_path) == before


def test_train_command_is_dry_run_by_default(tmp_path):
    cmd = router_training.train_command(tmp_path / "pack", tmp_path / "out", go=False)
    assert "--dry-run" in cmd and "--go" not in cmd
    assert cmd[1].endswith("train_pointer_lora.py")
