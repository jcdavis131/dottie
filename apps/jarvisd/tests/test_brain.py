"""jarvisd brain — offline tests with a scripted fake client (spec §6).

No network: the fake client's ``stream()`` context manager hands back scripted
Message-like objects, and the FakeState is an in-memory stand-in for the real
SQLite State with the same method names.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any

import pytest

from jarvisd import brain

# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #


class FakeState:
    def __init__(self) -> None:
        self.memories: list[dict[str, Any]] = []
        self.timeline: list[dict[str, Any]] = []
        self.recall_calls: list[tuple[Any, ...]] = []

    def context(self, agent: str, repo: str | None) -> dict[str, Any]:
        return {"ok": True, "repo": repo, "agent": agent, "claims": [], "goals": []}

    def recall(self, query: str, scope: str | None, limit: int) -> list[dict[str, Any]]:
        self.recall_calls.append((query, scope, limit))
        return [m for m in self.memories if query.lower() in m["text"].lower()][:limit]

    def remember(
        self, agent: str, scope: str, text: str, tags: list[str], source: str
    ) -> dict[str, Any]:
        row = {"agent": agent, "scope": scope, "text": text, "tags": tags, "source": source}
        self.memories.append(row)
        return {"ok": True, "id": len(self.memories)}

    def claims(self, repo: str | None) -> list[dict[str, Any]]:
        return [{"repo": repo, "area": "brain", "agent": "worker-b"}]

    def claim(self, agent: str, repo: str, area: str, note: str) -> dict[str, Any]:
        return {"ok": True}

    def timeline_add(
        self, agent: str, repo: str | None, kind: str, payload: dict[str, Any]
    ) -> None:
        self.timeline.append({"agent": agent, "repo": repo, "kind": kind, "payload": payload})


class FakeStream:
    def __init__(self, message: Any) -> None:
        self._message = message

    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def get_final_message(self) -> Any:
        return self._message


class FakeMessages:
    """Scripted `.stream()`; a script entry that is an exception is raised."""

    def __init__(self, script: list[Any], calls: list[dict[str, Any]]) -> None:
        self.script = list(script)
        self.calls = calls

    def stream(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("fake client script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return FakeStream(item)


class FakeClient:
    def __init__(self, script: list[Any], *, beta: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        messages = FakeMessages(script, self.calls)
        self.messages = messages
        if beta:
            self.beta = SimpleNamespace(messages=messages)


def _usage(inp: int = 100, out: int = 20, cached: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out, cache_read_input_tokens=cached
    )


def _message(content: list[Any], stop_reason: str, **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=extra.pop("usage", _usage()),
        model="claude-opus-5",
        stop_details=extra.pop("stop_details", None),
        **extra,
    )


def text_msg(text: str, **extra: Any) -> SimpleNamespace:
    return _message([SimpleNamespace(type="text", text=text)], "end_turn", **extra)


def tool_msg(*calls: tuple[str, str, dict[str, Any]], text: str = "") -> SimpleNamespace:
    blocks: list[Any] = []
    if text:
        blocks.append(SimpleNamespace(type="text", text=text))
    blocks.extend(
        SimpleNamespace(type="tool_use", id=tid, name=name, input=inp)
        for tid, name, inp in calls
    )
    return _message(blocks, "tool_use")


def _tool_results(call: dict[str, Any]) -> list[dict[str, Any]]:
    last = call["messages"][-1]
    assert last["role"] == "user"
    return last["content"]


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #


def test_direct_text_answer_and_request_shape() -> None:
    state = FakeState()
    client = FakeClient([text_msg("Measured: 3 open claims.", usage=_usage(120, 30, 90))])

    res = brain.ask("what is open?", "dottie", state, "cursor", client=client, effort="xhigh")

    assert res["ok"] is True
    assert res["answer"] == "Measured: 3 open claims."
    assert res["turns"] == 1
    assert res["tool_calls"] == []
    assert res["usage"] == {
        "input_tokens": 120,
        "output_tokens": 30,
        "cache_read_input_tokens": 90,
    }
    assert res["model"] == "claude-opus-5"
    assert res["stop_reason"] == "end_turn"

    call = client.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": "xhigh"}
    assert call["betas"] == [brain.FALLBACK_BETA]
    assert call["fallbacks"] == "default"
    assert "tool_choice" not in call
    assert [t["name"] for t in call["tools"]] == [
        "jarvis_context",
        "jarvis_recall",
        "jarvis_remember",
        "jarvis_claims",
        "harness_route",
    ]
    # Stable system text carries the cache breakpoint; volatile context is in the user turn.
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["system"][0]["text"] == brain.SYSTEM_PROMPT
    voice = call["system"][0]["text"].lower()
    assert "measured" in voice and "evidence-backed" in voice
    assert "do not use sports metaphors" in voice
    user = call["messages"][0]
    assert user["role"] == "user"
    assert "Repo: dottie" in user["content"]
    assert '"agent": "cursor"' in user["content"]
    assert "Question: what is open?" in user["content"]

    events = [row["payload"]["event"] for row in state.timeline]
    assert events == ["answer"]
    assert all(row["kind"] == "brain" for row in state.timeline)


def test_recall_round_trip_then_final_text() -> None:
    state = FakeState()
    state.memories.append(
        {"agent": "op", "scope": "repo:dottie", "text": "Postgres runs on :5433", "tags": []}
    )
    client = FakeClient(
        [
            tool_msg(("tu_1", "jarvis_recall", {"query": "postgres", "limit": 5})),
            text_msg("Postgres is on port 5433 (from a stored memory)."),
        ]
    )

    res = brain.ask("which port is postgres on?", "dottie", state, "cursor", client=client)

    assert res["ok"] is True
    assert res["turns"] == 2
    assert res["answer"].startswith("Postgres is on port 5433")
    assert state.recall_calls == [("postgres", None, 5)]
    assert res["tool_calls"] == [
        {
            "turn": 1,
            "id": "tu_1",
            "name": "jarvis_recall",
            "input": {"query": "postgres", "limit": 5},
            "ok": True,
        }
    ]

    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"][0]["type"] == "tool_use"
    results = _tool_results(client.calls[1])
    assert len(results) == 1
    assert results[0]["type"] == "tool_result"
    assert results[0]["tool_use_id"] == "tu_1"
    assert "is_error" not in results[0]
    assert json.loads(results[0]["content"])[0]["text"] == "Postgres runs on :5433"

    events = [row["payload"]["event"] for row in state.timeline]
    assert events == ["tool_call", "tool_result", "answer"]
    assert state.timeline[0]["payload"]["tool"] == "jarvis_recall"
    assert state.timeline[1]["payload"]["ok"] is True


def test_parallel_tool_uses_answered_in_one_user_message_with_is_error() -> None:
    state = FakeState()
    client = FakeClient(
        [
            tool_msg(
                ("tu_a", "jarvis_claims", {}),
                ("tu_b", "no_such_tool", {"x": 1}),
                ("tu_c", "jarvis_remember", {"text": "keep this", "tags": ["t"]}),
                text="Checking.",
            ),
            text_msg("done"),
        ]
    )

    res = brain.ask("q", "dottie", state, "cursor", client=client)

    assert res["ok"] is True
    results = _tool_results(client.calls[1])
    assert [r["tool_use_id"] for r in results] == ["tu_a", "tu_b", "tu_c"]
    assert "is_error" not in results[0]
    assert results[1]["is_error"] is True
    assert "unknown tool" in json.loads(results[1]["content"])["error"]
    assert "is_error" not in results[2]
    # remember defaulted scope to the repo and tagged the source as brain
    assert state.memories == [
        {
            "agent": "cursor",
            "scope": "repo:dottie",
            "text": "keep this",
            "tags": ["t"],
            "source": "brain",
        }
    ]
    assert [c["ok"] for c in res["tool_calls"]] == [True, False, True]
    assert client.calls[1]["messages"][1]["content"][0] == {"type": "text", "text": "Checking."}


def test_max_turns_cutoff() -> None:
    state = FakeState()
    loop = [tool_msg((f"tu_{i}", "jarvis_claims", {})) for i in range(5)]
    client = FakeClient(loop)

    res = brain.ask("q", "dottie", state, client=client, max_turns=2)

    assert res["ok"] is False
    assert "max_turns" in res["error"]
    assert res["turns"] == 2
    assert len(client.calls) == 2
    assert len(res["tool_calls"]) == 2
    assert res["stop_reason"] == "tool_use"


def test_refusal_surfaces_stop_details() -> None:
    state = FakeState()
    details = SimpleNamespace(type="refusal", category="cyber", explanation="declined")
    client = FakeClient([_message([], "refusal", stop_details=details)])

    res = brain.ask("q", "dottie", state, client=client)

    assert res["ok"] is False
    assert res["error"] == "refusal"
    assert res["stop_details"] == {
        "type": "refusal",
        "category": "cyber",
        "explanation": "declined",
    }
    assert res["stop_reason"] == "refusal"
    assert state.timeline[-1]["payload"]["error"] == "refusal"


def test_missing_key_raises_brain_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"^brain unavailable: "):
        brain.ask("q", "dottie", FakeState())
    ok, why = brain.available()
    assert ok is False
    assert why


def test_api_error_returns_ok_false() -> None:
    class FakeRateLimitError(Exception):
        pass

    state = FakeState()
    client = FakeClient([FakeRateLimitError("slow down")])

    res = brain.ask("q", "dottie", state, client=client)

    assert res["ok"] is False
    assert res["error"] == "FakeRateLimitError: slow down"
    assert res["turns"] == 1
    assert state.timeline[-1]["payload"]["event"] == "answer"


def test_real_sdk_error_classes_are_recognised() -> None:
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx2")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = FakeClient([anthropic.APIConnectionError(request=request)])

    res = brain.ask("q", "dottie", FakeState(), client=client)

    assert res["ok"] is False
    assert res["error"].startswith("APIConnectionError:")
    assert res["hint"]


def test_harness_route_tool_uses_scout_router() -> None:
    pytest.importorskip("bigbang.plugins.harness.cli")
    state = FakeState()
    goal = "compare Stripe vs Lemon Squeezy Aug 2026"
    client = FakeClient([tool_msg(("tu_r", "harness_route", {"goal": goal})), text_msg("ok")])

    res = brain.ask("route this", "dottie", state, client=client)

    assert res["ok"] is True
    routed = json.loads(_tool_results(client.calls[1])[0]["content"])
    assert routed["intent"] == "deep_research"
    assert routed["moma_tier"] == "deep_research"
    assert "deep-researcher" in routed["routed_agents"]
    assert 0 < routed["confidence"] <= 0.96


def test_client_without_beta_surface_uses_plain_messages() -> None:
    client = FakeClient([text_msg("hi")], beta=False)

    res = brain.ask("q", None, FakeState(), client=client)

    assert res["ok"] is True
    assert "betas" not in client.calls[0]
    assert "fallbacks" not in client.calls[0]
    assert "Repo: (none)" in client.calls[0]["messages"][0]["content"]


def test_missing_state_method_is_a_tool_error_not_a_raise() -> None:
    class ThinState:
        def context(self, agent: str, repo: str | None) -> dict[str, Any]:
            return {}

        def timeline_add(self, *args: Any) -> None:
            pass

    client = FakeClient([tool_msg(("tu_1", "jarvis_recall", {"query": "x"})), text_msg("ok")])

    res = brain.ask("q", "dottie", ThinState(), client=client)

    assert res["ok"] is True
    result = _tool_results(client.calls[1])[0]
    assert result["is_error"] is True
    assert "state has no method 'recall'" in json.loads(result["content"])["error"]


def test_effort_and_model_resolve_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_EFFORT", "bogus")
    monkeypatch.setenv("JARVIS_MODEL", "claude-opus-5")
    assert brain._resolve_effort(None) == "high"
    assert brain._resolve_effort("Low") == "low"
    assert brain._resolve_model(None) == "claude-opus-5"
    assert brain._resolve_model("override") == "override"


# --------------------------------------------------------------------------- #
# Ollama provider (stdlib urllib; `urllib.request.urlopen` is faked, no network)
# --------------------------------------------------------------------------- #

OLLAMA_HOST = "http://ollama.test:11434"


class FakeHTTPResponse:
    def __init__(self, body: Any) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class FakeOllama:
    """Scripted `urllib.request.urlopen`.

    `GET /api/tags` answers (or refuses when `tags_ok=False`); `POST /api/chat`
    pops the script. A script entry that is an exception is raised.
    """

    def __init__(self, script: list[Any] = (), *, tags_ok: bool = True) -> None:
        self.script = list(script)
        self.tags_ok = tags_ok
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req: Any, timeout: float | None = None) -> FakeHTTPResponse:
        payload = json.loads(req.data) if req.data else None
        self.requests.append(
            {"url": req.full_url, "method": req.get_method(), "payload": payload, "timeout": timeout}
        )
        if req.full_url.endswith("/api/tags"):
            if not self.tags_ok:
                raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
            return FakeHTTPResponse({"models": [{"name": "qwen3:32b"}]})
        assert req.full_url.endswith("/api/chat"), req.full_url
        if not self.script:
            raise AssertionError("fake ollama script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return FakeHTTPResponse(item)

    @property
    def chats(self) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["url"].endswith("/api/chat")]


def ollama_text(text: str, *, prompt: int = 50, eval_: int = 10) -> dict[str, Any]:
    return {
        "model": "qwen3:32b",
        "message": {"role": "assistant", "content": text},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": prompt,
        "eval_count": eval_,
    }


def ollama_tool(*calls: tuple[str, Any], text: str = "") -> dict[str, Any]:
    return {
        "model": "qwen3:32b",
        "message": {
            "role": "assistant",
            "content": text,
            "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls],
        },
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 40,
        "eval_count": 8,
    }


@pytest.fixture
def ollama_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("JARVIS_BRAIN", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", OLLAMA_HOST)
    for var in ("JARVIS_MODEL", "OLLAMA_MODEL", "JARVIS_BRAIN_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)


def _fake(monkeypatch: pytest.MonkeyPatch, *script: Any, tags_ok: bool = True) -> FakeOllama:
    fake = FakeOllama(list(script), tags_ok=tags_ok)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def test_ollama_direct_answer_and_request_shape(
    ollama_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = FakeState()
    fake = _fake(monkeypatch, ollama_text("<think>hmm</think>Measured: no open claims.", prompt=50, eval_=10))

    res = brain.ask("what is open?", "dottie", state, "cursor")

    assert res["ok"] is True
    assert res["answer"] == "Measured: no open claims."
    assert res["provider"] == "ollama"
    assert res["model"] == "qwen3:32b"
    assert res["turns"] == 1
    assert res["tool_calls"] == []
    assert res["usage"] == {"input_tokens": 50, "output_tokens": 10, "cache_read_input_tokens": 0}
    assert res["stop_reason"] == "end_turn"

    # explicit JARVIS_BRAIN=ollama goes straight to /api/chat (no probe) with a 120 s default
    assert [r["url"] for r in fake.requests] == [f"{OLLAMA_HOST}/api/chat"]
    call = fake.requests[0]
    assert call["method"] == "POST" and call["timeout"] == 120.0
    payload = call["payload"]
    assert payload["model"] == "qwen3:32b"
    assert payload["stream"] is False
    assert [t["type"] for t in payload["tools"]] == ["function"] * 5
    assert [t["function"]["name"] for t in payload["tools"]] == [
        "jarvis_context",
        "jarvis_recall",
        "jarvis_remember",
        "jarvis_claims",
        "harness_route",
    ]
    assert payload["tools"][1]["function"]["parameters"] == brain.TOOLS[1]["input_schema"]
    assert payload["messages"][0] == {"role": "system", "content": brain.SYSTEM_PROMPT}
    user = payload["messages"][1]
    assert user["role"] == "user"
    assert "Repo: dottie" in user["content"]
    assert '"agent": "cursor"' in user["content"]
    assert "Question: what is open?" in user["content"]

    events = [row["payload"]["event"] for row in state.timeline]
    assert events == ["answer"]
    assert state.timeline[0]["payload"]["provider"] == "ollama"
    assert all(row["kind"] == "brain" for row in state.timeline)


@pytest.mark.parametrize(
    "arguments",
    [{"query": "postgres", "limit": 5}, json.dumps({"query": "postgres", "limit": 5})],
    ids=["dict", "json-string"],
)
def test_ollama_tool_round_trip(
    ollama_env: None, monkeypatch: pytest.MonkeyPatch, arguments: Any
) -> None:
    state = FakeState()
    state.memories.append(
        {"agent": "op", "scope": "repo:dottie", "text": "Postgres runs on :5433", "tags": []}
    )
    fake = _fake(
        monkeypatch,
        ollama_tool(("jarvis_recall", arguments)),
        ollama_text("Postgres is on port 5433 (from a stored memory)."),
    )

    res = brain.ask("which port is postgres on?", "dottie", state, "cursor")

    assert res["ok"] is True
    assert res["turns"] == 2
    assert res["answer"].startswith("Postgres is on port 5433")
    assert res["stop_reason"] == "end_turn"
    assert res["usage"] == {"input_tokens": 90, "output_tokens": 18, "cache_read_input_tokens": 0}
    assert state.recall_calls == [("postgres", None, 5)]
    assert res["tool_calls"] == [
        {
            "turn": 1,
            "id": "call_1_0",
            "name": "jarvis_recall",
            "input": {"query": "postgres", "limit": 5},
            "ok": True,
        }
    ]

    second = fake.chats[1]["payload"]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"]
    assert second[2]["tool_calls"][0]["function"]["name"] == "jarvis_recall"
    assert second[3]["tool_name"] == "jarvis_recall"
    assert json.loads(second[3]["content"])[0]["text"] == "Postgres runs on :5433"

    events = [row["payload"]["event"] for row in state.timeline]
    assert events == ["tool_call", "tool_result", "answer"]
    assert state.timeline[0]["payload"]["tool"] == "jarvis_recall"
    assert state.timeline[0]["payload"]["input"] == {"query": "postgres", "limit": 5}
    assert state.timeline[1]["payload"]["ok"] is True


def test_ollama_parallel_calls_one_tool_message_each_with_errors(
    ollama_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = FakeState()
    fake = _fake(
        monkeypatch,
        ollama_tool(
            ("jarvis_claims", {}),
            ("no_such_tool", {"x": 1}),
            ("jarvis_remember", "not json {"),
            ("jarvis_remember", {"text": "keep this", "tags": ["t"]}),
        ),
        ollama_text("done"),
    )

    res = brain.ask("q", "dottie", state, "cursor")

    assert res["ok"] is True
    msgs = fake.chats[1]["payload"]["messages"]
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert len(tool_msgs) == 4
    assert json.loads(tool_msgs[0]["content"])[0]["area"] == "brain"
    assert "unknown tool" in json.loads(tool_msgs[1]["content"])["error"]
    assert "not a JSON object" in json.loads(tool_msgs[2]["content"])["error"]
    assert json.loads(tool_msgs[3]["content"]) == {"ok": True, "id": 1}
    assert [c["ok"] for c in res["tool_calls"]] == [True, False, False, True]
    assert state.memories == [
        {
            "agent": "cursor",
            "scope": "repo:dottie",
            "text": "keep this",
            "tags": ["t"],
            "source": "brain",
        }
    ]


def test_ollama_max_turns_cutoff(ollama_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    state = FakeState()
    fake = _fake(monkeypatch, *[ollama_tool(("jarvis_claims", {})) for _ in range(5)])

    res = brain.ask("q", "dottie", state, max_turns=2)

    assert res["ok"] is False
    assert "max_turns" in res["error"]
    assert res["turns"] == 2
    assert len(fake.chats) == 2
    assert len(res["tool_calls"]) == 2
    assert res["stop_reason"] == "max_turns"


@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
        TimeoutError("timed out"),
    ],
    ids=["refused", "timeout"],
)
def test_ollama_unreachable_returns_ok_false(
    ollama_env: None, monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    state = FakeState()
    _fake(monkeypatch, exc)

    res = brain.ask("q", "dottie", state)

    assert res["ok"] is False
    assert res["error"].startswith(f"ollama unreachable at {OLLAMA_HOST}: ")
    assert res["provider"] == "ollama"
    assert res["turns"] == 1
    assert res["answer"] if "answer" in res else True
    assert state.timeline[-1]["payload"]["event"] == "answer"
    assert state.timeline[-1]["payload"]["error"] == res["error"]


def test_ollama_http_error_and_error_body(
    ollama_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    http_err = urllib.error.HTTPError(
        f"{OLLAMA_HOST}/api/chat", 404, "Not Found", {}, io.BytesIO(b'{"error":"model not found"}')
    )
    _fake(monkeypatch, http_err)
    res = brain.ask("q", "dottie", FakeState())
    assert res["ok"] is False
    assert res["error"].startswith(f"ollama HTTP 404 at {OLLAMA_HOST}: ")
    assert "model not found" in res["error"]

    _fake(monkeypatch, {"error": "model 'x' not found"})
    res = brain.ask("q", "dottie", FakeState())
    assert res["ok"] is False
    assert res["error"] == "ollama error: model 'x' not found"


def test_auto_picks_ollama_when_no_key_and_tags_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("JARVIS_BRAIN", "auto")
    monkeypatch.setenv("OLLAMA_HOST", OLLAMA_HOST)
    monkeypatch.delenv("JARVIS_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    fake = _fake(monkeypatch, ollama_text("hi"))

    assert brain.available() == (True, "ok (ollama)")
    status = brain.status()
    assert status["provider"] == "ollama" and status["available"] is True
    assert status["model"] == "qwen3:8b" and status["host"] == OLLAMA_HOST
    assert status["reason"] is None and status["requested"] == "auto"
    assert fake.requests[0]["url"] == f"{OLLAMA_HOST}/api/tags"
    assert fake.requests[0]["timeout"] == 1.0

    res = brain.ask("q", "dottie", FakeState())
    assert res["ok"] is True and res["provider"] == "ollama"
    assert fake.chats[0]["payload"]["model"] == "qwen3:8b"


def test_auto_unavailable_when_no_key_and_no_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("JARVIS_BRAIN", "auto")
    monkeypatch.setenv("OLLAMA_HOST", OLLAMA_HOST)
    fake = _fake(monkeypatch, tags_ok=False)

    ok, why = brain.available()
    assert ok is False
    assert "ANTHROPIC_API_KEY unset" in why
    assert f"ollama unreachable at {OLLAMA_HOST}" in why
    assert brain.status()["provider"] == "none"
    with pytest.raises(RuntimeError, match=r"^brain unavailable: .*ollama unreachable"):
        brain.ask("q", "dottie", FakeState())
    assert all(r["url"].endswith("/api/tags") for r in fake.requests)


def test_auto_prefers_anthropic_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("JARVIS_BRAIN", "auto")
    fake = _fake(monkeypatch)

    provider, _ok, _why = brain.resolve_provider()
    assert provider == "anthropic"
    assert brain.status()["provider"] == "anthropic"
    assert fake.requests == []  # no Ollama probe when the key decides


def test_brain_off_is_unavailable_without_probing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("JARVIS_BRAIN", "off")
    fake = _fake(monkeypatch)

    assert brain.available() == (False, "JARVIS_BRAIN=off")
    assert brain.status() == {
        "provider": "off",
        "requested": "off",
        "available": False,
        "reason": "JARVIS_BRAIN=off",
        "model": None,
    }
    with pytest.raises(RuntimeError, match=r"^brain unavailable: JARVIS_BRAIN=off$"):
        brain.ask("q", "dottie", FakeState())
    assert fake.requests == []

    monkeypatch.setenv("JARVIS_BRAIN", "bogus")
    ok, why = brain.available()
    assert ok is False and "JARVIS_BRAIN='bogus' is not one of" in why


def test_explicit_ollama_status_probes_and_reports_down_host(
    ollama_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake(monkeypatch, tags_ok=False)
    ok, why = brain.available()
    assert ok is False and why.startswith(f"ollama unreachable at {OLLAMA_HOST}")
    status = brain.status()
    assert status["provider"] == "ollama" and status["available"] is False


def test_ollama_env_resolution(ollama_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_BRAIN_TIMEOUT", "7.5")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_HOST", "host.docker.internal:11434/")
    fake = _fake(monkeypatch, ollama_text("hi"))

    res = brain.ask("q", None, FakeState())

    assert res["ok"] is True
    call = fake.chats[0]
    assert call["url"] == "http://host.docker.internal:11434/api/chat"
    assert call["timeout"] == 7.5
    assert call["payload"]["model"] == "qwen3:8b"
    assert "Repo: (none)" in call["payload"]["messages"][1]["content"]

    monkeypatch.setenv("JARVIS_MODEL", "qwen3:14b")  # JARVIS_MODEL wins over OLLAMA_MODEL
    assert brain._resolve_ollama_model(None) == "qwen3:14b"
    assert brain._resolve_ollama_model("override") == "override"
    monkeypatch.setenv("JARVIS_BRAIN_TIMEOUT", "not-a-number")
    assert brain._resolve_timeout() == 120.0
