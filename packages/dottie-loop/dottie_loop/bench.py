"""Benchmark builder (spec §23): workflows, goldens, and a report with its own
accounting checks. Measures workflows, not demos.

A workflow is a named list of steps, each a callable returning a JSON-able result.
The runner records per-step status, latency and output, then the report reconciles
``ok + failed + skipped == total`` before it may claim anything. Results labeled
``synthetic`` or ``mock`` are reported but excluded from evidence (ML-11).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dottie_loop.hashing import digest, now_iso
from dottie_loop.schema import active, check_compatible

if TYPE_CHECKING:
    from collections.abc import Callable

SUITES = ("workflow_inventory", "goldens", "retrieval", "task_slices", "safety", "efficiency", "canary")


@dataclass
class Step:
    name: str
    fn: Callable[[], Any]
    verifier: Callable[[Any], bool] | None = None


@dataclass
class Workflow:
    name: str
    steps: list[Step]
    synthetic: bool = False
    tags: list[str] = field(default_factory=list)


def run_workflow(wf: Workflow) -> dict[str, Any]:
    steps_out: list[dict[str, Any]] = []
    ok = True
    for st in wf.steps:
        if not ok:
            steps_out.append({"step": st.name, "status": "skipped", "latency_ms": 0})
            continue
        t0 = time.monotonic()
        try:
            out = st.fn()
            verified = st.verifier(out) if st.verifier is not None else True
            status = "ok" if verified else "verifier_failed"
        except Exception as e:  # a real failure is data, not an abort
            out = {"error": e.__class__.__name__}
            status = "failed"
        latency = int((time.monotonic() - t0) * 1000)
        if status != "ok":
            ok = False
        steps_out.append({"step": st.name, "status": status, "latency_ms": latency, "output_digest": digest(_jsonable(out))})
    return {"workflow": wf.name, "ok": ok, "synthetic": wf.synthetic, "tags": wf.tags, "steps": steps_out, "latency_ms": sum(s["latency_ms"] for s in steps_out)}


def _jsonable(o: Any) -> Any:
    try:
        json.dumps(o)
        return o
    except (TypeError, ValueError):
        return repr(o)


def golden_check(record: dict[str, Any], record_type: str, required: list[str]) -> dict[str, Any]:
    """Structural golden: schema-compatible and every required field present."""
    problems: list[str] = []
    try:
        check_compatible(record.get("schema"), record_type)
    except Exception as e:
        problems.append(f"schema: {e}")
    problems += [f"missing {k}" for k in required if k not in record]
    return {"record_type": record_type, "valid": not problems, "problems": problems}


def build_report(workflows: list[dict[str, Any]], goldens: list[dict[str, Any]], *, harness_commit: str = "unknown") -> dict[str, Any]:
    """Report with accounting that must reconcile before any claim is made."""
    total = len(workflows)
    ok = sum(1 for w in workflows if w["ok"])
    failed = sum(1 for w in workflows if not w["ok"])
    evidence = [w for w in workflows if not w["synthetic"]]
    excluded = [w["workflow"] for w in workflows if w["synthetic"]]
    steps_total = sum(len(w["steps"]) for w in workflows)
    steps_acc = sum(1 for w in workflows for s in w["steps"] if s["status"] in ("ok", "failed", "verifier_failed", "skipped"))
    accounting_ok = (ok + failed == total) and (steps_acc == steps_total)
    report = {
        "schema": active("bench-report"),
        "harness_commit": harness_commit,
        "generated_at": now_iso(),
        "workflows": {"total": total, "ok": ok, "failed": failed, "evidence_eligible": len(evidence), "excluded_synthetic": excluded},
        "goldens": {"total": len(goldens), "valid": sum(1 for g in goldens if g["valid"]), "invalid": [g for g in goldens if not g["valid"]]},
        "wall_ms": sum(w["latency_ms"] for w in workflows),
        "harness_score": (sum(1 for w in evidence if w["ok"]) / len(evidence)) if evidence else None,
        "accounting_ok": accounting_ok,
        "capability_claim": "none",
        "results": workflows,
    }
    if not accounting_ok:
        report["harness_score"] = None
        report["abort"] = "item accounting does not balance"
    return report
