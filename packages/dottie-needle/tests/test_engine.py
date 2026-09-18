"""Tests for the guided loop: retrieval, repair, fail-closed refusal."""

import pytest

from dottie_needle.engine import (
    GuidedCaller,
    NoValidCallError,
    extract_call_span,
    retrieve_tools,
)
from dottie_needle.grammar import ToolSpec

TOOLS = [
    ToolSpec(name="leaks_scan", description="Scan the repo for leaked secrets",
             parameters={"type": "object", "required": ["path"],
                         "properties": {"path": {"type": "string"}}},
             triggers=("leak", "secret")),
    ToolSpec(name="lint", description="Run ruff lint over a path",
             parameters={"type": "object", "required": ["path"],
                         "properties": {"path": {"type": "string"}}},
             triggers=("lint",)),
    ToolSpec(name="plan_validate", description="Validate the plan graph",
             parameters={"type": "object", "properties": {}}),
]


def test_trigger_pins_tool_first():
    got = retrieve_tools("there may be a leaked secret here", TOOLS, top_k=2)
    assert got[0].name == "leaks_scan"


def test_top_k_respected():
    assert len(retrieve_tools("scan lint plan", TOOLS, top_k=2)) == 2


def test_top_k_zero_rejected():
    with pytest.raises(ValueError):
        retrieve_tools("x", TOOLS, top_k=0)


def test_extract_balanced_span():
    text = 'Reasoning: ok.\nCall: {"tool": "lint", "arguments": {"path": "a{b}c"}} trailing'
    assert extract_call_span(text) == '{"tool": "lint", "arguments": {"path": "a{b}c"}}'


def test_extract_none_when_absent():
    assert extract_call_span("just prose, no json") is None


def test_guided_caller_perfect_sampler():
    def sampler(prompt):
        assert "leaks_scan" in prompt  # schema rendered into the prompt
        return 'Reasoning: scanning.\nCall: {"tool": "leaks_scan", "arguments": {"path": "."}}'

    res = GuidedCaller(sampler=sampler)("scan for leaked secrets", TOOLS)
    assert res["tool"] == "leaks_scan"
    assert res["arguments"] == {"path": "."}
    assert res["attempts"] == 1


def test_guided_caller_repairs_sloppy_first_attempt():
    calls = {"n": 0}

    def sampler(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return 'Call: {"tool": "leaks_scan", "arguments": {"path": ".",},}'  # trailing comma
        assert "Repair" in prompt  # the grammar error was fed back
        return 'Call: {"tool": "leaks_scan", "arguments": {"path": "."}}'

    res = GuidedCaller(sampler=sampler, max_attempts=3)("scan for leaked secrets", TOOLS)
    assert res["tool"] == "leaks_scan"
    assert res["attempts"] == 2


def test_guided_caller_fail_closed():
    def sampler(prompt):
        return "prose forever, never a call"

    with pytest.raises(NoValidCallError, match="no grammar-valid tool call"):
        GuidedCaller(sampler=sampler, max_attempts=2)("scan", TOOLS)


def test_unselected_tools_unreachable():
    # top_k=1 with a lint intent: leaks_scan is out of the grammar entirely.
    def sampler(prompt):
        return 'Call: {"tool": "leaks_scan", "arguments": {"path": "."}}'

    with pytest.raises(NoValidCallError):
        GuidedCaller(sampler=sampler, max_attempts=1, top_k=1)("run ruff lint", TOOLS)
