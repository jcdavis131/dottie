"""registry.py — SessionRegistry: disk index, idle eviction, scoping (SPEC v1).

Contract (SPEC.md, registry.py section):

- Root dir defaults to ``%LOCALAPPDATA%/dottie-rlm/sessions``; overridable
  (tests always pass a tmp_path). Index ``registry.json`` is written via the
  atomic contract (helpers imported from session.py — see its build-order
  note; Wave C may unify onto atomic.py).
- Tracks per session: ``id``, ``parent_id``, ``state`` ("live"|"idle"|"done"),
  ``last_active_utc``.
- ``evict_idle(now, idle_minutes=30)``: live → idle unloads the in-memory
  Session (turns flushed to disk first, kernel dropped); the state persists
  on disk. Addressing an idle session via :meth:`get` reloads it — fresh
  kernel, full history — and flips it back to live. Explicit, tested.
- ``allowed_targets(sender_id)`` = parent + siblings (same parent) + direct
  children. Messaging outside that set raises :class:`ScopeError` — enforced
  by :meth:`check_scope`, not advisory.

Resolved ambiguities (documented, tested):

- Two root sessions (``parent_id is None``) are NOT siblings: sharing "no
  parent" is not sharing a parent. Independent session trees stay isolated.
- A session is never a target of itself.
- ``get()`` on a "done" session refuses with :class:`RegistryError` — done is
  terminal; only idle sessions reload on address.
- Index entries whose state is "live" but that are not held in memory (e.g.
  after a process restart) are still flipped to "idle" by ``evict_idle`` —
  the on-disk state is the truth the site/status reads.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .session import (
    CorruptStateError,
    Session,
    atomic_write_json,
    preserve_corrupt,
    read_json_guarded,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = [
    "STATES",
    "RegistryError",
    "ScopeError",
    "SessionRegistry",
    "default_root",
]

STATES = ("live", "idle", "done")

DEFAULT_IDLE_MINUTES = 30.0


class RegistryError(Exception):
    """Registry state problem: unknown session, duplicate id, done-session address."""


class ScopeError(RegistryError):
    """Messaging outside parent/siblings/children. Actionable, never advisory."""


def default_root() -> Path:
    """``%LOCALAPPDATA%/dottie-rlm/sessions`` (pathlib, no POSIX assumptions)."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "dottie-rlm" / "sessions"


def _as_dt(value: datetime | str | None) -> datetime:
    """Coerce None/iso-string/datetime to an aware UTC datetime."""
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError as exc:
            raise RegistryError(f"unparseable timestamp {value!r}") from exc
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    raise RegistryError(f"unsupported timestamp type {type(value).__name__}")


def _iso(value: datetime | str | None) -> str:
    return _as_dt(value).isoformat(timespec="seconds")


class SessionRegistry:
    """Disk-indexed registry of sessions with idle eviction and scoping.

    ``kernel_factory`` is threaded into every Session it creates or reloads,
    so tests stay kernel-free (kernel.py is another wave's file; Session's
    default factory imports it lazily only when no factory was injected).
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        kernel_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "registry.json"
        self._kernel_factory = kernel_factory
        self._live: dict[str, Session] = {}
        # Sessions with a turn IN FLIGHT. evict_idle must never unload one:
        # last_active_utc is only stamped AFTER a turn completes, so a turn
        # slower than idle_minutes (routine with qwen3:8b on CPU) looked idle
        # and had its kernel dropped mid-execution -- the namespace the model
        # had been building simply vanished (review finding registry.py:276).
        self._busy: set[str] = set()
        self._busy_depth: dict[str, int] = {}
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return f"SessionRegistry(root={str(self.root)!r}, loaded={len(self._live)})"

    # -- index IO --------------------------------------------------------------

    def _read_index(self) -> dict[str, dict]:
        """Index mapping id -> entry. Missing file is an empty registry;
        corrupt is preserved + loud (never silently reset — the fail-silent
        read-modify-write lesson applies verbatim)."""
        if not self.index_path.exists():
            return {}
        obj = read_json_guarded(self.index_path)  # corrupt → preserve + raise
        sessions = obj.get("sessions") if isinstance(obj, dict) else None
        if not isinstance(sessions, dict) or not all(
            isinstance(v, dict) for v in sessions.values()
        ):
            dest = preserve_corrupt(
                self.index_path, "expected {'sessions': {id: {...}}} shape"
            )
            raise CorruptStateError(
                f"{self.index_path} is corrupt (unexpected shape); "
                f"bytes preserved at {dest}"
            )
        return {str(k): dict(v) for k, v in sessions.items()}

    def _write_index(self, sessions: dict[str, dict]) -> None:
        atomic_write_json(
            self.index_path,
            {"updated_utc": _iso(None), "sessions": sessions},
        )

    def _require(self, index: dict[str, dict], session_id: str) -> dict:
        entry = index.get(session_id)
        if entry is None:
            raise RegistryError(
                f"unknown session {session_id!r} (not in {self.index_path})"
            )
        return entry

    # -- registration ----------------------------------------------------------

    def create(
        self,
        *,
        role: str = "root",
        parent_id: str | None = None,
        model_spec: str = "fake:",
        base_prompt: str = "",
        now: datetime | str | None = None,
    ) -> Session:
        """Build a Session (registry's kernel_factory attached) and add it."""
        with self._lock:
            if parent_id is not None and parent_id not in self._read_index():
                raise RegistryError(
                    f"cannot create a child of unknown session {parent_id!r}"
                )
            session = Session(
                role=role,
                parent_id=parent_id,
                model_spec=model_spec,
                base_prompt=base_prompt,
                kernel_factory=self._kernel_factory,
            )
            self.add(session, now=now)
            return session

    def add(self, session: Session, *, now: datetime | str | None = None) -> None:
        """Register a session: persist it under root, index it as live."""
        with self._lock:
            index = self._read_index()
            if session.id in index:
                raise RegistryError(f"session {session.id!r} is already registered")
            session.save(self.root)
            index[session.id] = {
                "id": session.id,
                "parent_id": session.parent_id,
                "state": "live",
                "last_active_utc": _iso(now),
            }
            self._write_index(index)
            self._live[session.id] = session

    # -- addressing ------------------------------------------------------------

    def get(self, session_id: str, *, now: datetime | str | None = None) -> Session:
        """Address a session. Live → same object; idle → reload from disk
        (fresh kernel, full history) and flip back to live; done → refuse."""
        with self._lock:
            index = self._read_index()
            entry = self._require(index, session_id)
            if entry.get("state") == "done":
                raise RegistryError(
                    f"session {session_id!r} is done; done sessions are not "
                    "reloadable (only idle sessions reload on address)"
                )
            if session_id in self._live:
                entry["last_active_utc"] = _iso(now)
                self._write_index(index)
                return self._live[session_id]
            session = Session.load(
                self.root, session_id, kernel_factory=self._kernel_factory
            )
            entry["state"] = "live"
            entry["last_active_utc"] = _iso(now)
            self._write_index(index)
            self._live[session_id] = session
            return session

    def touch(self, session_id: str, *, now: datetime | str | None = None) -> None:
        """Update ``last_active_utc`` for a session (any state)."""
        with self._lock:
            index = self._read_index()
            self._require(index, session_id)["last_active_utc"] = _iso(now)
            self._write_index(index)

    def mark_done(self, session_id: str, *, now: datetime | str | None = None) -> None:
        """Terminal state: flush + unload if in memory, index state = done."""
        with self._lock:
            index = self._read_index()
            entry = self._require(index, session_id)
            session = self._live.pop(session_id, None)
            if session is not None:
                session.save(self.root)
                session.drop_kernel()
            entry["state"] = "done"
            entry["last_active_utc"] = _iso(now)
            self._write_index(index)

    # -- idle eviction ---------------------------------------------------------

    @contextmanager
    def busy(self, session_id: str) -> Iterator[None]:
        """Mark a session in-flight for the duration of the block.

        Re-entrant by refcount so nested turns (a child driven inside a
        parent's step) cannot clear the flag early.
        """
        with self._lock:
            self._busy_depth[session_id] = self._busy_depth.get(session_id, 0) + 1
            self._busy.add(session_id)
        try:
            yield
        finally:
            with self._lock:
                depth = self._busy_depth.get(session_id, 1) - 1
                if depth <= 0:
                    self._busy_depth.pop(session_id, None)
                    self._busy.discard(session_id)
                else:
                    self._busy_depth[session_id] = depth

    def is_busy(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._busy

    def evict_idle(
        self,
        now: datetime | str | None = None,
        idle_minutes: float = DEFAULT_IDLE_MINUTES,
    ) -> list[str]:
        """live → idle for every session idle at least ``idle_minutes``.

        Unloads the in-memory Session (turns flushed to disk FIRST, then the
        kernel is dropped and the object released); the idle state persists in
        the index. Returns the evicted ids, sorted.
        """
        cutoff = _as_dt(now) - timedelta(minutes=idle_minutes)
        evicted: list[str] = []
        with self._lock:
            index = self._read_index()
            for sid, entry in index.items():
                if entry.get("state") != "live":
                    continue
                raw_last = entry.get("last_active_utc")
                try:
                    last = _as_dt(raw_last)
                except RegistryError as exc:
                    raise RegistryError(
                        f"index entry {sid!r} has unusable last_active_utc "
                        f"{raw_last!r}: {exc}"
                    ) from exc
                if last > cutoff:
                    continue
                if sid in self._busy:
                    # A turn is executing right now. Its clock is only stamped
                    # on completion, so "idle" here would be a lie.
                    continue
                session = self._live.pop(sid, None)
                if session is not None:
                    session.save(self.root)  # nothing in memory is lost
                    session.drop_kernel()
                entry["state"] = "idle"
                evicted.append(sid)
            if evicted:
                self._write_index(index)
        return sorted(evicted)

    # -- scoping ---------------------------------------------------------------

    def allowed_targets(self, sender_id: str) -> set[str]:
        """parent + siblings (same non-None parent) + direct children.

        Never includes ``sender_id`` itself. Two root sessions do NOT count
        as siblings (a shared lack of parent is not a shared parent).
        Unknown sender raises :class:`ScopeError`.
        """
        with self._lock:  # locked: see entries() -- readers race mutations
            index = self._read_index()
        if sender_id not in index:
            raise ScopeError(
                f"unknown sender session {sender_id!r}: not in {self.index_path}"
            )
        targets: set[str] = set()
        parent = index[sender_id].get("parent_id")
        if parent is not None and parent in index:
            targets.add(parent)
            targets |= {
                sid
                for sid, entry in index.items()
                if entry.get("parent_id") == parent and sid != sender_id
            }
        targets |= {
            sid for sid, entry in index.items() if entry.get("parent_id") == sender_id
        }
        return targets

    def check_scope(self, sender_id: str, target_id: str) -> None:
        """Raise :class:`ScopeError` unless ``target_id`` is in scope for sender."""
        allowed = self.allowed_targets(sender_id)
        if target_id not in allowed:
            detail = ", ".join(sorted(allowed)) if allowed else "none registered"
            raise ScopeError(
                f"session {sender_id!r} may not message {target_id!r}: targets are "
                f"limited to its parent, siblings, and direct children "
                f"(currently: {detail})"
            )

    # -- introspection ---------------------------------------------------------

    def entry(self, session_id: str) -> dict | None:
        """One index entry, or None if unknown. Read under the lock -- an
        unsynchronized read of registry.json races every mutation (review
        finding registry.py:295)."""
        with self._lock:
            return self._read_index().get(session_id)

    def entries(self) -> list[dict]:
        """Index entries, sorted by id (what status.py publishes from).

        Under the lock: an unsynchronized read races every mutation (review
        finding registry.py:295 -- 6 touch threads vs 14 readers)."""
        with self._lock:
            index = self._read_index()
            return [dict(index[sid]) for sid in sorted(index)]

    def loaded_ids(self) -> set[str]:
        """Ids of sessions currently held in memory (live objects)."""
        with self._lock:
            return set(self._live)
