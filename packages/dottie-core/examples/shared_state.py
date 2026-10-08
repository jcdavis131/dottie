#!/usr/bin/env python3
"""Two agents, one WorldState — the Jev-pattern differentiator.

A "researcher" and a "critic" operate on the SAME WorldState instance. No
transcripts pass between them; they read and write shared, versioned beliefs
with provenance. Each write bumps the version and the diff shows exactly what
changed. The final decision is a typed CHOOSE query against the merged state,
and the provenance table shows which agent contributed what.

Run: python3 examples/shared_state.py  (no API keys, stdlib only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_core import (  # noqa: E402
    Belief,
    HeuristicModel,
    QueryKind,
    StateRef,
    TypedQuery,
    WorldState,
    empty_state,
)

_belief_n = 0


def new_belief(key, value, confidence, source, at_version, supersedes=None):
    """Mint a belief with a unique id. Clean-room: ids are local, no registry."""
    global _belief_n
    _belief_n += 1
    return Belief(
        belief_id=f"b{_belief_n:03d}",
        key=key,
        value=value,
        confidence=confidence,
        source=source,
        at_version=at_version,
        supersedes=supersedes,
    )


def show_diff(label, before: WorldState, after: WorldState) -> None:
    d = before.diff(after)
    print(f"  [{label}] v{d['version_from']} -> v{d['version_to']}")
    for k, ch in d["changed_keys"].items():
        b = after.beliefs[k]
        print(f"    {k}: {ch['from']!r} -> {ch['to']!r} "
              f"(conf {b.confidence:.2f}, src {b.source})")


def researcher(state: WorldState) -> WorldState:
    """Researcher observes a code change and records evidence beliefs."""
    print("RESEARCHER observes the change under review...")
    s = state
    for key, value, conf in [
        ("lines_changed", 42, 1.0),
        ("tests_pass", True, 0.90),
        ("touches_auth", True, 0.95),
    ]:
        before = s
        s = s.update(
            new_belief(key, value, conf, "researcher", s.version),
            actor="researcher",
        )
        show_diff("researcher write", before, s)
    return s


def critic(state: WorldState) -> WorldState:
    """Critic reads the researcher's beliefs and adds counter-assessment.

    It never edits the researcher's beliefs in place — state is immutable.
    It writes its own beliefs (with its own provenance), superseding where
    it disagrees.
    """
    print("CRITIC reads researcher's beliefs, adds counter-assessment...")
    old = state.beliefs["tests_pass"]
    print(f"  critic sees: tests_pass={old.value} conf={old.confidence:.2f} src={old.source}")

    s = state
    # Counter-belief: passing tests don't cover the auth path — downgrade.
    before = s
    s = s.update(
        new_belief("tests_pass", True, 0.55, "critic", s.version,
                   supersedes=old.belief_id),
        actor="critic",
    )
    show_diff("critic counter-belief (supersedes b002)", before, s)

    # New assessment belief only the critic holds.
    before = s
    s = s.update(
        new_belief("risk_assessment", "high", 0.70, "critic", s.version),
        actor="critic",
    )
    show_diff("critic assessment", before, s)
    return s


def agent_query(name: str, model, state: WorldState) -> None:
    """Each agent queries the SAME shared state — no transcript passing."""
    q = TypedQuery(
        kind=QueryKind.VERIFY,
        state_ref=StateRef(belief_keys=("touches_auth", "tests_pass")),
        claim="the change is safe to auto-merge",
    )
    ans = model.decide(state, q)
    print(f"  {name} asks model: 'is the change safe to auto-merge?'")
    print(f"    -> {ans.best.value} (conf {ans.best.confidence:.2f}, "
          f"model {ans.model_id})")


def main() -> int:
    model = HeuristicModel()  # shared; a JevModel drops in via the same protocol

    state = empty_state("goal-merge-review")
    print(f"shared state created at v{state.version}\n")

    state = researcher(state)
    print()
    state = critic(state)
    print()

    print("Both agents query the SHARED state (no transcripts exchanged):")
    agent_query("researcher", model, state)
    agent_query("critic", model, state)
    print()

    # Final decision on the merged state.
    # NOTE: the heuristic's CHOOSE has a documented first-option bias and low
    # confidence — it is illustrative only. The real decision below is made by
    # the HARNESS applying deterministic policy to the shared state, which is
    # the architecture's core rule: the model scores, the harness decides.
    q = TypedQuery(
        kind=QueryKind.CHOOSE,
        state_ref=StateRef(
            belief_keys=("lines_changed", "tests_pass", "touches_auth",
                         "risk_assessment")
        ),
        options=("auto_merge", "human_review", "reject"),
    )
    ans = model.decide(state, q)
    print("MODEL OPINION (advisory only, low confidence):")
    print(f"  -> {ans.best.value} (conf {ans.best.confidence:.2f})")
    for alt in ans.alternatives:
        print(f"     alt: {alt.value} (conf {alt.confidence:.2f})")

    # Harness-owned policy: deterministic, no model call.
    risk = state.beliefs["risk_assessment"]
    auth = state.beliefs["touches_auth"]
    if risk.value == "high" and risk.confidence >= 0.6 and auth.value is True:
        decision, why = "human_review", (
            f"policy: risk_assessment=high (conf {risk.confidence:.2f}, "
            f"src {risk.source}) + touches_auth=True -> HITL required"
        )
    else:
        decision, why = str(ans.best.value), "policy: no high-risk flags, model opinion stands"
    print("\nHARNESS DECISION (deterministic policy on shared state):")
    print(f"  -> {decision}")
    print(f"     {why}")

    print("\nPROVENANCE — who contributed what to the deciding state:")
    print(f"  {'key':<16} {'value':<10} {'conf':<6} {'source':<12} belief")
    for k in ("lines_changed", "tests_pass", "touches_auth", "risk_assessment"):
        b = state.beliefs[k]
        sup = f" supersedes {b.supersedes}" if b.supersedes else ""
        print(f"  {k:<16} {str(b.value):<10} {b.confidence:<6.2f} "
              f"{b.source:<12} {b.belief_id}{sup}")

    print(f"\nstate versions traversed: 0 -> {state.version} "
          f"({len(state.beliefs)} live beliefs, full history auditable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
