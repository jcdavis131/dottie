"""Native grammar compiler: tool schemas -> fail-closed call validator.

This is the load-bearing trick of the Needle concept, reimplemented as stdlib
Python: at init, tool JSON schemas are compiled into a strict grammar. Every
emitted call is validated against it **fail-closed** — a malformed call is
rejected at the gate with the position and expectation named, and never
reaches Dottie's tool plane.

Scope notes (honest, by design):
- This module validates *complete* call texts. Per-step "invalid is
  unreachable" masking needs a sampler we own (Tier 2's inference engine);
  here invalid is *rejected*, which is the same guarantee at the gate.
- The model's reasoning trace is intentionally NOT constrained — only the
  call envelope ``{"tool": ..., "arguments": {...}}`` is grammar-bound.
- Authorization and execution live in ``dottie_loop``; this module never
  authorizes or runs anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_WS = " \t\n\r"
_NUMBER_RE = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_INT_RE = re.compile(r"-?(?:0|[1-9]\d*)")
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class GrammarError(ValueError):
    """Fail-closed: the call text does not satisfy the compiled grammar."""

    def __init__(self, message: str, position: int | None = None, expected: str | None = None):
        self.position = position
        self.expected = expected
        loc = f" at char {position}" if position is not None else ""
        hint = f" (expected {expected})" if expected else ""
        super().__init__(f"{message}{loc}{hint}")


@dataclass(frozen=True)
class ToolSpec:
    """One tool the grammar is compiled over."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    triggers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise GrammarError(f"tool name {self.name!r} must match {_NAME_RE.pattern}")
        params = self.parameters or {"type": "object"}
        if not isinstance(params, dict) or params.get("type", "object") != "object":
            raise GrammarError(f"tool {self.name!r}: parameters must be an object schema")
        for t in self.triggers:
            try:
                re.compile(t, re.IGNORECASE)
            except re.error as e:
                raise GrammarError(f"tool {self.name!r}: bad trigger regex {t!r}: {e}") from e


class CompiledGrammar:
    """Tool specs compiled into a strict, fail-closed call validator."""

    def __init__(self, tools: list[ToolSpec]):
        tools = list(tools)
        if not tools:
            raise GrammarError("cannot compile a grammar over zero tools")
        seen: set[str] = set()
        for t in tools:
            if t.name in seen:
                raise GrammarError(f"duplicate tool name {t.name!r}")
            seen.add(t.name)
        self._tools: dict[str, ToolSpec] = {t.name: t for t in tools}
        # Pre-compile string patterns so a bad pattern fails at compile time.
        self._patterns: dict[tuple[str, str], re.Pattern[str]] = {}
        for t in tools:
            self._collect_patterns(t.name, t.parameters or {"type": "object"}, ())

    # -- public surface ----------------------------------------------------

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def validate_call(self, text: str) -> dict[str, Any]:
        """Validate a complete call text. Returns ``{"tool", "arguments"}``.

        Raises :class:`GrammarError` fail-closed on anything else: not an
        object, unknown tool, bad arguments, trailing garbage.
        """
        p = _Parser(text)
        call = p.parse_call(self)
        p.skip_ws()
        if not p.at_end():
            p.fail("end of input — trailing characters after the call", expected="end of input")
        return call

    def render_schema(self, names: list[str] | tuple[str, ...] | None = None) -> str:
        """Compact schema rendering for model prompts (one line per tool)."""
        names = list(names) if names is not None else list(self._tools)
        lines = []
        for n in names:
            t = self._tools[n]
            sig = _render_object_sig(t.parameters or {"type": "object"})
            desc = f": {t.description}" if t.description else ""
            lines.append(f"- {n}{sig}{desc}")
        return "\n".join(lines)

    # -- internals ----------------------------------------------------------

    def _collect_patterns(self, tool: str, schema: dict[str, Any], path: tuple[str, ...]) -> None:
        pat = schema.get("pattern")
        if isinstance(pat, str):
            try:
                self._patterns[(tool, "/".join(path))] = re.compile(pat)
            except re.error as e:
                raise GrammarError(f"tool {tool!r}: bad pattern {pat!r}: {e}") from e
        if schema.get("type") == "object":
            for k, sub in (schema.get("properties") or {}).items():
                if isinstance(sub, dict):
                    self._collect_patterns(tool, sub, path + (k,))
        if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
            self._collect_patterns(tool, schema["items"], path + ("[]",))

    def _pattern(self, tool: str, path: tuple[str, ...]) -> re.Pattern[str] | None:
        return self._patterns.get((tool, "/".join(path)))


def _render_object_sig(schema: dict[str, Any]) -> str:
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    parts = []
    for k, sub in props.items():
        parts.append(_render_param(k, sub, k in required))
    return "(" + ", ".join(parts) + ")"


def _render_param(name: str, schema: dict[str, Any], required: bool) -> str:
    t = schema.get("type", "string")
    if "enum" in schema:
        r = " | ".join(json_scalar(v) for v in schema["enum"])
    elif t == "string":
        r = "string"
    elif t == "integer":
        lo, hi = schema.get("minimum", ""), schema.get("maximum", "")
        r = f"int {lo}..{hi}".strip()
    elif t == "number":
        r = "number"
    elif t == "boolean":
        r = "bool"
    elif t == "array":
        r = "array"
    elif t == "object":
        r = "object"
    else:
        r = t
    if "default" in schema and not required:
        r += f" = {json_scalar(schema['default'])}"
    mark = "" if required else "?"
    return f"{name}{mark}: {r}"


def json_scalar(v: Any) -> str:
    if isinstance(v, str):
        return f'"{v}"'
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    return str(v)


class _Parser:
    """Strict recursive-descent, schema-directed JSON parser."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self._tool = ""  # tool context for pattern lookup
        self._path: tuple[str, ...] = ()
        self._grammar: CompiledGrammar | None = None

    # -- primitives ---------------------------------------------------------

    def at_end(self) -> bool:
        return self.pos >= len(self.text)

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def fail(self, message: str, expected: str | None = None) -> Any:
        raise GrammarError(message, position=self.pos, expected=expected)

    def skip_ws(self) -> None:
        # NOTE: compare against len(text), not `self.peek() in _WS`, because
        # peek() returns "" past the end and "" is "in" every string.
        while self.pos < len(self.text) and self.text[self.pos] in _WS:
            self.pos += 1

    def expect(self, ch: str) -> None:
        if self.peek() != ch:
            self.fail(f"expected {ch!r}, found {self.peek()!r}", expected=repr(ch))
        self.pos += 1

    def parse_string(self) -> str:
        if self.peek() != '"':
            self.fail("expected string", expected='"..."')
        self.pos += 1
        out: list[str] = []
        while True:
            if self.at_end():
                self.fail("unterminated string", expected='"')
            c = self.text[self.pos]
            if c == '"':
                self.pos += 1
                return "".join(out)
            if c == "\\":
                self.pos += 1
                if self.at_end():
                    self.fail("unterminated escape", expected="escape sequence")
                e = self.text[self.pos]
                if e == "u":
                    hex4 = self.text[self.pos + 1 : self.pos + 5]
                    if len(hex4) != 4 or not all(x in "0123456789abcdefABCDEF" for x in hex4):
                        self.fail("bad \\u escape", expected="4 hex digits")
                    out.append(chr(int(hex4, 16)))
                    self.pos += 5
                elif e in _ESCAPES:
                    out.append(_ESCAPES[e])
                    self.pos += 1
                else:
                    self.fail(f"bad escape \\{e}", expected="valid escape")
            elif ord(c) < 0x20:
                self.fail("unescaped control character in string", expected="escaped")
            else:
                out.append(c)
                self.pos += 1

    def parse_number(self) -> int | float:
        m = _NUMBER_RE.match(self.text, self.pos)
        if not m:
            self.fail("expected number", expected="JSON number")
        raw = m.group(0)
        self.pos = m.end()
        if "." not in raw and "e" not in raw and "E" not in raw:
            return int(raw)
        return float(raw)

    def parse_literal(self, word: str, value: Any) -> Any:
        if not self.text.startswith(word, self.pos):
            self.fail(f"expected {word}", expected=word)
        self.pos += len(word)
        return value

    # -- schema-directed values ----------------------------------------------

    def parse_value(self, schema: dict[str, Any]) -> Any:
        self.skip_ws()
        if "const" in schema:
            v = self.parse_generic()
            if v != schema["const"]:
                self.fail(f"value {v!r} != const {schema['const']!r}", expected=repr(schema["const"]))
            return v
        t = schema.get("type")
        if t is None:
            return self.parse_generic()
        if t == "object":
            v = self.parse_object(schema)
        elif t == "array":
            v = self.parse_array(schema)
        elif t == "string":
            v = self.parse_string()
            self.check_string(v, schema)
        elif t == "integer":
            v = self.parse_integer()
            self.check_number(v, schema)
        elif t == "number":
            v = self.parse_number()
            self.check_number(v, schema)
        elif t == "boolean":
            c = self.peek()
            v = self.parse_literal("true", True) if c == "t" else self.parse_literal("false", False)
        elif t == "null":
            v = self.parse_literal("null", None)
        else:
            self.fail(f"unsupported schema type {t!r}", expected="known type")
        if "enum" in schema and v not in schema["enum"]:
            self.fail(f"value {v!r} not in enum {schema['enum']!r}", expected="one of enum")
        return v

    def parse_generic(self) -> Any:
        """Parse any JSON value (used for const comparison / open content)."""
        self.skip_ws()
        c = self.peek()
        if c == '"':
            return self.parse_string()
        if c == "{":
            return self.parse_object({})
        if c == "[":
            return self.parse_array({})
        if c == "t":
            return self.parse_literal("true", True)
        if c == "f":
            return self.parse_literal("false", False)
        if c == "n":
            return self.parse_literal("null", None)
        return self.parse_number()

    def parse_integer(self) -> int:
        self.skip_ws()
        m = _INT_RE.match(self.text, self.pos)
        if not m:
            self.fail("expected integer", expected="integer")
        # Reject 1.5 / 1e3 masquerading as integers: next char must not continue a number.
        nxt = self.text[m.end() : m.end() + 1]
        if nxt in (".", "e", "E"):
            self.fail("expected integer", expected="integer (no fraction/exponent)")
        self.pos = m.end()
        return int(m.group(0))

    def check_string(self, v: str, schema: dict[str, Any]) -> None:
        if "minLength" in schema and len(v) < schema["minLength"]:
            self.fail(f"string shorter than minLength {schema['minLength']}", expected="longer string")
        if "maxLength" in schema and len(v) > schema["maxLength"]:
            self.fail(f"string longer than maxLength {schema['maxLength']}", expected="shorter string")
        pat = None
        if self._grammar is not None:
            pat = self._grammar._pattern(self._tool, self._path)
        if pat is not None and not pat.fullmatch(v):
            self.fail(f"string {v!r} does not match pattern {pat.pattern!r}", expected="matching string")

    def check_number(self, v: int | float, schema: dict[str, Any]) -> None:
        if "minimum" in schema and v < schema["minimum"]:
            self.fail(f"{v} < minimum {schema['minimum']}", expected="in-range number")
        if "maximum" in schema and v > schema["maximum"]:
            self.fail(f"{v} > maximum {schema['maximum']}", expected="in-range number")

    def parse_object(self, schema: dict[str, Any]) -> dict[str, Any]:
        self.skip_ws()
        self.expect("{")
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        additional = schema.get("additionalProperties", False)
        out: dict[str, Any] = {}
        self.skip_ws()
        if self.peek() == "}":
            self.pos += 1
        else:
            while True:
                self.skip_ws()
                key = self.parse_string()
                if key in out:
                    self.fail(f"duplicate key {key!r}", expected="unique keys")
                self.skip_ws()
                self.expect(":")
                sub = props.get(key)
                if sub is None:
                    if additional is False:
                        self.fail(f"unknown key {key!r}", expected="declared property")
                    sub = additional if isinstance(additional, dict) else {}
                save_path = self._path
                self._path = save_path + (key,)
                try:
                    out[key] = self.parse_value(sub)
                finally:
                    self._path = save_path
                self.skip_ws()
                c = self.peek()
                if c == ",":
                    self.pos += 1
                    self.skip_ws()
                    if self.peek() == "}":
                        self.fail("trailing comma", expected="property")
                    continue
                if c == "}":
                    self.pos += 1
                    break
                self.fail(f"expected ',' or '}}', found {c!r}", expected="',' or '}'")
        missing = required - out.keys()
        if missing:
            self.fail(f"missing required keys {sorted(missing)!r}", expected="required keys")
        return out

    def parse_array(self, schema: dict[str, Any]) -> list[Any]:
        self.skip_ws()
        self.expect("[")
        items = schema.get("items")
        out: list[Any] = []
        self.skip_ws()
        if self.peek() == "]":
            self.pos += 1
        else:
            idx = 0
            while True:
                save_path = self._path
                self._path = save_path + ("[]",)
                try:
                    out.append(self.parse_value(items if isinstance(items, dict) else {}))
                finally:
                    self._path = save_path
                idx += 1
                self.skip_ws()
                c = self.peek()
                if c == ",":
                    self.pos += 1
                    self.skip_ws()
                    if self.peek() == "]":
                        self.fail("trailing comma", expected="item")
                    continue
                if c == "]":
                    self.pos += 1
                    break
                self.fail(f"expected ',' or ']', found {c!r}", expected="',' or ']'")
        if "minItems" in schema and len(out) < schema["minItems"]:
            self.fail(f"array shorter than minItems {schema['minItems']}", expected="longer array")
        if "maxItems" in schema and len(out) > schema["maxItems"]:
            self.fail(f"array longer than maxItems {schema['maxItems']}", expected="shorter array")
        return out

    # -- the call envelope -----------------------------------------------------

    def parse_call(self, grammar: CompiledGrammar) -> dict[str, Any]:
        self._grammar = grammar
        self.skip_ws()
        self.expect("{")
        tool_name: str | None = None
        arguments: dict[str, Any] | None = None
        arguments_deferred = False
        seen: set[str] = set()
        self.skip_ws()
        if self.peek() == "}":
            self.fail("empty call object", expected='"tool" and "arguments"')
        while True:
            self.skip_ws()
            key = self.parse_string()
            if key in seen:
                self.fail(f"duplicate key {key!r}", expected="unique keys")
            seen.add(key)
            self.skip_ws()
            self.expect(":")
            self.skip_ws()
            if key == "tool":
                tool_name = self.parse_string()
                if tool_name not in grammar._tools:
                    self.fail(
                        f"unknown tool {tool_name!r}",
                        expected=f"one of {sorted(grammar._tools)}",
                    )
            elif key == "arguments":
                if tool_name is None:
                    # Arguments before tool: parse permissively, re-validate
                    # against the tool's schema once the name is known.
                    arguments = self.parse_object(
                        {"type": "object", "additionalProperties": True}
                    )
                    arguments_deferred = True
                else:
                    self._tool = tool_name
                    try:
                        arguments = self.parse_object(
                            grammar._tools[tool_name].parameters or {"type": "object"}
                        )
                    finally:
                        self._tool = ""
                    if not isinstance(arguments, dict):
                        self.fail("arguments must be an object", expected="object")
            else:
                self.fail(f"unknown call key {key!r}", expected='"tool" or "arguments"')
            self.skip_ws()
            c = self.peek()
            if c == ",":
                self.pos += 1
                continue
            if c == "}":
                self.pos += 1
                break
            self.fail(f"expected ',' or '}}', found {c!r}", expected="',' or '}'")
        if tool_name is None:
            self.fail("call is missing \"tool\"", expected='"tool"')
        if arguments is None:
            self.fail("call is missing \"arguments\"", expected='"arguments"')
        if arguments_deferred:
            # Parsed permissively because it came before "tool": validate now.
            _validate_value_against(
                grammar,
                tool_name,
                arguments,
                grammar._tools[tool_name].parameters or {"type": "object"},
            )
        return {"tool": tool_name, "arguments": arguments}


def _validate_value_against(
    grammar: CompiledGrammar, tool: str, value: Any, schema: dict[str, Any]
) -> None:
    """Re-validate an already-parsed value against a schema (fail-closed)."""
    import json as _json

    text = _json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    p = _Parser(text)
    p._grammar = grammar
    p._tool = tool
    p.parse_value(schema)
    p.skip_ws()
    if not p.at_end():
        p.fail("trailing characters", expected="end of input")
