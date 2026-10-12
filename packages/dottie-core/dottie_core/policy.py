# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Default-deny policy engine. Pure functions, zero I/O.

Clean-room principle: policy is deterministic code, never a prompt. The model
is never asked "should I allow this?" — the harness decides allow/deny/HITL
from rules, before the model is consulted and before any tool executes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dottie_core.state import WorldState


@dataclass(frozen=True)
class Action:
    """Something the harness is about to do."""

    kind: str  # e.g. "tool_call", "state_write", "external_send"
    name: str = ""
    side_effect_class: str = "read_only"
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    require_hitl: bool = False
    reason: str = ""
    rule_id: str = ""


@dataclass(frozen=True)
class PolicyRule:
    """One default-deny rule. First matching rule wins; no match = deny."""

    rule_id: str
    action_kinds: tuple[str, ...] = ()  # empty = any kind
    side_effect_classes: tuple[str, ...] = ()  # empty = any class
    effect: str = "allow"  # allow | deny | require_hitl
    reason: str = ""


@dataclass(frozen=True)
class Policy:
    """Ordered rules + floors. Pure: check() has no side effects."""

    rules: tuple[PolicyRule, ...] = ()
    confidence_floor: float = 0.6
    max_cost_units: float = 100.0

    def check(self, action: Action, state: WorldState) -> PolicyDecision:
        for rule in self.rules:
            kind_ok = not rule.action_kinds or action.kind in rule.action_kinds
            sec_ok = (not rule.side_effect_classes
                      or action.side_effect_class in rule.side_effect_classes)
            if kind_ok and sec_ok:
                if rule.effect == "allow":
                    return PolicyDecision(True, reason=rule.reason or "rule allow",
                                          rule_id=rule.rule_id)
                if rule.effect == "require_hitl":
                    return PolicyDecision(True, require_hitl=True,
                                          reason=rule.reason or "human approval required",
                                          rule_id=rule.rule_id)
                return PolicyDecision(False, reason=rule.reason or "rule deny",
                                      rule_id=rule.rule_id)
        # Default deny: no rule matched.
        return PolicyDecision(False, reason="default deny: no rule matched", rule_id="default")


class PolicyDeniedError(Exception):
    def __init__(self, action: Action, decision: PolicyDecision):
        self.action = action
        self.decision = decision
        super().__init__(f"policy denied {action.kind}:{action.name} — {decision.reason}")


class HITLRequiredError(Exception):
    """Control-flow gate, not a prompt. Harness persists context and waits."""

    def __init__(self, action: Action, decision: PolicyDecision, resume_token: str):
        self.action = action
        self.decision = decision
        self.resume_token = resume_token
        super().__init__(f"HITL required for {action.kind}:{action.name} — {decision.reason}")


def default_policy() -> Policy:
    """Sane default: reads allowed, local writes allowed, everything else gated."""
    return Policy(rules=(
        PolicyRule("run-goal", ("run_goal",), ("read_only", "write_local"), "allow",
                   "goal execution within read/local envelope"),
        PolicyRule("read-only", ("tool_call",), ("read_only",), "allow", "reads are safe"),
        PolicyRule("state-write", ("state_write",), ("read_only", "write_local"), "allow",
                   "state writes are versioned and reversible"),
        PolicyRule("local-write", ("tool_call",), ("write_local",), "allow",
                   "local writes stay on this machine"),
        PolicyRule("external-needs-human", ("tool_call", "external_send"),
                   ("external_send", "production_mutate"), "require_hitl",
                   "external effects need a human"),
    ))


def confidence_ok(confidence: float, policy: Policy, calibrated: bool) -> tuple[bool, str]:
    """Is a model answer confident enough to act on?

    Uncalibrated models are capped at 0.5 effective confidence: usable, never
    trusted for autonomous high-stakes decisions.
    """
    effective = confidence if calibrated else min(confidence, 0.5)
    if effective < policy.confidence_floor:
        return False, f"confidence {effective:.2f} < floor {policy.confidence_floor:.2f}"
    return True, ""
