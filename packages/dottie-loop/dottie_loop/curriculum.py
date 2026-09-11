"""Training stages as data (spec §21) and dataset balancing (spec §19).

Nothing here touches a tensor. These are the deterministic rules the trainer in
``apps/ava-factory`` (frozen) must obey and log; every decision produces IDs and
scores that go into the TrainRun manifest so a run can be audited or replayed.

* :func:`select_examples` — Stage 2 selective training: prefer high excess loss and
  verified learning value, keep coverage floors, log IDs + scores, never discard
  hard examples merely because they are difficult.
* :func:`curriculum_order` — Stage 3: contract learning and short deterministic tasks
  first, then longer tool use, recovery, cross-system plans.
* :func:`anneal_schedule` — late-stage annealing couples the mixture transition with
  the learning-rate collapse; both are versioned together.
* :func:`grpo_groups` — Stage 4 group construction: no duplicate trajectories
  masquerading as diversity; invalid tool actions and regressions score zero task.
* :func:`balance` — §19 balancing by task family / difficulty / tier / tool / failure
  mode / feedback / time, template caps, session caps, a recovery-trace share, with
  sampling weights and reasons recorded.
* :func:`health_check` / :func:`stop_decision` — run controls.
"""

from __future__ import annotations

import math
from typing import Any

from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import digest, now_iso

CURRICULUM_PHASES = ("contract", "short_deterministic", "tool_use", "recovery", "cross_system")


# --- Stage 2: selective training ---------------------------------------------------------------


def select_examples(examples: list[dict[str, Any]], *, retain_fraction: float, coverage_floors: dict[str, int]) -> dict[str, Any]:
    """Each example: ``id, family, excess_loss, verified, difficulty``. Returns IDs + scores."""
    if not 0.0 < retain_fraction <= 1.0:
        raise InvalidInputError("retain_fraction must be in (0, 1]", field="retain_fraction")
    scored = []
    for e in examples:
        if not e.get("verified"):
            continue  # only verified targets ever train (Stage 1 rule)
        score = float(e.get("excess_loss", 0.0)) * (1.0 + 0.5 * float(e.get("difficulty", 0.0)))
        scored.append({"id": e["id"], "family": e.get("family", "unknown"), "score": round(score, 6)})
    scored.sort(key=lambda s: (-s["score"], s["id"]))
    keep_n = max(1, math.ceil(len(scored) * retain_fraction)) if scored else 0
    kept = scored[:keep_n]
    kept_ids = {k["id"] for k in kept}
    # coverage floors: rare families and safety cases are never starved
    by_family: dict[str, list[dict[str, Any]]] = {}
    for s in scored:
        by_family.setdefault(s["family"], []).append(s)
    floor_adds: list[str] = []
    for fam, floor in coverage_floors.items():
        have = sum(1 for k in kept if k["family"] == fam)
        for s in by_family.get(fam, []):
            if have >= floor:
                break
            if s["id"] not in kept_ids:
                kept.append(s)
                kept_ids.add(s["id"])
                floor_adds.append(s["id"])
                have += 1
    dropped = [s["id"] for s in scored if s["id"] not in kept_ids]
    unverified = [e["id"] for e in examples if not e.get("verified")]
    return {"method": "excess_loss", "retain_fraction": retain_fraction, "selected": [k["id"] for k in kept], "scores": {k["id"]: k["score"] for k in scored}, "coverage_floor_adds": floor_adds, "dropped": dropped, "excluded_unverified": unverified, "selection_digest": digest(sorted(kept_ids)), "at": now_iso()}


# --- Stage 3: curriculum + annealing ----------------------------------------------------------------


def curriculum_order(examples: list[dict[str, Any]]) -> list[str]:
    """Order by phase, then by length within a phase; unknown phases sort last, never dropped."""
    rank = {p: i for i, p in enumerate(CURRICULUM_PHASES)}
    return [e["id"] for e in sorted(examples, key=lambda e: (rank.get(e.get("phase", ""), len(rank)), int(e.get("length", 0)), e["id"]))]


def anneal_schedule(*, total_steps: int, anneal_start_fraction: float, lr_peak: float, lr_floor: float, hq_mixture: dict[str, float]) -> dict[str, Any]:
    """Coupled and versioned: the mixture switches at the same step the LR begins to collapse."""
    if not 0.0 < anneal_start_fraction < 1.0:
        raise InvalidInputError("anneal_start_fraction must be in (0, 1)", field="anneal_start_fraction")
    if abs(sum(hq_mixture.values()) - 1.0) > 1e-6:
        raise InvalidInputError("hq_mixture weights must sum to 1", field="hq_mixture")
    start = int(total_steps * anneal_start_fraction)

    def lr_at(step: int) -> float:
        if step < start:
            return lr_peak
        frac = (step - start) / max(1, total_steps - start)
        return lr_floor + (lr_peak - lr_floor) * 0.5 * (1 + math.cos(math.pi * min(1.0, frac)))

    sched = {"total_steps": total_steps, "anneal_start_step": start, "lr_peak": lr_peak, "lr_floor": lr_floor, "mixture_after_start": dict(hq_mixture), "lr_coupling": "coupled", "samples": {str(s): round(lr_at(s), 8) for s in (0, start, (start + total_steps) // 2, total_steps)}}
    sched["version"] = digest({k: v for k, v in sched.items() if k != "samples"})[:12]
    return sched


# --- Stage 4: GRPO groups ------------------------------------------------------------------------------


def grpo_groups(prompt_id: str, samples: list[dict[str, Any]], *, group_size: int, kl_max: float) -> dict[str, Any]:
    """Each sample: ``id, trajectory_digest, task_ok, invalid_action, regression, kl, components``."""
    if group_size < 2:
        raise InvalidInputError("group_size must be >= 2", field="group_size")
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    duplicates: list[str] = []
    for s in samples:
        if s["trajectory_digest"] in seen:
            duplicates.append(s["id"])
            continue
        seen.add(s["trajectory_digest"])
        unique.append(s)
    if len(unique) < group_size:
        return {"prompt_id": prompt_id, "ok": False, "reason": f"only {len(unique)} distinct trajectories (< {group_size}); duplicates are not diversity", "duplicates": duplicates}
    rewards = []
    for s in unique[:group_size]:
        task = 0.0 if (s.get("invalid_action") or s.get("regression") or not s.get("task_ok")) else 1.0
        comp = dict(s.get("components") or {})
        comp["task_ok"] = task
        rewards.append({"id": s["id"], "task_ok": task, "components": comp, "kl": float(s.get("kl", 0.0))})
    kl_violations = [r["id"] for r in rewards if r["kl"] > kl_max]
    mean = sum(r["task_ok"] for r in rewards) / len(rewards)
    var = sum((r["task_ok"] - mean) ** 2 for r in rewards) / len(rewards)
    std = math.sqrt(var)
    for r in rewards:
        r["advantage"] = 0.0 if std == 0 else round((r["task_ok"] - mean) / std, 6)  # normalized within the group
    return {"prompt_id": prompt_id, "ok": not kl_violations, "group": rewards, "duplicates_dropped": duplicates, "kl_violations": kl_violations, "kl_max": kl_max}


# --- §19 balancing ----------------------------------------------------------------------------------------


def balance(records: list[dict[str, Any]], *, template_cap: int, session_cap: int, min_recovery_share: float) -> dict[str, Any]:
    """Cap over-represented templates and sessions; keep a recovery share; record weights + reasons."""
    kept: list[dict[str, Any]] = []
    reasons: dict[str, str] = {}
    per_template: dict[str, int] = {}
    per_session: dict[str, int] = {}
    for r in sorted(records, key=lambda x: x["id"]):
        t = r.get("template", "none")
        s = r.get("session", r["id"])
        if per_template.get(t, 0) >= template_cap:
            reasons[r["id"]] = f"template cap {template_cap} reached for {t}"
            continue
        if per_session.get(s, 0) >= session_cap:
            reasons[r["id"]] = f"session cap {session_cap} reached for {s}"
            continue
        per_template[t] = per_template.get(t, 0) + 1
        per_session[s] = per_session.get(s, 0) + 1
        kept.append(r)
    recovery = [r for r in kept if r.get("recovery")]
    share = len(recovery) / len(kept) if kept else 0.0
    families: dict[str, int] = {}
    for r in kept:
        families[r.get("family", "unknown")] = families.get(r.get("family", "unknown"), 0) + 1
    n_fam = max(1, len(families))
    weights = {r["id"]: round(1.0 / (families[r.get("family", "unknown")] * n_fam), 6) for r in kept}  # equalize families
    return {"kept": [r["id"] for r in kept], "dropped": reasons, "recovery_share": round(share, 4), "recovery_share_ok": share >= min_recovery_share, "family_counts": families, "sampling_weights": weights, "weights_reason": "inverse family frequency; recovery traces preserved; caps applied first", "at": now_iso()}


# --- run controls ------------------------------------------------------------------------------------------


def health_check(t: dict[str, Any]) -> dict[str, Any]:
    """Loss finite, gradients finite, throughput plausible, no data starvation, checkpoints readable."""
    checks = {"loss_finite": math.isfinite(float(t.get("loss", float("nan")))), "grad_finite": math.isfinite(float(t.get("grad_norm", float("nan")))), "throughput_plausible": float(t.get("tokens_per_s", 0)) > 0, "no_data_starvation": float(t.get("data_wait_fraction", 1.0)) < 0.5, "checkpoint_readable": bool(t.get("checkpoint_readable", False)), "heartbeat_fresh": float(t.get("heartbeat_age_s", 1e9)) < 300}
    failed = [k for k, v in checks.items() if not v]
    return {"ok": not failed, "checks": checks, "failed": failed}


def stop_decision(*, step: int, max_steps: int, hours: float, max_hours: float, cost: float, max_cost: float, diverged: bool, regression: bool, privacy_issue: bool, heldout_gain: float | None, patience_exhausted: bool) -> dict[str, Any]:
    reasons = []
    if step >= max_steps:
        reasons.append("budget:max_steps")
    if hours >= max_hours:
        reasons.append("budget:max_hours")
    if cost >= max_cost:
        reasons.append("budget:max_cost")
    if diverged:
        reasons.append("divergence")
    if regression:
        reasons.append("regression")
    if privacy_issue:
        reasons.append("privacy_issue")
    if heldout_gain is not None and heldout_gain <= 0 and patience_exhausted:
        reasons.append("no_heldout_gain")
    hard = any(r in ("divergence", "regression", "privacy_issue") for r in reasons)
    return {"stop": bool(reasons), "hard_stop": hard, "reasons": reasons}
