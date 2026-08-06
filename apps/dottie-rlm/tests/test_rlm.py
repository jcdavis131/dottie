"""Tests for dottie_rlm.rlm — the in-kernel function surface (SPEC floor).

Covered: rlm() returns AT ADMISSION and the parent turn completes while the
child is provably still pending (gated backend); the child's answer arrives
via the parent inbox and is recorded into history on the next drain;
agent_message to a stranger raises ScopeError (direct AND via the injected
surface); edit_file/read_file/sh/compact behave and stay dict-shaped; child
step-limit and child failure are delivered HONESTLY; anti-vacuity (parent
and child trajectories NON-EMPTY on disk after activity). No network:
FakeBackend + a stub exec()-based kernel only.
"""

from __future__ import annotations

import io
import sys
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_rlm.harness import Harness
from dottie_rlm.llm import Backend, FakeBackend
from dottie_rlm.loop import build_messages
from dottie_rlm.policy import PolicyRefusal, SafetyPolicy
from dottie_rlm.registry import ScopeError, SessionRegistry
from dottie_rlm.rlm import SURFACE_FUNCTIONS, Runtime


class StubKernel:
    """Kernel-contract stand-in (persistent ns, inject, run) using exec()."""

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


class GatedBackend:
    """Blocks every complete() until the gate opens, then delegates.

    This is how the admission test PROVES the child is still pending while
    the parent's turn finishes: the child cannot produce its answer until
    the test opens the gate."""

    def __init__(self, gate: threading.Event, inner: Backend) -> None:
        self.gate = gate
        self.inner = inner

    def complete(self, messages: list[dict], *, max_tokens: int) -> str:
        if not self.gate.wait(timeout=10):
            raise AssertionError("gate never opened; admission test is broken")
        return self.inner.complete(messages, max_tokens=max_tokens)


class ScriptedResolver:
    """model_spec -> pre-built backend. Unknown spec fails the test loudly."""

    def __init__(self, backends: dict[str, Backend]) -> None:
        self.backends = dict(backends)

    def __call__(self, spec: str) -> Backend:
        backend = self.backends.get(spec)
        if backend is None:
            raise AssertionError(f"test resolver has no backend for spec {spec!r}")
        return backend


def make_runtime(tmp_path: Path, backends: dict[str, Backend], **kw) -> Runtime:
    registry = SessionRegistry(tmp_path / "sessions", kernel_factory=StubKernel)
    harness = Harness(tmp_path / "harness")
    # Behavioral tests need the surface ENABLED, so they pass an explicit
    # policy: workspace = tmp_path, shell on. That is exactly the opt-in a real
    # caller must make -- the DEFAULT policy refuses both, asserted in
    # TestPolicyGates at the end of this file.
    kw.setdefault("policy", SafetyPolicy(workspace_root=tmp_path, allow_shell=True))
    return Runtime(registry, harness, backend_resolver=ScriptedResolver(backends), **kw)


SPAWN_CODE = (
    "```python\n"
    "res = rlm('add 2+2', model='fake:child')\n"
    "print(res['state'], res['id'])\n"
    "```"
)


# ---------------------------------------------------------------------------
# Admission-return + child answer via inbox (the SPEC floor's core)
# ---------------------------------------------------------------------------


def test_rlm_returns_at_admission_parent_completes_while_child_pending(
    tmp_path: Path,
) -> None:
    gate = threading.Event()
    parent_backend = FakeBackend([SPAWN_CODE, "child admitted; parent done."])
    child_backend = GatedBackend(gate, FakeBackend(["4"]))
    rt = make_runtime(
        tmp_path, {"fake:parent": parent_backend, "fake:child": child_backend}
    )
    parent = rt.create_root(model_spec="fake:parent")

    result = rt.run_turn(parent, "spawn a child to add 2+2")

    # Parent turn COMPLETED while the child is still gated (pending):
    assert result["stopped"] == "answer"
    assert result["answer"] == "child admitted; parent done."
    execs = [t for t in parent.history if t["kind"] == "exec"]
    assert len(execs) == 1
    assert execs[0]["error"] is None
    assert execs[0]["stdout"].startswith("admitted ")  # rlm() returned at admission
    child_id = execs[0]["stdout"].split()[1]
    assert rt.pending(parent.id) == 0  # no answer yet — child provably pending
    entry = {e["id"]: e for e in rt.registry.entries()}[child_id]
    assert entry["state"] == "live"
    assert entry["parent_id"] == parent.id

    # Open the gate: the child answers, delivery lands in the parent inbox.
    gate.set()
    assert rt.wait_children(timeout_s=10)
    msgs = rt.drain(parent.id)
    assert len(msgs) == 1
    assert msgs[0]["from"] == child_id
    assert msgs[0]["text"] == "4"
    entry = {e["id"]: e for e in rt.registry.entries()}[child_id]
    assert entry["state"] == "done"

    # Anti-vacuity: BOTH trajectories are NON-EMPTY on disk after activity.
    for sid in (parent.id, child_id):
        traj = rt.registry.root / sid / "trajectory.jsonl"
        assert traj.stat().st_size > 0


def test_child_answer_enters_parent_history_on_next_turn(tmp_path: Path) -> None:
    parent_backend = FakeBackend(
        [SPAWN_CODE, "spawned; done.", "the child said 4."]
    )
    rt = make_runtime(
        tmp_path,
        {"fake:parent": parent_backend, "fake:child": FakeBackend(["4"])},
    )
    parent = rt.create_root(model_spec="fake:parent")
    rt.run_turn(parent, "go")
    assert rt.wait_children(timeout_s=10)

    result = rt.run_turn(parent, "what did the child say?")
    assert result["answer"] == "the child said 4."
    # The drained child message became a durable "message" turn.
    child_msgs = [
        t
        for t in parent.history
        if t["kind"] == "message" and t.get("text") == "4"
    ]
    assert len(child_msgs) == 1
    assert child_msgs[0]["sender"] != "user"


def test_rlm_rejects_empty_prompt_without_spawning(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, {"fake:parent": FakeBackend([])})
    parent = rt.create_root(model_spec="fake:parent")
    out = rt.spawn_child(parent, "   ")
    assert "error" in out
    assert len(rt.registry.entries()) == 1  # no child was registered


# ---------------------------------------------------------------------------
# Scoping + messaging
# ---------------------------------------------------------------------------


def test_agent_message_to_stranger_raises_scope_error(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, {"fake:parent": FakeBackend([])})
    a = rt.create_root(model_spec="fake:parent")
    b = rt.registry.create(role="root", model_spec="fake:parent")  # unrelated root
    with pytest.raises(ScopeError, match="may not message"):
        rt.deliver(a.id, b.id, "hi stranger")
    # And through the INJECTED surface, exactly as the model would call it:
    kernel = rt.install(a)
    with pytest.raises(ScopeError):
        kernel.ns["agent_message"](b.id, "hi again")


def test_agent_message_parent_to_child_delivers_and_drains(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, {"fake:parent": FakeBackend([])})
    parent = rt.create_root(model_spec="fake:parent")
    child = rt.registry.create(role="sub", parent_id=parent.id, model_spec="fake:parent")
    out = rt.deliver(parent.id, child.id, "hello child")
    assert out == {"delivered": True, "to": child.id, "queued": 1}
    msgs = rt.drain(child.id)
    assert [m["text"] for m in msgs] == ["hello child"]
    assert rt.drain(child.id) == []  # drained means drained


def test_install_injects_full_surface(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, {"fake:parent": FakeBackend([])})
    s = rt.create_root(model_spec="fake:parent")
    kernel = rt.install(s)
    for name in SURFACE_FUNCTIONS:
        assert callable(kernel.ns.get(name)), f"{name} not injected"


# ---------------------------------------------------------------------------
# Honest child failure modes
# ---------------------------------------------------------------------------


def test_child_step_limit_is_delivered_honestly(tmp_path: Path) -> None:
    child_backend = FakeBackend(
        ["```python\na = 1\n```", "```python\na += 1\n```"]
    )
    rt = make_runtime(
        tmp_path,
        {"fake:parent": FakeBackend([SPAWN_CODE, "done."]), "fake:child": child_backend},
        child_max_steps=2,
    )
    parent = rt.create_root(model_spec="fake:parent")
    rt.run_turn(parent, "go")
    assert rt.wait_children(timeout_s=10)
    msgs = rt.drain(parent.id)
    assert len(msgs) == 1
    assert "step-limit" in msgs[0]["text"]  # never disguised as a clean answer


def test_child_failure_is_delivered_loudly_not_swallowed(tmp_path: Path) -> None:
    rt = make_runtime(
        tmp_path,
        # Child script EMPTY: first completion raises FakeBackendExhausted.
        {"fake:parent": FakeBackend([SPAWN_CODE, "done."]), "fake:child": FakeBackend([])},
    )
    parent = rt.create_root(model_spec="fake:parent")
    rt.run_turn(parent, "go")
    assert rt.wait_children(timeout_s=10)
    msgs = rt.drain(parent.id)
    assert len(msgs) == 1
    assert "FAILED" in msgs[0]["text"]
    assert "FakeBackendExhausted" in msgs[0]["text"]


# ---------------------------------------------------------------------------
# File / shell helpers (dict-shaped, atomic)
# ---------------------------------------------------------------------------


def test_edit_file_replaces_atomically_and_reports_count(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, {"fake:parent": FakeBackend([])})
    s = rt.create_root(model_spec="fake:parent")
    kernel = rt.install(s)
    target = tmp_path / "hello.txt"
    target.write_text("alpha beta alpha", encoding="utf-8")
    out = kernel.ns["edit_file"](str(target), "alpha", "gamma")
    assert out == {"path": str(target), "replaced": 2}
    assert target.read_text(encoding="utf-8") == "gamma beta gamma"
    # No leftover temp files from the atomic write.
    assert list(tmp_path.glob("hello.txt.*.tmp")) == []


def test_edit_file_errors_are_dicts_not_raises(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, {"fake:parent": FakeBackend([])})
    s = rt.create_root(model_spec="fake:parent")
    kernel = rt.install(s)
    missing = tmp_path / "nope.txt"
    assert "error" in kernel.ns["edit_file"](str(missing), "a", "b")
    present = tmp_path / "yes.txt"
    present.write_text("content", encoding="utf-8")
    assert "error" in kernel.ns["edit_file"](str(present), "absent", "b")
    assert "error" in kernel.ns["edit_file"](str(present), "", "b")
    assert present.read_text(encoding="utf-8") == "content"  # untouched


def test_read_file_roundtrip_and_missing(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, {"fake:parent": FakeBackend([])})
    s = rt.create_root(model_spec="fake:parent")
    kernel = rt.install(s)
    p = tmp_path / "note.md"
    p.write_text("hello rlmé", encoding="utf-8")
    out = kernel.ns["read_file"](str(p))
    assert out["content"] == "hello rlmé"
    assert out["chars"] == len("hello rlmé")
    assert "error" in kernel.ns["read_file"](str(tmp_path / "absent.md"))


def test_sh_runs_and_rejects_empty(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, {"fake:parent": FakeBackend([])})
    s = rt.create_root(model_spec="fake:parent")
    kernel = rt.install(s)
    out = kernel.ns["sh"]("echo rlm-sh-marker")
    assert out["exit_code"] == 0
    assert "rlm-sh-marker" in out["stdout"]
    assert out["timeout"] is False
    assert "error" in kernel.ns["sh"]("   ")


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------


def test_compact_summarizes_older_turns_and_marks_trajectory(tmp_path: Path) -> None:
    backend = FakeBackend(["DIGEST-OF-OLDER-TURNS"])
    rt = make_runtime(tmp_path, {"fake:parent": backend})
    s = rt.create_root(model_spec="fake:parent")
    for i in range(25):
        s.record_turn("model", text=f"turn-{i}")
    out = rt.compact_session(s, keep_last=5)
    assert out["compacted"] is True
    assert out["replaced_turns"] == 20
    assert backend.remaining == 0  # the summary came from the backend

    # Model-visible history: digest + kept tail, old turns gone.
    flat = "\n".join(m["content"] for m in build_messages("SYS", s.history))
    assert "DIGEST-OF-OLDER-TURNS" in flat
    assert "turn-24" in flat and "turn-20" in flat
    assert "turn-0" not in flat and "turn-19" not in flat

    # The compaction record is durable in the trajectory (append-only).
    traj = rt.registry.root / s.id / "trajectory.jsonl"
    assert "compaction" in traj.read_text(encoding="utf-8")

    # Persistence invariant survives compaction: save/evict still works.
    s.save(rt.registry.root)


def test_compact_nothing_older_is_honest_noop(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, {"fake:parent": FakeBackend([])})
    s = rt.create_root(model_spec="fake:parent")
    s.record_turn("model", text="only turn")
    out = rt.compact_session(s, keep_last=20)
    assert out["compacted"] is False
    assert "reason" in out
    out2 = rt.compact_session(s, keep_last=0)
    assert "error" in out2


# ---------------------------------------------------------------------------
# Policy gates — the controls the SPEC's first draft omitted entirely.
# Each test below corresponds to a reproduced review finding.
# ---------------------------------------------------------------------------


class TestPolicyGates:
    """A default-constructed Runtime must refuse shell and out-of-workspace writes.

    The first SPEC draft had sh()/edit_file() with no confinement and rlm()
    with no caps: review reproduced 200 successive spawns with zero refusals,
    and sh("set") putting DOTTIE_RLM_API_KEY into a trajectory that feeds the
    PUBLIC gist status chain.
    """

    def _default_runtime(self, tmp_path: Path) -> Runtime:
        registry = SessionRegistry(tmp_path / "sessions", kernel_factory=StubKernel)
        harness = Harness(tmp_path / "harness")
        # No policy= : the restrictive default is what a plain caller gets.
        return Runtime(
            registry, harness, backend_resolver=ScriptedResolver({"fake:p": FakeBackend([])})
        )

    def test_default_policy_refuses_shell(self, tmp_path: Path) -> None:
        rt = self._default_runtime(tmp_path)
        kernel = rt.install(rt.create_root(model_spec="fake:p"))
        out = kernel.ns["sh"]("echo should-not-run")
        assert out.get("refused") is True, out
        assert "disabled by policy" in out["error"]
        assert "allow_shell=True" in out["error"]  # says how to enable it

    def test_default_policy_confines_writes_to_the_workspace(self, tmp_path: Path) -> None:
        rt = self._default_runtime(tmp_path)  # workspace defaults to cwd, not tmp_path
        kernel = rt.install(rt.create_root(model_spec="fake:p"))
        outside = tmp_path / "outside.txt"
        outside.write_text("original", encoding="utf-8")
        out = kernel.ns["edit_file"](str(outside), "original", "clobbered")
        assert "outside the workspace root" in out.get("error", ""), out
        assert outside.read_text(encoding="utf-8") == "original"  # untouched

    def test_workspace_confinement_resolves_both_sides(self, tmp_path: Path) -> None:
        """A junction/symlink inside the workspace pointing out must not pass.

        Resolving only the root (or only the target) is the escape the bigbang
        policy fix closed; realpath is non-strict so this works for paths that
        do not exist yet.
        """
        ws = tmp_path / "ws"
        ws.mkdir()
        pol = SafetyPolicy(workspace_root=ws)
        assert pol.resolve_in_workspace(ws / "sub" / "new.txt")  # not-yet-existing ok
        with pytest.raises(PolicyRefusal):
            pol.resolve_in_workspace(tmp_path / "elsewhere.txt")
        with pytest.raises(PolicyRefusal):
            pol.resolve_in_workspace(ws / ".." / "escape.txt")

    def test_approval_hook_can_refuse_shell_and_writes(self, tmp_path: Path) -> None:
        seen: list[tuple[str, str]] = []

        def deny(action: str, detail: str) -> bool:
            seen.append((action, detail))
            return False

        registry = SessionRegistry(tmp_path / "sessions", kernel_factory=StubKernel)
        harness = Harness(tmp_path / "harness")
        rt = Runtime(
            registry,
            harness,
            backend_resolver=ScriptedResolver({"fake:p": FakeBackend([])}),
            policy=SafetyPolicy(
                workspace_root=tmp_path, allow_shell=True, approval_hook=deny
            ),
        )
        kernel = rt.install(rt.create_root(model_spec="fake:p"))
        target = tmp_path / "f.txt"
        target.write_text("a", encoding="utf-8")
        assert "declined by approval hook" in kernel.ns["sh"]("echo x").get("error", "")
        assert "declined by approval hook" in kernel.ns["edit_file"](
            str(target), "a", "b"
        ).get("error", "")
        assert target.read_text(encoding="utf-8") == "a"
        assert [a for a, _ in seen] == ["shell", "write"]

    def test_sh_child_env_has_no_secret_shaped_names(self, tmp_path: Path) -> None:
        pol = SafetyPolicy(workspace_root=tmp_path, allow_shell=True)
        import os

        os.environ["DOTTIE_RLM_API_KEY"] = "sk-test-abcdefghijklmnop"
        os.environ["PLAIN_SETTING"] = "keepme"
        try:
            env = pol.child_env()
            assert "DOTTIE_RLM_API_KEY" not in env
            assert env.get("PLAIN_SETTING") == "keepme"
            # And even if a value reaches output another way, it is redacted.
            assert "sk-test-abcdefghijklmnop" not in pol.redact(
                "leak: sk-test-abcdefghijklmnop"
            )
            assert "[REDACTED]" in pol.redact("leak: sk-test-abcdefghijklmnop")
        finally:
            os.environ.pop("DOTTIE_RLM_API_KEY", None)
            os.environ.pop("PLAIN_SETTING", None)

    def test_redact_ignores_short_values(self, tmp_path: Path) -> None:
        """A 2-char secret must not blank out unrelated text (anti-vacuity)."""
        import os

        pol = SafetyPolicy(workspace_root=tmp_path)
        os.environ["TINY_TOKEN"] = "ab"  # noqa: S105 - a 2-char value IS the test
        try:
            assert pol.redact("cabbage") == "cabbage"
        finally:
            os.environ.pop("TINY_TOKEN", None)

    def test_spawn_is_capped_by_max_children(self, tmp_path: Path) -> None:
        rt = make_runtime(
            tmp_path,
            {"fake:p": FakeBackend([]), "fake:c": FakeBackend(["done"] * 20)},
            policy=SafetyPolicy(workspace_root=tmp_path, max_children=2, max_depth=5),
        )
        parent = rt.create_root(model_spec="fake:p")
        rt.install(parent)
        blocker = threading.Event()

        # Hold children open so the cap is observable rather than racing.
        original = rt._child_worker

        def slow(child_id: str, parent_id: str, prompt: str) -> None:
            blocker.wait(timeout=10)
            original(child_id, parent_id, prompt)

        rt._child_worker = slow  # type: ignore[method-assign]
        try:
            a = rt.spawn_child(parent, "one", model="fake:c")
            b = rt.spawn_child(parent, "two", model="fake:c")
            c = rt.spawn_child(parent, "three", model="fake:c")
            assert a["state"] == "admitted"
            assert b["state"] == "admitted"
            assert c.get("refused") is True, c
            assert "max_children=2" in c["error"]
        finally:
            blocker.set()
            rt.wait_children(timeout_s=10)

    def test_spawn_is_capped_by_max_depth(self, tmp_path: Path) -> None:
        rt = make_runtime(
            tmp_path,
            {"fake:p": FakeBackend([])},
            policy=SafetyPolicy(workspace_root=tmp_path, max_depth=1),
        )
        parent = rt.create_root(model_spec="fake:p")
        child = rt.registry.create(
            role="sub", parent_id=parent.id, model_spec="fake:p", base_prompt=""
        )
        assert rt.depth_of(parent) == 0
        assert rt.depth_of(child) == 1
        out = rt.spawn_child(child, "grandchild", model="fake:p")
        assert out.get("refused") is True, out
        assert "max_depth=1" in out["error"]
