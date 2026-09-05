"""jarvisd brain — offline tests with a scripted fake client (spec §6).

No network: the fake client's ``stream()`` context manager hands back scripted
Message-like objects, and the FakeState is an in-memory stand-in for the real
SQLite State with the same method names.
"""

from __future__ import annotations

import json
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
