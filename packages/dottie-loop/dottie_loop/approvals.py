"""Identity layers, the scope lattice and one-time approval tokens (spec §07, §37C).

An approval binds ``approval_id`` (a nonce consumed at most once), the approver,
the action type, the canonical action digest, the exact destination, the goal id,
issue/expiry times and the consumed timestamp. The executor recalculates the
digest immediately before the action; any mismatch, expiry, replay, scope increase
or destination change invalidates the token. Approvals are never transitive.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dottie_loop.errors import (
    ApprovalRequiredError,
    InvalidInputError,
    PolicyDeniedError,
)
from dottie_loop.hashing import digest, new_id, now_iso, parse_iso
from dottie_loop.schema import active

# --- §07 scope lattice ----------------------------------------------------------

#: scope -> (default, elevation rule). Data, not code, so policy is auditable.
SCOPE_LATTICE: dict[str, dict[str, str]] = {
    "read_local": {"default": "allowed_within_workspace", "elevation": "path expansion requires policy"},
    "write_local": {"default": "allowed_within_root", "elevation": "writes outside root denied"},
    "network_read": {"default": "domain_allowlist", "elevation": "per-connector capability"},
    "external_send": {"default": "denied", "elevation": "exact destination and content approval"},
    "credential_use": {"default": "denied", "elevation": "secure broker for intended target"},
    "production_mutate": {"default": "denied", "elevation": "explicit fresh approval"},
    "training_capture": {"default": "off", "elevation": "opt-in capture consent"},
}

#: Scopes whose default is denied and therefore need an approval token per action.
APPROVAL_SCOPES = frozenset({"external_send", "credential_use", "production_mutate"})

#: Action types an approval may name (§37C). One approval covers exactly one.
ACTION_TYPES = frozenset(
    {"merge", "release", "deploy", "promote", "send", "purchase", "capture", "credential", "experiment"}
)

#: An approval for one action type can never be reused for another (§07
#: "Approval identity", "Never transitive").
NON_TRANSITIVE_NOTE = (
    "'run this goal' does not imply send, capture, merge, deploy or promote; "
    "each is a separate approval"
)

#: Principals of this form are agents (research stage 6 proposers). An agent may
#: propose; it never approves, claims a lease or promotes.
AGENT_SUBJECT_PREFIX = "agent:"


def is_agent_subject(subject: object) -> bool:
    """True for any spelling of an ``agent:<name>`` principal.

    The kind is the token before the first colon, compared after strip and
    casefold, so ``Agent:x``, `` agent:x`` and ``agent :x`` are all agents.
    """
    if not isinstance(subject, str):
        return False
    kind, sep, _name = subject.partition(":")
    return bool(sep) and kind.strip().casefold() == AGENT_SUBJECT_PREFIX[:-1]


def _agent_approver(approver: object) -> bool:
    if not isinstance(approver, dict):
        return False
    role = str(approver.get("role") or "").strip().casefold()
    return is_agent_subject(approver.get("subject_id")) or role == "agent"


def scope_requires_approval(scope: str) -> bool:
    if scope not in SCOPE_LATTICE:
        raise PolicyDeniedError(f"unknown scope {scope!r}", field="scope")
    return scope in APPROVAL_SCOPES


# --- approval record --------------------------------------------------------------


def action_digest(action_type: str, payload: Any, destination: str) -> str:
    """Canonical digest of (type, payload, destination) — the thing the token binds."""
    return digest({"action": action_type, "payload": payload, "destination": destination})


@dataclass
class ApprovalRecord:
    approval_id: str
    approver: dict[str, str]
    action: str
    digest: str
    destination: str
    scope: dict[str, Any]
    issued_at: str
    expires_at: str
    consumed_at: str | None = None
    schema: str = field(default_factory=lambda: active("approval-record"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "approval_id": self.approval_id,
            "approver": self.approver,
            "action": self.action,
            "digest": self.digest,
            "destination": self.destination,
            "scope": self.scope,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
        }


class ApprovalStore:
    """In-memory, thread-safe approval registry with append-only decision history.

    Persisting is the caller's job (write ``history`` as JSONL); the verification
    logic is the contract and is what the tests pin.
    """

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._history: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.replay_attempts = 0

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def issue(
        self,
        *,
        approver_subject: str,
        approver_role: str,
        action_type: str,
        payload: Any,
        destination: str,
        goal_id: str,
        ttl_seconds: int = 900,
        limits: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        if action_type not in ACTION_TYPES:
            raise InvalidInputError(f"unknown action type {action_type!r}", field="action")
        if not destination:
            raise InvalidInputError("destination is required", field="destination")
        if not approver_subject:
            raise InvalidInputError("approver is required", field="approver")
        if _agent_approver({"subject_id": approver_subject, "role": approver_role}):
            raise PolicyDeniedError(
                "an agent cannot approve; approvals are issued by a human or operator",
                field="approver",
            )
        now = now or datetime.now(UTC)
        rec = ApprovalRecord(
            approval_id=new_id("apr_"),
            approver={"subject_id": approver_subject, "role": approver_role},
            action=action_type,
            digest=action_digest(action_type, payload, destination),
            destination=destination,
            scope={"goal_id": goal_id, "limits": limits or {}},
            issued_at=_iso(now),
            expires_at=_iso(now + timedelta(seconds=ttl_seconds)),
        )
        with self._lock:
            self._records[rec.approval_id] = rec
            self._history.append({"event": "issued", "at": rec.issued_at, **rec.to_dict()})
        return rec

    def verify_and_consume(
        self,
        approval_id: str | None,
        *,
        action_type: str,
        payload: Any,
        destination: str,
        goal_id: str,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        """Recalculate the digest immediately before the action and consume the nonce.

        Raises :class:`ApprovalRequiredError` on ANY mismatch. Replays are counted so an
        alert can fire on repeated attempts (§29 threat table).
        """
        now = now or datetime.now(UTC)
        if not approval_id:
            raise ApprovalRequiredError("no approval for this action", action=action_type)
        with self._lock:
            rec = self._records.get(approval_id)
            if rec is None:
                raise ApprovalRequiredError("unknown approval id", action=action_type)
            if _agent_approver(rec.approver):
                # a loaded or hand-built record is re-checked at consume time
                self._history.append(
                    {"event": "agent_approver_rejected", "at": _iso(now), "approval_id": approval_id}
                )
                raise PolicyDeniedError(
                    "approval was issued by an agent; agents never approve", field="approver"
                )
            if rec.consumed_at is not None:
                self.replay_attempts += 1
                self._history.append(
                    {"event": "replay_rejected", "at": _iso(now), "approval_id": approval_id}
                )
                raise ApprovalRequiredError("approval already consumed (replay)", replay=True)
            if parse_iso(rec.expires_at) <= now:
                raise ApprovalRequiredError("approval expired", expires_at=rec.expires_at)
            if rec.action != action_type:
                raise ApprovalRequiredError(
                    "approval is for a different action type", approved=rec.action
                )
            if rec.scope.get("goal_id") != goal_id:
                raise ApprovalRequiredError("approval is scoped to a different goal")
            if rec.destination != destination:
                raise ApprovalRequiredError("destination differs from the approved destination")
            expected = action_digest(action_type, payload, destination)
            if expected != rec.digest:
                raise ApprovalRequiredError("action digest differs from the approved action")
            rec.consumed_at = _iso(now)
            self._history.append(
                {"event": "consumed", "at": rec.consumed_at, "approval_id": approval_id}
            )
            return rec

    # -- persistence: records + append-only history in one JSON file --
    def save(self, path: Path) -> None:
        import json

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with self._lock:
            data = {"records": [r.to_dict() for r in self._records.values()], "history": list(self._history), "replay_attempts": self.replay_attempts}
        tmp.write_text(json.dumps(data, sort_keys=True, indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> ApprovalStore:
        import json

        store = cls()
        path = Path(path)
        if not path.exists():
            return store
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data.get("records", []):
            store._records[r["approval_id"]] = ApprovalRecord(**r)
        store._history = list(data.get("history", []))
        store.replay_attempts = int(data.get("replay_attempts", 0))
        return store

    def withdraw(self, approval_id: str, reason: str, now: datetime | None = None) -> None:
        """Withdrawal is appended, never edited (§37C "Append-only decisions")."""
        with self._lock:
            rec = self._records.get(approval_id)
            if rec is None:
                raise InvalidInputError("unknown approval id", field="approval_id")
            rec.expires_at = _iso(now or datetime.now(UTC))
            self._history.append(
                {
                    "event": "withdrawn",
                    "at": rec.expires_at,
                    "approval_id": approval_id,
                    "reason": reason,
                }
            )


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "ACTION_TYPES",
    "AGENT_SUBJECT_PREFIX",
    "APPROVAL_SCOPES",
    "SCOPE_LATTICE",
    "ApprovalRecord",
    "ApprovalStore",
    "action_digest",
    "is_agent_subject",
    "now_iso",
    "scope_requires_approval",
]
