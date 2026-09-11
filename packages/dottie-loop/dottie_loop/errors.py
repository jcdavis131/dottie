"""Error taxonomy (spec §11) and the API error envelope / HTTP conventions (§37D).

Every failure in this package is a :class:`LoopError` carrying a stable ``code``, a
safe ``message`` (never echoing sensitive values), the ``field`` it concerns when
one applies, a ``retryable`` flag and the HTTP status the boundary should return.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

# --- §11 error taxonomy ---------------------------------------------------------

#: error class -> (retry policy, required response). Kept as DATA so a policy
#: change is a config edit, not a code edit.
ERROR_TAXONOMY: dict[str, dict[str, str]] = {
    "transient_dependency": {
        "retry": "bounded",
        "response": "backoff; preserve idempotency key",
    },
    "policy_denied": {"retry": "no", "response": "stop; name missing scope"},
    "approval_required": {
        "retry": "no_automatic",
        "response": "present exact action for approval",
    },
    "invalid_input": {
        "retry": "after_correction",
        "response": "typed field error; no model guessing",
    },
    "verification_failed": {
        "retry": "patch_or_replan",
        "response": "keep failed evidence; do not mark success",
    },
    "rate_limited": {
        "retry": "no_within_task",
        "response": "hard stop for provider scope",
    },
    "stale_evidence": {
        "retry": "after_refresh",
        "response": "block promotion or decision",
    },
    "unknown": {"retry": "no", "response": "fail closed and escalate"},
}

#: Only this class may be retried automatically without a change to inputs.
AUTO_RETRYABLE = frozenset({"transient_dependency"})


def classify_error(error_class: str | None) -> str:
    """Map a raw class to the taxonomy; anything unrecognised is ``unknown`` (fail closed)."""
    if error_class in ERROR_TAXONOMY:
        return error_class
    return "unknown"


# --- §37D HTTP conventions ------------------------------------------------------

HTTP_STATUS_MEANING: dict[int, str] = {
    200: "successful read or idempotent result",
    202: "accepted asynchronous work; not complete",
    400: "malformed or invalid request",
    401: "authentication missing or invalid",
    403: "authenticated but policy denies",
    409: "conflict or idempotency mismatch",
    422: "well-formed but semantically unexecutable",
    429: "provider or local rate limit",
    503: "required backend unavailable",
}


@dataclass
class LoopError(Exception):
    """Typed failure with a stable code, safe message, field, retryable flag and status."""

    message: str
    code: str = "unknown"
    field: str | None = None
    retryable: bool = False
    status: int = 500
    error_class: str = "unknown"
    details: dict[str, Any] = dc_field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "retryable": self.retryable,
            "error_class": self.error_class,
        }
        if self.details:
            out["details"] = self.details
        return out


class InvalidInputError(LoopError):
    def __init__(self, message: str, field: str | None = None, **details: Any) -> None:
        super().__init__(
            message,
            code="invalid_input",
            field=field,
            retryable=False,
            status=400,
            error_class="invalid_input",
            details=details,
        )


class UnauthenticatedError(LoopError):
    def __init__(self, message: str = "unknown principal", **details: Any) -> None:
        super().__init__(
            message,
            code="unauthenticated",
            retryable=False,
            status=401,
            error_class="policy_denied",
            details=details,
        )


class PolicyDeniedError(LoopError):
    def __init__(self, message: str, field: str | None = None, **details: Any) -> None:
        super().__init__(
            message,
            code="policy_denied",
            field=field,
            retryable=False,
            status=403,
            error_class="policy_denied",
            details=details,
        )


class ApprovalRequiredError(LoopError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(
            message,
            code="approval_required",
            retryable=False,
            status=403,
            error_class="approval_required",
            details=details,
        )


class IdempotencyConflictError(LoopError):
    def __init__(self, message: str = "same key, different payload", **d: Any) -> None:
        super().__init__(
            message,
            code="idempotency_conflict",
            field="idempotency_key",
            retryable=False,
            status=409,
            error_class="invalid_input",
            details=d,
        )


class UnexecutableError(LoopError):
    def __init__(self, message: str, field: str | None = None, **details: Any) -> None:
        super().__init__(
            message,
            code="unexecutable",
            field=field,
            retryable=False,
            status=422,
            error_class="invalid_input",
            details=details,
        )


class VerificationFailedError(LoopError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(
            message,
            code="verification_failed",
            retryable=False,
            status=422,
            error_class="verification_failed",
            details=details,
        )


class StaleEvidenceError(LoopError):
    def __init__(self, message: str, field: str | None = None, **details: Any) -> None:
        super().__init__(
            message,
            code="stale_evidence",
            field=field,
            retryable=True,
            status=422,
            error_class="stale_evidence",
            details=details,
        )


class RateLimitedError(LoopError):
    def __init__(self, message: str = "provider rate limit", **details: Any) -> None:
        super().__init__(
            message,
            code="rate_limited",
            retryable=False,
            status=429,
            error_class="rate_limited",
            details=details,
        )


class BackendUnavailableError(LoopError):
    """Honest 503: missing model, checkpoint, torch, runner or invalid artifact."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(
            message,
            code="backend_unavailable",
            retryable=True,
            status=503,
            error_class="transient_dependency",
            details=details,
        )


class BlockedError(LoopError):
    """A typed blocked state: named dependency, owner and safe resumption condition."""

    def __init__(self, message: str, dependency: str, **details: Any) -> None:
        details = {"dependency": dependency, **details}
        super().__init__(
            message,
            code="blocked",
            retryable=True,
            status=503,
            error_class="transient_dependency",
            details=details,
        )


class TransientDependencyError(LoopError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(
            message,
            code="transient_dependency",
            retryable=True,
            status=503,
            error_class="transient_dependency",
            details=details,
        )


# --- envelopes -------------------------------------------------------------------


def new_request_id() -> str:
    return uuid.uuid4().hex


def error_envelope(
    err: LoopError, request_id: str | None = None, schema: str = "api-error-1.0.0"
) -> dict[str, Any]:
    """Spec §06 API error envelope + §37D response invariants."""
    return {
        "ok": False,
        "schema": schema,
        "request_id": request_id or new_request_id(),
        "error": err.to_dict(),
        "status": "rejected" if err.status < 500 else "unavailable",
        "http_status": err.status,
    }


def ok_envelope(
    data: Any,
    request_id: str | None = None,
    schema: str = "api-result-1.0.0",
    status: str = "ok",
    http_status: int = 200,
) -> dict[str, Any]:
    return {
        "ok": True,
        "schema": schema,
        "request_id": request_id or new_request_id(),
        "data": data,
        "status": status,
        "http_status": http_status,
    }
