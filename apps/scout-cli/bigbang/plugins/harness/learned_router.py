"""
harness learned router — the `--learned` keys of `scout harness route`.

The orchestrator MLP is one of the router's backends:
dottie_loop.backends.LearnedMLPBackend (weights: SCOUT_ORCH_MODEL or
apps/ava-factory/reports/orchestrator/champion_weights.json; inference: the
shared apps/ava-factory/orchestrator_infer.py when importable, SCOUT_ORCH_INFER
overrides, else dottie_loop.mlp_infer, the in-package copy of the same frozen
contract). This module only maps that backend's answer onto the flat keys
`--learned` has always added, so existing consumers keep reading:

  * success adds learned_tier / learned_probs / risk / cost / model_version /
    gate_passed / learned_source="champion_weights" / infer_impl;
  * any failure adds learned_tier=None / learned_fallback="heuristic" /
    learned_reason="<specific reason>".

The answer stays ADVISORY: dottie_loop.router.route_goal lets it move the tier
only when gate_passed AND a human stamped the weights (scout router promote).
Nothing here raises; cli.py imports this module lazily so a defect cannot make
the harness plugin vanish (plugin_loader.py swallows import errors).
"""
from __future__ import annotations

from typing import Any


def legacy_keys(answer: dict[str, Any]) -> dict[str, Any]:
    """LearnedMLPBackend answer -> the flat `--learned` envelope keys."""
    if not answer.get("available"):
        return {"learned_tier": None, "learned_fallback": "heuristic",
                "learned_reason": str(answer.get("reason") or "learned backend unavailable")}
    return {
        "learned_tier": answer.get("tier"),
        "learned_probs": dict(answer.get("tier_probs") or {}),
        "risk": float(answer.get("risk", 0.0)),
        "cost": float(answer.get("cost", 0.0)),
        "model_version": str(answer.get("model_version", "")),
        "gate_passed": bool(answer.get("gate_passed", False)),
        "learned_source": "champion_weights",
        "infer_impl": answer.get("infer_impl"),
    }


def learned_route(goal: str, heuristic: dict | None = None) -> dict:
    """Keys to merge into a route envelope. Never raises. ``heuristic`` is unused (signature stability)."""
    try:
        from dottie_loop.backends import LearnedMLPBackend

        return legacy_keys(LearnedMLPBackend().answer(goal))
    except Exception as exc:  # belt-and-braces: this function must never raise
        return {"learned_tier": None, "learned_fallback": "heuristic",
                "learned_reason": f"learned route error: {type(exc).__name__}: {exc}"}
