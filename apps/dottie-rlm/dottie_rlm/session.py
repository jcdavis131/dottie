"""session.py — Session: one agent = one kernel + one history (SPEC v1).

Contract (SPEC.md, session.py section):

- Fields: ``id`` (uuid4 hex12), ``parent_id``, ``role`` ("root"|"sub"),
  ``model_spec``, ``created_utc``, ``kernel``, ``history`` (list of turn
  dicts), ``base_prompt``.
- Turn record: ``{"t": iso_utc, "kind": "model"|"exec"|"message"|"system", ...}``.
- ``save(dir)`` -> ``<dir>/<id>/session.json`` (meta, atomic write) +
  ``trajectory.jsonl`` (append-only, atomic appends). Once a session is
  bound to a directory (first save, or load), every ``record_turn`` is
  appended to the trajectory immediately; ``save`` reconciles by line count
  and never duplicates or rewrites existing lines.
- ``load(dir, id)`` reconstructs meta + history. The KERNEL namespace is NOT
  persisted: reload = fresh kernel, history intact — the same tradeoff Prime
  Agent makes on reload. ``kernel`` is ``None`` after load until
  ``ensure_kernel()`` builds one via the injected factory.
- Corrupt state is NEVER read silently: the bytes are preserved as
  ``<name>.corrupt-<ts>-<pid>``, announced on stderr, and
  :class:`CorruptStateError` is raised. Missing is empty; unreadable is not.

NOTE (build order, same call harness.py made): the atomic helpers here
(``atomic_write_json`` / ``append_jsonl`` / ``read_json_guarded`` /
``read_jsonl_guarded`` / ``preserve_corrupt``) implement the atomic.py
contract INLINE, because atomic.py is owned by a different wave and does not
exist on disk at the time of writing. registry.py imports them from here.
Wave C may unify onto atomic.py; the contract is identical: per-pid+thread
temp file + ``os.replace`` with a bounded retry on WinError 32 (sharing
violation), and NO fail-silent reads.

Likewise ``kernel.py`` (PersistentKernel) is another wave's file: the default
kernel factory imports it lazily at first ``ensure_kernel()`` call, so this
module imports and tests cleanly whether or not kernel.py has landed. Tests
inject a stub factory and never touch a real kernel.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = [
    "ROLES",
    "TURN_KINDS",
    "CorruptStateError",
    "Session",
    "SessionError",
    "append_jsonl",
    "atomic_write_json",
    "preserve_corrupt",
    "read_json_guarded",
    "read_jsonl_guarded",
]

TURN_KINDS = ("model", "exec", "message", "system")
ROLES = ("root", "sub")

#: Session ids double as directory names — constrain them hard (no path
#: separators, no dot-dot, sane length). uuid4().hex[:12] always matches.
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

_REPLACE_TRIES = 10

META_NAME = "session.json"
TRAJECTORY_NAME = "trajectory.jsonl"


class SessionError(Exception):
    """Base error for session state problems."""


class CorruptStateError(SessionError):
    """On-disk state was unreadable; the bytes were preserved and announced.

    This is the atomic.read_json contract: corrupt state is never dropped,
    never silently replaced with a default. registry.py raises it too.
    """


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Atomic helpers — the atomic.py contract, inline (see module docstring)
# ---------------------------------------------------------------------------


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomic write: unique per-pid+thread temp in the same dir, then replace.

    Bounded retry on PermissionError (WinError 32 — the target briefly held
    open by a reader/scanner), per the house atomic_json contract.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    last_err: OSError | None = None
    for attempt in range(_REPLACE_TRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:  # WinError 32: sharing violation
            last_err = exc
            time.sleep(0.05 * (attempt + 1))
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    raise SessionError(
        f"atomic replace of {path} failed after {_REPLACE_TRIES} attempts: {last_err}"
    ) from last_err


def atomic_write_json(path: Path, obj: object) -> None:
    """Atomically serialize ``obj`` as UTF-8 JSON at ``path``."""
    text = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_bytes(path, text.encode("utf-8"))


def append_jsonl(path: Path, record: dict) -> None:
    """Append one JSONL record atomically (existing bytes + line, one replace)."""
    append_jsonl_many(path, [record])


def append_jsonl_many(path: Path, records: Iterable[dict]) -> None:
    """Append several JSONL records in ONE atomic replace (no torn writes)."""
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records]
    if not lines:
        return
    existing = b""
    if path.exists():
        existing = path.read_bytes()
        if existing and not existing.endswith(b"\n"):
            existing += b"\n"
    payload = existing + ("\n".join(lines) + "\n").encode("utf-8")
    _atomic_write_bytes(path, payload)


def preserve_corrupt(path: Path, reason: str) -> Path:
    """Preserve unreadable state bytes, announce on stderr. Caller then raises."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    dest = path.with_name(f"{path.name}.corrupt-{stamp}-{os.getpid()}")
    try:
        data = path.read_bytes()
    except OSError:
        data = b""
    _atomic_write_bytes(dest, data)
    print(
        f"[dottie-rlm] CORRUPT state in {path}: {reason}; bytes preserved at {dest}",
        file=sys.stderr,
    )
    return dest


def read_json_guarded(path: Path) -> Any:
    """Read+parse JSON. Corrupt (bad UTF-8 or bad JSON) → preserve + raise.

    Missing raises FileNotFoundError — "missing is empty" is a CALLER policy
    (the caller checks ``exists()`` first when a default is legitimate);
    unreadable never gets a default.
    """
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        dest = preserve_corrupt(path, f"not valid UTF-8 ({exc})")
        raise CorruptStateError(
            f"{path} is not valid UTF-8; bytes preserved at {dest}"
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        dest = preserve_corrupt(path, f"invalid JSON ({exc})")
        raise CorruptStateError(
            f"{path} is corrupt (invalid JSON); bytes preserved at {dest}"
        ) from exc


def read_jsonl_guarded(path: Path) -> list[dict]:
    """Read a JSONL file into a list of dicts. Missing → empty list.

    Any undecodable / unparseable / non-object line → preserve + raise
    :class:`CorruptStateError`. Blank lines are tolerated.
    """
    if not path.exists():
        return []  # missing is empty; unreadable (below) is NOT
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        dest = preserve_corrupt(path, f"not valid UTF-8 ({exc})")
        raise CorruptStateError(
            f"{path} is not valid UTF-8; bytes preserved at {dest}"
        ) from exc
    records: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            dest = preserve_corrupt(path, f"invalid JSON on line {lineno} ({exc})")
            raise CorruptStateError(
                f"{path} line {lineno} is not valid JSON; bytes preserved at {dest}"
            ) from exc
        if not isinstance(obj, dict):
            dest = preserve_corrupt(path, f"line {lineno} is not a JSON object")
            raise CorruptStateError(
                f"{path} line {lineno} is not a JSON object; bytes preserved at {dest}"
            )
        records.append(obj)
    return records


# ---------------------------------------------------------------------------
# Kernel factory (lazy — kernel.py is another wave's file)
# ---------------------------------------------------------------------------


def _default_kernel_factory() -> Any:
    try:
        from .kernel import PersistentKernel
    except ImportError as exc:
        raise SessionError(
            "no kernel_factory was configured and dottie_rlm.kernel is not "
            f"importable ({exc}). Pass kernel_factory= to Session/SessionRegistry, "
            "or land kernel.py (it is a separate wave's file)."
        ) from exc
    return PersistentKernel()


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class Session:
    """One agent: one (lazily built) kernel + one persistent history.

    All constructor arguments are keyword-only. ``kernel_factory`` is how
    tests stay kernel-free: inject any zero-arg callable and
    :meth:`ensure_kernel` uses it instead of importing kernel.py.
    """

    def __init__(
        self,
        *,
        role: str = "root",
        parent_id: str | None = None,
        model_spec: str = "fake:",
        base_prompt: str = "",
        id: str | None = None,
        created_utc: str | None = None,
        kernel: Any = None,
        kernel_factory: Callable[[], Any] | None = None,
        history: list[dict] | None = None,
    ) -> None:
        if role not in ROLES:
            raise ValueError(f"invalid role {role!r}: must be one of {ROLES}")
        sid = id if id is not None else uuid.uuid4().hex[:12]
        if not isinstance(sid, str) or not _ID_RE.fullmatch(sid) or ".." in sid:
            raise ValueError(
                f"invalid session id {sid!r}: must match [A-Za-z0-9][A-Za-z0-9._-]* "
                "with no path separators (ids double as directory names)"
            )
        if parent_id is not None and (
            not isinstance(parent_id, str) or not _ID_RE.fullmatch(parent_id)
        ):
            raise ValueError(f"invalid parent_id {parent_id!r}")
        if history is not None and not all(isinstance(t, dict) for t in history):
            raise ValueError("history must be a list of turn dicts")

        self.id = sid
        self.parent_id = parent_id
        self.role = role
        self.model_spec = model_spec
        self.base_prompt = base_prompt
        self.created_utc = created_utc if created_utc is not None else _utc_now()
        self.kernel = kernel
        self.history: list[dict] = list(history or [])
        self._kernel_factory = kernel_factory
        self._dir: Path | None = None  # session dir once bound (saved/loaded)
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return (
            f"Session(id={self.id!r}, role={self.role!r}, "
            f"parent_id={self.parent_id!r}, turns={len(self.history)}, "
            f"kernel={'yes' if self.kernel is not None else 'no'})"
        )

    # -- kernel ---------------------------------------------------------------

    def ensure_kernel(self) -> Any:
        """Return the kernel, building a FRESH one via the factory if absent."""
        with self._lock:
            if self.kernel is None:
                factory = self._kernel_factory or _default_kernel_factory
                self.kernel = factory()
            return self.kernel

    def drop_kernel(self) -> None:
        """Drop the in-memory kernel (idle eviction). History is untouched."""
        with self._lock:
            self.kernel = None

    # -- turns ----------------------------------------------------------------

    def record_turn(self, kind: str, **fields: Any) -> dict:
        """Append a turn to history (and, if bound to a dir, to the trajectory).

        ``kind`` must be one of :data:`TURN_KINDS`; ``t`` and ``kind`` are
        reserved keys and may not appear in ``fields``.
        """
        if kind not in TURN_KINDS:
            raise ValueError(f"invalid turn kind {kind!r}: must be one of {TURN_KINDS}")
        # "kind" can never appear in **fields (Python raises TypeError on the
        # collision with the positional parameter); "t" is the reachable one.
        if "t" in fields:
            raise ValueError("reserved turn key may not be supplied: 't'")
        turn: dict = {"t": _utc_now(), "kind": kind, **fields}
        with self._lock:
            self.history.append(turn)
            if self._dir is not None:
                append_jsonl(self._dir / TRAJECTORY_NAME, turn)
        return turn

    # -- persistence ----------------------------------------------------------

    @property
    def session_dir(self) -> Path | None:
        """The bound ``<dir>/<id>`` directory, or None before first save/load."""
        return self._dir

    def save(self, directory: str | Path) -> Path:
        """Persist meta atomically + append any not-yet-persisted turns.

        Reconciles against the existing trajectory by line count, so calling
        ``save`` repeatedly (or after live appends) never duplicates lines.
        Returns the session directory.
        """
        with self._lock:
            sdir = Path(directory) / self.id
            sdir.mkdir(parents=True, exist_ok=True)
            meta = {
                "id": self.id,
                "parent_id": self.parent_id,
                "role": self.role,
                "model_spec": self.model_spec,
                "created_utc": self.created_utc,
                "base_prompt": self.base_prompt,
                "saved_utc": _utc_now(),
                "turns": len(self.history),
            }
            atomic_write_json(sdir / META_NAME, meta)
            traj_path = sdir / TRAJECTORY_NAME
            already = len(read_jsonl_guarded(traj_path))  # corrupt → loud, never guessed
            if already > len(self.history):
                raise SessionError(
                    f"{traj_path} holds {already} turns but this Session only has "
                    f"{len(self.history)} in memory — refusing to save over a longer "
                    "trajectory (another writer? stale object?)."
                )
            append_jsonl_many(traj_path, self.history[already:])
            self._dir = sdir
            return sdir

    @classmethod
    def load(
        cls,
        directory: str | Path,
        id: str,
        *,
        kernel_factory: Callable[[], Any] | None = None,
    ) -> Session:
        """Reconstruct meta + history from ``<directory>/<id>``.

        The kernel namespace is NOT persisted: the returned session has
        ``kernel=None`` (fresh kernel on first ``ensure_kernel()``), history
        intact. Missing session → FileNotFoundError. Corrupt session.json or
        trajectory.jsonl → preserve + announce + :class:`CorruptStateError`.
        """
        sdir = Path(directory) / id
        meta_path = sdir / META_NAME
        if not meta_path.exists():
            raise FileNotFoundError(
                f"no session {id!r} under {directory} ({meta_path} does not exist)"
            )
        meta = read_json_guarded(meta_path)
        if not isinstance(meta, dict):
            dest = preserve_corrupt(meta_path, "top-level value is not an object")
            raise CorruptStateError(
                f"{meta_path} is corrupt (expected an object); bytes preserved at {dest}"
            )
        for key in ("id", "role", "created_utc"):
            if not isinstance(meta.get(key), str):
                dest = preserve_corrupt(meta_path, f"missing/invalid {key!r} field")
                raise CorruptStateError(
                    f"{meta_path} is corrupt (missing/invalid {key!r}); "
                    f"bytes preserved at {dest}"
                )
        if meta["id"] != id:
            dest = preserve_corrupt(
                meta_path, f"meta id {meta['id']!r} does not match directory id {id!r}"
            )
            raise CorruptStateError(
                f"{meta_path} is corrupt (id {meta['id']!r} != directory {id!r}); "
                f"bytes preserved at {dest}"
            )
        if meta["role"] not in ROLES:
            dest = preserve_corrupt(meta_path, f"invalid role {meta['role']!r}")
            raise CorruptStateError(
                f"{meta_path} is corrupt (role {meta['role']!r} not in {ROLES}); "
                f"bytes preserved at {dest}"
            )
        history = read_jsonl_guarded(sdir / TRAJECTORY_NAME)  # missing → empty
        session = cls(
            id=meta["id"],
            parent_id=meta.get("parent_id"),
            role=meta["role"],
            model_spec=str(meta.get("model_spec", "fake:")),
            base_prompt=str(meta.get("base_prompt", "")),
            created_utc=meta["created_utc"],
            kernel=None,  # documented: reload = fresh kernel, history intact
            kernel_factory=kernel_factory,
            history=history,
        )
        session._dir = sdir
        return session
