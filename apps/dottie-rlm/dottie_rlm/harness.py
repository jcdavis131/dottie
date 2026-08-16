"""harness.py — H = (rho, G, K, M) per SPEC.md.

- rho: base system prompt. IMMUTABLE. Stored once at ``<root>/base_prompt.md``
  with its sha256 recorded at ``<root>/base_prompt.sha256``. Any refinement
  targeting rho is REJECTED with :class:`RhoImmutableError`; any on-disk
  tampering is detected on load and refused loudly.
- G: sub-agent defaults (model spec per role), stored at ``<root>/agents.json``.
- K: skills — markdown files in ``<root>/skills/``.
- M: memory — markdown notes in ``<root>/memory/``.
- Refinement ledger: ``<root>/refinements.jsonl``, strictly append-only.
  Outcome recording and rollback are expressed as APPENDED marker records
  ({"outcome_for": ...} / {"rollback_of": ...}) and folded into the base
  entries by :meth:`Harness.ledger` — the file is never rewritten in place.

NOTE (Wave A build order): the atomic write/append helpers here
(``_atomic_write_bytes`` / ``_append_jsonl`` / guarded reads) are written
INLINE so this module does not depend on ``atomic.py``, which is owned by a
different wave and may not exist yet. Wave C may unify them onto atomic.py;
the contract is the same: per-pid+thread temp file + ``os.replace`` with a
bounded retry on WinError 32, and NO fail-silent reads (missing is empty;
corrupt is preserved as ``<name>.corrupt-<ts>-<pid>``, announced on stderr,
then raised loudly).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "DEFAULT_RHO",
    "Harness",
    "HarnessError",
    "LedgerCorruptError",
    "Refinement",
    "RefinementOrderError",
    "RhoImmutableError",
    "UnknownRefinementError",
]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HarnessError(Exception):
    """Base error for harness state problems."""


class RhoImmutableError(HarnessError):
    """The base prompt (rho) is immutable; the attempted operation touches it."""


class UnknownRefinementError(HarnessError):
    """A refinement id was addressed that does not exist in the ledger."""


class RefinementOrderError(HarnessError):
    """Rolling this back would destroy a NEWER refinement to the same target.

    Roll back in reverse order (newest first); the message names the blocker.
    """


class LedgerCorruptError(HarnessError):
    """The refinement ledger is unreadable/inconsistent (preserved + loud)."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RHO = (
    "You are Dottie-RLM, a recursive language-model agent. You have exactly ONE\n"
    "tool: a persistent IPython kernel. Everything else — file edits, shell,\n"
    "sub-agents, messaging, compaction — is a function call INSIDE that kernel.\n"
    "Write fenced ```python blocks to act; reply with no code block to answer.\n"
)

_VALID_TARGETS = ("skills", "memory", "agents")
_VALID_OPS = ("add", "update", "remove")
# Any of these as a refinement target means "edit the base prompt" — rejected.
_RHO_ALIASES = frozenset(
    {"rho", "base_prompt", "base-prompt", "baseprompt", "prompt", "system", "system_prompt"}
)
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
_TRUNCATE_NOTE_CHARS = 2_000
_REPLACE_TRIES = 10


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Local atomic helpers (inline on purpose — see module docstring)
# ---------------------------------------------------------------------------


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomic write: unique per-pid+thread temp in the same dir, then replace.

    Bounded retry on PermissionError (WinError 32 — target briefly held open
    by a scanner/reader), per the house atomic_json contract.
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
    raise HarnessError(
        f"atomic replace of {path} failed after {_REPLACE_TRIES} attempts: {last_err}"
    ) from last_err


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_json(path: Path, obj: object) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _append_jsonl(path: Path, record: dict) -> None:
    """Append one JSONL record atomically (read existing + rewrite + replace).

    Inline here so harness.py does not depend on atomic.py (Wave C may unify).
    """
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    existing = b""
    if path.exists():
        existing = path.read_bytes()
        if existing and not existing.endswith(b"\n"):
            existing += b"\n"
    _atomic_write_bytes(path, existing + line.encode("utf-8") + b"\n")


def _preserve_corrupt(path: Path, reason: str) -> Path:
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


def _read_text_guarded(path: Path) -> str:
    """UTF-8 read; undecodable bytes are preserved + announced + raised, never dropped."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        dest = _preserve_corrupt(path, f"not valid UTF-8 ({exc})")
        raise HarnessError(f"{path} is not valid UTF-8; bytes preserved at {dest}") from exc


# ---------------------------------------------------------------------------
# Refinement record
# ---------------------------------------------------------------------------


@dataclass
class Refinement:
    """One folded ledger entry: ``{"id": "r-<n>", "t", "trigger", "edit", "outcome", "rolled_back"}``."""

    id: str
    t: str
    trigger: str
    edit: dict = field(default_factory=dict)
    outcome: str | None = None
    rolled_back: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "t": self.t,
            "trigger": self.trigger,
            "edit": dict(self.edit),
            "outcome": self.outcome,
            "rolled_back": self.rolled_back,
        }


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class Harness:
    """H = (rho, G, K, M) with an append-only refinement ledger.

    ``root`` is the harness directory itself (SPEC's ``harness/``); tests pass
    a tmp_path. On first construction rho is written once (``base_prompt``
    argument, else :data:`DEFAULT_RHO`) and its sha256 recorded. Later
    constructions verify the recorded hash and refuse a differing
    ``base_prompt`` argument — rho is immutable.
    """

    def __init__(self, root: str | Path, base_prompt: str | None = None) -> None:
        self.root = Path(root)
        self.skills_dir = self.root / "skills"
        self.memory_dir = self.root / "memory"
        self.rho_path = self.root / "base_prompt.md"
        self.rho_hash_path = self.root / "base_prompt.sha256"
        self.agents_path = self.root / "agents.json"
        self.ledger_path = self.root / "refinements.jsonl"
        self._lock = threading.RLock()

        self.root.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        if self.rho_path.exists():
            stored = _read_text_guarded(self.rho_path)
            stored_hash = _sha256_text(stored)
            if self.rho_hash_path.exists():
                recorded = _read_text_guarded(self.rho_hash_path).strip()
                if recorded != stored_hash:
                    raise RhoImmutableError(
                        f"base prompt at {self.rho_path} does not match its recorded "
                        f"hash ({recorded[:12]}… recorded vs {stored_hash[:12]}… on disk). "
                        "rho is immutable — it was modified outside the harness; refusing to proceed."
                    )
            else:
                # rho exists but its hash was never recorded (half-created
                # layout): record it now, first-write semantics.
                _atomic_write_text(self.rho_hash_path, stored_hash + "\n")
            if base_prompt is not None and base_prompt != stored:
                raise RhoImmutableError(
                    f"rho is immutable: a base prompt is already recorded at {self.rho_path} "
                    "and the one supplied differs; refusing to overwrite."
                )
            self._rho = stored
        else:
            text = DEFAULT_RHO if base_prompt is None else base_prompt
            _atomic_write_text(self.rho_path, text)
            _atomic_write_text(self.rho_hash_path, _sha256_text(text) + "\n")
            self._rho = text

        self._rho_hash = _sha256_text(self._rho)

    # -- rho -----------------------------------------------------------------

    @property
    def rho(self) -> str:
        """The immutable base prompt."""
        return self._rho

    @property
    def rho_hash(self) -> str:
        """sha256 hex of rho, as recorded at creation."""
        return self._rho_hash

    # -- K / M / G readers ----------------------------------------------------

    def skills(self) -> dict[str, str]:
        """name -> markdown content of every skill file."""
        return self._read_md_dir(self.skills_dir)

    def memory(self) -> dict[str, str]:
        """name -> markdown content of every memory note."""
        return self._read_md_dir(self.memory_dir)

    def agents(self) -> dict[str, str]:
        """role -> model spec (G). Missing file is empty; corrupt is loud."""
        return self._read_agents()

    def model_for(self, role: str) -> str | None:
        """Convenience: the default model spec for a role, or None."""
        return self._read_agents().get(role)

    @staticmethod
    def _read_md_dir(directory: Path) -> dict[str, str]:
        out: dict[str, str] = {}
        if not directory.exists():
            return out
        for p in sorted(directory.glob("*.md")):
            out[p.stem] = _read_text_guarded(p)
        return out

    def _read_agents(self) -> dict[str, str]:
        if not self.agents_path.exists():
            return {}
        text = _read_text_guarded(self.agents_path)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            dest = _preserve_corrupt(self.agents_path, f"invalid JSON ({exc})")
            raise HarnessError(
                f"{self.agents_path} is corrupt (invalid JSON); bytes preserved at {dest}"
            ) from exc
        if not isinstance(obj, dict):
            dest = _preserve_corrupt(self.agents_path, "top-level value is not an object")
            raise HarnessError(
                f"{self.agents_path} is corrupt (expected an object); bytes preserved at {dest}"
            )
        return {str(k): str(v) for k, v in obj.items()}

    # -- effective prompt ------------------------------------------------------

    def effective_prompt(self) -> str:
        """rho + skill listing + memory digest. Rebuilt from disk on every call,
        never mutated in place — rho itself is untouched."""
        parts: list[str] = [self._rho.rstrip("\n"), "", "## Skills"]
        skills = self.skills()
        if skills:
            for name in sorted(skills):
                parts.append(f"- {name}: {self._describe(skills[name])}")
        else:
            parts.append("- (none)")
        parts += ["", "## Memory"]
        memory = self.memory()
        if memory:
            for name in sorted(memory):
                parts.append(f"### {name}")
                parts.append(self._truncate(memory[name].rstrip("\n")))
        else:
            parts.append("- (none)")
        return "\n".join(parts) + "\n"

    @staticmethod
    def _describe(content: str) -> str:
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if not lines:
            return "(empty)"
        for ln in lines:
            if not ln.startswith("#"):
                return ln[:200]
        return lines[0].lstrip("#").strip()[:200]

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) <= _TRUNCATE_NOTE_CHARS:
            return text
        over = len(text) - _TRUNCATE_NOTE_CHARS
        return text[:_TRUNCATE_NOTE_CHARS] + f"\n...[truncated {over} chars]"

    # -- ledger ----------------------------------------------------------------

    def ledger(self) -> list[dict]:
        """Folded ledger: refinement entries in order, with outcome/rollback
        markers applied. Missing file is an empty ledger; corrupt is loud."""
        with self._lock:
            raw = self._read_ledger_raw()
        entries: dict[str, dict] = {}
        order: list[str] = []
        for rec in raw:
            if "edit" in rec:
                rid = rec.get("id")
                if not isinstance(rid, str):
                    raise LedgerCorruptError(
                        f"{self.ledger_path}: refinement record without a string id: {rec!r}"
                    )
                entries[rid] = dict(rec)
                order.append(rid)
            elif "outcome_for" in rec:
                rid = rec["outcome_for"]
                if rid not in entries:
                    raise LedgerCorruptError(
                        f"{self.ledger_path}: outcome marker for unknown refinement {rid!r}"
                    )
                entries[rid]["outcome"] = rec.get("outcome")
            elif "rollback_of" in rec:
                rid = rec["rollback_of"]
                if rid not in entries:
                    raise LedgerCorruptError(
                        f"{self.ledger_path}: rollback marker for unknown refinement {rid!r}"
                    )
                entries[rid]["rolled_back"] = True
            else:
                raise LedgerCorruptError(
                    f"{self.ledger_path}: unrecognized ledger record shape: {rec!r}"
                )
        return [entries[rid] for rid in order]

    def _read_ledger_raw(self) -> list[dict]:
        if not self.ledger_path.exists():
            return []  # missing is empty; unreadable (below) is NOT
        text = _read_text_guarded(self.ledger_path)
        records: list[dict] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                dest = _preserve_corrupt(
                    self.ledger_path, f"invalid JSON on line {lineno} ({exc})"
                )
                raise LedgerCorruptError(
                    f"{self.ledger_path} line {lineno} is not valid JSON; "
                    f"bytes preserved at {dest}"
                ) from exc
            if not isinstance(obj, dict):
                dest = _preserve_corrupt(
                    self.ledger_path, f"line {lineno} is not a JSON object"
                )
                raise LedgerCorruptError(
                    f"{self.ledger_path} line {lineno} is not a JSON object; "
                    f"bytes preserved at {dest}"
                )
            records.append(obj)
        return records

    # -- refine / outcome / rollback -------------------------------------------

    def refine(
        self,
        trajectory_tail: str,
        trigger: str,
        edit: dict | None = None,
    ) -> Refinement:
        """Apply the SMALLEST relevant edit to G/K/M (never rho) and ledger it.

        If ``edit`` is given it must be
        ``{"target": "skills"|"memory"|"agents", "op": "add"|"update"|"remove",
        "name": str, "content": str|None}``. If omitted, the smallest edit is
        derived deterministically: a single memory note capturing the trigger
        and the trajectory tail (update-by-append if the note already exists).
        Any edit targeting rho raises :class:`RhoImmutableError` and appends
        NOTHING to the ledger.
        """
        with self._lock:
            raw = self._read_ledger_raw()
            next_n = sum(1 for rec in raw if "edit" in rec) + 1
            rid = f"r-{next_n}"
            if edit is None:
                edit = self._derive_edit(trajectory_tail, trigger)
            staged = self._validate_and_stage(dict(edit))
            self._apply(staged)
            entry = {
                "id": rid,
                "t": _utc_now(),
                "trigger": trigger,
                "edit": staged,
                "outcome": None,
                "rolled_back": False,
            }
            _append_jsonl(self.ledger_path, entry)
            return Refinement(**entry)

    def record_outcome(self, refinement_id: str, outcome: str) -> None:
        """Attach an outcome to a ledger entry (appends a marker record)."""
        with self._lock:
            entries = {e["id"] for e in self.ledger()}
            if refinement_id not in entries:
                raise UnknownRefinementError(
                    f"no refinement {refinement_id!r} in {self.ledger_path}"
                )
            _append_jsonl(
                self.ledger_path,
                {"outcome_for": refinement_id, "outcome": str(outcome), "t": _utc_now()},
            )

    @staticmethod
    def _same_target(a: dict | None, b: dict | None) -> bool:
        """Two edits touch the same object (same target bucket AND name)."""
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        return (a.get("target"), a.get("name")) == (b.get("target"), b.get("name"))

    @staticmethod
    def _seq(refinement_id: str) -> int:
        """Numeric ordering key for ``r-<n>`` ids.

        String comparison is what the out-of-order-rollback guard originally
        used, and it silently breaks past r-9: ``"r-10" > "r-2"`` is False,
        because '1' < '2' at the second character, even though 10 is
        numerically newer than 2. That let rollback(r-2) proceed as if r-10
        did not exist -- reproducing the exact corruption this guard was
        built to prevent (harness.py:615's r-1/r-2 case), just for the 10th
        refinement to any target instead of the 2nd.
        """
        m = re.match(r"^r-(\d+)$", refinement_id)
        if not m:
            raise HarnessError(f"unrecognized refinement id format: {refinement_id!r}")
        return int(m.group(1))

    def rollback(self, refinement_id: str) -> dict:
        """Reverse the edit of ``refinement_id`` and mark it rolled back.

        Idempotent: rolling back an already-rolled-back refinement is a no-op
        with a clear message (no marker appended, nothing reversed twice).
        """
        with self._lock:
            entry = next(
                (e for e in self.ledger() if e["id"] == refinement_id), None
            )
            if entry is None:
                raise UnknownRefinementError(
                    f"no refinement {refinement_id!r} in {self.ledger_path}"
                )
            if entry.get("rolled_back"):
                return {
                    "id": refinement_id,
                    "rolled_back": True,
                    "no_op": True,
                    "message": (
                        f"{refinement_id} is already rolled back; "
                        "rollback of a rollback is a no-op."
                    ),
                }
            edit = entry["edit"]
            # A LATER live refinement to the same target owns the current
            # content. Reversing an older one on top of it destroys the newer
            # edit: r-1 add skills/foo "A", r-2 update skills/foo "B",
            # rollback('r-1') saw op="add" and unlinked foo.md -- taking B with
            # it (review finding harness.py:615). Out-of-order rollback is
            # refused, and the message names the entry that has to go first.
            target_seq = self._seq(refinement_id)
            superseding = [
                e["id"]
                for e in self.ledger()
                if e["id"] != refinement_id
                and not e.get("rolled_back")
                and self._same_target(e.get("edit"), edit)
                and self._seq(e["id"]) > target_seq
            ]
            if superseding:
                raise RefinementOrderError(
                    f"{refinement_id} cannot be rolled back while "
                    f"{superseding} still apply to the same target "
                    f"({edit.get('target')}/{edit.get('name')}). Roll back "
                    f"{superseding[-1]} first, or the newer content would be "
                    f"destroyed along with this one."
                )
            self._reverse(edit)
            _append_jsonl(
                self.ledger_path, {"rollback_of": refinement_id, "t": _utc_now()}
            )
            return {
                "id": refinement_id,
                "rolled_back": True,
                "no_op": False,
                "message": (
                    f"reversed {edit['op']} of {edit['target']}/{edit['name']}"
                ),
            }

    # -- edit machinery --------------------------------------------------------

    def _derive_edit(self, trajectory_tail: str, trigger: str) -> dict:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", (trigger or "").strip().lower()).strip("-")[:40]
        name = slug or "note"
        tail = (trajectory_tail or "").strip()
        if len(tail) > _TRUNCATE_NOTE_CHARS:
            tail = tail[-_TRUNCATE_NOTE_CHARS:]
        addition = f"# {trigger}\n\nTrajectory tail:\n\n{tail}\n"
        existing = self.memory()
        if name in existing:
            return {
                "target": "memory",
                "op": "update",
                "name": name,
                "content": existing[name].rstrip("\n") + "\n\n---\n\n" + addition,
            }
        return {"target": "memory", "op": "add", "name": name, "content": addition}

    def _validate_and_stage(self, edit: dict) -> dict:
        target = edit.get("target")
        if isinstance(target, str) and target.strip().lower() in _RHO_ALIASES:
            raise RhoImmutableError(
                f"refinement targeting {target!r} rejected: rho (the base prompt) is "
                f"IMMUTABLE. Refinements may only target {', '.join(_VALID_TARGETS)}."
            )
        if target not in _VALID_TARGETS:
            raise ValueError(
                f"invalid refinement target {target!r}: must be one of {_VALID_TARGETS}"
            )
        op = edit.get("op")
        if op not in _VALID_OPS:
            raise ValueError(f"invalid refinement op {op!r}: must be one of {_VALID_OPS}")
        name = edit.get("name")
        if (
            not isinstance(name, str)
            or not _NAME_RE.fullmatch(name)
            or ".." in name
            or "/" in name
            or "\\" in name
        ):
            raise ValueError(
                f"invalid refinement name {name!r}: must match "
                "[A-Za-z0-9][A-Za-z0-9._-]* with no path separators"
            )
        content = edit.get("content")
        if op in ("add", "update"):
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"op {op!r} requires non-empty string content")
        else:
            content = None

        prev_content: str | None = None
        if target == "agents":
            agents = self._read_agents()
            exists = name in agents
            if exists:
                prev_content = agents[name]
        else:
            path = self._md_path(target, name)
            exists = path.exists()
            if exists:
                prev_content = _read_text_guarded(path)
        if op == "add" and exists:
            raise ValueError(
                f"{target}/{name} already exists; use op='update' to change it"
            )
        if op in ("update", "remove") and not exists:
            raise ValueError(f"{target}/{name} does not exist; cannot {op}")

        return {
            "target": target,
            "op": op,
            "name": name,
            "content": content,
            "prev_content": prev_content,
        }

    def _md_path(self, target: str, name: str) -> Path:
        directory = self.skills_dir if target == "skills" else self.memory_dir
        return directory / f"{name}.md"

    def _apply(self, edit: dict) -> None:
        target, op, name, content = edit["target"], edit["op"], edit["name"], edit["content"]
        if target == "agents":
            agents = self._read_agents()
            if op in ("add", "update"):
                agents[name] = content
            else:
                agents.pop(name, None)
            _atomic_write_json(self.agents_path, agents)
            return
        path = self._md_path(target, name)
        if op in ("add", "update"):
            _atomic_write_text(path, content)
        else:
            path.unlink(missing_ok=True)

    def _reverse(self, edit: dict) -> None:
        target, op, name = edit["target"], edit["op"], edit["name"]
        prev = edit.get("prev_content")
        if op in ("update", "remove") and not isinstance(prev, str):
            raise HarnessError(
                f"cannot reverse {op} of {target}/{name}: no prev_content recorded"
            )
        if target == "agents":
            agents = self._read_agents()
            if op == "add":
                agents.pop(name, None)
            else:  # update/remove — restore the previous value
                agents[name] = prev
            _atomic_write_json(self.agents_path, agents)
            return
        path = self._md_path(target, name)
        if op == "add":
            path.unlink(missing_ok=True)
        else:  # update/remove — restore the previous content
            _atomic_write_text(path, prev)
