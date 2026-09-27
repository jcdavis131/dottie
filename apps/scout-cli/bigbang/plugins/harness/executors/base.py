"""The executor contract: one result shape, two refusals, measured cost.

Every real executor returns an :class:`ExecResult` and raises exactly one of:

* :class:`ExecutorUnavailable`: its backend is not reachable or not
  configured (no Ollama, the network is down). The outcome is NOT
  a label: nobody learned whether the tier would have sufficed.
* :class:`NotApplicable`: the backend is up but this executor has no way to
  attempt the goal (the deterministic tier has no solver for it). That IS an
  observation: the tier could not satisfy the goal.

Tokens, latency and cost are measured, never estimated: tokens are the
backend's own usage counts (0 for local code), latency is ``perf_counter``
around the call, cost is 0 for local work. Every model backend is local since
the hosted ones were removed on 2026-09-27, and with them the
``DOTTIE_LLM_PRICE_PER_MTOK_*`` env pricing: a non-local backend records
``None`` with ``cost_basis: unpriced`` rather than a guessed price.
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
    """(cost_usd, cost_basis) for measured tokens. Local work costs 0.

    Nothing non-local is wired since the hosted backends were removed; should one
    appear it is recorded as unpriced, never given an estimated price. The token
    arguments stay so a call site reads the same whichever backend answered.
    """
    if local:
        return 0.0, "local"
    return None, "unpriced (not a local backend; hosted APIs were removed 2026-09-27)"
