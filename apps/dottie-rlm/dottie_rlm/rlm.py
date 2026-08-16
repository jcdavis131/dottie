"""rlm.py — the in-kernel function surface (SPEC v1).

The model gets ONE tool: a persistent kernel. Everything else is a plain
function injected into that kernel's namespace by :class:`Runtime`:

- ``rlm(prompt, model=None)`` — spawn a CHILD session (own kernel, own
  history, base prompt = harness rho for role "sub"). Returns AT ADMISSION:
  ``{"id": ..., "state": "admitted"}`` — it never blocks on the child's
  answer. The child runs its loop in a daemon thread; its final answer is
  delivered as an agent_message to the parent inbox.
- ``agent_message(target_id, text)`` — delivers into the target's inbox if
  target is in ``registry.allowed_targets(sender)``, else
  :class:`~dottie_rlm.registry.ScopeError` (which propagates — actionable).
- ``inbox()`` — drain pending messages for this session.
- ``edit_file(path, old, new)`` / ``read_file(path)`` / ``sh(cmd,
  timeout_s=120)`` / ``compact(keep_last=20)``.

Every function returns plain dicts/strings (kernel-reprable). Expected
failures come back as ``{"error": ...}`` dicts; only ScopeError and
BackendUnavailable raise, with actionable text (SPEC).

Resolved SPEC-vs-module points (coded against the modules):

- Atomic file writes import ``_atomic_write_bytes`` from session.py —
  atomic.py never landed (both Wave A/B modules inlined the contract and
  registry.py already imports from session.py; this module follows suit).
- ``compact`` appends a ``{"kind": "system", "event": "compaction"}`` marker
  turn (summary produced via the session's backend) instead of truncating
  ``session.history`` in place: ``Session.save()`` refuses to save a memory
  history SHORTER than the on-disk trajectory (its reconciliation
  invariant), and the trajectory is append-only. loop.build_messages honors
  the marker, so the MODEL-VISIBLE history is truncated as SPEC intends; the
  in-memory list keeps its tail so persistence stays consistent.
- Inboxes are in-memory (per-Runtime, lock-guarded). Delivered messages
  enter the durable trajectory when the receiving loop drains them at the
  start of its next completion step.
"""

from __future__ import annotations

import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from . import loop
from .llm import Backend, resolve_backend
from .policy import PolicyRefusal, SafetyPolicy
from .registry import ScopeError, SessionRegistry
from .session import Session, _atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Callable

    from .harness import Harness

__all__ = ["SURFACE_FUNCTIONS", "Runtime", "ScopeError"]

#: Names injected into every kernel namespace.
SURFACE_FUNCTIONS = (
    "rlm",
    "agent_message",
    "inbox",
    "edit_file",
    "read_file",
    "sh",
    "compact",
)

#: Output ceiling for sh/read helpers (matches the kernel contract's 20k).
_CLIP_CHARS = 20_000

_SURFACE_DOC = """
## Kernel function surface

You act by writing fenced ```python blocks. These functions are pre-loaded:

- rlm(prompt, model=None) -> {"id", "state": "admitted"} — spawn a sub-agent.
  Returns immediately; the child's final answer arrives later in your inbox.
- agent_message(target_id, text) -> {"delivered": True, ...} — message your
  parent, a sibling, or a direct child. Anything else raises ScopeError.
- inbox() -> list[dict] — drain messages addressed to you.
- edit_file(path, old, new) -> {"path", "replaced"} | {"error"} — exact
  string replacement, atomic write.
- read_file(path) -> {"path", "content", "chars"} | {"error"}.
- sh(cmd, timeout_s=120) -> {"exit_code", "stdout", "stderr", "timeout"}.
- compact(keep_last=20) -> summarize older turns; your visible history
  becomes the summary plus the last keep_last turns.

Reply with NO code block when you have the final answer.
""".rstrip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clip(text: str, limit: int = _CLIP_CHARS) -> str:
    if len(text) <= limit:
        return text
    over = len(text) - limit
    return text[:limit] + f"...[truncated {over} chars]"


def _decode(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


# ---------------------------------------------------------------------------
# Plain-function helpers (model-facing; errors as dicts, never tracebacks)
# ---------------------------------------------------------------------------


def _read_file(path: str, policy: SafetyPolicy) -> dict:
    try:
        p = policy.resolve_in_workspace(path)
    except PolicyRefusal as exc:
        return {"error": str(exc)}
    if not p.exists():
        return {"error": f"{p} does not exist"}
    if p.is_dir():
        return {"error": f"{p} is a directory, not a file"}
    try:
        data = p.read_bytes()
    except OSError as exc:
        return {"error": f"cannot read {p}: {exc}"}
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"error": f"{p} is not valid UTF-8 ({exc}); refusing a lossy read"}
    return {"path": str(p), "content": content, "chars": len(content)}


def _edit_file(path: str, old: str, new: str, policy: SafetyPolicy) -> dict:
    if not isinstance(old, str) or old == "":
        return {"error": "edit_file requires a non-empty 'old' string to replace"}
    if not isinstance(new, str):
        return {"error": "edit_file requires 'new' to be a string"}
    try:
        p = policy.resolve_in_workspace(path)
        policy.require_approval("write", str(p))
    except PolicyRefusal as exc:
        return {"error": str(exc)}
    if not p.exists():
        return {"error": f"{p} does not exist"}
    try:
        data = p.read_bytes()
    except OSError as exc:
        return {"error": f"cannot read {p}: {exc}"}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"error": f"{p} is not valid UTF-8 ({exc}); refusing a lossy edit"}
    count = text.count(old)
    if count == 0:
        return {"error": f"old string not found in {p} (0 occurrences)"}
    _atomic_write_bytes(p, text.replace(old, new).encode("utf-8"))
    return {"path": str(p), "replaced": count}


def _sh(cmd: str, timeout_s: float, policy: SafetyPolicy) -> dict:
    if not isinstance(cmd, str) or not cmd.strip():
        return {"error": "sh(cmd) requires a non-empty command string"}
    try:
        policy.check_shell(cmd)
    except PolicyRefusal as exc:
        return {"error": str(exc), "refused": True}
    try:
        proc = subprocess.run(  # noqa: S602 — sh() IS the model's shell tool; shell=True is the contract
            cmd,
            shell=True,
            capture_output=True,
            timeout=float(timeout_s),
            env=policy.child_env(),
            cwd=str(policy.workspace_root),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "error": f"TimeoutError: command exceeded {timeout_s}s",
            "timeout": True,
            "cmd": cmd,
            "stdout": policy.redact(_clip(_decode(exc.stdout))),
            "stderr": policy.redact(_clip(_decode(exc.stderr))),
        }
    except OSError as exc:
        return {"error": f"cannot run command: {exc}", "cmd": cmd}
    return {
        "exit_code": proc.returncode,
        "stdout": policy.redact(_clip(_decode(proc.stdout))),
        "stderr": policy.redact(_clip(_decode(proc.stderr))),
        "timeout": False,
    }


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class Runtime:
    """Owns the registry + harness + inboxes and wires the function surface.

    ``backend_resolver`` maps a model spec string to a Backend; the default
    is :func:`dottie_rlm.llm.resolve_backend`. Tests inject a resolver that
    returns pre-scripted FakeBackends — zero network. Backends are cached
    per session id so one session's turns share one backend (a FakeBackend's
    script survives across steps).
    """

    def __init__(
        self,
        registry: SessionRegistry,
        harness: Harness,
        *,
        backend_resolver: Callable[[str], Backend] | None = None,
        max_steps: int = loop.DEFAULT_MAX_STEPS,
        child_max_steps: int = loop.CHILD_MAX_STEPS,
        max_tokens: int = loop.DEFAULT_MAX_TOKENS,
        policy: SafetyPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.harness = harness
        # Default policy is RESTRICTIVE: shell off, writes confined to cwd,
        # depth 3 / 8 children. The permissive settings exist but must be
        # asked for by name -- see dottie_rlm/policy.py for why.
        self.policy = policy or SafetyPolicy()
        self.max_steps = int(max_steps)
        self.child_max_steps = int(child_max_steps)
        self.max_tokens = int(max_tokens)
        self._resolver = backend_resolver or resolve_backend
        self._backends: dict[str, Backend] = {}
        self._inboxes: dict[str, list[dict]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        with self._lock:
            pending = sum(len(v) for v in self._inboxes.values())
            children = sum(1 for t in self._threads.values() if t.is_alive())
        return (
            f"Runtime(root={str(self.registry.root)!r}, "
            f"pending_messages={pending}, live_children={children})"
        )

    # -- sessions --------------------------------------------------------------

    def create_root(
        self, *, model_spec: str = "fake:", base_prompt: str | None = None
    ) -> Session:
        """Create + register a root session. Base prompt defaults to rho."""
        return self.registry.create(
            role="root",
            model_spec=model_spec,
            base_prompt=self.harness.rho if base_prompt is None else base_prompt,
        )

    def backend_for(self, session: Session) -> Backend:
        with self._lock:
            backend = self._backends.get(session.id)
            if backend is None:
                backend = self._resolver(session.model_spec)
                self._backends[session.id] = backend
            return backend

    def system_prompt_for(self, session: Session) -> str:
        role_note = (
            "\n\n(You are a SUB-AGENT: answer your parent's prompt, then stop.)"
            if session.role == "sub"
            else ""
        )
        return self.harness.effective_prompt() + "\n" + _SURFACE_DOC + role_note + "\n"

    def install(self, session: Session) -> Any:
        """Ensure the session's kernel exists and (re-)inject the surface.

        Injection is idempotent and repeated on purpose: idle eviction drops
        the kernel, and a rebuilt kernel needs the functions again.
        """
        kernel = session.ensure_kernel()
        for name, fn in self._surface(session).items():
            kernel.inject(name, fn)
        return kernel

    def _executor_for(self, session: Session) -> Callable[[str], Any]:
        def _exec(code: str) -> Any:
            return self.install(session).run(code)

        return _exec

    # -- the loop --------------------------------------------------------------

    def run_turn(
        self, session: Session, user_text: str | None, *, max_steps: int | None = None
    ) -> dict:
        """One user turn with everything wired: backend, prompt, inbox, exec."""
        # busy() for the WHOLE turn: touch() only fires on completion, so a
        # turn longer than the idle window would otherwise be evicted from
        # under itself, dropping the kernel mid-execution.
        with self.registry.busy(session.id):
            result = loop.run_turn(
                session,
                user_text,
                backend=self.backend_for(session),
                system_prompt=self.system_prompt_for(session),
                max_steps=self.max_steps if max_steps is None else int(max_steps),
                max_tokens=self.max_tokens,
                inbox_drain=lambda: self.drain(session.id),
                executor=self._executor_for(session),
            )
        self.registry.touch(session.id)
        return result

    # -- messaging -------------------------------------------------------------

    def deliver(self, sender_id: str, target_id: str, text: str) -> dict:
        """Scope-checked delivery into the target's in-memory inbox."""
        self.registry.check_scope(sender_id, target_id)  # ScopeError propagates
        msg = {"t": _utc_now(), "from": sender_id, "to": target_id, "text": str(text)}
        with self._lock:
            box = self._inboxes.setdefault(target_id, [])
            box.append(msg)
            queued = len(box)
        return {"delivered": True, "to": target_id, "queued": queued}

    def drain(self, session_id: str) -> list[dict]:
        """Pop and return every pending message for ``session_id``."""
        with self._lock:
            return self._inboxes.pop(session_id, [])

    def pending(self, session_id: str) -> int:
        with self._lock:
            return len(self._inboxes.get(session_id, []))

    # -- children --------------------------------------------------------------

    def spawn_child(
        self, parent: Session, prompt: str, model: str | None = None
    ) -> dict:
        """ADMISSION-RETURN child spawn. Never blocks on the child's answer."""
        if not isinstance(prompt, str) or not prompt.strip():
            return {"error": "rlm(prompt) requires a non-empty prompt string"}
        # Depth + fanout caps. Without these, 200 successive spawns were
        # admitted with zero refusals (measured in review) -- an agent in a
        # loop could fork until the box died.
        try:
            self.policy.check_spawn(self.depth_of(parent), self.live_children(parent.id))
        except PolicyRefusal as exc:
            return {"error": str(exc), "refused": True}
        spec = model or self.harness.model_for("sub") or parent.model_spec
        child = self.registry.create(
            role="sub",
            parent_id=parent.id,
            model_spec=spec,
            base_prompt=self.harness.rho,  # SPEC: base prompt = rho for role "sub"
        )
        thread = threading.Thread(
            target=self._child_worker,
            args=(child.id, parent.id, prompt),
            daemon=True,
            name=f"rlm-child-{child.id}",
        )
        with self._lock:
            self._threads[child.id] = thread
        thread.start()
        return {"id": child.id, "state": "admitted"}

    def depth_of(self, session: Session) -> int:
        """0 for a root, +1 per ancestor. Walks the registry, capped so a
        corrupted parent cycle cannot spin forever."""
        depth = 0
        pid = session.parent_id
        seen = {session.id}
        while pid and depth < 64:
            if pid in seen:  # cycle in the index; stop and report the depth so far
                break
            seen.add(pid)
            depth += 1
            try:
                entry = self.registry.entry(pid)
            except Exception:
                break
            if entry is None:
                break
            pid = entry.get("parent_id") if isinstance(entry, dict) else None
        return depth

    def live_children(self, parent_id: str) -> int:
        """Count this parent's still-running child threads, pruning dead ones."""
        with self._lock:
            for cid, th in list(self._threads.items()):
                if not th.is_alive():
                    self._threads.pop(cid, None)
            live = 0
            for cid, th in self._threads.items():
                if not th.is_alive():
                    continue
                try:
                    entry = self.registry.entry(cid)
                except Exception:
                    entry = None
                if isinstance(entry, dict) and entry.get("parent_id") == parent_id:
                    live += 1
            return live

    def _child_worker(self, child_id: str, parent_id: str, prompt: str) -> None:
        try:
            child = self.registry.get(child_id)
            # busy() for the WHOLE turn, same as Runtime.run_turn's parent
            # path: without it, evict_idle could not tell this child's turn
            # was in flight. A child's last_active_utc is stamped only at
            # create() and mark_done() -- there is no per-step touch() the way
            # the parent path has -- so from the moment it is spawned it reads
            # as idle to evict_idle for as long as its turn takes (routine
            # with qwen3:8b on CPU, per SPEC). This worker used to call
            # loop.run_turn directly with no busy() at all: the exact
            # mid-turn-eviction bug 2d6de00 fixed for the parent path
            # (registry.py:276) was unfixed for every sub-agent turn.
            with self.registry.busy(child_id):
                result = loop.run_turn(
                    child,
                    prompt,
                    backend=self.backend_for(child),
                    system_prompt=self.system_prompt_for(child),
                    max_steps=self.child_max_steps,
                    max_tokens=self.max_tokens,
                    inbox_drain=lambda: self.drain(child_id),
                    executor=self._executor_for(child),
                )
            if result["stopped"] == "answer":
                answer = result["answer"]
            else:  # honest step-limit — never disguised as a clean answer
                answer = (
                    f"[child {child_id} hit step-limit after {result['steps']} "
                    f"steps; last reply follows]\n{result.get('last_text') or ''}"
                )
            try:
                self.deliver(child_id, parent_id, answer)
            finally:
                self.registry.mark_done(child_id)
        except BaseException as exc:
            try:
                self.deliver(
                    child_id,
                    parent_id,
                    f"[child {child_id} FAILED] {type(exc).__name__}: {exc}",
                )
            except Exception:
                pass  # parent gone/out of scope: nothing more we can do
            try:
                self.registry.mark_done(child_id)
            except Exception:
                pass

    def wait_children(self, timeout_s: float = 30.0) -> bool:
        """Join child threads (test/CLI helper). True if all finished."""
        end = time.monotonic() + float(timeout_s)
        with self._lock:
            threads = list(self._threads.values())
        for t in threads:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            t.join(timeout=remaining)
        return all(not t.is_alive() for t in threads)

    # -- compaction ------------------------------------------------------------

    def compact_session(self, session: Session, keep_last: int = 20) -> dict:
        """Summarize turns older than the last ``keep_last`` via the backend.

        Appends a compaction marker system turn (see module docstring for why
        the in-memory list is not truncated); loop.build_messages truncates
        the MODEL-VISIBLE history to summary + last ``keep_last`` turns.
        BackendUnavailable propagates (actionable, per SPEC).
        """
        try:
            keep = int(keep_last)
        except (TypeError, ValueError):
            return {"error": f"keep_last must be an integer, got {keep_last!r}"}
        if keep < 1:
            return {"error": f"keep_last must be >= 1, got {keep}"}
        history = list(session.history)
        if len(history) <= keep:
            return {
                "compacted": False,
                "reason": (
                    f"history has {len(history)} turns; nothing older than "
                    f"keep_last={keep} to summarize"
                ),
            }
        older = history[:-keep]
        backend = self.backend_for(session)
        summary = backend.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Summarize the following agent trajectory turns into a "
                        "compact digest. Preserve decisions, open questions, "
                        "file paths, and concrete results. Reply with the "
                        "digest only."
                    ),
                },
                {"role": "user", "content": _render_turns(older)},
            ],
            max_tokens=512,
        )
        session.record_turn(
            "system",
            event="compaction",
            summary=str(summary),
            replaced_turns=len(older),
            keep_last=keep,
        )
        return {
            "compacted": True,
            "replaced_turns": len(older),
            "keep_last": keep,
            "summary_chars": len(str(summary)),
        }

    # -- the injected surface --------------------------------------------------

    def _surface(self, session: Session) -> dict[str, Callable]:
        """Closures over THIS session — what gets injected into its kernel."""

        def rlm(prompt: str, model: str | None = None) -> dict:
            return self.spawn_child(session, prompt, model)

        def agent_message(target_id: str, text: str) -> dict:
            return self.deliver(session.id, target_id, text)

        def inbox() -> list[dict]:
            return self.drain(session.id)

        def edit_file(path: str, old: str, new: str) -> dict:
            return _edit_file(path, old, new, self.policy)

        def read_file(path: str) -> dict:
            return _read_file(path, self.policy)

        def sh(cmd: str, timeout_s: float = 120) -> dict:
            return _sh(cmd, timeout_s, self.policy)

        def compact(keep_last: int = 20) -> dict:
            return self.compact_session(session, keep_last)

        return {
            "rlm": rlm,
            "agent_message": agent_message,
            "inbox": inbox,
            "edit_file": edit_file,
            "read_file": read_file,
            "sh": sh,
            "compact": compact,
        }


def _render_turns(turns: list[dict], per_turn_chars: int = 500) -> str:
    """Compact plain-text rendering of turns for the compaction prompt."""
    lines: list[str] = []
    for turn in turns:
        kind = turn.get("kind", "?")
        if kind == "model":
            body = str(turn.get("text", ""))
        elif kind == "exec":
            body = (
                f"code={turn.get('code', '')!r} stdout={turn.get('stdout', '')!r} "
                f"error={turn.get('error')!r}"
            )
        elif kind == "message":
            body = f"from={turn.get('sender', '?')} text={turn.get('text', '')!r}"
        else:
            body = str({k: v for k, v in turn.items() if k not in ("t", "kind")})
        if len(body) > per_turn_chars:
            body = body[:per_turn_chars] + "..."
        lines.append(f"- {kind}: {body}")
    return "\n".join(lines)
