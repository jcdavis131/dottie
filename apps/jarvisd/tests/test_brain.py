"""jarvisd brain — offline tests against a scripted fake Ollama (spec §6).

No network: ``urllib.request.urlopen`` is replaced by a scripted fake that
answers ``/api/tags`` and ``/api/chat``, and the FakeState is an in-memory
stand-in for the real SQLite State with the same method names.

The brain is local-only (Ollama). The paid Anthropic provider and its tests were
removed on 2026-09-27; the tests below also pin that it stays removed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
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
            return FakeHTTPResponse({"models": [{"name": "qwen3:8b"}]})
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
        "model": "qwen3:8b",
        "message": {"role": "assistant", "content": text},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": prompt,
        "eval_count": eval_,
    }


def ollama_tool(*calls: tuple[str, Any], text: str = "") -> dict[str, Any]:
    return {
        "model": "qwen3:8b",
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
    assert res["model"] == "qwen3:8b"
    assert res["turns"] == 1
    assert res["tool_calls"] == []
    assert res["usage"] == {"input_tokens": 50, "output_tokens": 10, "cache_read_input_tokens": 0}
    assert res["stop_reason"] == "end_turn"

    # explicit JARVIS_BRAIN=ollama goes straight to /api/chat (no probe) with a 120 s default
    assert [r["url"] for r in fake.requests] == [f"{OLLAMA_HOST}/api/chat"]
    call = fake.requests[0]
    assert call["method"] == "POST" and call["timeout"] == 120.0
    payload = call["payload"]
    # the code default, with JARVIS_MODEL / OLLAMA_MODEL unset: the one model pulled locally
    assert brain.DEFAULT_OLLAMA_MODEL == "qwen3:8b"
    assert payload["model"] == "qwen3:8b"
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
    voice = payload["messages"][0]["content"].lower()
    assert "measured" in voice and "evidence-backed" in voice
    assert "do not use sports metaphors" in voice
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


def test_auto_picks_ollama_when_tags_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_BRAIN", "auto")
    monkeypatch.setenv("OLLAMA_HOST", OLLAMA_HOST)
    monkeypatch.delenv("JARVIS_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")
    fake = _fake(monkeypatch, ollama_text("hi"))

    assert brain.available() == (True, "ok (ollama)")
    status = brain.status()
    assert status["provider"] == "ollama" and status["available"] is True
    assert status["model"] == "qwen3:4b" and status["host"] == OLLAMA_HOST
    assert status["reason"] is None and status["requested"] == "auto"
    assert fake.requests[0]["url"] == f"{OLLAMA_HOST}/api/tags"
    assert fake.requests[0]["timeout"] == 1.0

    res = brain.ask("q", "dottie", FakeState())
    assert res["ok"] is True and res["provider"] == "ollama"
    assert fake.chats[0]["payload"]["model"] == "qwen3:4b"


def test_auto_unavailable_when_no_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_BRAIN", "auto")
    monkeypatch.setenv("OLLAMA_HOST", OLLAMA_HOST)
    fake = _fake(monkeypatch, tags_ok=False)

    ok, why = brain.available()
    assert ok is False
    assert "ANTHROPIC" not in why
    assert f"ollama unreachable at {OLLAMA_HOST}" in why
    assert brain.status()["provider"] == "none"
    with pytest.raises(RuntimeError, match=r"^brain unavailable: .*ollama unreachable"):
        brain.ask("q", "dottie", FakeState())
    assert all(r["url"].endswith("/api/tags") for r in fake.requests)


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


def test_anthropic_provider_is_removed_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An old `JARVIS_BRAIN=anthropic` in an .env is refused, not swapped for Ollama."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("JARVIS_BRAIN", "anthropic")
    monkeypatch.setenv("OLLAMA_HOST", OLLAMA_HOST)
    fake = _fake(monkeypatch)

    assert "anthropic" not in brain.PROVIDERS
    ok, why = brain.available()
    assert ok is False
    assert why.startswith("JARVIS_BRAIN='anthropic': removed") and "no paid APIs" in why
    status = brain.status()
    assert status["provider"] == "off" and status["available"] is False
    assert status["model"] is None
    with pytest.raises(RuntimeError, match=r"^brain unavailable: JARVIS_BRAIN='anthropic': removed"):
        brain.ask("q", "dottie", FakeState())
    assert fake.requests == []  # no Ollama probe, no chat


def test_anthropic_key_is_ignored_auto_still_uses_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("JARVIS_BRAIN", "auto")
    monkeypatch.setenv("OLLAMA_HOST", OLLAMA_HOST)
    for var in ("JARVIS_MODEL", "OLLAMA_MODEL"):
        monkeypatch.delenv(var, raising=False)
    fake = _fake(monkeypatch, ollama_text("hi"))

    provider, ok, _why = brain.resolve_provider()
    assert (provider, ok) == ("ollama", True)
    res = brain.ask("q", "dottie", FakeState())
    assert res["ok"] is True and res["provider"] == "ollama"
    assert fake.chats[0]["payload"]["model"] == "qwen3:8b"


def test_harness_route_tool_uses_scout_router(
    ollama_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("bigbang.plugins.harness.cli")
    goal = "compare Stripe vs Lemon Squeezy Aug 2026"
    fake = _fake(monkeypatch, ollama_tool(("harness_route", {"goal": goal})), ollama_text("ok"))

    res = brain.ask("route this", "dottie", FakeState())

    assert res["ok"] is True
    tool_msg = next(m for m in fake.chats[1]["payload"]["messages"] if m["role"] == "tool")
    routed = json.loads(tool_msg["content"])
    assert routed["intent"] == "deep_research"
    assert routed["moma_tier"] == "deep_research"
    assert "deep-researcher" in routed["routed_agents"]
    assert 0 < routed["confidence"] <= 0.96


def test_missing_state_method_is_a_tool_error_not_a_raise(
    ollama_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ThinState:
        def context(self, agent: str, repo: str | None) -> dict[str, Any]:
            return {}

        def timeline_add(self, *args: Any) -> None:
            pass

    fake = _fake(monkeypatch, ollama_tool(("jarvis_recall", {"query": "x"})), ollama_text("ok"))

    res = brain.ask("q", "dottie", ThinState())

    assert res["ok"] is True
    assert res["tool_calls"][0]["ok"] is False
    tool_msg = next(m for m in fake.chats[1]["payload"]["messages"] if m["role"] == "tool")
    assert "state has no method 'recall'" in json.loads(tool_msg["content"])["error"]


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
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")  # env beats the qwen3:8b default
    monkeypatch.setenv("OLLAMA_HOST", "host.docker.internal:11434/")
    fake = _fake(monkeypatch, ollama_text("hi"))

    res = brain.ask("q", None, FakeState())

    assert res["ok"] is True
    call = fake.chats[0]
    assert call["url"] == "http://host.docker.internal:11434/api/chat"
    assert call["timeout"] == 7.5
    assert call["payload"]["model"] == "qwen3:4b"
    assert "Repo: (none)" in call["payload"]["messages"][1]["content"]

    monkeypatch.setenv("JARVIS_MODEL", "qwen3:14b")  # JARVIS_MODEL wins over OLLAMA_MODEL
    assert brain._resolve_ollama_model(None) == "qwen3:14b"
    assert brain._resolve_ollama_model("override") == "override"
    monkeypatch.setenv("JARVIS_BRAIN_TIMEOUT", "not-a-number")
    assert brain._resolve_timeout() == 120.0
