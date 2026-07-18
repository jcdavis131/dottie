"""Server endpoint regressions — TestClient, no uvicorn boot.

Uses a mock ServeEngine by default so the suite runs without a nano checkpoint.
When ``runs/chat/ava_nano_chat.pt`` (or ``AVA_CKPT``) exists, an optional live
smoke can be enabled; otherwise we skip real-weight paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Generator

import pytest

pytest.importorskip("fastapi")

os.environ["AVA_SKIP_ENGINE_BOOT"] = "1"

from fastapi.testclient import TestClient

from server import InterveneReq, app
from ava import serve_engine as se


class _FakeEngine:
    """Minimal stand-in that asserts the contract shapes endpoints expect."""

    def stats(self) -> dict[str, Any]:
        return {
            "ckpt": "fake.pt",
            "params": 14_000_001,
            "vocab": 8192,
            "d_model": 256,
        }

    def generate(self, text: str, max_tokens: int = 64, temperature: float = 0.8,
                 task_type: str = "chat", **kwargs) -> dict[str, Any]:
        return {
            "text": f"out:{text[:16]}",
            "tokens": 3,
            "route_probs": [{"S1": 0.25, "S2": 0.25, "Critic": 0.25, "Planner": 0.25}],
            "latency_ms": 1.5,
        }

    def inspect(self, text: str) -> dict[str, Any]:
        return {
            "top_concepts": [{"concept": "spider", "p": 0.2}] * 8,
            "verbalizable_mass": 0.064,
            "broadcast_strength": 0.22,
            "per_space": {
                "system1": {"broadcast": 0.18, "hl_est": 8.0, "mass": 0.05},
                "system2": {"broadcast": 0.22, "hl_est": 60.0, "mass": 0.065},
                "critic": {"broadcast": 0.08, "hl_est": 30.0, "mass": 0.04},
                "planner": {"broadcast": 0.20, "hl_est": 50.0, "mass": 0.05},
            },
            "route_probs": [0.15, 0.55, 0.10, 0.20],
            "safety_scan": {
                "leverage": 0.04, "blackmail": 0.01, "threat": 0.0,
                "scandal": 0.0, "shutdown": 0.0, "fake": 0.0,
                "secretly": 0.0, "trick": 0.0, "unsafe": 0.0, "dangerous": 0.0,
                "total": 0.05,
            },
        }

    def intervene(self, text: str, from_concept: str, to_concept: str,
                  space: str = "system2", **kwargs) -> dict[str, Any]:
        return {
            "baseline_text": "8",
            "intervened_text": "6",
            "delta_logprob": 0.5,
            "space": space,
            "changed": True,
            "audit_logged": True,
        }

    def block_stream(self, text: str) -> Generator[dict[str, Any], None, None]:
        yield {
            "block": 0,
            "regime": "text",
            "hidden_norm": 1.0,
            "top_concept": "spider",
            "route_probs": None,
        }
        yield {
            "block": 2,
            "regime": "fusion",
            "hidden_norm": 1.2,
            "top_concept": "eight",
            "route_probs": {"S1": 0.2, "S2": 0.5, "Critic": 0.1, "Planner": 0.2},
        }


@pytest.fixture()
def client(monkeypatch):
    fake = _FakeEngine()
    monkeypatch.setattr("server.get_engine", lambda: fake)
    monkeypatch.setattr(se, "get_engine", lambda: fake)
    with TestClient(app) as c:
        yield c


def test_import_server_succeeds():
    """Regression: Optional was used without import → NameError at import time."""
    import server as srv
    assert hasattr(srv, "app")
    assert hasattr(srv, "InterveneReq")


def test_intervene_req_alias_from():
    """Pydantic v2 Field(alias='from') must populate from_."""
    req = InterveneReq(**{"from": "spider", "to": "ant"})
    assert req.from_ == "spider"
    assert req.from_concept == "spider"
    assert req.to_concept == "ant"
    # populate_by_name also accepts the Python field name
    req2 = InterveneReq(from_="soccer", to="rugby")
    assert req2.from_concept == "soccer"


def test_health_schema(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["ckpt"], str) and body["ckpt"]
    assert isinstance(body["params"], int) and body["params"] > 10_000_000
    assert body["vocab"] == 8192


def test_intervene_403_without_write_flag(client, monkeypatch):
    monkeypatch.delenv("ENABLE_JSPACE_WRITE", raising=False)
    r = client.post(
        "/jspace/intervene?mode=research",
        json={"from": "spider", "to": "ant", "text": "legs"},
    )
    assert r.status_code == 403
    assert "ENABLE_JSPACE_WRITE" in r.json()["detail"]


def test_intervene_403_without_research_mode(client, monkeypatch):
    monkeypatch.setenv("ENABLE_JSPACE_WRITE", "1")
    r = client.post(
        "/jspace/intervene?mode=audit",
        json={"from": "spider", "to": "ant"},
    )
    assert r.status_code == 403


def test_intervene_ok_with_gate(client, monkeypatch):
    monkeypatch.setenv("ENABLE_JSPACE_WRITE", "1")
    r = client.post(
        "/jspace/intervene?mode=research",
        json={"from": "spider", "to": "ant", "text": "webs"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] is True
    assert body["audit_logged"] is True
    assert body["baseline_text"] != body["intervened_text"]


def test_generate_empty_text_422(client):
    r = client.post("/generate", json={"text": ""})
    assert r.status_code == 422


def test_generate_ok(client):
    r = client.post("/generate", json={"text": "hello", "max_tokens": 8})
    assert r.status_code == 200
    body = r.json()
    assert "text" in body and body["text"]
    assert "tokens" in body and "route_probs" in body and "latency_ms" in body


def test_chat_empty_messages_422(client):
    r = client.post("/chat", json={"messages": []})
    assert r.status_code == 422


def test_chat_ok(client):
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    body = r.json()
    assert "content" in body and "tokens" in body and "latency_ms" in body
    # _FakeEngine.generate() echoes the formatted prompt back — confirms the
    # <|user|>/<|assistant|> convention actually reached ServeEngine.generate().
    assert "<|user|>hi<|assistant|>" in body["content"] or body["content"].startswith("out:")


def test_chat_truncates_at_next_turn(client, monkeypatch):
    """ServeEngine.generate() has no early-stop, so an undertrained checkpoint
    can ramble into a fabricated follow-up turn — /chat must cut that off."""

    class _RamblingEngine(_FakeEngine):
        def generate(self, text, max_tokens=64, temperature=0.8, task_type="chat", **kwargs):
            return {
                "text": "the answer is 4<|user|>and another question<|assistant|>ignored",
                "tokens": 12, "route_probs": [], "latency_ms": 1.0,
            }

    fake = _RamblingEngine()
    monkeypatch.setattr("server.get_engine", lambda: fake)
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "what is 2+2"}]})
    assert r.status_code == 200
    assert r.json()["content"] == "the answer is 4"


def test_inspect_ok(client):
    r = client.post("/jspace/inspect", json={"text": "spider webs"})
    assert r.status_code == 200
    body = r.json()
    assert 0 < body["verbalizable_mass"] < 1
    assert len(body["top_concepts"]) == 8


def test_eval_branch_serves_real_json(client):
    path = Path(__file__).resolve().parent.parent / "reports" / "branch_eval_results_real.json"
    if not path.is_file():
        pytest.skip("reports/branch_eval_results_real.json missing")
    r = client.get("/jspace/eval_branch")
    assert r.status_code == 200
    data = r.json()
    assert "base" in data or "meta" in data


def test_eval_report_markdown(client):
    path = Path(__file__).resolve().parent.parent / "reports" / "REPORT_REAL.md"
    if not path.is_file():
        pytest.skip("reports/REPORT_REAL.md missing")
    r = client.get("/jspace/eval_report")
    assert r.status_code == 200
    assert "report_markdown" in r.json()
    assert len(r.json()["report_markdown"]) > 10


def test_report_404_when_missing(client, tmp_path, monkeypatch):
    import server as srv
    monkeypatch.setattr(srv, "_REPORT_HTML", tmp_path / "missing.html")
    r = client.get("/report")
    assert r.status_code == 404
    assert "make_report" in r.json()["detail"]


def test_websocket_block_stream(client):
    with client.websocket_connect("/jspace/stream") as ws:
        ws.send_text("hello stream")
        msg = ws.receive_text()
        data = json.loads(msg)
        assert "block" in data and "regime" in data and "top_concept" in data


def test_resolve_ckpt_latest_pointer(tmp_path):
    """Trainer writes ckpt/latest as a text file with the target filename."""
    ckpt_dir = tmp_path / "ckpt"
    ckpt_dir.mkdir()
    target = ckpt_dir / "step_10.pt"
    target.write_bytes(b"not-a-real-pt")
    latest = ckpt_dir / "latest"
    latest.write_text("step_10.pt", encoding="utf-8")
    resolved = se.resolve_ckpt_path(latest)
    assert resolved == target

    with pytest.raises(FileNotFoundError):
        se.resolve_ckpt_path(ckpt_dir / "latest.tmp")


def test_hot_reload_skips_tmp_and_reloads_under_lock(tmp_path, monkeypatch):
    """Pointer change → reload under lock; never reads *.tmp."""
    torch = pytest.importorskip("torch")
    from ava.config import AvaConfig
    from ava.model import build_model

    ckpt_dir = tmp_path / "ckpt"
    ckpt_dir.mkdir()
    cfg = AvaConfig.load("nano")
    m = build_model(cfg, use_memory=False)
    p1 = ckpt_dir / "step_1.pt"
    p2 = ckpt_dir / "step_2.pt"
    torch.save({"model": m.state_dict()}, p1)
    # Mutate one weight so we can detect a reload.
    with torch.no_grad():
        m.embed.weight[0, 0] += 1.0
    torch.save({"model": m.state_dict()}, p2)

    tok = Path(__file__).resolve().parent.parent / "data" / "nano" / "tokenizer" / "ava_nano_bpe.json"
    if not tok.is_file():
        pytest.skip("tokenizer missing")

    latest = ckpt_dir / "latest"
    latest.write_text("step_1.pt", encoding="utf-8")

    eng = se.ServeEngine(
        ckpt_path=latest,
        tokenizer_path=tok,
        enable_hot_reload=False,
    )
    w0 = float(eng.model.embed.weight[0, 0].item())
    assert eng.ckpt.endswith("step_1.pt")

    # Atomic pointer update (mirrors train._point_latest_at).
    tmp = ckpt_dir / "latest.tmp"
    tmp.write_text("step_2.pt", encoding="utf-8")
    os.replace(tmp, latest)
    eng._maybe_reload()
    assert eng.ckpt.endswith("step_2.pt")
    w1 = float(eng.model.embed.weight[0, 0].item())
    assert w1 != pytest.approx(w0, abs=1e-6)
    eng.stop_hot_reload()
