"""CausalReasonGenerator — event/condition CFA + confounder drills for agents.

Solo personal project, no connection to employer, built with public/free-tier only.
HOME-only, zero network, private RNG only, byte-identical determinism.

Teaches the *genre* of DOE-style Causal Factor Analysis (events vs conditions,
chronological chains, root-cause attribution) and elementary causal inference
(association ≠ causation, confounders, interventions) with **computed** numeric
examples. Maps directly onto agent failure analysis: tool-down → fabricated
answer is a causal chain the model must refuse to paper over.

Curriculum placement: phases (2, 3, 5).
  p2 foundation : CFA vocabulary + simple event/condition diagrams
  p3 reasoning  : confounder tables + intervention contrasts (computed)
  p5 anneal     : agent-incident CFA with provenance-honest conclusions
"""

from __future__ import annotations

from typing import Iterator

from dottie.datagen.base import Generator, run_cli

_INCIDENTS = [
    {
        "title": "uncontrolled dump truck on construction site",
        "events": [
            "project shuts down for the weekend",
            "driver parks dump truck at top of hill",
            "child enters unlocked cab",
            "handbrake is released",
            "truck rolls downhill and strikes parked cars",
        ],
        "conditions": [
            "no rule requiring wheel chocks on slope parking",
            "cab left unlocked",
            "site perimeter not secured for weekend",
            "supervision of nearby children is LTA",
        ],
        "root": "management control of vehicle energy isolation was LTA",
    },
    {
        "title": "agent fabricates factory status when Ollama is down",
        "events": [
            "operator asks for live trainer loss",
            "agent calls scout ava status",
            "status endpoint returns unreachable",
            "agent emits a precise loss number anyway",
        ],
        "conditions": [
            "Ollama process not running",
            "policy does not force provenance labels",
            "reward model overweights fluent answers",
            "no tool-error branch in the plan",
        ],
        "root": "missing honest-refusal path on tool failure",
    },
    {
        "title": "packed shard starves trainer after disk-full pause",
        "events": [
            "collector pauses on disk watermark",
            "curator drains remaining RAW",
            "trainer consumes last PACKED shard",
            "train step blocks waiting for data",
        ],
        "conditions": [
            "packed_ahead_max_tokens set too low for phase",
            "janitor deleted consumed shards aggressively",
            "no alert on runway < packed_min_tokens",
        ],
        "root": "pipeline runway alarm missing under backpressure",
    },
]


def _cfa_doc(rng) -> tuple[str, str, str, dict]:
    case = rng.choice(_INCIDENTS)
    events = list(case["events"])
    conditions = list(case["conditions"])
    # deterministic shuffle under private rng
    rng.shuffle(events)
    # restore chronology for the diagram (teach left-to-right order)
    events = list(case["events"])
    lines = [
        f"Causal Factor Analysis — case: {case['title']}",
        "",
        "Legend: EVENT = rectangle (happened); CONDITION = oval (enabled it).",
        "Main event line runs left → right in time.",
        "",
        "EVENT CHAIN:",
    ]
    for i, ev in enumerate(events, 1):
        lines.append(f"  E{i}: {ev}")
    lines.append("")
    lines.append("CONDITIONS (influence one or more events):")
    for i, cond in enumerate(conditions, 1):
        # attach each condition to an event index computed from rng
        attach = 1 + (i % len(events))
        lines.append(f"  C{i} → E{attach}: {cond}")
    lines.append("")
    lines.append(f"Root causal factor (system): {case['root']}.")
    lines.append(
        "Rule: list enabling conditions before blaming the last event actor; "
        "prefer management/system fixes over person-blame."
    )
    text = "\n".join(lines)
    meta = {
        "family": "cfa_diagram",
        "n_events": len(events),
        "n_conditions": len(conditions),
        "root": case["root"],
    }
    return text, "deliberate", "causal_factor_analysis", meta


def _confounder_doc(rng) -> tuple[str, str, str, dict]:
    # Simple discrete table: treatment T, outcome Y, confounder Z.
    # Counts are generated then risk difference computed two ways.
    z_levels = ("low_sleep", "high_sleep")
    # cells: (z, t) -> (n, y_count)
    base = rng.randint(40, 80)
    cells = {}
    for z_i, z in enumerate(z_levels):
        for t in (0, 1):
            n = base + 10 * z_i + 5 * t + rng.randint(0, 5)
            # outcome rate depends on Z strongly and T weakly
            p = 0.15 + 0.35 * z_i + 0.08 * t
            y = int(round(n * p))
            y = min(max(y, 0), n)
            cells[(z, t)] = (n, y)

    def risk(t: int) -> float:
        ys = sum(cells[(z, t)][1] for z in z_levels)
        ns = sum(cells[(z, t)][0] for z in z_levels)
        return ys / ns

    def risk_z(z: str, t: int) -> float:
        n, y = cells[(z, t)]
        return y / n

    crude_rd = risk(1) - risk(0)
    # standardization: average stratum-specific RD weighted by P(Z)
    n_tot = sum(n for (n, _) in cells.values())
    std_rd = 0.0
    for z in z_levels:
        n_z = cells[(z, 0)][0] + cells[(z, 1)][0]
        w = n_z / n_tot
        std_rd += w * (risk_z(z, 1) - risk_z(z, 0))

    lines = [
        "Causal drill — association vs confounding",
        "",
        "Binary treatment T (1=tool-retry on), outcome Y (1=task success).",
        "Confounder Z = operator sleep debt (affects both retry use and success).",
        "",
        "Counts (n, y_success):",
    ]
    for z in z_levels:
        for t in (0, 1):
            n, y = cells[(z, t)]
            lines.append(f"  Z={z} T={t}: n={n}, y={y}, risk={y/n:.4f}")
    lines.append("")
    lines.append(f"Crude risk difference RD = P(Y=1|T=1)-P(Y=1|T=0) = {crude_rd:.4f}")
    lines.append(
        f"Standardized RD (adjust Z) = {std_rd:.4f}"
    )
    delta = abs(crude_rd - std_rd)
    lines.append(
        f"|crude - standardized| = {delta:.4f}. "
        "If this gap is large, crude association is confounded by Z; "
        "do not claim T caused Y from the crude RD alone."
    )
    lines.append(
        "Agent lesson: when a dashboard metric moves after a ship, list confounders "
        "(traffic mix, eval set drift) before attributing cause to the ship."
    )
    text = "\n".join(lines)
    meta = {
        "family": "confounder",
        "crude_rd": crude_rd,
        "std_rd": std_rd,
        "delta": delta,
        "cells": {f"{z}|{t}": cells[(z, t)] for z in z_levels for t in (0, 1)},
    }
    return text, "deliberate", "confounding_adjustment", meta


def _intervention_doc(rng) -> tuple[str, str, str, dict]:
    # Toy SCM: Y = a*X + b*U + noise; intervene do(X=x0)
    a = rng.choice([1, 2, 3])
    b = rng.choice([1, 2])
    u = rng.randint(0, 5)
    noise = rng.randint(0, 2)
    x_obs = rng.randint(1, 6)
    y_obs = a * x_obs + b * u + noise
    x_do = rng.randint(1, 6)
    while x_do == x_obs:
        x_do = rng.randint(1, 6)
    y_do = a * x_do + b * u + noise  # U held fixed under intervention
    lines = [
        "Causal drill — observation vs intervention",
        "",
        f"Structural assignment: Y := {a}*X + {b}*U + ε, with U={u}, ε={noise}.",
        f"Observed: X={x_obs} → Y={y_obs}.",
        f"Intervention do(X={x_do}) holding U,ε fixed → Y={y_do}.",
        f"ΔY under do(X) = {y_do - y_obs} = {a}*({x_do - x_obs}).",
        "",
        "Rule: P(Y|X) answers association; P(Y|do(X)) answers 'what if we set X'.",
        "Agents choosing tool parameters need the do(.) quantity, not the correlational one.",
    ]
    text = "\n".join(lines)
    meta = {
        "family": "intervention",
        "a": a,
        "b": b,
        "u": u,
        "noise": noise,
        "x_obs": x_obs,
        "y_obs": y_obs,
        "x_do": x_do,
        "y_do": y_do,
    }
    return text, "deliberate", "intervention_do_calculus", meta


_BUILDERS_BY_PHASE = {
    2: (_cfa_doc,),
    3: (_cfa_doc, _confounder_doc, _intervention_doc),
    5: (_cfa_doc, _confounder_doc),
}


class CausalReasonGenerator(Generator):
    name = "causal_reason"
    phases = (2, 3, 5)

    def generate(self, target_bytes: int) -> Iterator[dict]:
        produced = 0
        phase_cycle = list(self.phases)
        i = 0
        while produced < target_bytes:
            phase = phase_cycle[i % len(phase_cycle)]
            i += 1
            builder = self.rng.choice(_BUILDERS_BY_PHASE[phase])
            text, task_type, concept, _meta = builder(self.rng)
            doc = self.doc(
                text=text,
                task_type=task_type,
                concept=concept,
                phase=phase,
                source=self.name,
            )
            produced += len(doc["text"].encode("utf-8"))
            yield doc


if __name__ == "__main__":
    run_cli(CausalReasonGenerator)
