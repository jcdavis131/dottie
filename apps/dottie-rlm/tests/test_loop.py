"""Tests for dottie_rlm.loop — the RLM loop (SPEC floor: loop section).

Covered: scripted FakeBackend drives code-exec-code-answer; exec results are
fed to the next completion; max_steps recorded HONESTLY (step-limit system
turn in the trajectory, never disguised as an answer); inbox drained at the
start of every completion step; kernel namespace persists across steps;
compaction marker respected by build_messages; anti-vacuity (trajectory
NON-EMPTY after a scripted run). No network, no real kernel: FakeBackend +
a stub exec()-based kernel only.
"""

from __future__ import annotations

import io
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_rlm.llm import FakeBackend, FakeBackendExhausted
from dottie_rlm.loop import (
    build_messages,
    extract_code_blocks,
    run_turn,
)
from dottie_rlm.session import Session


class StubKernel:
    """Kernel-contract stand-in: persistent namespace, inject(), run().

    Executes with plain exec() so loop tests never import kernel.py/IPython
    (another wave's file). Returns an ExecResult-shaped SimpleNamespace.
    """

    def __init__(self) -> None:
        self.ns: dict = {}

    def inject(self, name: str, obj) -> None:
        self.ns[name] = obj

    def run(self, code: str):
        out, err = io.StringIO(), io.StringIO()
        error = None
        t0 = time.perf_counter()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                exec(compile(code, "<cell>", "exec"), self.ns)  # noqa: S102
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
        return SimpleNamespace(
            stdout=out.getvalue(),
            stderr=err.getvalue(),
            result_repr="",
            error=error,
            duration_s=time.perf_counter() - t0,
        )


def make_session() -> Session:
    return Session(role="root", model_spec="fake:", kernel_factory=StubKernel)


# ---------------------------------------------------------------------------
# extract_code_blocks
# ---------------------------------------------------------------------------


def test_extract_code_blocks_basic_and_ordering() -> None:
    text = "intro\n```python\na = 1\n```\nmiddle\n```py\nb = 2\n```\ndone"
    assert extract_code_blocks(text) == ["a = 1", "b = 2"]


def test_extract_code_blocks_crlf_and_empty() -> None:
    assert extract_code_blocks("```python\r\nx = 1\r\n```") == ["x = 1"]
    assert extract_code_blocks("no code here") == []
    assert extract_code_blocks("```python\n\n```") == []  # empty block dropped


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def test_no_code_reply_is_the_answer_immediately() -> None:
    session = make_session()
    backend = FakeBackend(["Just an answer, no code."])
    result = run_turn(session, "hello", backend=backend, system_prompt="SYS")
    assert result["stopped"] == "answer"
    assert result["answer"] == "Just an answer, no code."
    assert result["steps"] == 0
    assert backend.remaining == 0
    kinds = [t["kind"] for t in session.history]
    assert kinds == ["message", "model"]


def test_code_exec_then_answer_and_namespace_persists() -> None:
    session = make_session()
    backend = FakeBackend(
        [
            "thinking\n```python\nx = 21\nprint('setup done')\n```",
            "again\n```python\nprint(x * 2)\n```",
            "The answer is 42.",
        ]
    )
    result = run_turn(session, "compute", backend=backend, system_prompt="SYS")
    assert result["stopped"] == "answer"
    assert result["answer"] == "The answer is 42."
    assert result["steps"] == 2
    execs = [t for t in session.history if t["kind"] == "exec"]
    assert len(execs) == 2
    assert execs[0]["stdout"] == "setup done\n"
    # namespace persisted across run() calls: x survived into step 2
    assert execs[1]["stdout"] == "42\n"
    assert execs[1]["error"] is None
    assert session.kernel.ns["x"] == 21


def test_exec_results_fed_to_next_completion() -> None:
    session = make_session()
    backend = FakeBackend(
        ["```python\nprint('MARKER-4242')\n```", "saw it."]
    )
    run_turn(session, "go", backend=backend, system_prompt="SYS")
    # The SECOND completion's message list must contain the exec stdout.
    second_messages = backend.calls[1][0]
    flat = "\n".join(m["content"] for m in second_messages)
    assert "[exec result]" in flat
    assert "MARKER-4242" in flat
    # And the system prompt heads every completion.
    assert second_messages[0] == {"role": "system", "content": "SYS"}


def test_multiple_blocks_in_one_reply_execute_in_order() -> None:
    session = make_session()
    backend = FakeBackend(
        ["```python\nacc = ['a']\n```\nand\n```python\nacc.append('b')\nprint(''.join(acc))\n```", "done."]
    )
    result = run_turn(session, "go", backend=backend)
    assert result["steps"] == 1  # one code-bearing completion, two blocks
    execs = [t for t in session.history if t["kind"] == "exec"]
    assert len(execs) == 2
    assert execs[1]["stdout"] == "ab\n"


def test_exec_error_is_captured_not_raised() -> None:
    session = make_session()
    backend = FakeBackend(
        ["```python\n1 / 0\n```", "it failed, as expected."]
    )
    result = run_turn(session, "go", backend=backend)
    assert result["stopped"] == "answer"
    execs = [t for t in session.history if t["kind"] == "exec"]
    assert execs[0]["error"] is not None
    assert "ZeroDivisionError" in execs[0]["error"]
    # The error text was fed to the next completion.
    flat = "\n".join(m["content"] for m in backend.calls[1][0])
    assert "ZeroDivisionError" in flat


def test_max_steps_recorded_honestly(tmp_path: Path) -> None:
    session = make_session()
    session.save(tmp_path)  # bind so turns hit the trajectory live
    backend = FakeBackend(
        ["```python\ni = 1\n```", "```python\ni += 1\n```"]
    )
    result = run_turn(session, "loop forever", backend=backend, max_steps=2)
    assert result["stopped"] == "step-limit"
    assert result["answer"] is None  # never disguised as an answer
    assert result["steps"] == 2
    assert backend.remaining == 0  # no third completion was requested
    limits = [
        t
        for t in session.history
        if t["kind"] == "system" and t.get("event") == "step-limit"
    ]
    assert len(limits) == 1
    assert limits[0]["max_steps"] == 2
    # Honest in the TRAJECTORY too, not just memory.
    traj = (tmp_path / session.id / "trajectory.jsonl").read_text(encoding="utf-8")
    assert "step-limit" in traj


def test_over_consuming_script_fails_loudly_not_loops() -> None:
    session = make_session()
    backend = FakeBackend(["```python\npass\n```"])  # loop will ask for a 2nd
    with pytest.raises(FakeBackendExhausted):
        run_turn(session, "go", backend=backend)


def test_inbox_drained_at_start_of_every_completion() -> None:
    session = make_session()
    backend = FakeBackend(["```python\npass\n```", "ok."])
    batches = [
        [{"from": "aaa111", "text": "first wave"}],
        [{"from": "bbb222", "text": "second wave"}],
    ]

    def drain() -> list[dict]:
        return batches.pop(0) if batches else []

    run_turn(session, "go", backend=backend, inbox_drain=drain)
    msgs = [t for t in session.history if t["kind"] == "message"]
    # user + one drained message per completion step
    assert [m["text"] for m in msgs] == ["go", "first wave", "second wave"]
    # The second wave was visible to the second completion.
    flat = "\n".join(m["content"] for m in backend.calls[1][0])
    assert "[message from bbb222] second wave" in flat


def test_kernel_is_lazy_no_code_no_kernel() -> None:
    session = Session(role="root")  # NO kernel_factory: building would raise
    backend = FakeBackend(["pure narration answer."])
    result = run_turn(session, "hi", backend=backend)
    assert result["stopped"] == "answer"
    assert session.kernel is None  # never built


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------


def test_build_messages_maps_kinds_and_tail() -> None:
    history = [
        {"t": "x", "kind": "message", "sender": "user", "text": "hi"},
        {"t": "x", "kind": "model", "text": "reply"},
        {"t": "x", "kind": "exec", "stdout": "out", "stderr": "", "result_repr": "", "error": None},
        {"t": "x", "kind": "system", "event": "step-limit", "max_steps": 2, "steps": 2},
    ]
    messages = build_messages("SYS", history)
    assert messages[0] == {"role": "system", "content": "SYS"}
    assert messages[1]["content"] == "[message from user] hi"
    assert messages[2] == {"role": "assistant", "content": "reply"}
    assert "stdout:\nout" in messages[3]["content"]
    assert messages[4]["content"].startswith("[system:step-limit]")
    # tail bound applies
    assert len(build_messages("SYS", history, tail=1)) == 2


def test_build_messages_honors_compaction_marker() -> None:
    history = [{"t": "x", "kind": "model", "text": f"old-{i}"} for i in range(10)]
    history += [{"t": "x", "kind": "model", "text": f"kept-{i}"} for i in range(3)]
    history.append(
        {
            "t": "x",
            "kind": "system",
            "event": "compaction",
            "summary": "THE-DIGEST",
            "replaced_turns": 10,
            "keep_last": 3,
        }
    )
    history.append({"t": "x", "kind": "model", "text": "after-marker"})
    messages = build_messages("SYS", history)
    flat = "\n".join(m["content"] for m in messages)
    assert "THE-DIGEST" in flat
    assert "kept-0" in flat and "kept-2" in flat
    assert "after-marker" in flat
    assert "old-0" not in flat and "old-9" not in flat


# ---------------------------------------------------------------------------
# Anti-vacuity: activity leaves a NON-EMPTY trajectory on disk
# ---------------------------------------------------------------------------


def test_trajectory_nonempty_after_scripted_run(tmp_path: Path) -> None:
    session = make_session()
    session.save(tmp_path)
    backend = FakeBackend(["```python\nprint('hi')\n```", "done."])
    run_turn(session, "go", backend=backend)
    traj = tmp_path / session.id / "trajectory.jsonl"
    assert traj.stat().st_size > 0
    lines = [ln for ln in traj.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 4  # user message + model + exec + answer model
