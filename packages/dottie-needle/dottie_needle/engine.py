"""Guided generation loop: retrieve, prompt, extract, validate, repair, fail closed.

Mirrors Needle 3's runtime shape, natively:
- **tool retrieval**: the intent is scored against tool descriptions and only
  the top-k tools enter the prompt; the grammar is compiled over that subset,
  so unselected tools are unreachable in the emitted call;
- **triggers**: case-insensitive regexes on the intent force-include (and
  restrict to) matched tools;
- **reasoning unconstrained, call grammar-bound**: the model may write a
  short derivation in free text; the engine extracts the call span and
  validates it fail-closed;
- **deterministic repair**: a grammar failure is fed back verbatim (position
  + expectation) for up to N attempts, then the engine refuses loudly instead
  of emitting a guess.

The ``sampler`` is any callable ``prompt -> text`` (Ollama, our Tier 2
sampler, or a mock in tests). This module never executes or authorizes calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from dottie_needle.grammar import CompiledGrammar, GrammarError, ToolSpec

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class NoValidCallError(ValueError):
    """Fail-closed: no grammar-valid call after max_attempts. Carries the trail."""

    def __init__(self, intent: str, attempts: list[dict[str, Any]]):
        self.intent = intent
        self.attempts = attempts
        last = attempts[-1]["error"] if attempts else "no attempts made"
        super().__init__(
            f"no grammar-valid tool call after {len(attempts)} attempt(s); "
            f"last failure: {last}"
        )


def _tokens(s: str) -> set[str]:
    return set(_TOKEN_RE.findall(s.lower()))


def retrieve_tools(
    intent: str, tools: list[ToolSpec], top_k: int = 5
) -> list[ToolSpec]:
    """Top-k tools for the intent; trigger matches pin to the front.

    Scoring is deliberately transparent stdlib token overlap (no embeddings):
    ``|intent ∩ (name+description)|``. Trigger regexes (case-insensitive)
    force-include matched tools ahead of scored ones.
    """
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    want = _tokens(intent)
    scored: list[tuple[int, int, ToolSpec]] = []
    for i, t in enumerate(tools):
        doc = _tokens(f"{t.name} {t.description}")
        scored.append((len(want & doc), -i, t))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    ranked = [t for _, _, t in scored]

    triggered: list[ToolSpec] = []
    for t in tools:
        if any(re.search(rx, intent, re.IGNORECASE) for rx in t.triggers):
            if t not in triggered:
                triggered.append(t)
    if triggered:
        rest = [t for t in ranked if t not in triggered]
        return (triggered + rest)[:top_k]
    return ranked[:top_k]


def extract_call_span(text: str) -> str | None:
    """Extract the first balanced ``{...}`` span, respecting strings/escapes."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


_PROMPT_TEMPLATE = """You are Dottie's tool router. Reply with a brief reasoning trace (free text), then emit EXACTLY ONE tool call as JSON matching the schema below. The call must be valid JSON — no trailing commas, no comments, no extra keys.

Available tools:
{schema}

Intent: {intent}

Format your reply as:

Reasoning: <one or two sentences, free text>
Call: {{"tool": "<name>", "arguments": {{...}}}}
"""


@dataclass
class GuidedCaller:
    """Generate -> extract -> validate -> repair (N attempts) -> fail closed."""

    sampler: Callable[[str], str]
    max_attempts: int = 3
    top_k: int = 5

    def __call__(self, intent: str, tools: list[ToolSpec]) -> dict[str, Any]:
        considered = retrieve_tools(intent, tools, self.top_k)
        grammar = CompiledGrammar(considered)
        prompt = _PROMPT_TEMPLATE.format(
            schema=grammar.render_schema(), intent=intent
        )
        attempts: list[dict[str, Any]] = []
        feedback = ""
        for n in range(1, self.max_attempts + 1):
            raw = self.sampler(prompt + feedback)
            span = extract_call_span(raw)
            if span is None:
                err = "no balanced {...} call span found in model output"
                attempts.append({"n": n, "raw": raw, "error": err})
                feedback = f"\nRepair: {err}. Emit the call as JSON.\n"
                continue
            try:
                call = grammar.validate_call(span)
            except GrammarError as e:
                attempts.append({"n": n, "raw": raw, "error": str(e)})
                feedback = f"\nRepair: your call failed validation: {e}. Fix it and re-emit.\n"
                continue
            attempts.append({"n": n, "raw": raw, "error": None})
            return {
                "tool": call["tool"],
                "arguments": call["arguments"],
                "attempts": n,
                "tools_considered": [t.name for t in considered],
                "trail": attempts,
            }
        raise NoValidCallError(intent, attempts)
