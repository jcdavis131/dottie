# Solo personal project, no connection to employer, built with public/free-tier only
"""Backend dispatcher (Ollama vs KoboldCpp) + `scout ava infer` command.

The contract under test: chat_with_metrics dispatches to the right endpoint,
computes tokens/sec, and on ANY failure returns ok=False with content=None — it
never fabricates a completion. All network is faked; no live runner required."""
from __future__ import annotations

import time

import pytest

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
    client = _patch(monkeypatch, {
        "/v1/models": (200, {"data": [{"id": "loaded.gguf"}]}),
        "/v1/chat/completions": (200, {
            "choices": [{"message": {"content": "a merkle proof"}}],
            "usage": {"completion_tokens": 12},
        }),
    })
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


def test_resolve_num_predict_env_and_arg_precedence(monkeypatch):
    """Mirrors apps/dottie's test_policy.py::test_ollama_num_predict_env_and_arg
    (PR #66) — DOTTIE_OLLAMA_NUM_PREDICT is the SAME env var, shared across apps."""
    monkeypatch.delenv("DOTTIE_OLLAMA_NUM_PREDICT", raising=False)
    assert llm.resolve_num_predict() == llm.DEFAULT_OLLAMA_NUM_PREDICT == 2048
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", "512")
    assert llm.resolve_num_predict() == 512
    assert llm.resolve_num_predict(64) == 64  # explicit argument beats the env
    for off in ("0", "-1"):
        monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", off)
        assert llm.resolve_num_predict() is None  # 0/negative from the env = no cap
    assert llm.resolve_num_predict(0) is None  # 0/negative from the arg = no cap
    assert llm.resolve_num_predict(-5) is None
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", "  ")
    assert llm.resolve_num_predict() == 2048  # blank is unset, not zero
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", "lots")
    with pytest.raises(ValueError, match="DOTTIE_OLLAMA_NUM_PREDICT"):
        llm.resolve_num_predict()


def test_ollama_chat_with_metrics_sends_the_default_cap(monkeypatch):
    """Before this, the ollama branch ignored max_tokens and sent no options at
    all — the exact bug apps/dottie's OllamaPolicy fixed for its own callers."""
    monkeypatch.delenv("DOTTIE_OLLAMA_NUM_PREDICT", raising=False)
    client = _patch(monkeypatch, {
        "/api/chat": (200, {"message": {"content": "hi"}, "eval_count": 1}),
    })
    res = llm.chat_with_metrics("ollama", "qwen3:8b", [{"role": "user", "content": "hi"}],
                                base="http://ollama.test:11434")
    assert res["ok"] is True
    posts = [c for c in client.calls if c[0] == "POST"]
    assert posts[0][2]["options"]["num_predict"] == 2048


def test_ollama_chat_with_metrics_honors_explicit_max_tokens_first(monkeypatch):
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", "999")
    client = _patch(monkeypatch, {
        "/api/chat": (200, {"message": {"content": "hi"}, "eval_count": 1}),
    })
    llm.chat_with_metrics("ollama", "qwen3:8b", [{"role": "user", "content": "hi"}],
                          base="http://ollama.test:11434", max_tokens=64)
    posts = [c for c in client.calls if c[0] == "POST"]
    assert posts[0][2]["options"]["num_predict"] == 64


def test_ollama_chat_with_metrics_a_garbage_cap_fails_closed_not_uncapped(monkeypatch):
    """A typo in DOTTIE_OLLAMA_NUM_PREDICT must refuse the call, not silently run
    without a cap — that would defeat the exact protection this exists to add."""
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", "lots")
    client = _patch(monkeypatch, {
        "/api/chat": (200, {"message": {"content": "hi"}, "eval_count": 1}),
    })
    res = llm.chat_with_metrics("ollama", "qwen3:8b", [{"role": "user", "content": "hi"}],
                                base="http://ollama.test:11434")
    assert res["ok"] is False and res["content"] is None
    assert client.calls == []  # never reached the network with an unresolved cap


def test_ollama_chat_also_sends_the_cap(monkeypatch):
    """ollama_chat() is the other direct /api/chat caller in this module (used by
    the ava plugin's real path); it must not be the one left uncapped. Loopback
    base on purpose: a non-loopback host goes through ollama_chat's own
    resolvability probe first, which is a separate concern from this cap."""
    monkeypatch.delenv("DOTTIE_OLLAMA_NUM_PREDICT", raising=False)
    client = _patch(monkeypatch, {"/api/chat": (200, {"message": {"content": "hi"}})})
    llm.ollama_chat("qwen3:8b", [{"role": "user", "content": "hi"}], base="http://127.0.0.1:11434")
    posts = [c for c in client.calls if c[0] == "POST"]
    assert posts[-1][2]["options"]["num_predict"] == 2048
    llm.ollama_chat("qwen3:8b", [{"role": "user", "content": "hi"}],
                    base="http://127.0.0.1:11434", num_predict=10)
    posts = [c for c in client.calls if c[0] == "POST"]
    assert posts[-1][2]["options"]["num_predict"] == 10


def test_ollama_routes_to_api_chat_and_uses_server_timing(monkeypatch):
    client = _patch(monkeypatch, {
        "/api/tags": (200, {"models": [{"name": "qwen3:8b"}]}),
        "/api/chat": (200, {
            "message": {"content": "yo"},
            "eval_count": 20,
            "eval_duration": 1_000_000_000,  # 1.0s in ns -> 20 tok/s server-side
        }),
    })
    res = llm.chat_with_metrics("ollama", "qwen3:8b", [{"role": "user", "content": "hi"}])
    assert res["ok"] is True and res["content"] == "yo"
    assert res["completion_tokens"] == 20
    assert res["server_tok_per_s"] == 20.0
    assert any(c[0] == "POST" and "/api/chat" in c[1] for c in client.calls)


def test_failure_never_fabricates_a_completion(monkeypatch):
    # server up for detection but the generation call 500s
    _patch(monkeypatch, {
        "/v1/models": (200, {"data": []}),
        "/v1/chat/completions": (500, {}),
    })
    res = llm.chat_with_metrics("koboldcpp", "x", [{"role": "user", "content": "hi"}],
                                base="http://localhost:5001")
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
    res = llm.chat_with_metrics("banana", "x", [{"role": "user", "content": "hi"}],
                                base="http://localhost:1")
    assert res["ok"] is False and "unknown backend" in res["error"]


def test_removed_hosted_backends_fail_closed_before_any_request(monkeypatch):
    """'openai' used to be an alias for the KoboldCpp path, and 'anthropic' read as
    merely unknown. Both hosted providers were removed 2026-09-27 (local models
    only); naming one is refused with that reason and nothing is contacted."""
    client = _patch(monkeypatch, {
        "/v1/models": (200, {"data": []}),
        "/v1/chat/completions": (200, {"choices": [{"message": {"content": "x"}}]}),
    })
    for name in ("openai", "OpenAI", "anthropic"):
        res = llm.chat_with_metrics(name, "x", [{"role": "user", "content": "hi"}],
                                    base="http://localhost:5001")
        assert res["ok"] is False and res["content"] is None
        assert "removed 2026-09-27" in res["error"] and "local models only" in res["error"]
    assert "koboldcpp" in llm.chat_with_metrics("openai", "x", [])["error"]  # the local way
    assert client.calls == []


def test_koboldcpp_discovery_ignores_the_hosted_sdk_base_url(monkeypatch):
    """OPENAI_BASE_URL is the hosted SDK's variable and often points at the paid
    API in a developer's shell. Discovery reads KOBOLDCPP_BASE only."""
    client = _patch(monkeypatch, {})
    monkeypatch.setenv("OPENAI_BASE_URL", "http://paid.invalid/v1")
    monkeypatch.delenv("KOBOLDCPP_BASE", raising=False)
    assert llm.koboldcpp_available() is None
    assert not any("paid.invalid" in c[1] for c in client.calls)
    monkeypatch.setenv("KOBOLDCPP_BASE", "http://localhost:5002")
    before = len(client.calls)
    llm.koboldcpp_available()
    assert client.calls[before][1] == "http://localhost:5002/v1/models"  # the override goes first


def _tags(monkeypatch, names):
    monkeypatch.setattr(llm, "list_ollama_models", lambda base=None, timeout=2.0: list(names))


def test_best_model_prefers_the_installed_8b_over_a_larger_qwen(monkeypatch):
    _tags(monkeypatch, ["qwen3:32b", "qwen3:14b", "qwen3:8b"])
    assert llm.get_best_model() == "qwen3:8b"
    assert llm.PREFERRED_MODELS[0] == llm.DEFAULT_MODEL == "qwen3:8b"


def test_best_model_with_nothing_listed_is_the_8b(monkeypatch):
    _tags(monkeypatch, [])
    assert llm.get_best_model() == "qwen3:8b"


def test_larger_models_are_fallbacks_only_when_installed(monkeypatch):
    _tags(monkeypatch, ["qwen3:32b"])
    assert llm.get_best_model() == "qwen3:32b"  # the only thing installed
    _tags(monkeypatch, ["qwen3:32b", "llama3.1:8b"])
    assert llm.get_best_model() == "llama3.1:8b"  # anything small in the list beats it
    big = {"qwen3:14b", "qwen2.5:14b", "qwen3:32b", "qwen3:32b-instruct", "qwen2.5:32b"}
    order = llm.PREFERRED_MODELS
    assert min(order.index(m) for m in big) > max(order.index(m) for m in order if m not in big)


def test_context_shift_is_recorded_telemetry(monkeypatch):
    _patch(monkeypatch, {
        "/v1/chat/completions": (200, {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"completion_tokens": 3},
        }),
    })
    res = llm.chat_with_metrics("koboldcpp", "x", [{"role": "user", "content": "hi"}],
                                base="http://localhost:5001", context_shift=True)
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


def test_ava_infer_refuses_a_removed_backend_without_probing_anything(monkeypatch):
    """`--backend openai` was an alias for the KoboldCpp path. It is refused now,
    and model selection does not probe Ollama for a backend that will not run."""
    import json

    from typer.testing import CliRunner

    from bigbang.core import output
    from bigbang.plugins.ava import cli as ava_cli

    def no_network(*a, **k):
        raise AssertionError("contacted a backend for a removed provider")

    monkeypatch.setattr(llm, "_httpx_client", no_network)
    monkeypatch.setattr(ava_cli, "_ollama_available", no_network)
    output.set_json_mode(True)
    try:
        res = CliRunner().invoke(ava_cli.app, ["infer", "hello", "--backend", "openai"])
    finally:
        output.set_json_mode(False)
    assert res.exit_code == 1, res.output
    body = json.loads(res.stdout)
    assert body["ok"] is False and body["content"] is None
    assert "removed 2026-09-27" in body["error"] and "koboldcpp" in body["error"]
