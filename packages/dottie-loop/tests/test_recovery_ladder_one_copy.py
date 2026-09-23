"""One recovery ladder: dottie_loop.execution.recovery_ladder.

The oracle below is pipeline/recovery_ladder.py's function exactly as it was
before it became a re-export (fa04d85). The one implementation must make the
same decision for every input, and every former copy must now BE it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from dottie_loop.execution import FAILURE_TAXONOMY, SIDE_EFFECT_CLASSES, recovery_ladder

REPO = Path(__file__).resolve().parents[3]

_ORACLE_TAXONOMY = ["INPUT_CORRUPTION", "CONTEXT_STARVATION", "TOOL_FAILURE", "REASONING_COLLAPSE", "OUTPUT_CORRUPTION"]
_ORACLE_SIDE = ("READ", "WRITE_IDEMPOTENT", "WRITE_DESTRUCTIVE", "EXTERNAL_NOTIFY")


def _oracle(error_class, side_effect, attempt):
    if error_class not in _ORACLE_TAXONOMY:
        error_class = "TOOL_FAILURE"
    if side_effect not in _ORACLE_SIDE:
        side_effect = "READ"
    if side_effect in ("WRITE_DESTRUCTIVE", "EXTERNAL_NOTIFY"):
        return {"action": "escalate", "reason": f"{side_effect} never auto — needs human gate", "attempt": attempt, "errorClass": error_class, "sideEffect": side_effect, "bounded": True, "bio_map": "Remodeling — human gate, parallel true"}
    if attempt == 1:
        return {"action": "retry1", "attempt": 1, "errorClass": error_class, "sideEffect": side_effect, "safe": side_effect in ("READ", "WRITE_IDEMPOTENT"), "bio": "Hemostasis — stop bleeding, retry exact", "next_if_fail": "patch"}
    if attempt == 2:
        return {"action": "patch", "attempt": 2, "errorClass": error_class, "sideEffect": side_effect, "fix": "single-resp patch — fix concrete file:line evidence, no reformat ocean", "bio": "Inflammation — narrow scope, one file, one resp", "next_if_fail": "replan"}
    if attempt == 3:
        return {"action": "replan", "attempt": 3, "errorClass": error_class, "sideEffect": side_effect, "dag_version_inc": True, "bounded": True, "bio": "Proliferation — pure-function DAG re-plan, version++ never mutate in place", "next_if_fail": "escalate"}
    return {"action": "escalate", "attempt": attempt, "errorClass": error_class, "sideEffect": side_effect, "bounded": True, "bio": "Remodeling — human gate, visible abandonment", "reason": "3 attempts exhausted — escalate with evidence packet"}


CLASSES = [*_ORACLE_TAXONOMY, "SOMETHING_ELSE", ""]
SIDES = [*_ORACLE_SIDE, "UNKNOWN", ""]
ATTEMPTS = [-1, 0, 1, 2, 3, 4, 5]


@pytest.mark.parametrize("attempt", ATTEMPTS)
def test_same_decisions_as_the_ladder_it_replaced(attempt):
    for cls in CLASSES:
        for side in SIDES:
            assert recovery_ladder(cls, side, attempt) == _oracle(cls, side, attempt), (cls, side, attempt)
    assert list(FAILURE_TAXONOMY) == _ORACLE_TAXONOMY and tuple(SIDE_EFFECT_CLASSES) == _ORACLE_SIDE


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_pipeline_modules_re_export_the_one_ladder():
    ladder = _load(REPO / "pipeline" / "recovery_ladder.py", "pipeline_recovery_ladder_under_test")
    assert ladder.recovery_ladder is recovery_ladder
    cm = _load(REPO / "pipeline" / "checkpoint_manager.py", "pipeline_checkpoint_manager_under_test")
    for cls in CLASSES:
        for side in SIDES:
            for attempt in ATTEMPTS:
                assert cm.recovery_ladder(cls, side, attempt) == recovery_ladder(cls, side, attempt)


def test_scout_runner_uses_the_one_ladder():
    runner = pytest.importorskip("bigbang.plugins.harness.runner")
    assert runner._recovery_ladder is recovery_ladder
    assert not hasattr(runner, "_inline_recovery_ladder")
    assert not (REPO / "bundles" / "ultra" / "recovery-ladder.js").exists()
