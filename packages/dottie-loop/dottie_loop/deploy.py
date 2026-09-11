"""Deployment sequence and served truth (spec §31).

Green CI is not "live". The sequence is: build from the reviewed commit and record
the artifact digest → deploy to an immutable candidate URL → health + representative
smoke BEFORE aliasing → after explicit approval, move the alias → fetch production
directly with cache-busting and compare served bytes or model hash → record
deployment id, commit, time, approver, checks and rollback target.

The fetcher is injected so the sequence is testable against a loopback server; in
production it is ``urllib`` behind the same allowlist the tool plane uses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import (
    ApprovalRequiredError,
    BlockedError,
    InvalidInputError,
    VerificationFailedError,
)
from dottie_loop.hashing import new_id, now_iso, sha256_hex

if TYPE_CHECKING:
    from collections.abc import Callable

Fetcher = "Callable[[str], tuple[int, bytes]]"


@dataclass
class DeploymentRecord:
    artifact_digest: str
    source_commit: str
    candidate_url: str
    deployment_id: str = field(default_factory=lambda: new_id("dep_"))
    smoke: dict[str, Any] = field(default_factory=dict)
    aliased_at: str | None = None
    approver: str | None = None
    approval_id: str | None = None
    served_verification: dict[str, Any] = field(default_factory=dict)
    rollback_target: str | None = None
    status: str = "candidate"
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def build_record(artifact_bytes: bytes, source_commit: str, candidate_url: str) -> DeploymentRecord:
    """Step 1-2: the digest of what was built, bound to the reviewed commit and the immutable URL."""
    if not source_commit or not candidate_url.startswith("http"):
        raise InvalidInputError("source_commit and an http(s) candidate_url are required", field="deploy")
    rec = DeploymentRecord(artifact_digest=sha256_hex(artifact_bytes), source_commit=source_commit, candidate_url=candidate_url)
    rec.events.append({"step": "build", "at": now_iso(), "digest": rec.artifact_digest})
    return rec


def smoke(rec: DeploymentRecord, fetch: Callable[[str], tuple[int, bytes]], checks: dict[str, str], *, attempts: int = 3, backoff_s: float = 0.0) -> DeploymentRecord:
    """Step 3: every URL must return 200 AND contain its expected string, under a bounded retry budget."""
    results: dict[str, dict[str, Any]] = {}
    for path, expected in checks.items():
        url = rec.candidate_url.rstrip("/") + path
        ok = False
        last: dict[str, Any] = {}
        for attempt in range(1, attempts + 1):
            status, body = fetch(url)
            text = body.decode("utf-8", errors="replace")
            ok = status == 200 and expected in text
            last = {"status": status, "found": expected in text, "attempt": attempt}
            if ok:
                break
            if backoff_s:
                time.sleep(backoff_s * attempt)
        results[path] = {"ok": ok, **last}
    rec.smoke = {"ok": all(r["ok"] for r in results.values()), "results": results, "at": now_iso()}
    rec.events.append({"step": "smoke", "at": rec.smoke["at"], "ok": rec.smoke["ok"]})
    if not rec.smoke["ok"]:
        rec.status = "smoke_failed"
        raise VerificationFailedError("pre-alias smoke failed", results=results)
    rec.status = "smoke_passed"
    return rec


def alias(rec: DeploymentRecord, *, approver: str | None, approval_id: str | None, rollback_target: str, move_alias: Callable[[], None]) -> DeploymentRecord:
    """Step 4: only after approval, and only from a smoke-passed candidate."""
    if rec.status != "smoke_passed":
        raise BlockedError("alias requires a smoke-passed candidate", dependency="smoke")
    if not approver or not approval_id:
        raise ApprovalRequiredError("production alias requires an explicit approval")
    move_alias()
    rec.approver = approver
    rec.approval_id = approval_id
    rec.rollback_target = rollback_target
    rec.aliased_at = now_iso()
    rec.status = "aliased"
    rec.events.append({"step": "alias", "at": rec.aliased_at, "approver": approver, "approval_id": approval_id})
    return rec


def verify_served(rec: DeploymentRecord, production_url: str, fetch: Callable[[str], tuple[int, bytes]], *, expected_digest: str | None = None) -> DeploymentRecord:
    """Step 5: fetch production directly with cache-busting and compare served bytes."""
    if rec.status != "aliased":
        raise BlockedError("served verification runs after aliasing", dependency="alias")
    sep = "&" if "?" in production_url else "?"
    url = f"{production_url}{sep}_cb={new_id()[:12]}"
    status, body = fetch(url)
    observed = sha256_hex(body)
    target = expected_digest or rec.artifact_digest
    passed = status == 200 and observed == target
    rec.served_verification = {"at": now_iso(), "url": url, "status": status, "observed_hash": observed, "expected_hash": target, "pass": passed}
    rec.events.append({"step": "served_verification", "at": rec.served_verification["at"], "pass": passed})
    rec.status = "live" if passed else "served_mismatch"
    if not passed:
        raise VerificationFailedError("served bytes do not match the approved artifact", observed=observed, expected=target)
    return rec
