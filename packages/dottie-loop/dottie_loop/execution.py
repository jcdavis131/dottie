"""Execution kernel (spec §10), recovery ladder and verifier budget (§11), sandbox rules.

Lifecycle: ``admit → hydrate → execute → observe → verify → commit``. The kernel
never calls a model; ``execute`` is an injected callable (deterministic code, a
model client, a sandboxed CodeAct loop or a Scout command). Every attempt writes a
seven-field timeline event, including the ones that fail.
"""

from __future__ import annotations

import ipaddress
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from dottie_loop.errors import (
    AUTO_RETRYABLE,
    LoopError,
    PolicyDeniedError,
    RateLimitedError,
    classify_error,
)
from dottie_loop.timeline import RunEvent, RunStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from dottie_loop.plan import PlanStep

# --- §11 recovery ladder ---------------------------------------------------------

LADDER = ("retry", "patch", "replan", "escalate")


def next_recovery_action(error_class: str, attempt: int, max_retries: int = 1) -> str:
    """Bounded ladder: retry (transient only) → patch → replan → escalate.

    ``attempt`` is the attempt that just failed. Anything unrecognised escalates.
    """
    cls = classify_error(error_class)
    if cls in ("policy_denied", "approval_required", "rate_limited", "unknown"):
        return "escalate"
    if cls == "stale_evidence":
        return "escalate"  # a refresh is a human/infra decision, not a loop
    if cls in AUTO_RETRYABLE and attempt <= max_retries:
        return "retry"
    if cls in ("invalid_input", "verification_failed"):
        return "patch" if attempt <= 1 else ("replan" if attempt == 2 else "escalate")
    if attempt <= 2:
        return "replan"
    return "escalate"


# --- §11 verifier budget ---------------------------------------------------------

VERIFIER_MIN_SCORE = 8.0
VERIFIER_MAX_LOOPS = 2


@dataclass
class VerifierBudget:
    """Score 1-10, requires >= 8.0, fixes the largest gap once, stops after two loops.

    ``fix`` is applied to the output once; the verifier cannot change the requirement,
    hide failed checks, or substitute an opinion for a deterministic test — the
    deterministic ``checks`` are evaluated first and any failure is final.
    """

    checks: list[Callable[[Any], bool]] = field(default_factory=list)
    rubric: Callable[[Any], float] | None = None
    fix: Callable[[Any], Any] | None = None

    def run(self, output: Any) -> dict[str, Any]:
        loops = 0
        failed_checks: list[int] = []
        score: float | None = None
        while loops < VERIFIER_MAX_LOOPS:
            loops += 1
            failed_checks = [i for i, c in enumerate(self.checks) if not c(output)]
            if failed_checks:
                # deterministic failure is decisive; a rubric cannot override it
                score = None
                if self.fix is not None and loops < VERIFIER_MAX_LOOPS:
                    output = self.fix(output)
                    continue
                break
            score = float(self.rubric(output)) if self.rubric is not None else 10.0
            if score >= VERIFIER_MIN_SCORE:
                break
            if self.fix is not None and loops < VERIFIER_MAX_LOOPS:
                output = self.fix(output)
        passed = not failed_checks and score is not None and score >= VERIFIER_MIN_SCORE
        return {
            "pass": passed,
            "score": score,
            "failed_checks": failed_checks,
            "loops": loops,
            "output": output,
            "reward_eligible": passed and bool(self.checks or self.rubric),
        }


# --- §10 sandbox rules -----------------------------------------------------------


def canonical_in_root(path: str | Path, root: Path) -> Path:
    """Canonicalize and require containment in ``root``; no traversal, no symlink escape."""
    root_r = Path(root).resolve()
    cand = (root_r / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        cand.relative_to(root_r)
    except ValueError as e:
        raise PolicyDeniedError("path escapes allowed root", field="path") from e
    return cand


def check_url_allowed(url: str, domains: list[str], methods: list[str], method: str = "GET") -> None:
    """Domain/method allowlist; redirects must be re-checked by the caller with this."""
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise PolicyDeniedError("only http(s) is allowed", field="url")
    host = (u.hostname or "").lower()
    if not host:
        raise PolicyDeniedError("url has no host", field="url")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local):
        raise PolicyDeniedError("private/loopback addresses are denied (SSRF)", field="url")
    if not any(host == d.lower() or host.endswith("." + d.lower()) for d in domains):
        raise PolicyDeniedError(f"host {host} not in allowlist", field="url")
    if method.upper() not in {m.upper() for m in methods}:
        raise PolicyDeniedError(f"method {method} not allowed for {host}", field="method")


def run_argv(
    argv: list[str],
    *,
    cwd: Path,
    timeout_s: float = 30.0,
    max_output_bytes: int = 1 << 20,
    env_allow: list[str] | None = None,
) -> dict[str, Any]:
    """Argument-array execution, no shell, wall-clock and output caps, normalized env."""
    if not argv or not all(isinstance(a, str) for a in argv):
        raise PolicyDeniedError("argv must be a non-empty list of strings", field="argv")
    env = {k: os.environ[k] for k in (env_allow or ["PATH", "HOME", "LANG"]) if k in os.environ}
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            timeout=timeout_s,
            env=env,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as e:
        raise LoopError(
            "process exceeded wall-clock cap",
            code="timeout",
            error_class="transient_dependency",
            status=503,
        ) from e
    latency = int((time.monotonic() - t0) * 1000)
    out = proc.stdout[:max_output_bytes]
    err = proc.stderr[:max_output_bytes]
    return {
        "exit_code": proc.returncode,
        "stdout": out.decode("utf-8", errors="replace"),
        "stderr": err.decode("utf-8", errors="replace"),
        "truncated": len(proc.stdout) > max_output_bytes or len(proc.stderr) > max_output_bytes,
        "latency_ms": latency,
    }


# --- §10 the kernel ----------------------------------------------------------------

_SECRETISH = re.compile(r"(sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|AKIA[0-9A-Z]{12,})")


def redact_observation(text: str) -> str:
    return _SECRETISH.sub("[REDACTED]", text)


@dataclass
class ProviderScope:
    """Rate-limit hard stop: a 429 ends every further call in this provider scope (RT-15)."""

    provider: str
    blocked: bool = False
    calls: int = 0

    def call(self, fn: Callable[[], Any]) -> Any:
        if self.blocked:
            raise RateLimitedError(f"provider {self.provider} is blocked for this task")
        self.calls += 1
        try:
            return fn()
        except RateLimitedError:
            self.blocked = True
            raise


@dataclass
class Kernel:
    """admit → hydrate → execute → observe → verify → commit, resumable per node."""

    store: RunStore
    goal_id: str
    agent_id: str = "dottie"
    policy_check: Callable[[PlanStep], None] | None = None
    approval_check: Callable[[PlanStep], None] | None = None
    cancelled: bool = False
    budget_tokens: int | None = None
    tokens_used: int = 0

    def admit(self, step: PlanStep, completed: set[str]) -> None:
        if self.cancelled:
            raise LoopError("run cancelled", code="cancelled", status=409)
        missing = [d for d in step.depends_on if d not in completed]
        if missing:
            raise LoopError(f"dependencies not committed: {missing}", code="dependency", status=409)
        if self.policy_check is not None:
            self.policy_check(step)
        if step.risk.get("approval_required") and self.approval_check is not None:
            self.approval_check(step)
        if self.budget_tokens is not None and self.tokens_used >= self.budget_tokens:
            raise LoopError("token budget exhausted", code="budget_exhausted", status=409)

    def run_step(
        self,
        step: PlanStep,
        *,
        completed: set[str],
        upstream_hashes: dict[str, str],
        execute: Callable[[dict[str, Any]], bytes],
        verifier: Callable[[bytes], dict[str, Any]],
        context: dict[str, Any] | None = None,
        attempt: int = 1,
        plan_version: int = 1,
        capability_digest: str = "",
        tokens_est: int = 0,
        token_method: str = "measured_zero",  # noqa: S107 - spec field, not a secret
    ) -> dict[str, Any]:
        """One attempt. Returns the checkpoint on success; raises typed error otherwise."""
        self.admit(step, completed)
        hydrated = {"step": step.id, "inputs": step.inputs, "upstream": upstream_hashes, **(context or {})}
        t0 = time.monotonic()
        try:
            output = execute(hydrated)
        except LoopError as e:
            latency = int((time.monotonic() - t0) * 1000)
            self.store.append(
                RunEvent(
                    goal_id=self.goal_id,
                    run_id=self.store.run_id,
                    nodeId=step.id,
                    agentId=self.agent_id,
                    attempt=attempt,
                    status="failed",
                    latency_ms=latency,
                    tokens_est=tokens_est,
                    token_method=token_method,
                    errorClass=classify_error(e.error_class),
                    plan_version=plan_version,
                )
            )
            raise
        latency = int((time.monotonic() - t0) * 1000)
        if not isinstance(output, bytes):
            output = str(output).encode("utf-8")
        observed = redact_observation(output.decode("utf-8", errors="replace")).encode("utf-8")
        self.tokens_used += tokens_est
        return self.store.commit_checkpoint(
            node_id=step.id,
            attempt=attempt,
            plan_version=plan_version,
            output=observed,
            upstream_hashes=upstream_hashes,
            verifier=verifier,
            capability_digest=capability_digest,
            agent_id=self.agent_id,
            goal_id=self.goal_id,
            latency_ms=latency,
            tokens_est=tokens_est,
            token_method=token_method,
        )
