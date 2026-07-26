# Solo personal project, no connection to employer, built with public/free-tier only
"""Backend dispatcher (Ollama vs KoboldCpp) + `scout ava infer` command.

The contract under test: chat_with_metrics dispatches to the right endpoint,
computes tokens/sec, and on ANY failure returns ok=False with content=None — it
never fabricates a completion. All network is faked; no live runner required."""

from __future__ import annotations

import time

import bigbang.core.llm as llm


class _FakeResp:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Routes a request to the first payload whose key is a substring of the URL."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list = []

    def _match(self, url: str) -> _FakeResp:
        for key, (status, payload) in self.routes.items():
            if key in url:
                return _FakeResp(status, payload)
        return _FakeResp(404, {})

    def get(self, url):
        self.calls.append(("GET", url))
        return self._match(url)

    def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        return self._match(url)

    def close(self):
        pass


def _patch(monkeypatch, routes) -> _FakeClient:
    client = _FakeClient(routes)
    monkeypatch.setattr(llm, "_httpx_client", lambda timeout=2.0: client)
    return client


def _pin_clock(monkeypatch, elapsed: float = 0.5) -> float:
    """Pin the interval clock so a rate assertion is arithmetic, not a race.

    A faked backend can return faster than the clock can resolve, so asserting
    `tok_per_s > 0` against the real clock silently depends on the call being slow
    enough to register (perf_counter reads 0.0 for a trivial interval often enough
    to matter). First read is t0, every later read is t0 + elapsed.
    """
    reads = {"n": 0}

    def clock() -> float:
        reads["n"] += 1
        return 0.0 if reads["n"] == 1 else elapsed

    monkeypatch.setattr(llm, "_clock", clock)
    return elapsed


def test_interval_clock_is_monotonic_not_wall_clock():
    """Pins the clock CHOICE, not just its effect.

    Reverting to time.time() would still leave `tok_per_s > 0` passing whenever a
    call happened to take a measurable moment, so the guard has to name the clock.
    """
    assert llm._clock is time.perf_counter
    assert llm._clock is not time.time


def test_koboldcpp_routes_to_openai_v1_and_computes_tps(monkeypatch):
    elapsed = _pin_clock(monkeypatch, 0.5)
    client = _patch(
        monkeypatch,
        {
            "/v1/models": (200, {"data": [{"id": "loaded.gguf"}]}),
            "/v1/chat/completions": (
                200,
                {
                    "choices": [{"message": {"content": "a merkle proof"}}],
                    "usage": {"completion_tokens": 12},
                },
            ),
        },
    )
    res = llm.chat_with_metrics("koboldcpp", "any", [{"role": "user", "content": "hi"}])
    assert res["ok"] is True
    assert res["content"] == "a merkle proof"
    assert res["completion_tokens"] == 12
    # exact, not just >0: 12 tokens over a pinned 0.5s is 24.0 t/s
    assert res["tok_per_s"] == round(12 / elapsed, 2) == 24.0
    assert res["elapsed_s"] == round(elapsed, 4)
    # it auto-detected via /v1/models, then hit the OpenAI chat endpoint
    assert any("/v1/models" in c[1] for c in client.calls)
    assert any(c[0] == "POST" and "/v1/chat/completions" in c[1] for c in client.calls)


def test_ollama_routes_to_api_chat_and_uses_server_timing(monkeypatch):
    client = _patch(
        monkeypatch,
        {
            "/api/tags": (200, {"models": [{"name": "qwen3:8b"}]}),
            "/api/chat": (
                200,
                {
                    "message": {"content": "yo"},
                    "eval_count": 20,
                    "eval_duration": 1_000_000_000,  # 1.0s in ns -> 20 tok/s server-side
                },
            ),
        },
    )
    res = llm.chat_with_metrics(
        "ollama", "qwen3:8b", [{"role": "user", "content": "hi"}]
    )
    assert res["ok"] is True and res["content"] == "yo"
    assert res["completion_tokens"] == 20
    assert res["server_tok_per_s"] == 20.0
    assert any(c[0] == "POST" and "/api/chat" in c[1] for c in client.calls)


def test_failure_never_fabricates_a_completion(monkeypatch):
    # server up for detection but the generation call 500s
    _patch(
        monkeypatch,
        {
            "/v1/models": (200, {"data": []}),
            "/v1/chat/completions": (500, {}),
        },
    )
    res = llm.chat_with_metrics(
        "koboldcpp",
        "x",
        [{"role": "user", "content": "hi"}],
        base="http://localhost:5001",
    )
    assert res["ok"] is False
    assert res["content"] is None
    assert res["error"]


def test_unreachable_backend_is_honest(monkeypatch):
    _patch(monkeypatch, {})  # nothing answers 200
    res = llm.chat_with_metrics("koboldcpp", "x", [{"role": "user", "content": "hi"}])
    assert res["ok"] is False and res["content"] is None
    assert "not reachable" in res["error"]


def test_unknown_backend_rejected(monkeypatch):
    _patch(monkeypatch, {})
    res = llm.chat_with_metrics(
        "banana", "x", [{"role": "user", "content": "hi"}], base="http://localhost:1"
    )
    assert res["ok"] is False and "unknown backend" in res["error"]


def test_context_shift_is_recorded_telemetry(monkeypatch):
    _patch(
        monkeypatch,
        {
            "/v1/chat/completions": (
                200,
                {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"completion_tokens": 3},
                },
            ),
        },
    )
    res = llm.chat_with_metrics(
        "koboldcpp",
        "x",
        [{"role": "user", "content": "hi"}],
        base="http://localhost:5001",
        context_shift=True,
    )
    assert res["ok"] is True and res["context_shift"] is True


def test_ava_infer_command_exits_nonzero_and_honest_on_backend_down(monkeypatch):
    from typer.testing import CliRunner

    from bigbang.core import output
    from bigbang.plugins.ava.cli import app

    # deterministic JSON capture + force the backend layer to see nothing reachable
    output.set_json_mode(True)
    monkeypatch.setattr(llm, "_httpx_client", lambda timeout=2.0: _FakeClient({}))
    try:
        res = CliRunner().invoke(app, ["infer", "hello", "--backend", "koboldcpp"])
    finally:
        output.set_json_mode(False)
    assert res.exit_code == 1
    assert '"ok": false' in res.stdout.lower() or '"ok":false' in res.stdout.lower()
