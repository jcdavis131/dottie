# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie — the agentic-assistant platform for the dottie monorepo.

(Category, not codename: dottie is the personally built equivalent of assistants like
NousResearch's Hermes Agent or OpenClaw — those names refer to EXTERNAL products and are
never used as names for this app.)

Dottie closes the loop: run tasks through the real CodeAct sandbox -> capture real traces ->
export RFT datasets (scout-cli ETL) + mint memories (ava-skills) -> gate with the eval harness
(ava-open-harness) -> take real GRPO training steps (ava-factory) -> a better checkpoint feeds
the AvaPolicy backend.

Honesty contract (repo-wide ANTI-FABRICATION rule): every number Dottie reports is computed
from real inputs; absent resources (Ollama server, ava checkpoint, torch) produce honest
refuse-with-error responses, never canned fake replies or invented metrics. Today the working
"brain" is an external Ollama model; the ava backend is smoke-scale with zero capability and
exists only so the training flywheel has a trainee.
"""

__version__ = "0.2.0-prime-sota"  # SOTA edition of prime-agent — RLM v2 + Continual Harness v2 + factory loop

from dottie.policy import (  # noqa: F401
    AvaPolicy,
    DottiePolicyUnavailable,
    EchoPolicy,
    OllamaPolicy,
    get_policy,
)

# SOTA edition exports (RLM + Continual Harness are first-class)
try:
    from dottie.rlm import MissionLog, VerifierWithBudget, StuckDetector, make_rlm_environment  # noqa: F401
    from dottie.harness_continual import ContinualHarness  # noqa: F401
    from dottie.sessions import SessionRegistry, send_message, read_inbox  # noqa: F401
    from dottie.goals import GoalStore  # noqa: F401
except Exception:
    # tests that import only policy still work if new deps missing
    pass
