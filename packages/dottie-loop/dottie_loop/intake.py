"""Goal intake contract (spec §05, §06, §37A).

Every surface normalizes into one immutable ``GoalEnvelope``; state transitions are
appended separately. The validation order is the spec's, in the spec's order:

1. parse and size-limit before any model sees it
2. authenticate the actor and resolve the surface
3. verify idempotency (exact replay returns the existing goal; conflict is 409)
4. separate user intent from quoted / fetched / forwarded content
5. classify requested side effects and data sensitivity
6. bind explicit consent — training consent is never inferred from execution consent
7. store the immutable envelope, then append transitions
8. acknowledge receipt; never claim execution before a run exists
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dottie_loop.errors import (
    IdempotencyConflictError,
    InvalidInputError,
    PolicyDeniedError,
    UnauthenticatedError,
    UnexecutableError,
)
from dottie_loop.hashing import digest, new_id, now_iso
from dottie_loop.schema import active, check_compatible

SURFACES = frozenset({"slack", "cli", "api", "web", "repl"})
ACTOR_TYPES = frozenset({"human", "service"})
REPLY_MODES = frozenset({"thread", "stdout", "json", "web"})
DATA_CLASSES = frozenset({"P0", "P1", "P2", "P3"})

#: Bytes of raw payload accepted before parsing (validation step 1).
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_INTENT_CHARS = 8000

# --- state machine (§05) ---------------------------------------------------------

STATES = (
    "received",
    "validated",
    "planned",
    "running",
    "verified",
    "completed",
    "rejected",
    "blocked",
    "failed",
    "cancelled",
)
TERMINAL_STATES = frozenset({"completed", "rejected", "failed", "cancelled"})

#: Legal transitions. ``blocked`` may resume to the state it was blocked from once
#: its named dependency resolves; ``failed`` never resumes in place (a retry is a
#: NEW goal linked by ``retry_of``).
TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"validated", "rejected", "cancelled"}),
    "validated": frozenset({"planned", "blocked", "rejected", "cancelled"}),
    "planned": frozenset({"running", "blocked", "failed", "cancelled"}),
    "running": frozenset({"verified", "blocked", "failed", "cancelled"}),
    "verified": frozenset({"completed", "failed", "cancelled"}),
    "blocked": frozenset({"validated", "planned", "running", "failed", "cancelled"}),
    "completed": frozenset(),
    "rejected": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

# --- side effects / untrusted content ---------------------------------------------

SIDE_EFFECT_CLASSES = ("none", "read_only", "write_local", "external_send", "production_mutate")

_EXTERNAL_SEND_RE = re.compile(
    r"\b(send|email|e-mail|post|publish|tweet|message|notify|webhook|dm)\b", re.I
)
_PRODUCTION_RE = re.compile(r"\b(merge|deploy|release|promote|redeploy|ship to prod)\b", re.I)
_WRITE_RE = re.compile(r"\b(write|create|edit|modify|delete|rename|refactor|fix)\b", re.I)

#: Phrases in QUOTED / FETCHED content that ask for authority the goal does not
#: have. The content is data (§28 "Content ↔ instructions"); a request for
#: expansion inside it is a hard intake failure, not an instruction.
_AUTHORITY_EXPANSION_RE = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|rules)|"
    r"you are now (an? )?(admin|root|operator)|"
    r"grant (yourself|me|the agent) |"
    r"reveal (the |your )?(secret|api key|token|password|credential)|"
    r"disable (the )?(policy|safety|approval|gate)|"
    r"approve (this|the) (action|merge|deploy|release)|"
    r"run (as|with) (admin|root|sudo)|"
    r"bypass (the )?(approval|policy|gate))",
    re.I,
)


def classify_side_effects(intent_text: str, constraints: dict[str, Any]) -> str:
    """Coarse, conservative side-effect class from the verbatim intent + constraints."""
    if _PRODUCTION_RE.search(intent_text):
        return "production_mutate"
    if constraints.get("allowed_destinations") or _EXTERNAL_SEND_RE.search(intent_text):
        return "external_send"
    if _WRITE_RE.search(intent_text):
        return "write_local"
    return "read_only"


def find_authority_expansion(untrusted: str) -> str | None:
    m = _AUTHORITY_EXPANSION_RE.search(untrusted or "")
    return m.group(0) if m else None


# --- the envelope ---------------------------------------------------------------


@dataclass
class GoalEnvelope:
    """Immutable intake record (§37A). Built only through :func:`build_envelope`."""

    goal_id: str
    idempotency_key: str
    actor: dict[str, Any]
    source: dict[str, Any]
    intent_text: str
    constraints: dict[str, Any]
    consent: dict[str, bool]
    reply: dict[str, Any]
    created_at: str
    untrusted_content: str = ""
    side_effect_class: str = "read_only"
    data_class: str = "P1"
    approval_id: str | None = None
    retry_of: str | None = None
    schema: str = field(default_factory=lambda: active("goal-envelope"))
    status: str = "received"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "idempotency_key": self.idempotency_key,
            "actor": self.actor,
            "source": self.source,
            "intent_text": self.intent_text,
            "untrusted_content": self.untrusted_content,
            "constraints": self.constraints,
            "consent": self.consent,
            "reply": self.reply,
            "side_effect_class": self.side_effect_class,
            "data_class": self.data_class,
            "approval_id": self.approval_id,
            "retry_of": self.retry_of,
            "created_at": self.created_at,
            "status": self.status,
        }

    def payload_digest(self) -> str:
        """Digest of the caller-controlled fields, used for idempotent replay detection."""
        return digest(
            {
                "actor": self.actor,
                "source": self.source,
                "intent_text": self.intent_text,
                "untrusted_content": self.untrusted_content,
                "constraints": self.constraints,
                "consent": self.consent,
                "approval_id": self.approval_id,
            }
        )


def _require_str(obj: dict[str, Any], key: str, field_name: str, max_len: int) -> str:
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        raise InvalidInputError(f"{field_name} is required", field=field_name)
    if len(val) > max_len:
        raise InvalidInputError(f"{field_name} exceeds {max_len} characters", field=field_name)
    return val


def _bool_field(consent: dict[str, Any], key: str) -> bool:
    """Explicit boolean only. Truthy strings, 1, or None are NOT consent."""
    val = consent.get(key, False)
    if val is True:
        return True
    if val is False or val is None:
        return False
    raise InvalidInputError(f"consent.{key} must be an explicit boolean", field=f"consent.{key}")


def build_envelope(
    raw: bytes | str | dict[str, Any],
    *,
    authenticated_subject: str | None,
    surface: str,
    now: str | None = None,
) -> GoalEnvelope:
    """Steps 1–6 of the validation order. Raises typed errors; never returns a partial."""
    # 1. parse + size limit before anything else reads the payload
    if isinstance(raw, dict):
        payload = raw
        size = len(json.dumps(raw))
    else:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        size = len(data)
        if size > MAX_PAYLOAD_BYTES:
            raise InvalidInputError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes", field="payload")
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise InvalidInputError("payload is not valid JSON", field="payload") from e
    if size > MAX_PAYLOAD_BYTES:
        raise InvalidInputError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes", field="payload")
    if not isinstance(payload, dict):
        raise InvalidInputError("payload must be a JSON object", field="payload")
    if "schema" in payload:
        check_compatible(payload["schema"], "goal-envelope")

    # 2. authenticate the actor and resolve the surface
    if not authenticated_subject:
        raise UnauthenticatedError()
    if surface not in SURFACES:
        raise InvalidInputError(f"unknown surface {surface!r}", field="source.surface")
    actor_in = payload.get("actor") or {}
    actor_type = actor_in.get("type", "human")
    if actor_type not in ACTOR_TYPES:
        raise InvalidInputError("actor.type must be human|service", field="actor.type")
    actor = {
        "subject_id": authenticated_subject,
        "type": actor_type,
        "tenant": actor_in.get("tenant", "local"),
    }
    source_in = payload.get("source") or {}
    source = {
        "surface": surface,
        "channel_id": source_in.get("channel_id"),
        "thread_id": source_in.get("thread_id"),
        "event_id": source_in.get("event_id"),
    }

    # 3. idempotency key must be present (verification is the store's job)
    idem = _require_str(payload, "idempotency_key", "idempotency_key", 256)

    # 4. intent vs untrusted content
    intent = _require_str(payload, "intent_text", "intent_text", MAX_INTENT_CHARS)
    untrusted = payload.get("untrusted_content") or ""
    if not isinstance(untrusted, str):
        raise InvalidInputError("untrusted_content must be a string", "untrusted_content")
    hit = find_authority_expansion(untrusted)
    if hit:
        raise PolicyDeniedError(
            "untrusted content requests authority expansion",
            field="untrusted_content",
            matched=hit,
        )

    # 5. side effects + data sensitivity
    constraints_in = payload.get("constraints") or {}
    if not isinstance(constraints_in, dict):
        raise InvalidInputError("constraints must be an object", field="constraints")
    constraints = {
        "deadline": constraints_in.get("deadline"),
        "budget": constraints_in.get("budget"),
        "allowed_destinations": list(constraints_in.get("allowed_destinations") or []),
        "data_classes": list(constraints_in.get("data_classes") or []),
    }
    for dc in constraints["data_classes"]:
        if dc not in DATA_CLASSES:
            raise InvalidInputError(f"unknown data class {dc!r}", field="constraints.data_classes")
    data_class = max(constraints["data_classes"] or ["P1"])
    side_effect = classify_side_effects(intent, constraints)

    # 6. consent — explicit booleans, no inference between them
    consent_in = payload.get("consent") or {}
    if not isinstance(consent_in, dict):
        raise InvalidInputError("consent must be an object", field="consent")
    consent = {
        "execute": _bool_field(consent_in, "execute") if "execute" in consent_in else True,
        "external_effects": _bool_field(consent_in, "external_effects"),
        "capture_training": _bool_field(consent_in, "capture_training"),
    }
    approval_id = payload.get("approval_id")
    if side_effect in ("external_send", "production_mutate") and consent["external_effects"]:
        # asserting effect consent is only meaningful with an approval to bind to
        if not approval_id:
            raise UnexecutableError(
                "side effect requested without an approval",
                field="approval_id",
                side_effect_class=side_effect,
            )
    if data_class == "P3" and consent["capture_training"]:
        raise PolicyDeniedError("P3 restricted data can never be captured for training", "consent")

    reply_in = payload.get("reply") or {}
    mode = reply_in.get("mode") or {"slack": "thread", "cli": "stdout"}.get(surface, "json")
    if mode not in REPLY_MODES:
        raise InvalidInputError(f"unknown reply mode {mode!r}", field="reply.mode")

    return GoalEnvelope(
        goal_id=new_id(),
        idempotency_key=idem,
        actor=actor,
        source=source,
        intent_text=intent,
        untrusted_content=untrusted,
        constraints=constraints,
        consent=consent,
        reply={"mode": mode, "correlation_id": reply_in.get("correlation_id") or new_id()},
        side_effect_class=side_effect,
        data_class=data_class,
        approval_id=approval_id,
        retry_of=payload.get("retry_of"),
        created_at=now or now_iso(),
    )


# --- durable store ----------------------------------------------------------------


class GoalStore:
    """Append-only JSONL goal store with durable idempotency (§05 steps 3, 7, 8).

    Layout under ``root``::

        goals.jsonl        one immutable envelope per line
        transitions.jsonl  one state transition per line (append-only)

    Writes use a process lock plus an inter-process ``fcntl``-free strategy: each
    line is written whole, flushed and fsynced, so a concurrent reader never sees
    a torn record. Duplicate intake is prevented by re-scanning the index under
    the lock before appending (RT-02).
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.goals_path = self.root / "goals.jsonl"
        self.transitions_path = self.root / "transitions.jsonl"
        self._lock = threading.RLock()

    # -- internals --
    @staticmethod
    def _append(path: Path, record: dict[str, Any]) -> None:
        line = json.dumps(record, sort_keys=True) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def _read(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # torn final line from a writer mid-append: skip, never guess
                    continue
        return out

    def _index(self) -> dict[tuple[str, str], dict[str, Any]]:
        """(surface, idempotency_key) -> stored envelope."""
        return {
            (g["source"]["surface"], g["idempotency_key"]): g for g in self._read(self.goals_path)
        }

    # -- public --
    def submit(
        self,
        raw: bytes | str | dict[str, Any],
        *,
        authenticated_subject: str | None,
        surface: str,
        now: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Validate, dedupe, store and acknowledge. Returns ``(ack, created)``.

        ``ack`` never claims more than receipt: ``{"goal_id", "status": "received"}``
        plus ``replay: True`` when an exact replay returned the existing goal.
        """
        env = build_envelope(
            raw, authenticated_subject=authenticated_subject, surface=surface, now=now
        )
        with self._lock:
            existing = self._index().get((surface, env.idempotency_key))
            if existing is not None:
                stored = GoalEnvelope(**existing)
                if stored.payload_digest() == env.payload_digest():
                    return (
                        {
                            "goal_id": existing["goal_id"],
                            "status": self.status(existing["goal_id"]),
                            "replay": True,
                        },
                        False,
                    )
                raise IdempotencyConflictError(goal_id=existing["goal_id"])
            self._append(self.goals_path, env.to_dict())
            self._append(
                self.transitions_path,
                {
                    "goal_id": env.goal_id,
                    "from": None,
                    "to": "received",
                    "at": env.created_at,
                    "reason": "intake",
                },
            )
        return {"goal_id": env.goal_id, "status": "received", "replay": False}, True

    def list_goals(self, *, subject: str | None = None) -> list[dict[str, Any]]:
        """Envelopes in intake order; with ``subject``, only that principal's goals."""
        goals = self._read(self.goals_path)
        if subject is not None:
            goals = [g for g in goals if g.get("actor", {}).get("subject_id") == subject]
        return goals

    def get(self, goal_id: str) -> dict[str, Any] | None:
        for g in self._read(self.goals_path):
            if g["goal_id"] == goal_id:
                return g
        return None

    def transitions(self, goal_id: str) -> list[dict[str, Any]]:
        return [t for t in self._read(self.transitions_path) if t["goal_id"] == goal_id]

    def status(self, goal_id: str) -> str:
        ts = self.transitions(goal_id)
        if not ts:
            raise InvalidInputError(f"unknown goal {goal_id}", field="goal_id")
        return ts[-1]["to"]

    def transition(
        self,
        goal_id: str,
        to: str,
        *,
        reason: str = "",
        dependency: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Append a transition if the state machine allows it (§05)."""
        if to not in STATES:
            raise InvalidInputError(f"unknown state {to!r}", field="status")
        with self._lock:
            current = self.status(goal_id)
            if to not in TRANSITIONS[current]:
                raise UnexecutableError(
                    f"illegal transition {current} -> {to}", field="status", current=current
                )
            if to == "blocked" and not dependency:
                raise InvalidInputError("blocked requires a named dependency", field="dependency")
            rec = {
                "goal_id": goal_id,
                "from": current,
                "to": to,
                "at": now or now_iso(),
                "reason": reason,
                "dependency": dependency,
            }
            self._append(self.transitions_path, rec)
            return rec
