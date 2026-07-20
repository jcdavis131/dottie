# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie status — REAL probes only, the JSON a dashboard (arxiviq, later) will render.

Every field is measured live: the Ollama probe is a real HTTP ping, the ava probe checks the
real checkpoint file + torch importability, the integration probes stat the real sibling
paths, and the counts come from the real trace log / task store. ``capability_note`` states
the honest capability picture and is part of the stable shape — keep it."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from dottie import __version__, resolve
from dottie.policy import AvaPolicy, EchoPolicy, OllamaPolicy

if TYPE_CHECKING:
    from dottie.engine import DottieEngine

CAPABILITY_NOTE = (
    "Ollama (external local model, e.g. qwen3:32b) is the only backend with real task "
    "capability today. The ava backend decodes from a smoke-scale checkpoint (~90 base + ~25 "
    "agentic optimizer steps, capability_claim=none) and exists to close the training "
    "flywheel, not to assist. The echo backend is a deterministic plumbing test."
)


def build_status(
    engine: DottieEngine, task_counts: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Assemble the /status payload. Stable keys: service, version, ts, capability_note,
    backends{ollama,ava,echo}, integrations, data{...}."""
    return {
        "service": "dottie",
        "version": __version__,
        "ts": time.time(),
        "capability_note": CAPABILITY_NOTE,
        "backends": {
            "ollama": OllamaPolicy().probe(),  # real HTTP ping (short timeout)
            "ava": AvaPolicy().probe(),  # real ckpt stat + torch find_spec
            "echo": EchoPolicy().probe(),
        },
        "integrations": resolve.probe(),  # real filesystem probes of the siblings
        "data": {
            "data_dir": str(engine.data_dir),
            "traces": engine.trace_count(),
            "tasks": task_counts or {"note": "no task store attached (CLI status)"},
        },
    }
