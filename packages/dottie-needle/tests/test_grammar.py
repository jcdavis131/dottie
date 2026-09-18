"""Tests for the native grammar compiler: strict, fail-closed, well-named errors."""

import pytest

from dottie_needle.grammar import CompiledGrammar, GrammarError, ToolSpec


@pytest.fixture()
def grammar():
    return CompiledGrammar(
        [
            ToolSpec(
                name="leaks_scan",
                description="Scan for leaked secrets",
                parameters={
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "fail_on": {"type": "string", "enum": ["error", "warning"]},
                        "max_commits": {"type": "integer", "minimum": 0, "maximum": 100},
                        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                        "dry": {"type": "boolean"},
                    },
                },
            ),
            ToolSpec(
                name="loop_run",
                parameters={
                    "type": "object",
                    "required": ["goal_id"],
                    "properties": {"goal_id": {"type": "string", "pattern": r"^g[0-9]+$"}},
                },
            ),
        ]
    )


def test_valid_call(grammar):
    call = grammar.validate_call(
        '{"tool": "leaks_scan", "arguments": {"path": ".", "fail_on": "error"}}'
    )
    assert call == {"tool": "leaks_scan", "arguments": {"path": ".", "fail_on": "error"}}


def test_key_order_either_way(grammar):
    call = grammar.validate_call(
        '{"arguments": {"goal_id": "g7"}, "tool": "loop_run"}'
    )
    assert call["tool"] == "loop_run"


def test_whitespace_tolerant(grammar):
    call = grammar.validate_call('{\n  "tool" : "loop_run" ,\n "arguments" : { "goal_id" : "g1" } }')
    assert call["arguments"] == {"goal_id": "g1"}


def test_unknown_tool_rejected(grammar):
    with pytest.raises(GrammarError, match="unknown tool"):
        grammar.validate_call('{"tool": "nope", "arguments": {}}')


def test_missing_required_rejected(grammar):
    with pytest.raises(GrammarError, match="missing required"):
        grammar.validate_call('{"tool": "leaks_scan", "arguments": {"fail_on": "error"}}')


def test_bad_enum_rejected(grammar):
    with pytest.raises(GrammarError, match="not in enum"):
        grammar.validate_call(
            '{"tool": "leaks_scan", "arguments": {"path": ".", "fail_on": "ERROR"}}'
        )


def test_pattern_violation_rejected(grammar):
    with pytest.raises(GrammarError, match="pattern"):
        grammar.validate_call('{"tool": "loop_run", "arguments": {"goal_id": "abc"}}')


def test_integer_range_rejected(grammar):
    with pytest.raises(GrammarError, match="maximum"):
        grammar.validate_call(
            '{"tool": "leaks_scan", "arguments": {"path": ".", "max_commits": 500}}'
        )
    with pytest.raises(GrammarError, match="integer"):
        grammar.validate_call(
            '{"tool": "leaks_scan", "arguments": {"path": ".", "max_commits": 2.5}}'
        )


def test_array_limits(grammar):
    with pytest.raises(GrammarError, match="maxItems"):
        grammar.validate_call(
            '{"tool": "leaks_scan", "arguments": {"path": ".", "tags": ["a","b","c","d"]}}'
        )
    ok = grammar.validate_call(
        '{"tool": "leaks_scan", "arguments": {"path": ".", "tags": ["a","b"]}}'
    )
    assert ok["arguments"]["tags"] == ["a", "b"]


def test_trailing_garbage_rejected(grammar):
    with pytest.raises(GrammarError, match="trailing"):
        grammar.validate_call('{"tool": "loop_run", "arguments": {"goal_id": "g1"}} extra')


def test_duplicate_keys_rejected(grammar):
    with pytest.raises(GrammarError, match="duplicate key"):
        grammar.validate_call(
            '{"tool": "loop_run", "tool": "loop_run", "arguments": {"goal_id": "g1"}}'
        )


def test_trailing_comma_rejected(grammar):
    with pytest.raises(GrammarError, match="trailing comma"):
        grammar.validate_call('{"tool": "loop_run", "arguments": {"goal_id": "g1",}}')


def test_unknown_argument_key_rejected(grammar):
    with pytest.raises(GrammarError, match="unknown key"):
        grammar.validate_call('{"tool": "loop_run", "arguments": {"goal_id": "g1", "zzz": 1}}')


def test_not_json_rejected(grammar):
    with pytest.raises(GrammarError):
        grammar.validate_call("hello world")


def test_unknown_call_key_rejected(grammar):
    with pytest.raises(GrammarError, match="unknown call key"):
        grammar.validate_call('{"tool": "loop_run", "arguments": {"goal_id": "g1"}, "extra": 1}')


def test_string_escapes_and_unicode(grammar):
    call = grammar.validate_call(
        '{"tool": "leaks_scan", "arguments": {"path": "a\\"b\\u0041"}}'
    )
    assert call["arguments"]["path"] == 'a"bA'


def test_empty_tool_list_rejected():
    with pytest.raises(GrammarError, match="zero tools"):
        CompiledGrammar([])


def test_duplicate_tool_names_rejected():
    with pytest.raises(GrammarError, match="duplicate tool name"):
        CompiledGrammar([ToolSpec(name="a"), ToolSpec(name="a")])


def test_bad_tool_name_rejected():
    with pytest.raises(GrammarError):
        ToolSpec(name="Bad Name!")


def test_render_schema_lists_tools(grammar):
    s = grammar.render_schema()
    assert "leaks_scan" in s and "loop_run" in s and "fail_on" in s


def test_error_names_position():
    g = CompiledGrammar([ToolSpec(name="a", parameters={"type": "object", "properties": {}})])
    with pytest.raises(GrammarError) as ei:
        g.validate_call('{"tool": "a", "arguments": {"x": }}')
    assert ei.value.position is not None
