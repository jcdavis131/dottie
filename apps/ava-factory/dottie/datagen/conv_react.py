# Solo personal project, no connection to employer, built with public/free-tier only
"""Generic conversation-list -> training-text adapter (``conversations_react``).

Flattens multi-turn agent/tool dialogues into the same marker format
``xlam_adapt`` emits, handling both field conventions in the wild:

    [{"role": "user", "content": ...}, ...]      (code-act / OpenAI style)
    [{"from": "user", "value": ...}, ...]        (ToolACE / ShareGPT style)

Tool/observation turns keep their own marker so the model sees the
act -> observe -> continue structure of multi-step workflows, not a blur of
assistant text. Degenerate records (no turns, no assistant turn, empty text)
return None and are skipped by the collector — never emitted as junk.
"""

from __future__ import annotations

from typing import Any

SYSTEM = "<|system|>"
USER = "<|user|>"
ASSISTANT = "<|assistant|>"
TOOL = "<|tool|>"

_MARKERS = {
    "system": SYSTEM,
    "user": USER,
    "human": USER,
    "assistant": ASSISTANT,
    "gpt": ASSISTANT,
    "tool": TOOL,
    "observation": TOOL,
    "function": TOOL,
}


def adapt_record(rec: dict) -> dict[str, Any] | None:
    conv = rec.get("conversations")
    if not isinstance(conv, list) or not conv:
        return None
    parts: list[str] = []
    system = rec.get("system")
    if isinstance(system, str) and system.strip():
        parts.append(f"{SYSTEM}\n{system.strip()}")
    has_assistant = False
    for turn in conv:
        if not isinstance(turn, dict):
            return None
        role = str(turn.get("role") or turn.get("from") or "").strip().lower()
        text = turn.get("content") if "content" in turn else turn.get("value")
        if not isinstance(text, str) or not text.strip():
            continue
        marker = _MARKERS.get(role)
        if marker is None:
            continue
        if marker is ASSISTANT:
            has_assistant = True
        parts.append(f"{marker}\n{text.strip()}")
    if not has_assistant or len(parts) < 2:
        return None
    return {"text": "\n".join(parts), "_task_type": "tool_selection"}
