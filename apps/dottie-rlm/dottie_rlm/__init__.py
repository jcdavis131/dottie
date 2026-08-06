"""dottie-rlm — Prime-Agent-style RLM harness for Dottie (SPEC v1).

The model gets ONE tool: a persistent IPython kernel. Everything else —
file edits, shell, sub-agents, messaging, compaction — is a function call
inside that kernel (see :mod:`dottie_rlm.rlm`).

Import policy: this package root re-exports the library API only. It does
NOT import ``.cli`` (typer stays a CLI-only cost) or ``.kernel``
(IPython loads lazily via Session's kernel factory the first time a code
block actually executes) — ``import dottie_rlm`` stays light.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .harness import (
    DEFAULT_RHO,
    Harness,
    HarnessError,
    LedgerCorruptError,
    Refinement,
    RhoImmutableError,
    UnknownRefinementError,
)
from .llm import (
    Backend,
    BackendUnavailable,
    FakeBackend,
    FakeBackendExhausted,
    OllamaBackend,
    OpenAICompatBackend,
    resolve_backend,
)
from .loop import (
    CHILD_MAX_STEPS,
    DEFAULT_MAX_STEPS,
    build_messages,
    extract_code_blocks,
    run_turn,
)
from .registry import (
    RegistryError,
    ScopeError,
    SessionRegistry,
    default_root,
)
from .rlm import Runtime
from .session import CorruptStateError, Session, SessionError
from .status import build_status, collect_sessions, publish_status

__all__ = [
    # loop
    "CHILD_MAX_STEPS",
    "DEFAULT_MAX_STEPS",
    # harness
    "DEFAULT_RHO",
    # llm
    "Backend",
    "BackendUnavailable",
    # session
    "CorruptStateError",
    "FakeBackend",
    "FakeBackendExhausted",
    "Harness",
    "HarnessError",
    "LedgerCorruptError",
    "OllamaBackend",
    "OpenAICompatBackend",
    "Refinement",
    # registry
    "RegistryError",
    "RhoImmutableError",
    # rlm
    "Runtime",
    "ScopeError",
    "Session",
    "SessionError",
    "SessionRegistry",
    "UnknownRefinementError",
    "__version__",
    "build_messages",
    # status
    "build_status",
    "collect_sessions",
    "default_root",
    "extract_code_blocks",
    "publish_status",
    "resolve_backend",
    "run_turn",
]
