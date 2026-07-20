# Solo personal project, no connection to employer, built with public/free-tier only
"""conversations_react adapter — both field conventions, tool turns, honest None."""

from __future__ import annotations

from dottie.datagen.adapters import ADAPTERS, apply_adapter
from dottie.datagen.conv_react import ASSISTANT, TOOL, USER, adapt_record


def test_role_content_convention_codeact_style():
    rec = {
        "conversations": [
            {"role": "system", "content": "You are an agent."},
            {"role": "user", "content": "list files then count them"},
            {"role": "assistant", "content": "ls -1"},
            {"role": "user", "content": "OBSERVATION: a.txt\nb.txt"},
            {"role": "assistant", "content": "ls -1 | wc -l  # 2 files"},
        ]
    }
    out = adapt_record(rec)
    assert out is not None and out["_task_type"] == "tool_selection"
    assert out["text"].count(ASSISTANT) == 2 and USER in out["text"]
    assert "wc -l" in out["text"]


def test_from_value_convention_with_tool_turns_toolace_style():
    rec = {
        "system": "Tools: get_weather(city)",
        "conversations": [
            {"from": "user", "value": "weather in Oslo?"},
            {"from": "assistant", "value": "get_weather(city='Oslo')"},
            {"from": "tool", "value": '{"temp_c": 4}'},
            {"from": "assistant", "value": "4°C in Oslo right now."},
        ],
    }
    out = adapt_record(rec)
    assert out is not None
    assert TOOL in out["text"]  # observation structure preserved
    assert out["text"].index("Tools:") < out["text"].index("weather in Oslo?")


def test_degenerate_records_return_none_not_junk():
    assert adapt_record({"conversations": []}) is None
    assert (
        adapt_record({"conversations": [{"from": "user", "value": "hi"}]}) is None
    )  # no assistant
    assert adapt_record({"text": "not a conversation"}) is None


def test_registered_and_dispatchable():
    assert "conversations_react" in ADAPTERS
    out = apply_adapter(
        "conversations_react",
        {
            "conversations": [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"},
            ]
        },
    )
    assert out and out["text"].endswith("a")
