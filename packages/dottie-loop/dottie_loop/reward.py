"""Pair-programming reward contract (spec §22, §37B RewardRecord).

    R = 1.00·task_ok + 0.25·accept + 0.15·time + 0.15·quality + 0.10·token_eff

Task success dominates. The anti-hacking rules are code, not prose:

* any pre-existing test regression sets ``task_ok`` to zero (regression is decisive)
* positive ``accept`` credit requires task success; a heavy edit discounts it
* ``time`` cannot compensate for failure
* verbose output gains no quality credit by length (quality comes from the verifier)
* silence is neutral: no response is not acceptance
* unknown remains null: missing components are NOT imputed, and the total is
  computed over the known components only with the missing ones listed
* every component and its evidence is persisted so the total can be replayed
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import now_iso
from dottie_loop.rubric import quality_for_reward
from dottie_loop.schema import active

FORMULA = "v1"
WEIGHTS: dict[str, float] = {
    "task_ok": 1.00,
    "accept": 0.25,
    "time": 0.15,
    "quality": 0.15,
    "token_eff": 0.10,
}
COMPONENTS = tuple(WEIGHTS)

#: An edit that changes more than this fraction of the output is "heavy" and
#: discounts acceptance to this factor.
HEAVY_EDIT_FRACTION = 0.5
HEAVY_EDIT_ACCEPT_CREDIT = 0.25


@dataclass
class RewardInputs:
    trace_id: str
    task_ok: bool | None
    regression: bool = False
    feedback: str | None = None  # accept | reject | edit | apply | dismiss | None (silence)
    edit_fraction: float | None = None
    latency_ms: int | None = None
    latency_baseline_ms: int | None = None  # median for comparable tasks in the class
    verifier_score: float | None = None  # 1-10 from the verifier, deterministic-first
    verifier_version: str | None = None
    tokens_used: int | None = None
    token_budget: int | None = None
    evidence: list[str] = field(default_factory=list)


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_reward(inp: RewardInputs) -> dict[str, Any]:
    """Decomposed reward with evidence. Nulls stay null; the total lists what was missing."""
    if inp.feedback is not None and inp.feedback not in ("accept", "reject", "edit", "apply", "dismiss"):
        raise InvalidInputError(f"unknown feedback {inp.feedback!r}", field="feedback")
    if inp.task_ok is not None and not isinstance(inp.task_ok, bool):
        raise InvalidInputError("task_ok must be True, False or None", field="task_ok")
    components: dict[str, float | None] = dict.fromkeys(COMPONENTS)
    evidence: list[str] = list(inp.evidence)

    # task_ok — regression is decisive
    if inp.task_ok is None:
        components["task_ok"] = None
        evidence.append("task_ok:unknown(no valid verifier)")
    elif inp.regression:
        components["task_ok"] = 0.0
        evidence.append("task_ok:zeroed(pre-existing test regression)")
    else:
        components["task_ok"] = 1.0 if inp.task_ok else 0.0
        evidence.append(f"task_ok:{'pass' if inp.task_ok else 'fail'}")
    task_success = components["task_ok"] == 1.0

    # accept — requires task success; silence neutral; reject negative; heavy edit discounted
    if inp.feedback is None:
        components["accept"] = None
        evidence.append("accept:silence(neutral)")
    elif inp.feedback in ("accept", "apply"):
        if not task_success:
            components["accept"] = 0.0
            evidence.append("accept:no_credit(task not successful)")
        elif inp.edit_fraction is not None and inp.edit_fraction > HEAVY_EDIT_FRACTION:
            components["accept"] = HEAVY_EDIT_ACCEPT_CREDIT
            evidence.append(f"accept:discounted(heavy edit {inp.edit_fraction:.2f})")
        else:
            components["accept"] = 1.0
            evidence.append(f"accept:{inp.feedback}")
    elif inp.feedback == "edit":
        if not task_success:
            components["accept"] = 0.0
            evidence.append("accept:no_credit(task not successful)")
        else:
            frac = inp.edit_fraction if inp.edit_fraction is not None else 1.0
            components["accept"] = HEAVY_EDIT_ACCEPT_CREDIT if frac > HEAVY_EDIT_FRACTION else _clip(1.0 - frac)
            evidence.append(f"accept:edit(fraction {frac:.2f})")
    else:  # reject / dismiss
        components["accept"] = 0.0
        evidence.append(f"accept:{inp.feedback}(negative)")

    # time — cannot compensate for failure; normalized by comparable tasks
    if inp.latency_ms is None or inp.latency_baseline_ms is None or inp.latency_baseline_ms <= 0:
        components["time"] = None
        evidence.append("time:unknown")
    elif not task_success:
        components["time"] = 0.0
        evidence.append("time:no_credit(task not successful)")
    else:
        ratio = inp.latency_ms / inp.latency_baseline_ms
        components["time"] = _clip(1.0 - max(0.0, ratio - 1.0))
        evidence.append(f"time:ratio {ratio:.2f} vs class baseline")

    # quality — verifier score; rubric version recorded; no length credit anywhere
    if inp.verifier_score is None:
        components["quality"] = None
        evidence.append("quality:unknown")
    else:
        if not 1.0 <= inp.verifier_score <= 10.0:
            raise InvalidInputError("verifier_score must be in 1..10", field="verifier_score")
        components["quality"] = _clip((inp.verifier_score - 1.0) / 9.0)
        evidence.append(f"quality:verifier {inp.verifier_score}/10 ({inp.verifier_version or 'unversioned'})")

    # token_eff — useful result per budget; cannot reward omission (needs task success)
    if inp.tokens_used is None or inp.token_budget is None or inp.token_budget <= 0:
        components["token_eff"] = None
        evidence.append("token_eff:unknown")
    elif not task_success:
        components["token_eff"] = 0.0
        evidence.append("token_eff:no_credit(task not successful)")
    else:
        components["token_eff"] = _clip(1.0 - inp.tokens_used / inp.token_budget)
        evidence.append(f"token_eff:{inp.tokens_used}/{inp.token_budget}")

    missing = [k for k, v in components.items() if v is None]
    known = {k: v for k, v in components.items() if v is not None}
    total = round(sum(WEIGHTS[k] * v for k, v in known.items()), 6) if known else None
    return {
        "schema": active("pair-reward"),
        "trace_id": inp.trace_id,
        "formula": FORMULA,
        "components": components,
        "weights": dict(WEIGHTS),
        "regression": bool(inp.regression),
        "total": total,
        "components_missing": missing,
        "evidence": evidence,
        "computed_at": now_iso(),
    }


def replay_total(record: dict[str, Any]) -> float | None:
    """Recompute the total from persisted components + weights (auditability)."""
    known = {k: v for k, v in record["components"].items() if v is not None}
    if not known:
        return None
    return round(sum(record["weights"][k] * v for k, v in known.items()), 6)


def compute_reward_with_rubric(inp: RewardInputs, rubric_eval: dict[str, Any]) -> dict[str, Any]:
    """§22 reward whose quality comes from a stage-1 rubric eval.

    The hard task-success gate lives in :func:`quality_for_reward`: a high rubric
    score cannot override task failure or a regression. Existing
    ``compute_reward`` behaviour is unchanged when this helper is not used.
    """
    if inp.trace_id and rubric_eval.get("trace_id") not in (None, inp.trace_id):
        raise InvalidInputError(
            "rubric eval trace_id does not match reward inputs", field="trace_id"
        )
    inp_success = inp.task_ok is True and not inp.regression
    if inp.task_ok is not None and rubric_eval.get("task_success") != inp_success:
        raise InvalidInputError(
            "reward task_ok/regression disagrees with rubric eval", field="task_ok"
        )
    score_10, extra = quality_for_reward(rubric_eval)
    patched = replace(
        inp,
        verifier_score=score_10,
        verifier_version=str(
            rubric_eval.get("rubric_version") or inp.verifier_version or "rubric"
        ),
        evidence=[*inp.evidence, *extra],
    )
    rec = compute_reward(patched)
    rec["rubric_eval_id"] = rubric_eval.get("eval_id")
    rec["rubric_gate"] = rubric_eval.get("gate")
    rec["rubric_ungated_score"] = rubric_eval.get("ungated_score")
    rec["rubric_gated_score"] = rubric_eval.get("gated_score")
    return rec


# --- preference pairs (§22) ---------------------------------------------------------


def form_preference_pair(
    context_digest_a: str,
    context_digest_b: str,
    reward_a: dict[str, Any],
    reward_b: dict[str, Any],
    *,
    tool_availability_a: list[str] | None = None,
    tool_availability_b: list[str] | None = None,
) -> dict[str, Any] | None:
    """Pair only comparable candidates with a supported ordering; else None with no pair.

    The ordering is supported by task outcome first, then user correction/acceptance,
    then verifier quality. Ties and unknowns do not form a pair.
    """
    if context_digest_a != context_digest_b:
        return None  # materially different requirements or hidden context
    if sorted(tool_availability_a or []) != sorted(tool_availability_b or []):
        return None
    ca, cb = reward_a["components"], reward_b["components"]
    for key, reason in (("task_ok", "task_outcome"), ("accept", "user_signal"), ("quality", "verifier")):
        va, vb = ca.get(key), cb.get(key)
        if va is None or vb is None:
            continue
        if va != vb:
            chosen, rejected = (reward_a, reward_b) if va > vb else (reward_b, reward_a)
            return {
                "chosen": chosen["trace_id"],
                "rejected": rejected["trace_id"],
                "basis": reason,
                "confidence": round(min(1.0, abs(va - vb)), 3),
            }
    return None
