# Solo personal project, no connection to employer, built with public/free-tier only
"""glaive_react adapter — real glaive-function-calling-v2 record shapes, honest skips."""

from __future__ import annotations

from dottie.datagen.adapters import ADAPTERS, apply_adapter
from dottie.datagen.glaive_adapt import adapt_record

CALL_REC = {
    "system": "SYSTEM: You are a helpful assistant with access to the following functions. "
    'Use them if required - {"name": "get_stock_price", "parameters": {...}}',
    "chat": "USER: What's Apple trading at right now? "
    'ASSISTANT: <functioncall> {"name": "get_stock_price", '
    '"arguments": \'{"symbol": "AAPL"}\'} <|endoftext|> '
    'FUNCTION RESPONSE: {"price": 227.52, "currency": "USD"} '
    "ASSISTANT: Apple is currently trading at $227.52. <|endoftext|>",
}

NO_CALL_REC = {
    "system": "SYSTEM: You are a helpful assistant.",
    "chat": "USER: What does HTTP stand for? "
    "ASSISTANT: HTTP stands for HyperText Transfer Protocol. <|endoftext|>",
}


def test_call_record_produces_full_react_cycle():
    out = adapt_record(CALL_REC)
    assert out is not None
    text = out["text"]
    # the frozen action grammar, with a REAL observation (not an echo)
    assert "Thought: this needs the get_stock_price API." in text
    assert 'Action: get_stock_price(symbol="AAPL")' in text
    assert 'Observation: {"price": 227.52' in text
    assert "trading at $227.52" in text
    assert (
        "<functioncall>" not in text and "<|endoftext|>" not in text
    )  # markup rewritten
    assert out["_task_type"] == "tool_selection"
    assert out["_concept"] == "glaive_get_stock_price"


def test_no_call_record_becomes_negative_case():
    out = adapt_record(NO_CALL_REC)
    assert out is not None
    assert "no tool is needed" in out["text"]
    assert "HyperText Transfer Protocol" in out["text"]
    assert out["_concept"] == "glaive_no_call"


def test_garbage_records_skip_honestly():
    assert adapt_record({}) is None
    assert adapt_record({"chat": "ASSISTANT: hello"}) is None  # no user turn
    assert (
        adapt_record(
            {"chat": "USER: hi ASSISTANT: <functioncall> not-json <|endoftext|>"}
        )
        is None
    )  # unparseable call
    # deterministic: same record, same output
    assert adapt_record(CALL_REC) == adapt_record(CALL_REC)


def test_registered_in_adapters():
    assert "glaive_react" in ADAPTERS
    assert (
        apply_adapter("glaive_react", CALL_REC)["_concept"] == "glaive_get_stock_price"
    )
