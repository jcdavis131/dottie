"""Golden-set benchmark for the native grammar engine.

Cases are built from Dottie's REAL tool surface (scout-cli / dottie_loop
commands: leaks scan, handoff freshness, ruff lint, goal submit, plan
validate, loop run). Mock samplers stand in for a model — no weights needed —
so this measures the *mechanism*: how often the guided loop lands a
grammar-valid call, how often repair saves a sloppy first attempt, and that
refusal is fail-closed.

Run: ``python -m dottie_needle.bench`` (stdlib only).
"""

from __future__ import annotations

import json
from typing import Any

from dottie_needle.catalog import build_catalog, get
from dottie_needle.engine import GuidedCaller, NoValidCallError, extract_call_span
from dottie_needle.grammar import CompiledGrammar, ToolSpec

TOOLS = get(["leaks_scan", "handoff_check", "lint", "goal_submit", "plan_validate", "loop_run"])

# intent -> expected (tool, arguments). ``None`` means: no tool applies and the
# engine must refuse fail-closed.
CASES: list[tuple[str, tuple[str, dict[str, Any]] | None]] = [
    ("scan the repo for leaked secrets and fail on errors",
     ("leaks_scan", {"path": ".", "config": "leaks.json", "fail_on": "error"})),
    ("look for leaked keys but only warn, don't fail",
     ("leaks_scan", {"path": ".", "config": "leaks.json", "fail_on": "warning"})),
    ("is the handoff doc fresh against git HEAD?",
     ("handoff_check", {})),
    ("run ruff over packages/dottie-loop",
     ("lint", {"path": "packages/dottie-loop", "fix": False})),
    ("submit a goal to refresh the nightly board",
     ("goal_submit", {"title": "refresh the nightly board", "kind": "board"})),
    ("validate the plan graph before we run",
     ("plan_validate", {"graph": "plan.json"})),
    ("run the full loop for goal g123",
     ("loop_run", {"goal_id": "g123", "dry_run": False})),
    ("dry-run the loop for goal g7",
     ("loop_run", {"goal_id": "g7", "dry_run": True})),
    ("what's the weather in Austin tomorrow", None),
]


def perfect_sampler_factory(expected: dict[str, Any]):
    def sampler(prompt: str) -> str:
        return (
            "Reasoning: the intent maps to this tool.\nCall: "
            + json.dumps(expected, separators=(",", ":"))
        )

    return sampler


# Realistic defects a small model actually emits (see Needle gotchas).
SLOPPY_FIRST = [
    'Reasoning: scanning now.\nCall: {"tool": "leaks_scan", "arguments": {"path": ".", "fail_on": "error",},}',
    'Reasoning: ok.\nCall: {"tool": "leak_scan", "arguments": {"path": "."}}',
    'Reasoning: fine.\nCall: {"tool": "leaks_scan", "arguments": {"fail_on": "error"}}',
    'Reasoning: sure.\nCall: {"tool": "leaks_scan", "arguments": {"path": ".", "fail_on": "ERROR"}}',
    'Here is my answer in prose with no JSON at all, just a helpful paragraph.',
]


def sloppy_then_fixed_sampler_factory(expected: dict[str, Any], defect_idx: int):
    calls = {"n": 0}

    def sampler(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return SLOPPY_FIRST[defect_idx % len(SLOPPY_FIRST)]
        return "Reasoning: fixed per the error.\nCall: " + json.dumps(expected, separators=(",", ":"))

    return sampler


def adversarial_sampler(prompt: str) -> str:
    return "Reasoning: I will now emit five broken calls.\nCall: {not json at all,,,"


def run() -> dict[str, Any]:
    report: dict[str, Any] = {"cases": [], "summary": {}}
    guided_ok = guided_refused_ok = 0
    baseline_valid_first_try = 0
    total_repairs = 0
    n_positive = sum(1 for _, e in CASES if e is not None)

    for ci, (intent, expected) in enumerate(CASES):
        if expected is not None:
            tool, args = expected
            golden = {"tool": tool, "arguments": args}
            # Guided loop with a sloppy first attempt, fixed on repair.
            caller = GuidedCaller(
                sampler=sloppy_then_fixed_sampler_factory(golden, ci), max_attempts=3
            )
            try:
                res = caller(intent, TOOLS)
                ok = res["tool"] == tool and res["arguments"] == args
                guided_ok += ok
                total_repairs += res["attempts"] - 1
                detail: dict[str, Any] = {"ok": ok, "attempts": res["attempts"]}
            except NoValidCallError as e:
                detail = {"ok": False, "error": str(e)[:120]}
            # Baseline: would the sloppy first attempt have been usable raw?
            raw = SLOPPY_FIRST[ci % len(SLOPPY_FIRST)]
            span = extract_call_span(raw)
            try:
                if span is None:
                    raise ValueError("no span")
                CompiledGrammar(TOOLS).validate_call(span)
                baseline_valid_first_try += 1
                detail["baseline_raw_valid"] = True
            except Exception:
                detail["baseline_raw_valid"] = False
        else:
            caller = GuidedCaller(sampler=adversarial_sampler, max_attempts=2)
            try:
                caller(intent, TOOLS)
                detail = {"ok": False, "error": "EMITTED A CALL FOR A NO-TOOL INTENT"}
            except NoValidCallError:
                guided_refused_ok += 1
                detail = {"ok": True, "refused": True}
        detail["intent"] = intent
        report["cases"].append(detail)

    report["summary"] = {
        "guided_valid_call_rate": f"{guided_ok}/{n_positive}",
        "guided_refusal_rate": f"{guided_refused_ok}/{len(CASES) - n_positive}",
        "baseline_raw_valid_first_try": f"{baseline_valid_first_try}/{n_positive}",
        "total_repair_rounds": total_repairs,
    }
    return report


def main() -> None:
    report = run()
    print("dottie_needle bench — golden set over Dottie tool surface (mock samplers)")
    for c in report["cases"]:
        status = "OK " if c["ok"] else "FAIL"
        extra = f" attempts={c['attempts']}" if "attempts" in c else ""
        extra += " refused" if c.get("refused") else ""
        print(f"  [{status}]{extra} {c['intent'][:60]}")
    print("summary:", json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
