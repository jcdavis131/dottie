"""Real executors for the harness tiers, and the stub fallback rule.

One entry per probe-able tier (:data:`TIER_RUNNERS`): ``deterministic``
(local Python solvers, allowlisted read-only scout commands), ``llm``
(``bigbang.core.llm``: Ollama at ``OLLAMA_HOST`` first, then Anthropic or an
OpenAI-compatible API when a key is set) and ``deep_research`` (arXiv,
Semantic Scholar with a key, jarvisd recall; cited answers).
``action_operator`` runs only through the existing fail-closed MCP path
(:mod:`.action`); outside-world effects stay default-deny and are never
probed.

``scout harness run`` asks :func:`real_for_role` for each plan node. Under
``DOTTIE_EXECUTORS=auto`` (the default) a node runs its real executor when the
backend is available and falls back to its deterministic stub when it is not;
the node, and so the outcome, is then tagged ``stub`` and never labels a pack
row. ``real`` fails the node instead of falling back; ``stub`` never tries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bigbang.plugins.harness.executors import deterministic, llm_exec, research
from bigbang.plugins.harness.executors.base import (
    PROBE_TIERS,
    SIDE_EFFECT_TIERS,
    ExecResult,
    ExecutorUnavailable,
    NotApplicable,
    executor_mode,
)

if TYPE_CHECKING:
    from collections.abc import Callable

TIER_RUNNERS: dict[str, Callable[[str], ExecResult]] = {
    "deterministic": deterministic.run,
    "llm": llm_exec.run,
    "deep_research": research.run,
}

#: The prompt each llm-backed harness role sends (the goal and prior artifacts follow).
ROLE_PROMPTS = {
    "strategist": "Decompose this goal into its ordered sub-goals, one per line.",
    "planner": "Write the ordered execution plan for the remaining steps, one numbered line each.",
    "synthesist": "Synthesize the prior artifacts into one coherent brief. Keep every cited source marker.",
    "critic": "Critique the deliverable against the goal: list what is missing or wrong, then a 0-10 score.",
}


def _prior_text(ctx: dict) -> str:
    parts = [f"## {nid}\n{art}" for nid, art in (ctx.get("prior") or {}).items() if art]
    return "\n\n".join(parts)[-6000:]


def _llm_role(role: str) -> Callable[[dict], ExecResult]:
    def run(ctx: dict) -> ExecResult:
        prompt = f"{ROLE_PROMPTS[role]}\n\nGoal: {ctx['goal']}"
        prior = _prior_text(ctx)
        if prior:
            prompt += f"\n\nPrior artifacts:\n{prior}"
        return llm_exec.complete(prompt, system="You are the " + role + " of an agent harness. Be concise.")
    return run


def _research(ctx: dict) -> ExecResult:
    return research.run(ctx["goal"])


def _operator(ctx: dict) -> ExecResult:
    # a heartbeat/monitor goal has no deterministic solver: NotApplicable -> the stub keeps running it
    return deterministic.run(ctx["goal"])


def _builder(ctx: dict) -> ExecResult:
    """Composition only: real when every prior artifact came from a real executor."""
    kinds = ctx.get("prior_kinds") or {}
    if not kinds or set(kinds.values()) != {"real"}:
        raise NotApplicable("builder composes real artifacts only; a prior node was a stub")
    body = [f"# deliverable: {ctx['goal']}", ""]
    for nid, art in (ctx.get("prior") or {}).items():
        body += [f"## {nid}", art or "(empty - node failed)", ""]
    text = "\n".join(body)
    return ExecResult(tier="deterministic", backend="local-compose", answer=text, text=text)


ROLE_RUNNERS: dict[str, Callable[[dict], ExecResult]] = {
    "deep-researcher": _research,
    "researcher": _research,
    "strategist": _llm_role("strategist"),
    "planner": _llm_role("planner"),
    "synthesist": _llm_role("synthesist"),
    "critic": _llm_role("critic"),
    "operator": _operator,
    "builder": _builder,
}


def real_for_role(role: str) -> Callable[[dict], ExecResult] | None:
    """The real executor for a harness role, or None (the role only has a stub: ``executor``)."""
    return ROLE_RUNNERS.get(role)


__all__ = [
    "PROBE_TIERS",
    "ROLE_RUNNERS",
    "SIDE_EFFECT_TIERS",
    "TIER_RUNNERS",
    "ExecResult",
    "ExecutorUnavailable",
    "NotApplicable",
    "executor_mode",
    "real_for_role",
]
