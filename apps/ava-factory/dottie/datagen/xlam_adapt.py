"""xLAM / APIGen → frozen-tokenizer ReAct adapter (Spec 15).

Streams ``Salesforce/xlam-function-calling-60k`` records (query / tools /
answers) into plain-text Thought:/Action:/Observation: dialogues that match
``AgenticOS/ava_bridge.py::_ACTION_RE``.

The public HF release has no execution result field, so Observations are
deterministic echoes of the chosen call (format + selection practice). Real
grounding still comes from ``synth_tool_use`` / ``synth_react``.

Collector wiring: ``adapter: xlam_react`` on an HF source. Returns a record
with ``text`` / ``_task_type`` / ``_concept``, or ``None`` to skip.
"""

from __future__ import annotations

import json
import re
from typing import Any

USER = "<|user|>"
ASSISTANT = "<|assistant|>"

# Production Action: name must be a plain identifier (no dots).
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def sanitize_tool_name(name: str) -> str | None:
    """Map API names like ``math_toolkit.sum`` → ``math_toolkit_sum``."""
    if not isinstance(name, str) or not name.strip():
        return None
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned or not _IDENT_RE.match(cleaned):
        return None
    return cleaned


def _format_arg_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    if v is None:
        return "null"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def format_action(name: str, arguments: dict | None) -> str:
    args = arguments or {}
    if not isinstance(args, dict):
        args = {}
    inner = ", ".join(f"{k}={_format_arg_value(v)}" for k, v in args.items())
    return f"{name}({inner})"


def _render_catalog(tools: list[dict]) -> str:
    lines = ["Available tools (choose the appropriate one(s)):"]
    for t in tools:
        name = sanitize_tool_name(t.get("name", ""))
        if not name:
            continue
        desc = (t.get("description") or "").strip() or "no description"
        params = t.get("parameters") or {}
        if isinstance(params, dict) and params:
            sig_bits = []
            for pk, meta in params.items():
                if isinstance(meta, dict):
                    typ = meta.get("type", "any")
                    req = "required" if meta.get("required") else "optional"
                    sig_bits.append(f"{pk}: {typ}/{req}")
                else:
                    sig_bits.append(str(pk))
            sig = f"{name}({', '.join(sig_bits)})"
        else:
            sig = f"{name}(...)"
        lines.append(f"- {sig} — {desc}")
    return "\n".join(lines)


def _dialogue(turns: list[tuple[str, str]]) -> str:
    parts = []
    for role, content in turns:
        marker = USER if role == "user" else ASSISTANT
        parts.append(f"{marker}\n{content}")
    return "\n".join(parts)


def record_to_react(rec: dict) -> dict | None:
    """Convert one xLAM row into a collector record, or None if unusable."""
    query = rec.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    tools = _loads(rec.get("tools"))
    answers = _loads(rec.get("answers"))
    if not isinstance(tools, list) or not tools:
        return None
    if not isinstance(answers, list) or not answers:
        return None

    catalog = _render_catalog(tools)
    if catalog.count("\n") < 1:
        return None

    turns: list[tuple[str, str]] = [
        ("user", f"{catalog}\n\nTask: {query.strip()}"),
    ]
    used: list[str] = []
    for ans in answers:
        if not isinstance(ans, dict):
            return None
        raw_name = ans.get("name") or ans.get("function")
        name = sanitize_tool_name(str(raw_name) if raw_name is not None else "")
        if not name:
            return None
        arguments = ans.get("arguments") or ans.get("parameters") or {}
        if isinstance(arguments, str):
            arguments = _loads(arguments)
        if not isinstance(arguments, dict):
            arguments = {}
        call = format_action(name, arguments)
        used.append(name)
        turns.append(
            (
                "assistant",
                f"Thought: of the listed tools, {name} fits this step.\nAction: {call}",
            )
        )
        obs = json.dumps(
            {"ok": True, "tool": name, "arguments": arguments},
            ensure_ascii=False,
        )
        turns.append(("user", f"Observation: {obs}"))

    summary = ", ".join(used)
    turns.append(
        (
            "assistant",
            f"I selected and called: {summary}. "
            f"Each Observation echoes the chosen call (verified format).",
        )
    )
    text = _dialogue(turns)
    return {
        "text": text,
        "_task_type": "tool_selection",
        "_concept": "xlam_tool_select",
    }


def adapt_record(rec: dict) -> dict | None:
    """Collector adapter entrypoint (``adapter: xlam_react``)."""
    return record_to_react(rec)
