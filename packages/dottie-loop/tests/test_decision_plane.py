"""The decision plane: context builder, run-history index, one state builder,
decide() + its cache, System One keep-alive/health cache, and the pack's
stub-executor exclusion and train/serve state parity."""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dottie_loop import backends, router, router_training, run_history, traces
from dottie_loop.context import (
    ContextBudget,
    ContextItem,
    ContextProvider,
    GraphifyProvider,
    JarvisStateProvider,
    RunHistoryProvider,
    build_context,
    context_summary,
    default_providers,
)
from dottie_loop.decide import DecisionCache, backend_config_key, decide
from dottie_loop.jev import load_decision_io

GOAL = "compare Stripe vs Lemon Squeezy Aug 2026 with 5-7 sources"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTTIE_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("DOTTIE_ROUTER_STAMPS", str(tmp_path / "stamps"))
    monkeypatch.setenv("SCOUT_CHECKPOINT_BASE", str(tmp_path / "checkpoints"))
    for var in ("DOTTIE_OS_URL", "DOTTIE_TRACE_TEXT", "DOTTIE_TRACE_SOURCE", "DOTTIE_CONTEXT_GRAPH"):
        monkeypatch.delenv(var, raising=False)
    backends.clear_caches()


class _Static:
    def __init__(self, name, items, delay=0.0, boom=False):
        self.name, self.items, self.delay, self.boom = name, items, delay, boom

    def fetch(self, goal, k):
        if self.delay:
            time.sleep(self.delay)
        if self.boom:
            raise RuntimeError("provider down")
        return list(self.items)


def _items(source, n, private=False, text="x"):
    return [ContextItem(source=source, id=f"{source}:{i}", score=1.0 - i / 100, text=f"{text} {i}", private=private) for i in range(n)]


# --- context builder ---------------------------------------------------------------------------


def test_providers_satisfy_the_protocol():
    assert isinstance(_Static("s", []), ContextProvider)
    assert isinstance(RunHistoryProvider(), ContextProvider)


def test_context_is_deterministic_and_order_independent():
    a = _Static("a", _items("a", 3))
    b = _Static("b", _items("b", 3))
    c1 = build_context(GOAL, [a, b])
    c2 = build_context(GOAL, [b, a])
    assert c1.digest == c2.digest and [i.id for i in c1.items] == [i.id for i in c2.items]
    assert len(c1.digest) == 64 and c1.providers["a"]["ok"] and "latency_ms" in c1.providers["b"]


def test_context_is_bounded():
    big = _Static("big", [ContextItem("big", f"i{i}", 0.5, text="y" * 5000) for i in range(50)])
    budget = ContextBudget(per_provider=40, max_items=7, max_text_chars=50, max_bytes=100_000)
    c = build_context(GOAL, [big], budget)
    assert len(c.items) == 7 and c.dropped == 33
    assert all(len(i.text) <= 50 for i in c.items)
    tight = build_context(GOAL, [big], ContextBudget(per_provider=40, max_items=40, max_bytes=600))
    assert tight.size_bytes <= 600 and len(json.dumps(tight.summary())) < 1200


def test_provider_failure_and_timeout_fail_soft():
    slow = _Static("slow", _items("slow", 2), delay=0.5)
    bad = _Static("bad", [], boom=True)
    good = _Static("good", _items("good", 1))
    c = build_context(GOAL, [slow, bad, good], ContextBudget(timeout_s=0.05))
    assert c.providers["slow"]["ok"] is False and "timeout" in c.providers["slow"]["error"]
    assert c.providers["bad"]["ok"] is False and "provider down" in c.providers["bad"]["error"]
    assert [i.id for i in c.items] == ["good:0"]


def test_private_text_leaves_only_on_opt_in(monkeypatch):
    c = build_context(GOAL, [_Static("m", _items("m", 1, private=True, text="my secret plan"))])
    assert "text" not in context_summary(c)["items"][0]
    assert "my secret plan" not in json.dumps(c.record())  # records never carry text
    monkeypatch.setenv("DOTTIE_TRACE_TEXT", "1")
    assert context_summary(c)["items"][0]["text"] == "my secret plan 0"
    assert context_summary({"digest": "d", "items": []}) == {"digest": "d", "items": []}  # stored summary passes through


class _FakeState:
    def __init__(self):
        self.recalled = []

    def recall(self, query, scope=None, limit=10):
        self.recalled.append(query)
        return [{"id": 7, "text": "stripe fees are 2.9% + 30c", "scope": "global"}]

    def goals(self, repo=None, status="open", limit=100):
        return [{"id": 1, "text": "compare payment providers", "repo": "dottie"}, {"id": 2, "text": "unrelated chore", "repo": "dottie"}]

    def claims(self, repo=None, include_released=False):
        return [{"id": 3, "agent": "cursor", "repo": "dottie", "area": "apps/jarvisd", "note": "wip"}]


def test_jarvis_state_provider_is_duck_typed_and_private():
    st = _FakeState()
    items = JarvisStateProvider(st, repo="dottie").fetch(GOAL, 5)
    kinds = {i.kind for i in items}
    assert kinds == {"memory", "open_goal", "active_claim"} and all(i.private for i in items)
    goal_items = [i for i in items if i.kind == "open_goal"]
    assert goal_items[0].id == "goal:1"  # the related goal ranks first
    assert "stripe" in st.recalled[0]


def test_graphify_off_unless_configured(tmp_path, monkeypatch):
    assert GraphifyProvider().enabled is False and GraphifyProvider().fetch(GOAL, 3) == []
    assert all(p.name != "graphify" for p in default_providers())
    monkeypatch.setenv("DOTTIE_CONTEXT_GRAPH", str(tmp_path / "absent.json"))
    assert GraphifyProvider().enabled is False


# --- run history -------------------------------------------------------------------------------


def _event(role, status="ok", tier="llm", attempt=1, latency=2.0):
    return json.dumps({"nodeId": "n", "agentId": role, "attempt": attempt, "latency": latency, "tokens": 0,
                       "status": status, "errorClass": "TOOL_FAILURE" if status == "fail" else "none", "tier": tier}) + "\n"


def test_history_index_is_incremental_and_matches_a_full_scan(tmp_path):
    base = tmp_path / "cp"
    (base / "r1").mkdir(parents=True)
    tl = base / "r1" / "timeline.jsonl"
    tl.write_text(_event("builder") + _event("builder", "fail"), encoding="utf-8")
    idx = run_history.HistoryIndex(base)
    s1 = idx.stats()
    assert s1["events"] == 2 and s1["per_role"]["builder"]["fail_rate"] == 0.5
    assert s1["per_run"]["r1"] == {"events": 2, "failures": 1}
    assert idx.stats() is s1  # nothing changed: the merged result is reused
    with tl.open("a", encoding="utf-8") as f:
        f.write(_event("critic", tier="deep_research", attempt=2))
        f.write('{"torn": ')  # writer mid-append
    s2 = idx.stats()
    assert s2["events"] == 3 and s2["per_tier"]["deep_research"]["recovery_rate"] == 1.0
    offset_before = idx._files["r1"]["offset"]
    with tl.open("a", encoding="utf-8") as f:
        f.write('"x"}\n')  # the torn line completes
    s3 = idx.stats()
    assert s3["events"] == 4 and idx._files["r1"]["offset"] > offset_before
    (base / "r2").mkdir()
    (base / "r2" / "timeline.jsonl").write_text(_event("planner", "fail", tier="llm"), encoding="utf-8")
    s4 = idx.stats()
    fresh = run_history.HistoryIndex(base).stats()
    assert s4 == fresh and s4["per_tier"]["llm"]["runs"] == 2 and s4["per_tier"]["llm"]["success_rate"] == 0.0
    tl.write_text(_event("builder"), encoding="utf-8")  # rewritten smaller: re-parsed
    os.utime(tl, (time.time() + 5, time.time() + 5))
    assert idx.stats()["per_run"]["r1"] == {"events": 1, "failures": 0}


def test_history_index_persists_for_cold_processes(tmp_path):
    base = tmp_path / "cp"
    (base / "r1").mkdir(parents=True)
    (base / "r1" / "timeline.jsonl").write_text(_event("builder"), encoding="utf-8")
    run_history.HistoryIndex(base, persist=True).stats()
    assert (base / run_history.INDEX_NAME).is_file()
    cold = run_history.HistoryIndex(base, persist=True)
    cold._load()
    assert "r1" in cold._files  # loaded, not re-parsed
    assert cold.stats()["events"] == 1
    (base / run_history.INDEX_NAME).write_text("{not json", encoding="utf-8")
    assert run_history.HistoryIndex(base, persist=True).stats()["events"] == 1  # a bad index is ignored


def test_run_history_provider_items(tmp_path):
    base = tmp_path / "cp"
    for r in range(3):
        (base / f"r{r}").mkdir(parents=True)
        (base / f"r{r}" / "timeline.jsonl").write_text(_event("executor", "fail" if r == 0 else "ok", tier="agentic_epic"), encoding="utf-8")
    items = RunHistoryProvider(base).fetch(GOAL, 5)
    tier = next(i for i in items if i.id == "tier:agentic_epic")
    assert tier.data["runs"] == 3 and tier.data["success_rate"] == pytest.approx(0.6667, abs=1e-4)
    assert not any(i.private for i in items)


# --- one state builder: serve == train ---------------------------------------------------------


def test_state_builder_is_backward_compatible():
    feats = backends.goal_features(GOAL)
    old_shape = {"goal_features": {k: feats[k] for k in ("n_words", "n_chars", "n_chain_signals", "has_code_terms", "complexity", "intent_scores", "mcp_prefix")}}
    assert backends.system_one_state(GOAL) == old_shape  # no context, no opt-in: the pre-context state
    assert backends.system_one_state(None, None, features=feats) == old_shape  # what the pack rebuilds for an old trace


def test_served_state_equals_packed_state(tmp_path, monkeypatch):
    """decide() -> trace -> pack rebuilds byte-identical state to the /decide request."""
    monkeypatch.setenv("DOTTIE_TRACE_SOURCE", "production")
    ctx_provider = _Static("m", _items("m", 2, private=True) + _items("h", 1))
    seen = []

    class _Capture:
        name = "system_one"

        def config_key(self):
            return "capture"

        def answer(self, goal, context=None):
            seen.append(backends.SystemOneBackend(url="http://127.0.0.1:1").request_body(goal, context)["state"])
            return {"backend": "system_one", "enabled": True, "available": False, "tier": None, "reason": "capture"}

    d = decide(GOAL, providers=[ctx_provider], backends=[_Capture()], cache=None)
    rows, _ = traces.read_traces(sorted((tmp_path / "traces").glob("route-*.jsonl")))
    route_row = rows[0]
    assert route_row["trace_id"] == d["trace"]["trace_id"] and route_row["context"]["digest"] == d["decision"]["context"]["digest"]
    rebuilt = backends.system_one_state(route_row.get("goal_text"), route_row.get("context"),
                                        features=route_row["features"], include_text=True)
    assert rebuilt == seen[0]
    assert backends.state_sha256(rebuilt) == route_row["state_sha256"]
    private = [i for i in route_row["context"]["items"] if i.get("private")]
    assert private and all("text" not in i for i in private)  # private texts stay out without the opt-in


def _pack_rows(executor, n_goals=6, with_state=False):
    out = []
    for i in range(n_goals):
        goal = f"goal {i} " + ("compare sources" if i % 2 else "ship the loop")
        feats = backends.goal_features(goal)
        tid = f"rt_{i:04d}"
        row = {"schema": traces.TRACE_SCHEMA, "kind": "route", "trace_id": tid, "at": "2026-09-23T00:00:00Z",
               "source": "production", "surface": "scout.harness.run", "goal_sha256": feats["goal_sha256"],
               "features": feats, "backends": {}, "decision": {"tier": "llm", "heuristic_tier": "llm", "authority": "heuristic"}}
        if with_state:
            row["context"] = {"digest": "d" * 64, "items": [{"source": "h", "id": "tier:llm", "kind": "tier_history", "score": 0.9}]}
            row["state_sha256"] = backends.state_sha256(backends.system_one_state(None, row["context"], features=feats, include_text=True))
        out.append(row)
        outcome = {"run_id": f"r{i}", "ok": True, "n_nodes": 3, "ok_nodes": 3, "failed_nodes": 0, "escalated": False,
                   "recovery_actions": [], "truncated": False}
        if executor is not None:
            outcome["executor"] = executor
        out.append({"schema": traces.TRACE_SCHEMA, "kind": "outcome", "trace_id": tid, "at": "2026-09-23T00:00:01Z",
                    "source": "production", "surface": "scout.harness.run", "outcome": outcome})
    return out


def _write(tmp_path, rows, name="in"):
    p = tmp_path / name / "route-20260923.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_pack_excludes_stub_and_untagged_executor_outcomes(tmp_path):
    from dottie_loop.errors import InvalidInputError

    with pytest.raises(InvalidInputError, match="stub executor"):
        router_training.pack([_write(tmp_path, _pack_rows("stub"), "a")], tmp_path / "pa")
    with pytest.raises(InvalidInputError, match="no executor tag"):
        router_training.pack([_write(tmp_path, _pack_rows(None), "b")], tmp_path / "pb")
    mixed = _pack_rows("real") + [dict(r, trace_id=r["trace_id"] + "s") for r in _pack_rows("stub", 3)]
    m = router_training.pack([_write(tmp_path, mixed, "c")], tmp_path / "pc", seed=2)
    assert m["executors"] == {"real": 6, "stub_excluded": 3, "untagged_excluded": 0}
    assert any("stub executor" in k for k in m["rejected"])


def test_pack_rebuilds_context_state_and_refuses_drift(tmp_path):
    rows = _pack_rows("real", with_state=True)
    m = router_training.pack([_write(tmp_path, rows, "ok")], tmp_path / "pok", seed=2)
    assert m["with_context"] == m["rows"]["total"] >= 2  # feature-identical goals dedupe
    rec = json.loads((tmp_path / "pok" / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["state"]["context"]["digest"] == "d" * 64
    assert load_decision_io().validate_record(rec) == rec
    drifted = [dict(r, state_sha256="0" * 64) if r["kind"] == "route" else r for r in rows]
    from dottie_loop.errors import InvalidInputError

    with pytest.raises(InvalidInputError, match="drift"):
        router_training.pack([_write(tmp_path, drifted, "bad")], tmp_path / "pbad")


# --- decide() ----------------------------------------------------------------------------------


def test_decide_keeps_the_heuristic_decision_and_records_latency():
    d = decide(GOAL, providers=[_Static("h", _items("h", 2))], backends=[], trace=False, cache=None)
    plain = router.route_goal(GOAL, backends=[], trace=False)
    assert d["moma_tier"] == plain["moma_tier"] == "deep_research" and d["authority"] == "heuristic"
    rec = d["decision"]
    assert set(rec["latency_ms"]) == {"context", "route", "backends", "total"}
    assert rec["context"]["n_items"] == 2 and rec["cache"]["hit"] is False
    assert "goal_text" not in rec and rec["goal_sha256"] == backends.goal_features(GOAL)["goal_sha256"]


def test_decide_cache_hits_and_keys_on_context():
    cache = DecisionCache(ttl_s=60)
    prov = _Static("h", _items("h", 1))
    a = decide(GOAL, providers=[prov], backends=[], trace=False, cache=cache)
    b = decide(GOAL, providers=[prov], backends=[], trace=False, cache=cache)
    assert a["decision"]["cache"]["hit"] is False and b["decision"]["cache"]["hit"] is True
    assert b["moma_tier"] == a["moma_tier"] and b["decision"]["decision_id"] != a["decision"]["decision_id"]
    prov.items = _items("h", 2)  # new knowledge -> new digest -> miss
    assert decide(GOAL, providers=[prov], backends=[], trace=False, cache=cache)["decision"]["cache"]["hit"] is False
    assert cache.stats()["hits"] == 1
    expired = DecisionCache(ttl_s=0.0)
    decide(GOAL, backends=[], trace=False, cache=expired)
    time.sleep(0.01)
    assert decide(GOAL, backends=[], trace=False, cache=expired)["decision"]["cache"]["hit"] is False


def test_backend_config_key_names_backends():
    assert backend_config_key([backends.SystemOneBackend(url="http://x:1")]) == "system_one:http://x:1"


def test_route_goal_passes_context_only_to_backends_that_take_it():
    got = {}

    class _Old:
        name = "learned_mlp"

        def answer(self, goal):
            return {"backend": "learned_mlp", "enabled": True, "available": False, "tier": None}

    class _New:
        name = "system_one"

        def answer(self, goal, context=None):
            got["context"] = context
            return {"backend": "system_one", "enabled": True, "available": False, "tier": None}

    ctx = build_context(GOAL, [_Static("h", _items("h", 1))])
    d = router.route_goal(GOAL, backends=[_Old(), _New()], trace=False, context=ctx)
    assert got["context"] is ctx and "latency_ms" in d["advisory"]["system_one"]


# --- System One: one request, cached health, keep-alive ----------------------------------------


class _Counting(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True
    log: list = []  # noqa: RUF012  test-local

    def log_message(self, *a):
        pass

    def _send(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        type(self).log.append(("GET", self.path, self.client_address[1]))
        self._send({"ok": True, "gate_passed": False, "checkpoint_sha256": "c" * 64})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n))
        type(self).log.append(("POST", self.path, self.client_address[1], sorted(body["questions"])))
        answers = {q: {"type": "choice", "choice": "llm", "probabilities": {}, "shape_concentration": 0.5} for q in body["questions"]}
        self._send({"schema": backends.SYSTEM_ONE_SCHEMA, "mode": "pointer-lora", "model": "t", "answers": answers})


def test_system_one_one_request_cached_health_and_keep_alive():
    _Counting.log = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Counting)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        for _ in range(4):
            ans = backends.SystemOneBackend(url=url).answer(GOAL)  # a new instance per route, as default_backends does
            assert ans["available"] is True and ans["artifact_sha256"] == "c" * 64
    finally:
        srv.shutdown()
        srv.server_close()
    gets = [e for e in _Counting.log if e[0] == "GET"]
    posts = [e for e in _Counting.log if e[0] == "POST"]
    assert len(gets) == 1 and len(posts) == 4  # health once, then one /decide per route
    assert all(p[3] == ["action", "safe", "severity", "tier"] for p in posts)  # all questions in one request
    assert len({e[2] for e in _Counting.log}) == 1  # one client port: the connection was kept alive


def test_system_one_state_carries_the_context_summary():
    ctx = build_context(GOAL, [_Static("h", _items("h", 1))])
    body = backends.SystemOneBackend(url="http://127.0.0.1:1").request_body(GOAL, ctx)
    assert body["state"]["context"]["digest"] == ctx.digest
    assert load_decision_io().validate_request(body)["state"]["context"]["items"][0]["id"] == "h:0"


def test_bench_percentile():
    from dottie_loop.bench_decide import percentile, summarize

    xs = [float(i) for i in range(1, 101)]
    assert percentile(xs, 50) == 50.0 and percentile(xs, 95) == 95.0
    assert summarize("x", [])["available"] is False
    assert Path(run_history.__file__).name == "run_history.py"
