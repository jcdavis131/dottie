#!/usr/bin/env python3
"""Classify a text sample as code, docs, or data — end to end, no API keys.

State in (a WorldState seeded with the sample), typed classification out
(a ScoredAnswer with calibrated-by-construction low confidence), plus a
7-field timeline and cost record. The whole run exercises:
observe -> policy -> route -> execute -> verify -> record.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_core import Goal, Harness, HeuristicModel, default_policy  # noqa: E402

SAMPLE = """\
def classify(text):
    import re
    return "code" if re.search(r"\\bdef\\b", text) else "docs"
"""


def main() -> int:
    goal = Goal(
        intent="Classify the sample as code, docs, or data",
        state_seed={"sample": SAMPLE},
    )
    harness = Harness(model=HeuristicModel(), policy=default_policy())
    result = harness.run(goal)

    belief = result.final_state.beliefs.get("classification")
    print(f"status:      {result.status}")
    if belief:
        print(f"class:       {belief.value}")
        print(f"confidence:  {belief.confidence:.3f} (heuristic: honest, low)")
        print(f"source:      {belief.source}")
    print(f"state v:     {result.final_state.version}")
    print(f"decisions:   {len(result.decisions)} model calls")
    print(f"cost units:  {result.cost.total():.1f}")
    print(f"timeline:    {len(result.timeline)} stages")
    for t in result.timeline:
        print(f"  - {t['nodeId']:<12} {t['status']:<8} {t['latency_ms']:>4}ms")
    if result.halt_reason:
        print(f"halt:        {result.halt_reason}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
