# Solo personal project, no connection to employer, built with public/free-tier only
"""Hermes (codename "openclaw") — the agentic-assistant platform for the dottie monorepo.

Hermes closes the loop: run tasks through the real CodeAct sandbox -> capture real traces ->
export RFT datasets (scout-cli ETL) + mint memories (ava-skills) -> gate with the eval harness
(ava-open-harness) -> take real GRPO training steps (ava-factory) -> a better checkpoint feeds
the AvaPolicy backend.

Honesty contract (repo-wide ANTI-FABRICATION rule): every number Hermes reports is computed
from real inputs; absent resources (Ollama server, ava checkpoint, torch) produce honest
refuse-with-error responses, never canned fake replies or invented metrics. Today the working
"brain" is an external Ollama model; the ava backend is smoke-scale with zero capability and
exists only so the training flywheel has a trainee.
"""

__version__ = "0.1.0"

from hermes.policy import (  # noqa: F401
    AvaPolicy,
    EchoPolicy,
    HermesPolicyUnavailable,
    OllamaPolicy,
    get_policy,
)
