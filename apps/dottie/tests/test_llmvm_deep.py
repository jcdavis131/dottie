# Solo personal project, no connection to employer, built with public/free-tier only
"""
Tests for Dottie llmvm deep integration v2 hardened + background orchestrator.
Zero_deps, stdlib only, runs with pytest or plain python.
"""

import json
import time
from pathlib import Path

def test_llmvm_import():
    from dottie.llmvm import LLMVMRuntime
    assert LLMVMRuntime is not None

def test_chunking():
    from dottie.llmvm import _chunk_text, _estimate_tokens
    text = " ".join([f"sentence {i} about Michael Jordan season {i%10} statistics." for i in range(200)])
    chunks = _chunk_text(text, chunk_tokens=64, overlap_tokens=8)
    assert len(chunks) > 1
    assert all(_estimate_tokens(c) <= 200 for c in chunks)

def test_keyword_rank():
    from dottie.llmvm import _chunk_text
    from dottie.llmvm import _estimate_tokens
    # simulate llmvm internal _keyword_rank via public llm_call path
    # we test direct helpers
    import dottie.llmvm as llmvm_mod
    # _keyword_rank is internal but accessible
    rank_fn = getattr(llmvm_mod, "_keyword_rank", None)
    if rank_fn:
        chunks = ["Michael Jordan stats", "random unrelated content about finance", "Jordan 1996 season"]
        ranked = rank_fn("Michael Jordan 1996", "extract Jordan season", chunks)
        assert len(ranked) == 3
        # top should be about Jordan
        assert "Jordan" in ranked[0][2]

def test_forge_discovery():
    from dottie.llmvm import list_forge_plugins
    plugins = list_forge_plugins()
    assert isinstance(plugins, list)
    # Expect at least forge + search etc
    names = [p["name"] for p in plugins]
    assert "forge" in names or len(names) >= 5

def test_llmvm_runtime_smoke():
    from dottie.llmvm import LLMVMRuntime
    def fake_pol(tr: str) -> str:
        return "<helpers>\nresult('smoke-42')\n</helpers>\nFINAL: smoke-42"
    rt = LLMVMRuntime(policy=fake_pol, mission=None)
    out = rt.run("test smoke", max_continuations=2)
    assert out["answers"] == ["smoke-42"] or "smoke-42" in str(out["final"])

def test_llm_call_chunking_path():
    from dottie.llmvm import LLMVMRuntime
    long_ctx = " ".join([f"player {i} stats season {i%5} player" for i in range(800)])
    def pol(tr: str) -> str:
        if "YES if you need ALL" in tr or ("YES" == tr.strip().upper()):
            return "NO"  # no need all → top-N path
        if "Top" in tr or "Context (top" in tr:
            return "answer from top chunks"
        return "top answer"
    rt = LLMVMRuntime(policy=pol, max_context_tokens=400, chunk_tokens=64)
    ans = rt.llm_call([long_ctx], "extract players", original_query="extract players")
    assert isinstance(ans, str)
    assert len(ans) > 0

def test_llm_call_map_reduce_path():
    from dottie.llmvm import LLMVMRuntime
    long_ctx = " ".join([f"doc {i} about all players aggregate" for i in range(500)])
    calls = []
    def pol(tr: str) -> str:
        calls.append(tr[:200])
        if "reduce" in tr.lower() or "combine into final" in tr.lower():
            return "FINAL aggregated answer"
        if "YES if you need ALL" in tr or "single word: YES" in tr:
            return "YES"
        if "Chunk" in tr and "process" in tr and "to process" in tr:
            return f"partial-{len(calls)}"
        return "partial"
    rt = LLMVMRuntime(policy=pol, max_context_tokens=300, chunk_tokens=50, enable_map_reduce=True)
    ans = rt.llm_call([long_ctx], "summarize all docs", original_query="need all docs summarize")
    assert "FINAL" in ans or "aggregat" in ans.lower()

def test_resume_helpers():
    from dottie.rlm import MissionLog
    from dottie.llmvm import resume_mission_log, latest_mission_state
    import tempfile, shutil
    base = Path("/tmp/test-llmvm-resume")
    base.mkdir(parents=True, exist_ok=True)
    mid = f"test-{int(time.time())}"
    m = MissionLog(mission_id=mid, base_dir=base)
    from dottie.rlm import MissionEvent
    m.append(MissionEvent(ts=time.time(), type="turn", agent_id="x", payload={"a":1}))
    mission, evs = resume_mission_log(mid, base_dir=base)
    assert len(evs) >= 1
    st = latest_mission_state(mid, base_dir=base)
    assert st["event_count"] >= 1

def test_background_orchestrator_scan():
    from dottie.background_orchestrator import scan_goals, BackgroundOrchestrator
    goals = scan_goals()
    assert isinstance(goals, list)

def test_background_orchestrator_run_one():
    from dottie.background_orchestrator import BackgroundOrchestrator
    from pathlib import Path
    # create tmp goal dir mimicking structure
    import tempfile, os
    tmp_root = Path("/tmp/test-goals-orch")
    tmp_root.mkdir(exist_ok=True)
    slug = f"test-goal-{int(time.time())}"
    gdir = tmp_root / slug
    gdir.mkdir(exist_ok=True)
    (gdir/"GOAL.md").write_text("# Test goal\nBuild test milestone 42", encoding="utf-8")
    missions = Path("/tmp/test-missions-orch")
    missions.mkdir(exist_ok=True)
    orch = BackgroundOrchestrator(goals_dir=tmp_root, missions_dir=missions, policy_backend="echo")
    goal = {"slug": slug, "dir": str(gdir), "goal_path": str(gdir/"GOAL.md"), "content": "# Test goal\nBuild test milestone 42", "title":"Test goal"}
    res = orch.run_one_goal(goal, max_continuations=1)
    assert res["slug"] == slug
    assert "mission_id" in res
    # check 7-field file exists
    mission_dir = Path(res["mission_dir"])
    tl = mission_dir / "timeline.jsonl"
    assert tl.exists()
    first = json.loads(tl.read_text().splitlines()[0])
    for field in ["nodeId","agentId","attempt","latency_ms","tokens_est","status","errorClass"]:
        assert field in first, f"missing {field}"

if __name__ == "__main__":
    # run manually without pytest
    tests = [o for o in globals().values() if callable(o) and o.__name__.startswith("test_")]
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            raise

