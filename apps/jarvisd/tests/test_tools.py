"""Tool-level behaviour: harness.route tier, jarvis.ask fallback, status, CLI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvisd.auth import verify_ephemeral
from jarvisd.cli import main
from jarvisd.config import Config
from jarvisd.state import State
from jarvisd.tools import Jarvis, agent_from_context, transport_security


@pytest.fixture
def jarvis(config: Config, state: State) -> Jarvis:
    return Jarvis(config, state)


def test_harness_route_returns_tier(jarvis: Jarvis) -> None:
    pytest.importorskip("bigbang")
    out = jarvis.route("claude", "compare Stripe vs Lemon Squeezy Aug 2026 with 5-7 sources")
    assert out["ok"] is True
    assert out["tier"] in {"deterministic", "llm", "deep_research", "action_operator", "agentic_epic"}
    assert out["tier"] == "deep_research" and out["routed_agents"]
    assert jarvis.state.timeline(kind="route")[0]["payload"]["tier"] == "deep_research"
    assert jarvis.route("claude", "   ")["ok"] is False


def test_harness_run_records_timeline(jarvis: Jarvis) -> None:
    pytest.importorskip("bigbang")
    out = jarvis.run("claude", "heartbeat monitor tick", repo="dottie")
    assert out["ok"] is True and out["runId"].startswith("harness-run-")
    assert Path(out["runs_dir"]) == jarvis.config.runs_dir
    row = jarvis.state.timeline(repo="dottie", kind="run")[0]
    assert row["payload"]["run_id"] == out["runId"]
    assert row["payload"]["critic_score"] == out["critic_score"]
    # an mcp: goal without a namespace is refused before any write
    refused = jarvis.run("claude", "mcp: something")
    assert (refused["ok"] is False and "mcp_namespace" in refused["error"]) or "namespace" in refused["error"]


def test_jarvis_ask_without_key(jarvis: Jarvis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = jarvis.ask("claude", "what is open?", repo="dottie")
    assert out["ok"] is False and out["error"].startswith("brain unavailable")
    assert "ANTHROPIC_API_KEY" in out["error"]
    status = jarvis.status()["brain"]
    assert status["available"] is False
    assert status["provider"] == "anthropic" and status["model"] == "claude-opus-5"
    assert "ANTHROPIC_API_KEY" in status["reason"]


def test_optional_integrations_degrade(jarvis: Jarvis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if "acne" not in os.environ.get("JARVISD_TEST_HAVE", ""):
        res = jarvis.contacts_resolve("my designer")
        assert res["ok"] in (True, False)
        if not res["ok"]:
            assert res["error"] in {"acne not installed"} or res["error"].startswith("acne resolve failed")
    monkeypatch.chdir(tmp_path)
    missing = jarvis.graph_query("auth middleware")
    assert missing["ok"] is False and ("graph.json not found" in missing["error"] or "not installed" in missing["error"])
    pytest.importorskip("personal_graphify")
    g = tmp_path / "graph.json"
    g.write_text('{"nodes":[{"id":"auth.py","label":"auth middleware","type":"file"}],"edges":[]}')
    hit = jarvis.graph_query("auth middleware", graph_path=str(g))
    assert hit["ok"] is True and hit["results"]


def test_status_and_agent_resolution(jarvis: Jarvis) -> None:
    st = jarvis.status()
    assert st["version"] and st["counts"]["memories"] == 0 and st["auth"] == "bearer"
    assert agent_from_context(None) == "anon"
    assert agent_from_context(None, "  cursor ") == "cursor"


def test_transport_security_modes(tmp_path: Path) -> None:
    loop = Config(host="127.0.0.1", db_path=tmp_path / "a.db", bearer="x")
    assert transport_security(loop) is None
    public = Config(host="0.0.0.0", db_path=tmp_path / "a.db", bearer="x", public_host="jarvis.example.com")  # noqa: S104
    ts = transport_security(public)
    assert ts is not None and ts.enable_dns_rebinding_protection
    assert "jarvis.example.com" in ts.allowed_hosts and "0.0.0.0:8790" in ts.allowed_hosts
    bare = Config(host="0.0.0.0", db_path=tmp_path / "a.db", bearer="x")  # noqa: S104
    off = transport_security(bare)
    assert off is not None and not off.enable_dns_rebinding_protection
    assert any("DNS-rebinding" in n for n in bare.status_notes())


def test_cli_token_and_export(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db_path: Path) -> None:
    monkeypatch.setenv("JARVIS_BEARER", "cli-secret")
    assert main(["token"]) == 0
    tok = capsys.readouterr().out.strip()
    assert verify_ephemeral("cli-secret", tok)
    monkeypatch.delenv("JARVIS_BEARER")
    assert main(["token"]) == 2
    s = State(db_path)
    s.remember("cli", "global", "exported via cli")
    s.close()
    assert main(["export", "memories", "--db", str(db_path)]) == 0
    assert "exported via cli" in capsys.readouterr().out
    assert main(["export", "bogus", "--db", str(db_path)]) == 2


def test_cli_serve_fails_closed(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.delenv("JARVIS_BEARER", raising=False)
    assert main(["serve", "--host", "0.0.0.0", "--db", str(db_path)]) == 2  # noqa: S104
