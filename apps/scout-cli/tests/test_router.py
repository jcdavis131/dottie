"""`scout route`, `scout router ...` and the harness wiring through dottie_loop.router.

conftest.py already points DOTTIE_TRACE_DIR / DOTTIE_ROUTER_STAMPS into the
throwaway HOME and tags traces source=test; each test here narrows them to its
own tmp dir so trace contents can be asserted exactly.

The golden file is the one dottie-loop's suite pins
(packages/dottie-loop/tests/fixtures/moma_route_goldens.json), generated from
this plugin's classifier BEFORE it moved into dottie_loop.backends. Checking a
sample of it through the real CLI proves the command surface did not drift
either.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GOLDENS = json.loads(
    (REPO / "packages" / "dottie-loop" / "tests" / "fixtures" / "moma_route_goldens.json").read_text(encoding="utf-8")
)["cases"]


@pytest.fixture(autouse=True)
def _router_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("DOTTIE_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("DOTTIE_ROUTER_STAMPS", str(tmp_path / "stamps"))


def _cli(*args: str, ok: bool = True) -> dict:
    r = subprocess.run([sys.executable, "-m", "bigbang.cli", "--json", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, env=dict(os.environ))
    if ok:
        assert r.returncode == 0, f"{args} exit {r.returncode}: {r.stderr[-800:]} {r.stdout[:800]}"
    return json.loads(r.stdout)


def _trace_rows(tmp_path: Path) -> list[dict]:
    rows = []
    for p in sorted((tmp_path / "traces").glob("route-*.jsonl")):
        rows += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


@pytest.mark.parametrize("case", [c for c in GOLDENS if c["goal"]][:6], ids=lambda c: c["goal"][:30])
def test_harness_route_matches_pre_unification_golden(case):
    d = _cli("harness", "route", case["goal"])
    for key in ("intent", "intent_scores", "complexity", "moma_tier", "moma_cap", "confidence", "routed_agents"):
        assert d[key] == case[key], key
    assert d["authority"] == "heuristic"
    assert d["advisory"]["heuristic"]["authoritative"] is True
    assert d["advisory"]["system_one"]["enabled"] is False


def test_scout_route_is_the_same_router(tmp_path):
    goal = "compare Stripe vs Lemon Squeezy Aug 2026"
    a = _cli("route", goal)
    b = _cli("harness", "route", goal)
    for key in ("intent", "moma_tier", "confidence", "routed_agents", "authority", "stickiness_guard", "spec_tier"):
        assert a[key] == b[key], key
    surfaces = [r["surface"] for r in _trace_rows(tmp_path)]
    assert surfaces == ["scout.route", "scout.harness.route"]


def test_harness_run_traces_route_and_outcome_tagged_test(tmp_path):
    d = _cli("harness", "run", "ship the harness end-to-end loop", "--runs-dir", str(tmp_path / "runs"))
    assert d["ok"] is True and d["tier"] == "agentic_epic" and d["authority"] == "heuristic"
    rows = _trace_rows(tmp_path)
    assert [r["kind"] for r in rows] == ["route", "outcome"]
    assert {r["source"] for r in rows} == {"test"}
    assert rows[0]["trace_id"] == rows[1]["trace_id"] == d["trace_id"]
    out = rows[1]["outcome"]
    assert out["run_id"] == d["runId"] and out["n_nodes"] == d["n_nodes"] and out["escalated"] is False
    assert "goal_text" not in rows[0]


def test_router_pack_refuses_test_traces(tmp_path):
    _cli("harness", "run", "heartbeat monitor tick", "--runs-dir", str(tmp_path / "runs"))
    _cli("harness", "run", "compare Stripe vs Lemon Squeezy", "--runs-dir", str(tmp_path / "runs"))
    d = _cli("router", "pack", "--out", str(tmp_path / "pack"), ok=False)
    assert d["ok"] is False and "not production" in d["error"]
    assert not (tmp_path / "pack").exists()


def _production_traces(tmp_path: Path, n: int = 80) -> Path:
    from dottie_loop.backends import goal_features

    rows = []
    for i in range(n):
        goal = f"real goal {i} " + ("compare sources" if i % 2 else "ship the loop")
        feats = goal_features(goal)
        tier = "deep_research" if i % 2 else "llm"
        failed = 1 if i % 4 != 3 else 0
        tid = f"rt_{i:04d}"
        rows.append({"schema": "dottie-router-trace-1", "kind": "route", "trace_id": tid, "source": "production",
                     "surface": "scout.harness.run", "goal_sha256": feats["goal_sha256"], "features": feats,
                     "goal_text": goal,  # the owner opted in (DOTTIE_TRACE_TEXT=1); features alone collide
                     "decision": {"tier": tier, "heuristic_tier": tier, "authority": "heuristic"}})
        rows.append({"schema": "dottie-router-trace-1", "kind": "outcome", "trace_id": tid, "source": "production",
                     "outcome": {"run_id": f"r{i}", "ok": True, "n_nodes": 4, "ok_nodes": 4 - failed,
                                 "failed_nodes": failed, "escalated": False}})
    p = tmp_path / "prod" / "route-20260923.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_router_pack_train_eval_promote(tmp_path):
    src = _production_traces(tmp_path)
    m = _cli("router", "pack", "--traces", str(src.parent), "--out", str(tmp_path / "pack"), "--seed", "3")["data"]
    assert m["consent"]["champion"] is False and m["rows"]["holdout_frac"] >= 0.2

    t = _cli("router", "train", "--pack", str(tmp_path / "pack"))["data"]
    assert t["go"] is False and "--dry-run" in t["command"]
    assert t["report"]["dry_run"] is True and t["report"]["torch_imported"] is False

    ck = tmp_path / "ckpt"
    ck.mkdir()
    (ck / "pointer.pt").write_bytes(b"placeholder bytes; this eval reads --predictions")
    hold = [json.loads(line) for line in (tmp_path / "pack" / "holdout.jsonl").read_text(encoding="utf-8").splitlines()]
    preds = tmp_path / "preds.jsonl"
    preds.write_text("\n".join(json.dumps({"id": r["id"], "tier": r["labels"]["tier"]["choice"]})
                               for r in hold if "tier" in r["labels"]) + "\n", encoding="utf-8")

    refused = _cli("router", "promote", str(ck), "--by", "cam", ok=False)
    assert refused["ok"] is False and "--i-have-reviewed" in refused["error"]

    # This candidate escalates most goals, so it spends several times the heuristic's
    # tier budget; the owner-tunable cost ratio is raised here on purpose (default 1.5).
    e = _cli("router", "eval", "--pack", str(tmp_path / "pack"), "--checkpoint", str(ck), "--predictions", str(preds),
             "--approved-cost-ratio", "10")["data"]
    assert e["gate_passed"] is True and e["promotion"]["outcome"] == "hold", e
    assert not (tmp_path / "stamps").exists()  # eval never stamps

    s = _cli("router", "promote", str(ck), "--i-have-reviewed", "--by", "cam")["data"]
    assert s["reviewed"] is True and (tmp_path / "stamps" / f"{s['artifact_sha256']}.json").is_file()
    assert _cli("router", "status")["data"]["stamps"] == [s["artifact_sha256"]]
