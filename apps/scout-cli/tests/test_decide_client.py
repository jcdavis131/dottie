"""`scout route` asks jarvisd `/api/decide` when it is up, and decides in-process when not.

conftest.py sets SCOUT_DECIDE_REMOTE=0 for the whole suite; these tests opt in
with their own JARVIS_URL, pointing at a daemon they start on a free loopback
port with a throwaway DB (never a developer's real jarvisd).
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from bigbang.core import decide_client
from bigbang.plugins.harness.cli import route_result

GOAL = "compare Stripe vs Lemon Squeezy Aug 2026"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def remote_on(monkeypatch, tmp_path):
    monkeypatch.setenv("SCOUT_DECIDE_REMOTE", "1")
    monkeypatch.setenv("DOTTIE_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("SCOUT_CHECKPOINT_BASE", str(tmp_path / "checkpoints"))


def test_unreachable_jarvisd_falls_back_in_process_fast(remote_on, monkeypatch):
    monkeypatch.setenv("JARVIS_URL", f"http://127.0.0.1:{_free_port()}")
    t0 = time.perf_counter()
    out = route_result(GOAL)
    assert time.perf_counter() - t0 < 2.0
    assert out["decided_by"] == "in-process" and "unreachable" in out["decided_by_note"]
    assert out["moma_tier"] == "deep_research" and out["decision"]["tier"] == "deep_research"


def test_remote_off_is_in_process(monkeypatch):
    monkeypatch.setenv("SCOUT_DECIDE_REMOTE", "0")
    assert decide_client.remote_decide(GOAL) is None and decide_client.last_error == "SCOUT_DECIDE_REMOTE=0"


def test_bad_url_is_in_process(remote_on, monkeypatch):
    monkeypatch.setenv("JARVIS_URL", "file:///etc/passwd")
    assert decide_client.remote_decide(GOAL) is None and "http" in decide_client.last_error


def test_reachable_jarvisd_decides(remote_on, monkeypatch, tmp_path):
    uvicorn = pytest.importorskip("uvicorn")
    app_mod = pytest.importorskip("jarvisd.app")
    from jarvisd.config import Config
    from jarvisd.state import State

    state = State(tmp_path / "jarvis.db")
    state.remember("owner", "global", "stripe payouts settle in two days", [])
    port = _free_port()
    bearer = "test-bearer-" + "x" * 8
    config = Config(host="127.0.0.1", port=port, db_path=tmp_path / "jarvis.db", bearer=bearer, workspace=tmp_path / "ws")
    server = uvicorn.Server(uvicorn.Config(app_mod.build_app(config, state=state), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    try:
        monkeypatch.setenv("JARVIS_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("JARVIS_BEARER", "wrong")
        assert route_result(GOAL)["decided_by"] == "in-process"  # 401 -> fall back, never fail
        assert "HTTP 401" in decide_client.last_error
        monkeypatch.setenv("JARVIS_BEARER", bearer)
        out = route_result(GOAL)
        assert out["decided_by"] == "jarvisd" and out["decided_by_note"] is None
        assert out["moma_tier"] == "deep_research" and out["authority"] == "heuristic"
        assert out["decision"]["context"]["sources"].get("jarvisd.memory") == 1
        rows = state.timeline(kind="decide")
        assert rows and rows[0]["agent"] == "scout"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        state.close()
