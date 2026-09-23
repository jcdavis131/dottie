"""dottie/pipeline/recovery_ladder.py — re-export of the one recovery ladder.

The implementation lives in ``packages/dottie-loop/dottie_loop/execution.py``
(``recovery_ladder``, ``contextual_recovery_table``, ``explain_ladder``,
``FAILURE_TAXONOMY``, ``SIDE_EFFECT_CLASSES``): scout's harness runner imports it
from there, so this file, the checkpoint manager and the runner can no longer
drift apart. Decisions are unchanged (retry1 -> patch -> replan -> escalate,
WRITE_DESTRUCTIVE / EXTERNAL_NOTIFY never auto).
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from dottie_loop import execution as _ladder
except ImportError:  # a bare checkout without the uv workspace installed
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "dottie-loop"))
    from dottie_loop import execution as _ladder

FAILURE_TAXONOMY = list(_ladder.FAILURE_TAXONOMY)
SIDE_EFFECT_CLASSES = _ladder.SIDE_EFFECT_CLASSES
recovery_ladder = _ladder.recovery_ladder
contextual_recovery_table = _ladder.contextual_recovery_table
explain_ladder = _ladder.explain_ladder

__all__ = ["FAILURE_TAXONOMY", "SIDE_EFFECT_CLASSES", "contextual_recovery_table", "explain_ladder", "recovery_ladder"]
