# Solo personal project, no connection to employer, built with public/free-tier only
"""Glaive function-calling v2 → frozen-tokenizer ReAct adapter.

Streams ``glaiveai/glaive-function-calling-v2`` (apache-2.0, verified ungated
2026-07-19) records — ``system`` (function definitions) + ``chat`` (USER /
ASSISTANT / <functioncall> / FUNCTION RESPONSE turns) — into the same
plain-text Thought:/Action:/Observation: dialogues xlam_adapt emits, so the
API-call curriculum shares one action grammar across sources.

Unlike xlam, glaive carries REAL function responses, so Observations here are
genuine tool outputs, not echoes. Records without a function call (plain chat)
are kept as short assistant dialogues at reduced value (they teach when NOT to
call a tool — the negative case synth_tool_use's L5 ladder wants). Records
that fail to parse return ``None`` — skipped honestly, never patched.
"""
from __future__ import annotations

import json
import re

from dottie.datagen.xlam_adapt import ASSISTANT, USER, format_action, sanitize_tool_name

# Anchor on <|endoftext|>, not the closing brace — glaive nests JSON-in-string
# arguments, so a brace-bounded non-greedy match truncates at the first '}'.
_CALL_RE = re.compile(r"<functioncall>\s*(\{.+?\})\s*(?:<\|endoftext\|>|FUNCTION RESPONSE|$)",
                      re.DOTALL)
_RESP_RE = re.compile(r"FUNCTION RESPONSE:\s*(\{.*?\})\s*(?=ASSISTANT:|USER:|$)", re.DOTALL)
_TURN_RE = re.compile(r"(USER|ASSISTANT):\s*", re.DOTALL)


def _parse_call(raw: str) -> tuple[str, dict] | None:
    """Glaive nests arguments as a single-quoted JSON string: robustly unwrap."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # The real glaive shape: {"name": ..., "arguments": '{...}'} — inline the
        # single-quoted inner object so the whole thing parses as one document.
        try:
            obj = json.loads(re.sub(r"'(\{.*\})'", r"\1", raw, flags=re.DOTALL))
        except json.JSONDecodeError:
            return None
    name = sanitize_tool_name(obj.get("name", ""))
    if not name:
        return None
    args = obj.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    return name, args if isinstance(args, dict) else {}


def adapt_record(rec: dict) -> dict | None:
    chat = rec.get("chat") or ""
    if not isinstance(chat, str) or "USER:" not in chat:
        return None
    call_m = _CALL_RE.search(chat)
    user_head = chat.split("ASSISTANT:")[0]
    query = user_head.replace("USER:", "").strip()
    if not query:
        return None

    if call_m is None:
        if "<functioncall>" in chat:
            return None       # a call we couldn't parse is a skip, not a "no-call" example
        # No tool call: keep as a short negative-case dialogue (answer directly).
        answer = _TURN_RE.split(chat.split("ASSISTANT:", 1)[-1])[0]
        answer = answer.replace("<|endoftext|>", "").strip()
        if len(answer) < 8:
            return None
        text = (f"{USER} {query}\n{ASSISTANT} Thought: no tool is needed for this; "
                f"I answer directly.\n{answer}\n")
        return {"text": text, "_task_type": "tool_selection", "_concept": "glaive_no_call"}

    parsed = _parse_call(call_m.group(1))
    if parsed is None:
        return None
    name, args = parsed
    resp_m = _RESP_RE.search(chat, call_m.end())
    observation = resp_m.group(1).strip() if resp_m else None
    tail = chat[(resp_m.end() if resp_m else call_m.end()):]
    final = _TURN_RE.split(tail.split("ASSISTANT:", 1)[-1])[0] if "ASSISTANT:" in tail else ""
    final = final.replace("<|endoftext|>", "").strip()

    lines = [f"{USER} {query}",
             f"{ASSISTANT} Thought: this needs the {name} API.",
             f"Action: {format_action(name, args)}"]
    if observation:
        lines.append(f"Observation: {observation}")
    if final:
        lines.append(final)
    if len(lines) < 4:          # a call with neither observation nor answer teaches nothing
        return None
    return {"text": "\n".join(lines) + "\n", "_task_type": "tool_selection",
            "_concept": f"glaive_{name}"}
