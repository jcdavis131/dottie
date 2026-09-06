"""Auth middleware: 401/200, ephemeral single-use, rate limits, headers, audit, fail-closed."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from jarvisd.app import build_app
from jarvisd.auth import RateLimiter, mint_token, verify_ephemeral
from jarvisd.config import Config, ConfigError, is_loopback
from jarvisd.state import State

from .conftest import BASE_URL

if TYPE_CHECKING:
    from pathlib import Path


def test_health_and_status_are_exempt(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    s = client.get("/")
    assert s.status_code == 200 and s.text.startswith("jarvisd ")


def test_missing_and_bad_bearer_401(client: TestClient) -> None:
    assert client.get("/api/claims").status_code == 401
    assert client.get("/api/claims", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/mcp", json={}).status_code == 401
    assert client.get("/sse").status_code == 401
    bad = client.get("/api/claims", headers={"Authorization": "Bearer nope"})
    assert bad.json() == {"ok": False, "error": "invalid bearer"}
    assert bad.headers["www-authenticate"] == "Bearer"


def test_static_bearer_200(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/api/claims", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"ok": True, "claims": []}


def test_ephemeral_token_single_use(client: TestClient, bearer: str) -> None:
    tok = mint_token(bearer)
    assert verify_ephemeral(bearer, tok)
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/claims", headers=h).status_code == 200
    reused = client.get("/api/claims", headers=h)
    assert reused.status_code == 401 and reused.json()["error"] == "single-use reused"


def test_ephemeral_token_expired_or_forged(client: TestClient, bearer: str) -> None:
    old = mint_token(bearer, ts=1_000_000)
    assert client.get("/api/claims", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    forged = mint_token("other-secret")
    assert client.get("/api/claims", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert not verify_ephemeral(bearer, "not:a:token:at:all")
    assert not verify_ephemeral(bearer, "abc")


def test_rate_limit_per_agent(tmp_path: Path, db_path: Path, bearer: str) -> None:
    cfg = Config(host="127.0.0.1", port=8790, db_path=db_path, bearer=bearer, rate_agent=2)
    state = State(db_path)
    with TestClient(build_app(cfg, state=state), base_url=BASE_URL) as c:
        h = {"Authorization": f"Bearer {bearer}", "X-Agent-Id": "chatty"}
        assert c.get("/api/claims", headers=h).status_code == 200
        assert c.get("/api/claims", headers=h).status_code == 200
        third = c.get("/api/claims", headers=h)
        assert third.status_code == 429 and third.json()["error"] == "rate limited"
        # another agent id is a separate bucket
        other = {"Authorization": f"Bearer {bearer}", "X-Agent-Id": "quiet"}
        assert c.get("/api/claims", headers=other).status_code == 200
    state.close()


def test_rate_limiter_windows() -> None:
    now = [0.0]
    rl = RateLimiter(clock=lambda: now[0])
    assert rl.check("k", 1) and not rl.check("k", 1)
    now[0] = 61.0
    assert rl.check("k", 1)


def test_audit_log_written_without_raw_key(client: TestClient, auth_headers: dict[str, str], config: Config) -> None:
    client.get("/api/claims", headers=auth_headers)
    lines = [json.loads(x) for x in config.audit_path.read_text().splitlines()]
    last = lines[-1]
    assert last["path"] == "/api/claims" and last["status"] == 200 and last["agent"] == "tester"
    assert last["key_last4"] == config.bearer[-4:]
    assert config.bearer not in config.audit_path.read_text()


def test_auth_disabled_on_loopback_without_bearer(db_path: Path) -> None:
    cfg = Config(host="127.0.0.1", port=8790, db_path=db_path, bearer=None)
    state = State(db_path)
    with TestClient(build_app(cfg, state=state), base_url=BASE_URL) as c:
        assert c.get("/api/claims").status_code == 200
        assert "AUTH DISABLED" in c.get("/").text
    state.close()


def test_fail_closed_public_bind_without_bearer(db_path: Path) -> None:
    cfg = Config(host="0.0.0.0", port=8790, db_path=db_path, bearer=None)  # noqa: S104
    with pytest.raises(ConfigError, match="JARVIS_BEARER"):
        cfg.validate()
    with pytest.raises(ConfigError):
        build_app(cfg)


def test_is_loopback() -> None:
    assert is_loopback("127.0.0.1") and is_loopback("localhost") and is_loopback("::1")
    assert is_loopback("127.0.0.5") and is_loopback("[::1]")
    assert not is_loopback("0.0.0.0") and not is_loopback("::") and not is_loopback("jarvis.example.com")  # noqa: S104


def test_config_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JARVIS_BEARER", "abc")
    monkeypatch.setenv("JARVIS_PORT", "9999")
    monkeypatch.setenv("JARVIS_DB", str(tmp_path / "x.db"))
    monkeypatch.setenv("JARVIS_PUBLIC_HOST", "jarvis.example.com")
    cfg = Config.from_env(host="0.0.0.0")  # noqa: S104
    assert cfg.port == 9999 and cfg.bearer == "abc" and cfg.db_path == tmp_path / "x.db"
    assert cfg.public_host == "jarvis.example.com" and cfg.audit_path == tmp_path / "audit.jsonl"
    cfg.validate()
    monkeypatch.setenv("JARVIS_PORT", "not-a-port")
    with pytest.raises(ConfigError):
        Config.from_env()
