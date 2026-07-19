"""Shared rendering helpers for Execution-Trace Chain-of-Thought (ET-CoT)
docs (db_trace.py, compress_trace.py).

ET-CoT docs teach the model to *simulate* a systems algorithm rather than
memorize its description. Every doc is a triplet rendered as one text blob:

    (Input State)      -- the task statement, with the complete starting
                          state (pages, buckets, byte streams) inlined so the
                          trace is derivable from the doc alone;
    (Execution Trace)  -- inside <think>...</think>, one "[step N]"-prefixed
                          line per state transition, every number computed by
                          actually running the algorithm in Python;
    (Final Output)     -- inside <answer>...</answer>, the terminal state.

Context-window management (the reason this module exists as shared code):
detailed traces are token-hungry, so every generator sizes its traces to the
curriculum phase it is emitting for (see PHASE_CHAR_BUDGET) and, when a trace
would still overflow, compresses the middle with `elide()` -- an explicit
"[.. K steps elided ..]" block that carries a *computed* state checkpoint, so
the doc stays verifiable end-to-end and the model learns to re-anchor from a
checkpoint instead of replaying every step. Step markers double as chunk
boundaries for Chonkie's RecursiveChunker, so a chunk never starts mid-state.
"""

from __future__ import annotations

THINK_OPEN, THINK_CLOSE = "<think>", "</think>"
ANSWER_OPEN, ANSWER_CLOSE = "<answer>", "</answer>"

#: Chat-turn markers, identical to chat_safety.py / react_tools.py so SFT
#: packs mixing those corpora with re-rendered ET-CoT docs share one dialect.
CHAT_USER, CHAT_ASSISTANT = "<|user|>", "<|assistant|>"

#: Rough char budget per curriculum phase for a whole doc, derived from the
#: phase seq_len schedule in dolma_config.yaml at ~4 chars/token. Phase 4
#: intentionally targets the spec-02 long-doc band (6000-12000 chars) rather
#: than the full 32k+ seq_len: long-context batches are built by packing.
PHASE_CHAR_BUDGET = {2: 4000, 3: 16000, 4: 12000}

#: Trace-step ceiling per phase before elide() kicks in. Phase 3 is where the
#: checkpoint-elision technique is deliberately exercised (medium inputs, hard
#: budget); phases 2 and 4 emit full traces (p2 inputs are small, p4 docs are
#: long-context material and *want* the full trace).
PHASE_ELIDE_OVER = {2: 10 ** 9, 3: 28, 4: 10 ** 9}


def render_etcot(task: str, think_lines: list[str], answer_lines: list[str]) -> str:
    """Assemble the (Input State, Execution Trace, Final Output) triplet."""
    parts = [task.rstrip("\n"), "", THINK_OPEN]
    parts.extend(think_lines)
    parts.append(THINK_CLOSE)
    parts.append(ANSWER_OPEN)
    parts.extend(answer_lines)
    parts.append(ANSWER_CLOSE)
    return "\n".join(parts)


def to_chat(text: str) -> str:
    """Re-render an ET-CoT pretraining doc as an R1-style chat SFT sample.

    The task statement (everything before the trace) becomes the user turn;
    the <think> trace plus <answer> block become the assistant turn. Purely a
    re-framing -- the trace and answer bytes are untouched, so everything the
    generators asserted about them still holds.
    """
    task, trace = text.split(f"\n\n{THINK_OPEN}\n", 1)
    return f"{CHAT_USER}\n{task}\n{CHAT_ASSISTANT}\n{THINK_OPEN}\n{trace}"


def elide(steps: list[str], states: list[str], elide_over: int,
          keep_head: int = 10, keep_tail: int = 4) -> list[str]:
    """Compress the middle of a long step trace with a state checkpoint.

    Call ``step_lines()`` *before* this so the surviving lines keep their
    original step numbers and the checkpoint's "before step N" reference
    stays consistent. ``states[i]`` must be the (computed, true) machine
    state *after* ``steps[i]`` executed; the checkpoint emitted is the state
    at the resume point, so the tail of the trace remains verifiable without
    the middle.
    """
    if len(steps) <= elide_over or len(steps) <= keep_head + keep_tail + 1:
        return list(steps)
    omitted = len(steps) - keep_head - keep_tail
    resume = len(steps) - keep_tail
    checkpoint = states[resume - 1]
    marker = (
        f"[.. {omitted} steps elided to fit the trace budget; "
        f"state checkpoint before step {resume + 1}: {checkpoint} ..]"
    )
    return steps[:keep_head] + [marker] + steps[-keep_tail:]


def step_lines(raw: list[str]) -> list[str]:
    """Prefix each line with its 1-based '[step N]' marker (elision markers,
    which arrive pre-bracketed, are left untouched)."""
    out = []
    n = 0
    for line in raw:
        if line.startswith("[.."):
            out.append(line)
        else:
            n += 1
            out.append(f"[step {n}] {line}")
    return out
