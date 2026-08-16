"""loop.py — the RLM loop (SPEC v1).

Contract (SPEC.md, loop.py section):

- ``run_turn(session, user_text, *, backend, ...)``: messages = effective
  prompt + history tail; ``backend.complete()``; fenced ```python blocks in
  the reply are EXECUTED in the kernel in order; everything else is
  narration. Exec results are appended as turns and fed to the next
  completion. Loop until the model replies with no code block (that reply is
  the answer) or ``max_steps`` (16) — hitting max_steps records a
  ``step-limit`` system turn honestly in the trajectory.
- The inbox is drained into the message stream at the start of every
  completion step (``inbox_drain`` is an injected callable — rlm.Runtime
  passes a closure, so loop.py never imports rlm.py and there is no import
  cycle).
- Child sessions run this same loop with ``max_steps=CHILD_MAX_STEPS`` (8).

Resolved SPEC-vs-module points (documented here, coded against the modules):

- SPEC writes the signature as ``run_turn(session, user_text)``, but a
  Session (Wave B module) holds neither a backend nor a harness, so the
  dependencies are explicit keyword-only arguments: ``backend`` (required),
  ``system_prompt`` (the harness effective prompt), ``inbox_drain``,
  ``executor``. rlm.Runtime.run_turn is the convenience wrapper that supplies
  them all.
- The kernel is built LAZILY: the default executor only calls
  ``session.ensure_kernel()`` when a code block actually needs executing, so
  a turn that never runs code never imports kernel.py/IPython (kernel.py is
  another wave's file; Session's factory handles the lazy import).
- Compaction (rlm.compact) appends a ``{"kind": "system", "event":
  "compaction"}`` marker turn instead of truncating ``session.history`` in
  place, because ``Session.save()`` refuses to save a memory history shorter
  than the on-disk trajectory (its reconciliation invariant). This module
  honors the marker: :func:`build_messages` shows the model the summary plus
  the ``keep_last`` turns preceding the marker plus everything after it —
  the model-visible context IS truncated even though the in-memory list is
  not.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .llm import Backend
    from .session import Session

__all__ = [
    "CHILD_MAX_STEPS",
    "DEFAULT_HISTORY_TAIL",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_MAX_TOKENS",
    "build_messages",
    "extract_code_blocks",
    "run_turn",
]

DEFAULT_MAX_STEPS = 16
CHILD_MAX_STEPS = 8
DEFAULT_MAX_TOKENS = 2048
#: How many trailing turns are shown to the model when no compaction applies.
DEFAULT_HISTORY_TAIL = 64
#: Defensive ceiling on stored exec fields. The kernel contract already
#: truncates stdout/stderr at 20k with its own marker; this is a wider safety
#: net so a non-conforming executor cannot bloat the trajectory.
_STORE_CLIP = 40_000

#: Fenced python blocks: ```python ... ``` (or ```py), tolerant of CRLF.
_CODE_FENCE_RE = re.compile(
    r"```(?:python|py)[ \t]*\r?\n(.*?)\r?\n?```",
    re.DOTALL | re.IGNORECASE,
)


def extract_code_blocks(text: str) -> list[str]:
    """All fenced ```python blocks in ``text``, in order. Empty blocks dropped."""
    if not isinstance(text, str) or not text:
        return []
    return [m.group(1) for m in _CODE_FENCE_RE.finditer(text) if m.group(1).strip()]


def _clip(text: str, limit: int = _STORE_CLIP) -> str:
    if len(text) <= limit:
        return text
    over = len(text) - limit
    return text[:limit] + f"...[truncated {over} chars]"


def _field(result: Any, name: str, default: Any) -> Any:
    """Duck-typed ExecResult access: dataclass/namespace attr OR mapping key."""
    if isinstance(result, Mapping):
        return result.get(name, default)
    return getattr(result, name, default)


def _format_exec(turn: dict) -> str:
    parts = ["[exec result]"]
    if turn.get("error"):
        parts.append(f"error: {turn['error']}")
    if turn.get("stdout"):
        parts.append(f"stdout:\n{turn['stdout']}")
    if turn.get("stderr"):
        parts.append(f"stderr:\n{turn['stderr']}")
    if turn.get("result_repr"):
        parts.append(f"result: {turn['result_repr']}")
    if len(parts) == 1:
        parts.append("(no output)")
    return "\n".join(parts)


def _turn_to_message(turn: dict) -> dict:
    kind = turn.get("kind")
    if kind == "model":
        return {"role": "assistant", "content": str(turn.get("text", ""))}
    if kind == "exec":
        return {"role": "user", "content": _format_exec(turn)}
    if kind == "message":
        sender = turn.get("sender", "?")
        return {"role": "user", "content": f"[message from {sender}] {turn.get('text', '')}"}
    # system turns (step-limit, compaction leftovers, custom events)
    body = {k: v for k, v in turn.items() if k not in ("t", "kind", "event")}
    rendered = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
    return {"role": "user", "content": f"[system:{turn.get('event', '?')}] {rendered}"}


def build_messages(
    system_prompt: str,
    history: list[dict],
    *,
    tail: int = DEFAULT_HISTORY_TAIL,
) -> list[dict]:
    """Chat messages for the backend: system prompt + model-visible history.

    Honors the LAST compaction marker in ``history``: the model sees the
    marker's summary, the ``keep_last`` turns immediately preceding the
    marker, and every turn after it. Without a marker, the last ``tail``
    turns are shown. ``tail`` applies in both cases as the outer bound.
    """
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    marker_idx: int | None = None
    for i in range(len(history) - 1, -1, -1):
        turn = history[i]
        if turn.get("kind") == "system" and turn.get("event") == "compaction":
            marker_idx = i
            break

    if marker_idx is None:
        visible = list(history)
    else:
        marker = history[marker_idx]
        try:
            keep = max(0, int(marker.get("keep_last") or 0))
        except (TypeError, ValueError):
            keep = 0
        window_start = max(0, marker_idx - keep)
        visible = list(history[window_start:marker_idx])
        visible += list(history[marker_idx + 1:])
        # Carry EVERY earlier compaction summary, not just this one. Honoring
        # only the LAST marker deleted the first digest along with the turns it
        # stood for: after two compactions, everything before the second window
        # vanished from the model's view AND the summary that represented it
        # went too (review finding loop.py:161). Those digests are the only
        # remaining record of the dropped turns -- losing them is the
        # difference between compaction and amnesia.
        for earlier in history[:window_start]:
            if earlier.get("kind") == "system" and earlier.get("event") == "compaction":
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"[compaction] {earlier.get('replaced_turns', '?')} "
                            f"earlier turns were summarized:\n"
                            f"{earlier.get('summary', '')}"
                        ),
                    }
                )
        messages.append(
            {
                "role": "user",
                "content": (
                    f"[compaction] {marker.get('replaced_turns', '?')} earlier "
                    f"turns were summarized:\n{marker.get('summary', '')}"
                ),
            }
        )

    if tail and tail > 0:
        visible = visible[-int(tail):]
    messages.extend(_turn_to_message(t) for t in visible)
    return messages


def run_turn(
    session: Session,
    user_text: str | None,
    *,
    backend: Backend,
    system_prompt: str = "",
    max_steps: int = DEFAULT_MAX_STEPS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    history_tail: int = DEFAULT_HISTORY_TAIL,
    inbox_drain: Callable[[], list[dict]] | None = None,
    executor: Callable[[str], Any] | None = None,
) -> dict:
    """One user turn of the RLM loop. Returns an honest result dict.

    Result: ``{"session_id", "steps", "stopped": "answer"|"step-limit",
    "answer": str|None, "last_text": str}``. ``steps`` counts completions
    that contained code (i.e. loop iterations that executed something);
    an immediate no-code answer is ``steps == 0``.

    ``max_steps`` bounds code-bearing completions: after the ``max_steps``-th
    one executes, a ``step-limit`` system turn is recorded in the trajectory
    (honestly — never disguised as an answer) and the loop stops.
    """
    if int(max_steps) < 1:
        raise ValueError(f"max_steps must be >= 1, got {max_steps!r}")

    if executor is None:
        def executor(code: str) -> Any:  # lazy: kernel only if code actually runs
            return session.ensure_kernel().run(code)

    if user_text is not None and str(user_text).strip():
        session.record_turn("message", sender="user", text=str(user_text))

    steps = 0
    while True:
        if inbox_drain is not None:
            for msg in inbox_drain():
                session.record_turn(
                    "message",
                    sender=str(msg.get("from", "?")),
                    text=str(msg.get("text", "")),
                )

        messages = build_messages(system_prompt, session.history, tail=history_tail)
        reply = backend.complete(messages, max_tokens=max_tokens)
        blocks = extract_code_blocks(reply)
        session.record_turn("model", text=reply, code_blocks=len(blocks))

        if not blocks:
            return {
                "session_id": session.id,
                "steps": steps,
                "stopped": "answer",
                "answer": reply,
                "last_text": reply,
            }

        steps += 1
        for code in blocks:
            result = executor(code)
            error = _field(result, "error", None)
            session.record_turn(
                "exec",
                code=_clip(str(code)),
                stdout=_clip(str(_field(result, "stdout", "") or "")),
                stderr=_clip(str(_field(result, "stderr", "") or "")),
                result_repr=_clip(str(_field(result, "result_repr", "") or "")),
                error=None if error is None else _clip(str(error)),
                duration_s=float(_field(result, "duration_s", 0.0) or 0.0),
            )

        if steps >= int(max_steps):
            session.record_turn(
                "system", event="step-limit", max_steps=int(max_steps), steps=steps
            )
            return {
                "session_id": session.id,
                "steps": steps,
                "stopped": "step-limit",
                "answer": None,
                "last_text": reply,
            }
