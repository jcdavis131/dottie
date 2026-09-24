"""The executor contract: one result shape, two refusals, measured cost.

Every real executor returns an :class:`ExecResult` and raises exactly one of:

* :class:`ExecutorUnavailable`: its backend is not reachable or not
  configured (no Ollama, no API key, the network is down). The outcome is NOT
  a label: nobody learned whether the tier would have sufficed.
* :class:`NotApplicable`: the backend is up but this executor has no way to
  attempt the goal (the deterministic tier has no solver for it). That IS an
  observation: the tier could not satisfy the goal.

Tokens, latency and cost are measured, never estimated: tokens are the
backend's own usage counts (0 for local code), latency is ``perf_counter``
around the call, cost is 0 for local work and is priced only from
``DOTTIE_LLM_PRICE_PER_MTOK_IN`` / ``_OUT`` for a paid API (otherwise ``None``
with ``cost_basis: unpriced``).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

#: Tiers the probe may run: none of them has an outside-world side effect.
PROBE_TIERS = ("deterministic", "llm", "deep_research")
#: Tiers whose executors can touch the outside world. Never probed; default-deny.
SIDE_EFFECT_TIERS = ("action_operator", "agentic_epic")
MODES = ("auto", "real", "stub")


class ExecutorUnavailable(RuntimeError):  # noqa: N818  (a state, not a bug: the backend is absent)
    """The executor's backend is not reachable or not configured."""


class NotApplicable(RuntimeError):  # noqa: N818
    """The executor is up but has no way to attempt this goal."""


@dataclass
class ExecResult:
    tier: str
    backend: str
    answer: str
    text: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    tokens: dict[str, int | None] = field(default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0})
    latency_ms: float = 0.0
    cost_usd: float | None = 0.0
    cost_basis: str = "local"
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def verifier_input(self) -> dict[str, Any]:
        return {"answer": self.answer, "text": self.text, "sources": self.sources, "meta": self.meta}


def executor_mode() -> str:
    """``DOTTIE_EXECUTORS``: auto (default) | real | stub.

    auto: a node runs its real executor when that executor's backend is
    available, and falls back to the deterministic stub (outcome tagged stub)
    when it is not. real: an unavailable backend fails the node instead.
    stub: every node runs its stub (tests, offline demos).
    """
    mode = os.environ.get("DOTTIE_EXECUTORS", "auto").strip().lower() or "auto"
    return mode if mode in MODES else "auto"


def price(prompt_tokens: int | None, completion_tokens: int | None, *, local: bool) -> tuple[float | None, str]:
    """(cost_usd, cost_basis) for measured tokens. Local work costs 0; an API is priced only from env."""
    if local:
        return 0.0, "local"
    p_in = os.environ.get("DOTTIE_LLM_PRICE_PER_MTOK_IN", "").strip()
    p_out = os.environ.get("DOTTIE_LLM_PRICE_PER_MTOK_OUT", "").strip()
    if not p_in or not p_out or prompt_tokens is None or completion_tokens is None:
        return None, "unpriced (set DOTTIE_LLM_PRICE_PER_MTOK_IN and _OUT)"
    try:
        cost = (prompt_tokens * float(p_in) + completion_tokens * float(p_out)) / 1_000_000
    except ValueError:
        return None, "unpriced (DOTTIE_LLM_PRICE_PER_MTOK_* is not a number)"
    return round(cost, 8), "env price per million tokens"
