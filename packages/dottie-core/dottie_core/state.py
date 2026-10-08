# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""WorldState: immutable, versioned, typed state substrate.

Clean-room principle: agents read and write ONE shared world-state instead of
passing raw transcripts. Every belief carries provenance and confidence. State
is immutable — writes return new versions — giving an audit trail and
time-travel debugging for free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Belief:
    """A typed fact with provenance and confidence.

    `key` names the fact. `value` is validated against the registered schema
    for that key. `confidence` is P(correct) in [0, 1]. `source` names the
    producer: 'model:<id>' | 'tool:<name>' | 'human:<id>' | 'prior'.
    `supersedes` links to the belief_id this replaces, forming a chain.
    """

    belief_id: str
    key: str
    value: Any
    confidence: float
    source: str
    at_version: int
    supersedes: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if not self.key or not self.source:
            raise ValueError("belief key and source are required")


@dataclass(frozen=True)
class Constraints:
    """Harness-owned execution envelope. The model never sets these."""

    max_cost_units: float = 100.0
    deadline_iso: str | None = None
    side_effect_class: str = "read_only"  # read_only | write_local | external_send | production_mutate
    require_hitl_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class StateRef:
    """Points at a state slice — what the model may see for one query."""

    belief_keys: tuple[str, ...] = ()
    include_actions: bool = False
    include_constraints: bool = True
    domain_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionRecord:
    """One executed action, for audit."""

    action_id: str
    kind: str
    inputs: dict[str, Any]
    at_version: int
    actor: str


# Very small schema registry: key -> python type name. Real schemas live in
# domain plugins; the core only needs enough to reject garbage at the boundary.
_SCHEMA: dict[str, str] = {}


def register_schema(key: str, type_name: str) -> None:
    """Register the expected value type for a belief key."""
    _SCHEMA[key] = type_name


def _check(key: str, value: Any) -> None:
    expected = _SCHEMA.get(key)
    if expected is None:
        return  # unregistered keys pass through; domains opt into strictness
    type_map = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
    want = type_map.get(expected)
    if want is not None and not isinstance(value, want):
        raise TypeError(f"belief {key!r} expects {expected}, got {type(value).__name__}")


@dataclass(frozen=True)
class WorldState:
    """Immutable world-state. `update()` returns a NEW state at version+1."""

    version: int
    goal_id: str
    beliefs: dict[str, Belief] = field(default_factory=dict)
    actions_taken: tuple[ActionRecord, ...] = ()
    constraints: Constraints = field(default_factory=Constraints)
    domain: dict[str, Any] = field(default_factory=dict)

    def query(self, ref: StateRef) -> dict[str, Any]:
        """Project a typed slice of state per a StateRef."""
        out: dict[str, Any] = {}
        for k in ref.belief_keys:
            b = self.beliefs.get(k)
            if b is not None:
                out[k] = {"value": b.value, "confidence": b.confidence, "source": b.source}
        if ref.include_actions:
            out["_actions"] = [
                {"kind": a.kind, "at_version": a.at_version, "actor": a.actor}
                for a in self.actions_taken
            ]
        if ref.include_constraints:
            out["_constraints"] = {
                "max_cost_units": self.constraints.max_cost_units,
                "side_effect_class": self.constraints.side_effect_class,
            }
        for k in ref.domain_keys:
            if k in self.domain:
                out[k] = self.domain[k]
        return out

    def update(self, belief: Belief, actor: str) -> "WorldState":
        """Write a belief, returning the next version. Never mutates."""
        _check(belief.key, belief.value)
        new_beliefs = dict(self.beliefs)
        new_beliefs[belief.key] = belief
        return WorldState(
            version=self.version + 1,
            goal_id=self.goal_id,
            beliefs=new_beliefs,
            actions_taken=self.actions_taken,
            constraints=self.constraints,
            domain=self.domain,
        )

    def record_action(self, action: ActionRecord, actor: str) -> "WorldState":
        """Append an action record, returning the next version."""
        return WorldState(
            version=self.version + 1,
            goal_id=self.goal_id,
            beliefs=self.beliefs,
            actions_taken=self.actions_taken + (action,),
            constraints=self.constraints,
            domain=self.domain,
        )

    def fork(self, reason: str = "") -> "WorldState":
        """Branch a copy for what-if exploration. Same version, new lineage."""
        return WorldState(
            version=self.version,
            goal_id=self.goal_id + f"?fork:{reason}" if reason else self.goal_id,
            beliefs=dict(self.beliefs),
            actions_taken=self.actions_taken,
            constraints=self.constraints,
            domain=dict(self.domain),
        )

    def diff(self, other: "WorldState") -> dict[str, Any]:
        """Keys whose beliefs differ between two states."""
        keys = set(self.beliefs) | set(other.beliefs)
        changed = {}
        for k in sorted(keys):
            a, b = self.beliefs.get(k), other.beliefs.get(k)
            if a != b:
                changed[k] = {
                    "from": a.value if a else None,
                    "to": b.value if b else None,
                }
        return {"changed_keys": changed, "version_from": self.version, "version_to": other.version}


def empty_state(goal_id: str, constraints: Constraints | None = None) -> WorldState:
    """Version-0 state for a new goal."""
    return WorldState(version=0, goal_id=goal_id, constraints=constraints or Constraints())
