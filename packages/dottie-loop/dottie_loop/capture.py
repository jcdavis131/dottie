"""Opt-in pair-session capture (spec §16) and the privacy controls it depends on (§17).

Capture is DISABLED by default (RT-12). It activates only through an explicit flag
or ``DOTTIE_TRACE_CAPTURE=1``, and every record is redacted BEFORE durable
persistence (RT-13): ``event → redact → validate → append JSONL → fsync``. An
unreachable sink records an honest error and re-raises; it never creates a
success-shaped trace.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dottie_loop.errors import (
    InvalidInputError,
    PolicyDeniedError,
    TransientDependencyError,
)
from dottie_loop.hashing import hashed_subject, new_id, now_iso
from dottie_loop.schema import active, check_compatible
from dottie_loop.timeline import SEVEN_FIELDS, validate_event

ENV_FLAG = "DOTTIE_TRACE_CAPTURE"
FEEDBACK_SIGNALS = frozenset({"accept", "reject", "edit", "apply", "dismiss"})
SURFACES = frozenset({"slack", "cli", "api", "web", "repl"})

# --- §17 data classification ------------------------------------------------------

DATA_CLASS_RULES: dict[str, dict[str, str]] = {
    "P0": {"name": "public", "training": "allowed with license and provenance"},
    "P1": {"name": "operational", "training": "allowed after validation and tenant check"},
    "P2": {"name": "personal", "training": "opt-in, minimized, redacted, purpose-bound"},
    "P3": {"name": "restricted", "training": "never; block and quarantine metadata only"},
}


def capture_enabled(flag: bool = False, env: dict[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return bool(flag) or env.get(ENV_FLAG, "") == "1"


# --- redaction ----------------------------------------------------------------------

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_BEARER = re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret|password|passwd)\b(\s*[:=]\s*|\s+)([^\s'\"]{6,})")
_KEYISH = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{12,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-+/=]{32,}\b")


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    """Remove emails, bearer/API secrets, long secret-like strings and IPs.

    Returns the redacted text and a count per detector (the redaction report).
    """
    report = {"email": 0, "secret": 0, "keyish": 0, "ip": 0, "long_token": 0}

    def sub(pattern: re.Pattern[str], repl: str, key: str, s: str) -> str:
        s2, n = pattern.subn(repl, s)
        report[key] += n
        return s2

    text = sub(_EMAIL, "[EMAIL]", "email", text)
    text = sub(_KEYISH, "[SECRET]", "keyish", text)
    text = _BEARER.sub(lambda m: (report.__setitem__("secret", report["secret"] + 1) or f"{m.group(1)}{m.group(2)}[SECRET]"), text)
    text = sub(_IPV4, "[IP]", "ip", text)
    text = sub(_IPV6, "[IP]", "ip", text)

    def long_token(m: re.Match[str]) -> str:
        tok = m.group(0)
        if _entropy(tok) >= 3.5 and not tok.isalpha():
            report["long_token"] += 1
            return "[SECRET]"
        return tok

    text = _LONG_TOKEN.sub(long_token, text)
    return text, report


#: Fields whose VALUES are user/tool content and are redacted before persistence.
#: Identity, lineage and identifier fields are hashed or content-addressed by the
#: caller and are never rewritten (a 36-char id must not become "[SECRET]").
CONTENT_FIELDS = ("goal", "turns", "actions", "tool_calls", "observations", "corrections", "feedback", "outcome", "resources")


def redact_record(rec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Redact only the content fields of a pair-session record; ids stay intact."""
    out = dict(rec)
    total = {"email": 0, "secret": 0, "keyish": 0, "ip": 0, "long_token": 0}
    for key in CONTENT_FIELDS:
        if key in out:
            out[key], rep = redact_obj(out[key])
            for k, v in rep.items():
                total[k] += v
    return out, total


def redact_obj(obj: Any) -> tuple[Any, dict[str, int]]:
    total = {"email": 0, "secret": 0, "keyish": 0, "ip": 0, "long_token": 0}

    def walk(o: Any) -> Any:
        if isinstance(o, str):
            s, rep = redact_text(o)
            for k, v in rep.items():
                total[k] += v
            return s
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o

    return walk(obj), total


# --- the record ----------------------------------------------------------------------


@dataclass
class PairSessionTrace:
    """Pair-session 1.0.0 record (§16 groups, §37B PairSessionTrace)."""

    session_id: str
    hashed_user_id: str
    surface: str
    agent_id: str
    goal: dict[str, Any]
    turns: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    corrections: list[dict[str, Any]] = field(default_factory=list)
    feedback: list[dict[str, Any]] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)
    consent_version: str = ""
    redaction_version: str = "redactor-1.0.0"
    data_class: str = "P2"
    trace_id: str = field(default_factory=lambda: new_id("trc_"))
    captured_at: str = field(default_factory=now_iso)
    schema: str = field(default_factory=lambda: active("pair-session"))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def validate_trace(rec: dict[str, Any]) -> None:
    check_compatible(rec.get("schema"), "pair-session")
    for k in ("session_id", "hashed_user_id", "surface", "agent_id", "goal", "consent_version"):
        if not rec.get(k):
            raise InvalidInputError(f"trace missing {k}", field=k)
    if rec["surface"] not in SURFACES:
        raise InvalidInputError("unknown surface", field="surface")
    if rec.get("data_class") == "P3":
        raise PolicyDeniedError("P3 restricted data is never persisted as a trace", "data_class")
    if _EMAIL.search(rec["hashed_user_id"]) or "@" in rec["hashed_user_id"]:
        raise PolicyDeniedError("hashed_user_id must not be a direct identifier", "hashed_user_id")
    for fb in rec.get("feedback", []):
        if fb.get("signal") not in FEEDBACK_SIGNALS:
            raise InvalidInputError(f"unknown feedback signal {fb.get('signal')!r}", "feedback")
    for cp in rec.get("checkpoints", []):
        missing = [f for f in SEVEN_FIELDS if f not in cp]
        if missing:
            raise InvalidInputError(f"checkpoint missing {missing}", field="checkpoints")
        validate_event({**cp, "schema": active("run-event")})


class CaptureWriter:
    """event → redact → validate → append JSONL → fsync. Off unless enabled."""

    def __init__(self, path: Path, *, enabled: bool, salt: str) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.salt = salt
        self.writes = 0

    def hash_identity(self, subject: str) -> str:
        return hashed_subject(subject, self.salt)

    def write(self, trace: PairSessionTrace | dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None  # RT-12: no file, no write, under default invocation
        rec = trace.to_dict() if isinstance(trace, PairSessionTrace) else dict(trace)
        # identity is HASHED by the caller, never redacted into shape: a direct
        # identifier here is a policy violation, not something to paper over
        if "@" in str(rec.get("hashed_user_id", "")):
            raise PolicyDeniedError("hashed_user_id must not be a direct identifier", "hashed_user_id")
        redacted, report = redact_record(rec)
        redacted["redaction_report"] = report
        validate_trace(redacted)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(redacted, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            # honest error, re-raised; no success-shaped trace
            raise TransientDependencyError(f"capture sink unreachable: {e.__class__.__name__}") from e
        self.writes += 1
        return redacted


# --- §16 export eligibility ------------------------------------------------------------


def export_eligibility(
    rec: dict[str, Any],
    *,
    consent_ledger: dict[str, dict[str, Any]],
    deletion_holds: set[str],
    detector_fired: bool = False,
) -> dict[str, Any]:
    """All six checks must pass; each failure is named. Redaction is not consent."""
    reasons: list[str] = []
    consent = consent_ledger.get(rec.get("hashed_user_id", ""), {})
    if not consent.get("capture_training") or consent.get("version") != rec.get("consent_version"):
        reasons.append("consent not active at event time")
    try:
        validate_trace(rec)
    except (InvalidInputError, PolicyDeniedError) as e:
        reasons.append(f"schema/redaction validation failed: {e.code}")
    if "@" in rec.get("hashed_user_id", ""):
        reasons.append("direct identifier present")
    outcome = rec.get("outcome") or {}
    if outcome.get("task_ok") is None:
        reasons.append("task outcome unknown")
    if detector_fired:
        reasons.append("unresolved secret/sensitive-data detector")
    if rec.get("lineage", {}).get("deletion_key") in deletion_holds:
        reasons.append("deletion hold")
    if consent.get("purpose") and consent.get("purpose") != rec.get("goal", {}).get("purpose", consent.get("purpose")):
        reasons.append("purpose changed")
    return {"eligible": not reasons, "reasons": reasons, "trace_id": rec.get("trace_id")}
