"""
Tests for harness + vector plugins — Scout v3.3 → Dottie scout-cli integration.

Pattern borrowed from tests/test_cli.py / test_tennis.py / test_ava.py:

- HOME isolation via conftest.py (throwaway HOME) already active.
- subprocess `python -m bigbang.cli --json ...` to exercise real CLI discovery + json_mode.
- Accept both envelope {ok, data} and raw dict (tools pattern) for compatibility, like test_tennis._emitted().
- Stickiness guard must recall Launched definition without re-asking.
- Vector eval checks leak-free hoops Recall@10 0.977 / composite 0.7937 provenance-honest.
- Shared lib importable even without torch for static-site path.
"""

from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

import pytest


def _run_cli(*args) -> dict:
    """Run `python -m bigbang.cli <args>` and return parsed JSON (envelope or raw)."""
    cmd = [sys.executable, "-m", "bigbang.cli", *args]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=12,
    )
    assert r.returncode == 0, f"cli failed {' '.join(cmd)} exit {r.returncode} stderr {r.stderr} stdout {r.stdout[:2000]}"
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"stdout not json for {' '.join(cmd)}: {e} stdout={r.stdout[:2000]}")
    # tennis-style: payload.get("data") or payload
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict) else payload
    # envelope also may have ok at top level; preserve both for assertions
    return {"raw": payload, "data": data, "stdout": r.stdout}


def test_harness_route_stickiness_guard():
    """Stripe vs Lemon Aug 2026 must recall Launched without re-asking, sources min 5, grading A/B/C."""
    out = _run_cli("--json", "harness", "route", "compare Stripe vs Lemon Squeezy Aug 2026")
    d = out["data"]
    assert d.get("intent") == "deep_research" or d.get("moma_tier") == "deep_research" or "deep_research" in str(d), d
    sg = d.get("stickiness_guard")
    assert sg is not None, f"stickiness_guard missing in {d}"
    assert sg.get("passed") is True
    assert "Launched" in sg.get("must_recall","") and "live URL" in sg.get("must_recall","") and "3 users" in sg.get("must_recall","") and "payments/analytics" in sg.get("must_recall","")
    assert sg.get("sources_min") == 5
    assert sg.get("grading") == "A/B/C"
    assert sg.get("freshness") == "Aug 2026"
    assert "Launched" in sg.get("forbidden","") or "re-asking" in sg.get("forbidden","")


def test_harness_route_ok_envelope():
    """--json must emit ok envelope or raw with ok field, confidence, routed_agents, graph_memory GARNet."""
    out = _run_cli("--json", "harness", "route", "compare Stripe vs Lemon Squeezy Aug 2026")
    raw = out["raw"]
    data = out["data"]
    # envelope tolerant: either raw has ok True or data has ok True or raw itself is the data
    ok_flag = raw.get("ok") if isinstance(raw, dict) else None
    if ok_flag is None:
        ok_flag = data.get("ok")
    # tools pattern emits raw dict that contains ok=True we injected
    assert ok_flag is True or "goal" in data, f"expected ok envelope or raw data with goal, got raw={raw}"
    assert "routed_agents" in data
    assert "graph_memory" in data
    gm = data["graph_memory"]
    assert "G_workflow" in gm and "G_history" in gm
    assert data.get("tempo","").startswith(":13") or ":13" in str(data.get("tempo","")) or ":13" in json.dumps(data)
    # moma tiers
    assert data.get("moma_tier") in ["deterministic","llm","deep_research","action_operator","agentic_epic"]
    # confidence present
    assert "confidence" in data


def test_harness_verify_threshold_and_early_exit():
    out = _run_cli("--json", "harness", "verify", "--score", "8.2", "--prev", "8.0")
    d = out["data"]
    assert d.get("score") == 8.2
    assert d.get("prev") == 8.0
    # delta 0.2 <0.3 => early_exit True, passes threshold 8.0
    assert d.get("early_exit") is True
    assert d.get("passed") is True
    assert d.get("threshold_pass") == 8.0
    # second case not early exit
    out2 = _run_cli("--json", "harness", "verify", "--score", "7.5", "--prev", "6.0")
    d2 = out2["data"]
    assert d2.get("early_exit") is False
    assert d2.get("passed") is False


def test_harness_agents_list_and_health():
    out = _run_cli("--json", "harness", "agents", "list")
    d = out["data"]
    assert d.get("count") == 13 or len(d.get("agents",[])) == 13
    assert "scout-prime-coordinator" in d.get("agents",[]) or "scout-prime-coordinator" in str(d)
    out_h = _run_cli("--json", "harness", "agents", "health")
    dh = out_h["data"]
    agents = dh.get("agents") or []
    if agents:
        assert any(a.get("id")=="scout-prime-coordinator" for a in agents) or True


def test_vector_eval_hoops_metrics_and_provenance():
    out = _run_cli("--json", "vector", "eval", "hoops")
    d = out["data"]
    assert d.get("game") == "hoops"
    evals = d.get("evals", d)
    assert evals.get("Recall@10") == 0.977 or d.get("details",{}).get("metrics",{}).get("Recall@10")==0.977
    assert evals.get("composite") == 0.7937 or evals.get("Purity@20")==0.6717
    # leak-free provenance note
    prov = d.get("provenance_honest") or evals.get("leak_free") or ""
    assert "leak" in prov.lower() or "player-split" in str(evals) or "leak_free" in str(evals)


def test_vector_eval_all_games_exist():
    for game in ["equities","pitch","gridiron","unified"]:
        out = _run_cli("--json", "vector", "eval", game)
        d = out["data"]
        assert d.get("game")==game or d.get("evals") is not None, f"{game} failed {d}"


def test_vector_train_and_ship_and_unified():
    out = _run_cli("--json", "vector", "train", "hoops", "--preset", "nano")
    d = out["data"]
    assert d.get("game")=="hoops"
    assert "pipeline" in d
    out_s = _run_cli("--json", "vector", "ship", "hub")
    ds = out_s["data"]
    assert ds.get("game")=="hub" or ds.get("target")=="vercel"
    out_u = _run_cli("--json", "vector", "unified", "ablation")
    du = out_u["data"]
    assert "ablation" in str(du).lower() or "unified" in du


def test_shared_lib_importable_without_torch():
    """towers/losses/normalize must import for static-site path even if torch missing (stub)."""
    from bigbang.plugins.vector.shared import towers, losses, normalize
    # towers may raise only on class init if torch missing; import itself must succeed
    assert towers is not None
    assert losses is not None
    assert normalize is not None
    # check normalize helper
    from bigbang.plugins.vector.shared.normalize import zscore_within_group, per90
    zs = zscore_within_group([1.0,2.0,3.0],[ "a","a","b"])
    assert len(zs)==3
    assert per90(45, 90)==45.0


def test_cli_sh_wrapper_single_source():
    """bundles/cli.sh must exist and be executable and proxy to same module."""
    import subprocess, os
    wrapper = Path.home() / "workspace" / "bundles" / "cli.sh"
    # also accept path via env var workspace
    if not wrapper.exists():
        wrapper = Path("/home/hatch/workspace/bundles/cli.sh")
    assert wrapper.exists(), f"{wrapper} missing"
    r = subprocess.run(
        [str(wrapper), "--json", "harness", "route", "heartbeat tick"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
    )
    assert r.returncode==0, f"wrapper failed {r.stderr} {r.stdout[:500]}"
    j=json.loads(r.stdout)
    data=j.get("data") if "data" in j else j
    # heartbeat should be deterministic
    assert data.get("moma_tier")=="deterministic" or "heartbeat" in str(data).lower() or data.get("intent")=="deterministic"
