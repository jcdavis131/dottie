"""Tests for dottie_rlm.llm — SPEC test floor for llm.py.

ZERO network: real backends are exercised via constructors plus a stubbed
``requests`` module swapped into dottie_rlm.llm's namespace (the real
``requests`` is imported only for its exception classes). FakeBackend covers
all completion behavior.
"""

from __future__ import annotations

import types

import pytest
import requests  # exception classes only — never used to make a request here
from dottie_rlm import llm
from dottie_rlm.llm import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OLLAMA_MODEL,
    HARD_TIMEOUT_S,
    Backend,
    BackendUnavailable,
    FakeBackend,
    FakeBackendExhausted,
    OllamaBackend,
    OpenAICompatBackend,
    resolve_backend,
)


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _swap_requests(monkeypatch, post):
    """Replace llm.requests with a stub whose .post is ``post``.

    Real exception classes are kept so llm.py's except clauses match.
    """
    stub = types.SimpleNamespace(post=post, exceptions=requests.exceptions)
    monkeypatch.setattr(llm, "requests", stub)
    return stub


# ---------------------------------------------------------------- FakeBackend


def test_fake_backend_pops_scripted_replies_in_order():
    fb = FakeBackend(["one", "two"])
    assert fb.complete([{"role": "user", "content": "a"}], max_tokens=8) == "one"
    assert fb.complete([{"role": "user", "content": "b"}], max_tokens=8) == "two"
    assert fb.remaining == 0


def test_fake_backend_does_not_mutate_caller_script():
    script = ["only"]
    fb = FakeBackend(script)
    fb.complete([], max_tokens=1)
    assert script == ["only"]


def test_fake_backend_records_calls():
    fb = FakeBackend(["r"])
    msgs = [{"role": "user", "content": "hi"}]
    fb.complete(msgs, max_tokens=42)
    assert fb.calls == [(msgs, 42)]


def test_fake_backend_exhaustion_raises():
    fb = FakeBackend(["only"])
    fb.complete([], max_tokens=1)
    with pytest.raises(FakeBackendExhausted):
        fb.complete([], max_tokens=1)


def test_fake_backend_empty_script_raises_immediately():
    fb = FakeBackend([])
    with pytest.raises(FakeBackendExhausted):
        fb.complete([], max_tokens=1)


def test_fake_backend_exhausted_is_runtime_error():
    # Anything catching broad RuntimeError still fails loudly, and pytest
    # reports uncaught exhaustion as a test error, never a loop.
    assert issubclass(FakeBackendExhausted, RuntimeError)


def test_fake_backend_satisfies_backend_protocol():
    assert isinstance(FakeBackend([]), Backend)


# -------------------------------------------------------------- OllamaBackend


def test_ollama_constructor_defaults_no_network():
    b = OllamaBackend()
    assert b.model == DEFAULT_OLLAMA_MODEL == "qwen3:8b"
    assert b.host == DEFAULT_OLLAMA_HOST
    assert b.timeout_s == HARD_TIMEOUT_S == 300.0


def test_ollama_constructor_custom_and_host_slash_stripped():
    b = OllamaBackend(model="llama3:8b", host="http://127.0.0.1:11434/")
    assert b.model == "llama3:8b"
    assert b.host == "http://127.0.0.1:11434"


def test_ollama_connection_failure_raises_actionable_backend_unavailable(
    monkeypatch,
):
    def post(url, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    _swap_requests(monkeypatch, post)
    b = OllamaBackend()
    with pytest.raises(BackendUnavailable) as ei:
        b.complete([{"role": "user", "content": "hi"}], max_tokens=8)
    msg = str(ei.value)
    assert "ollama serve" in msg  # actionable: how to start it
    assert "qwen3:8b" in msg  # actionable: which model to pull
    assert "/api/chat" in msg  # what was tried


def test_ollama_wires_hard_timeout_and_stream_false(monkeypatch):
    seen = {}

    def post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return _FakeResponse(payload={"message": {"content": "pong"}})

    _swap_requests(monkeypatch, post)
    out = OllamaBackend().complete([{"role": "user", "content": "ping"}], max_tokens=7)
    assert out == "pong"
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert seen["timeout"] == 300.0
    assert seen["json"]["stream"] is False
    assert seen["json"]["options"]["num_predict"] == 7


def test_ollama_http_error_raises_backend_unavailable(monkeypatch):
    _swap_requests(
        monkeypatch,
        lambda url, **kw: _FakeResponse(status_code=404, text="model not found"),
    )
    with pytest.raises(BackendUnavailable) as ei:
        OllamaBackend().complete([], max_tokens=1)
    assert "404" in str(ei.value)
    assert "ollama pull" in str(ei.value)


def test_ollama_unparseable_body_raises_backend_unavailable(monkeypatch):
    _swap_requests(
        monkeypatch, lambda url, **kw: _FakeResponse(payload=None, text="<html>")
    )
    with pytest.raises(BackendUnavailable):
        OllamaBackend().complete([], max_tokens=1)


# --------------------------------------------------------- OpenAICompatBackend


def test_openai_constructor_no_network_and_key_not_stored(monkeypatch):
    monkeypatch.setenv(DEFAULT_API_KEY_ENV, "sk-supersecret-123")
    b = OpenAICompatBackend("http://localhost:8000/v1/", "my-model")
    assert b.base_url == "http://localhost:8000/v1"  # trailing slash stripped
    assert b.model == "my-model"
    assert b.api_key_env == DEFAULT_API_KEY_ENV == "DOTTIE_RLM_API_KEY"
    # The key is never on the instance and never in the repr.
    assert "sk-supersecret-123" not in repr(b)
    assert all("sk-supersecret-123" not in str(v) for v in vars(b).values())


def test_openai_missing_key_refuses_before_any_network(monkeypatch):
    monkeypatch.delenv(DEFAULT_API_KEY_ENV, raising=False)
    calls = []

    def post(url, **kwargs):  # must never run
        calls.append(url)
        return _FakeResponse()

    _swap_requests(monkeypatch, post)
    with pytest.raises(BackendUnavailable) as ei:
        OpenAICompatBackend("http://localhost:8000/v1", "m").complete(
            [], max_tokens=1
        )
    assert DEFAULT_API_KEY_ENV in str(ei.value)  # actionable: which var to set
    assert calls == []  # refused before touching the transport


def test_openai_key_read_from_env_at_call_time_and_sent_as_bearer(monkeypatch):
    monkeypatch.setenv(DEFAULT_API_KEY_ENV, "sk-live-key")
    seen = {}

    def post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return _FakeResponse(
            payload={"choices": [{"message": {"content": "reply"}}]}
        )

    _swap_requests(monkeypatch, post)
    out = OpenAICompatBackend("http://localhost:8000/v1", "m").complete(
        [{"role": "user", "content": "q"}], max_tokens=5
    )
    assert out == "reply"
    assert seen["url"] == "http://localhost:8000/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-live-key"
    assert seen["json"]["max_tokens"] == 5
    assert seen["timeout"] == 300.0


def test_openai_errors_never_contain_the_key(monkeypatch):
    secret = "sk-must-not-leak"  # noqa: S105 — deliberately fake key for the leak test
    monkeypatch.setenv(DEFAULT_API_KEY_ENV, secret)

    # Connection failure path.
    def post_raises(url, **kwargs):
        raise requests.exceptions.ConnectionError(f"boom {secret}")

    _swap_requests(monkeypatch, post_raises)
    b = OpenAICompatBackend("http://localhost:8000/v1", "m")
    with pytest.raises(BackendUnavailable) as ei:
        b.complete([], max_tokens=1)
    assert secret not in str(ei.value)

    # HTTP-error path: body echoing the key gets scrubbed.
    _swap_requests(
        monkeypatch,
        lambda url, **kw: _FakeResponse(
            status_code=401, text=f"bad key {secret}"
        ),
    )
    with pytest.raises(BackendUnavailable) as ei:
        b.complete([], max_tokens=1)
    assert secret not in str(ei.value)
    assert "401" in str(ei.value)


def test_openai_custom_api_key_env_name(monkeypatch):
    monkeypatch.delenv("OTHER_KEY", raising=False)
    b = OpenAICompatBackend("http://x", "m", api_key_env="OTHER_KEY")
    with pytest.raises(BackendUnavailable) as ei:
        b.complete([], max_tokens=1)
    assert "OTHER_KEY" in str(ei.value)


# ------------------------------------------------------------- resolve_backend


def test_resolve_fake_empty_script():
    b = resolve_backend("fake:")
    assert isinstance(b, FakeBackend)
    assert b.remaining == 0


def test_resolve_fake_with_single_scripted_reply():
    b = resolve_backend("fake:done")
    assert isinstance(b, FakeBackend)
    assert b.complete([], max_tokens=1) == "done"


def test_resolve_ollama_with_model():
    b = resolve_backend("ollama:qwen3:8b")
    assert isinstance(b, OllamaBackend)
    assert b.model == "qwen3:8b"
    assert b.host == DEFAULT_OLLAMA_HOST


def test_resolve_ollama_default_model():
    for spec in ("ollama:", "ollama"):
        b = resolve_backend(spec)
        assert isinstance(b, OllamaBackend)
        assert b.model == "qwen3:8b"


def test_resolve_openai_base_url_with_colons():
    b = resolve_backend("openai:http://localhost:8000/v1:my-model")
    assert isinstance(b, OpenAICompatBackend)
    assert b.base_url == "http://localhost:8000/v1"
    assert b.model == "my-model"


def test_resolve_openai_missing_model_raises():
    with pytest.raises(ValueError):
        resolve_backend("openai:http-only-no-model-separator-here")
    with pytest.raises(ValueError):
        resolve_backend("openai:")


def test_resolve_unknown_scheme_raises_with_accepted_forms():
    with pytest.raises(ValueError) as ei:
        resolve_backend("anthropic:claude")
    msg = str(ei.value)
    assert "fake:" in msg and "ollama:" in msg and "openai:" in msg


def test_resolve_empty_spec_raises():
    with pytest.raises(ValueError):
        resolve_backend("")
    with pytest.raises(ValueError):
        resolve_backend("   ")


def test_resolved_backends_all_satisfy_protocol():
    for spec in ("fake:", "ollama:qwen3:8b", "openai:http://h:1/v1:m"):
        assert isinstance(resolve_backend(spec), Backend)
