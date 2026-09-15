"""Cam's Meta research sequence — stages 1–3 as one composable bundle.

Stage 1: :mod:`dottie_loop.rubric`
Stage 2: :mod:`dottie_loop.opt_lane`
Stage 3: :mod:`dottie_loop.experiment`

Stages 4–6 are not implemented here. The follow-up plan lives in
``docs/META_RESEARCH_SEQUENCE.md``.
"""

from __future__ import annotations

from typing import Any

from dottie_loop.hashing import new_id, now_iso
from dottie_loop.opt_lane import factory_pass
from dottie_loop.reward import RewardInputs, compute_reward_with_rubric
from dottie_loop.schema import active

STAGES_LANDED = (1, 2, 3)
STAGES_FOLLOW_UP = {
    4: "Compute-as-Teacher",
    5: "S-EMBER causal memory",
    6: "HyperAgents proposal-only",
}


def compose_bundle(
    *,
    reward_inputs: RewardInputs,
    rubric_eval: dict[str, Any],
    opt_report: dict[str, Any] | None = None,
    experiment_job: dict[str, Any] | None = None,
    split: dict[str, Any] | None = None,
    hidden_eval: dict[str, Any] | None = None,
    speed_threshold: float = 0.0,
) -> dict[str, Any]:
    """Wire stages 1–3 into one record. Manual promotion is unchanged."""
    reward = compute_reward_with_rubric(reward_inputs, rubric_eval)
    opt_gate = factory_pass(opt_report, speed_threshold=speed_threshold) if opt_report else None
    return {
        "schema": active("research-bundle"),
        "bundle_id": new_id("rsrch_"),
        "stages": list(STAGES_LANDED),
        "follow_up": dict(STAGES_FOLLOW_UP),
        "reward": reward,
        "rubric": {
            "eval_id": rubric_eval.get("eval_id"),
            "gate": rubric_eval.get("gate"),
            "ungated_score": rubric_eval.get("ungated_score"),
            "gated_score": rubric_eval.get("gated_score"),
            "audits": rubric_eval.get("audits"),
        },
        "opt_lane": None
        if opt_report is None
        else {
            "report_id": opt_report.get("report_id"),
            "correctness": opt_report.get("correctness"),
            "speed_credit": opt_report.get("speed_credit"),
            "speed_rejected": opt_report.get("speed_rejected"),
            "factory_gate": opt_gate,
        },
        "experiment": experiment_job,
        "split": None
        if split is None
        else {
            "experiment_id": split.get("experiment_id"),
            "digest": split.get("digest"),
            "counts": split.get("counts"),
        },
        "hidden_eval": None
        if hidden_eval is None
        else {
            "pack_id": hidden_eval.get("pack_id"),
            "mean": hidden_eval.get("mean"),
            "n": hidden_eval.get("n"),
            "scorer_version": hidden_eval.get("scorer_version"),
        },
        "capability_claim": "none",
        "promotion": "manual",
        "computed_at": now_iso(),
    }


__all__ = ["STAGES_FOLLOW_UP", "STAGES_LANDED", "compose_bundle"]
