"""Cam's Meta research sequence — stages 1–6 as one composable bundle.

Stage 1: :mod:`dottie_loop.rubric`
Stage 2: :mod:`dottie_loop.opt_lane`
Stage 3: :mod:`dottie_loop.experiment`
Stage 4: :mod:`dottie_loop.compute_teacher`
Stage 5: :mod:`dottie_loop.ember` (causal edges in :mod:`dottie_loop.memory`)
Stage 6: :mod:`dottie_loop.hyperagents`

Nothing here trains, deploys, or promotes. The operator plan lives in
``docs/META_RESEARCH_SEQUENCE.md``.
"""

from __future__ import annotations

from typing import Any

from dottie_loop.compute_teacher import factory_ready
from dottie_loop.errors import PolicyDeniedError
from dottie_loop.hashing import new_id, now_iso
from dottie_loop.opt_lane import factory_pass
from dottie_loop.reward import RewardInputs, compute_reward_with_rubric
from dottie_loop.schema import active

STAGES_LANDED = (1, 2, 3, 4, 5, 6)
STAGES_FOLLOW_UP: dict[int, str] = {}


def compose_bundle(
    *,
    reward_inputs: RewardInputs,
    rubric_eval: dict[str, Any],
    opt_report: dict[str, Any] | None = None,
    experiment_job: dict[str, Any] | None = None,
    split: dict[str, Any] | None = None,
    hidden_eval: dict[str, Any] | None = None,
    teacher_pack: dict[str, Any] | None = None,
    ember_eval: dict[str, Any] | None = None,
    proposal: dict[str, Any] | None = None,
    speed_threshold: float = 0.0,
) -> dict[str, Any]:
    """Wire stages 1–6 into one record. Manual promotion is unchanged."""
    reward = compute_reward_with_rubric(reward_inputs, rubric_eval)
    opt_gate = factory_pass(opt_report, speed_threshold=speed_threshold) if opt_report else None
    if proposal and proposal.get("production_change") is True:
        raise PolicyDeniedError("research bundle refuses a production_change proposal", field="proposal")
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
        "compute_teacher": None
        if teacher_pack is None
        else {
            "pack_id": teacher_pack.get("pack_id"),
            "n_traces": (teacher_pack.get("factory") or {}).get("n_traces"),
            "live_teacher": False,
            "training": False,
            "factory_gate": factory_ready(teacher_pack),
        },
        "ember": None
        if ember_eval is None
        else {
            "eval_id": ember_eval.get("eval_id"),
            "gate": ember_eval.get("gate"),
            "ungated_score": ember_eval.get("ungated_score"),
            "gated_score": ember_eval.get("gated_score"),
            "n_broken": ember_eval.get("n_broken"),
        },
        "hyperagent": None
        if proposal is None
        else {
            "proposal_id": proposal.get("proposal_id"),
            "action": proposal.get("action"),
            "destination": proposal.get("destination"),
            "digest": proposal.get("digest"),
            "production_change": False,
        },
        "capability_claim": "none",
        "promotion": "manual",
        "computed_at": now_iso(),
    }


__all__ = ["STAGES_FOLLOW_UP", "STAGES_LANDED", "compose_bundle"]
