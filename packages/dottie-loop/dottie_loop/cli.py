"""``python -m dottie_loop`` — the CLI surface contract (spec §06 CLI row).

Stable exit codes, JSON mode, dry-run, explicit destructive flags, stderr
diagnostics, and no interactive prompt anywhere::

    0  ok
    1  error (typed; see the JSON envelope on stdout)
    2  blocked (a named dependency or stale/missing evidence)
    3  invalid input

Commands::

    goal submit  --store DIR --surface cli --subject ID --json '{...}'
    goal status  --store DIR --goal-id ID
    plan validate --file plan.json
    loop evaluate --sources metrics.json [--baseline baseline.json] [--last-terminal-at T]
                  [--promote] [--approve-prod] [--out decisions.jsonl]
    loop run     --spec run.json --store DIR --root DIR --subject ID [--capture]
    reward compute --file inputs.json
    capture status
    forge runners --root DIR
    forge submit  --root DIR --file jobspec.json --allow owner/name
    bench smoke
    spec status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dottie_loop import SPEC_BASELINE, SPEC_VERSION, __version__
from dottie_loop.errors import (
    BlockedError,
    InvalidInputError,
    LoopError,
    StaleEvidenceError,
    error_envelope,
    ok_envelope,
)

EXIT_OK, EXIT_ERROR, EXIT_BLOCKED, EXIT_INVALID = 0, 1, 2, 3


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --- commands ------------------------------------------------------------------------------


def cmd_goal_submit(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.intake import GoalStore

    store = GoalStore(Path(a.store))
    ack, created = store.submit(a.json, authenticated_subject=a.subject, surface=a.surface)
    return {**ack, "created": created}


def cmd_goal_status(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.intake import GoalStore

    store = GoalStore(Path(a.store))
    return {"goal_id": a.goal_id, "status": store.status(a.goal_id), "transitions": store.transitions(a.goal_id)}


def cmd_plan_validate(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.plan import PlanGraph, PlanStep, validate_plan

    raw = _read_json(a.file)
    steps = [PlanStep(**s) for s in raw.pop("steps", [])]
    raw.pop("schema", None)
    plan = PlanGraph(steps=steps, **raw)
    return validate_plan(plan)


def cmd_loop_evaluate(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.closed_loop import (
        evaluate_trigger,
        load_sources,
        promote_guard,
        write_decision,
    )

    sources = load_sources(Path(a.sources))
    baseline = _read_json(a.baseline) if a.baseline else {}
    decision = evaluate_trigger(sources, baseline=baseline, lease=None, last_terminal_at=a.last_terminal_at)
    if a.out:
        write_decision(decision, Path(a.out))
    guard = promote_guard(promote=a.promote, approve_prod=a.approve_prod, decision=decision)
    out = {"decision": decision, "promotion": guard}
    if decision["decision"] == "blocked":
        raise BlockedError("loop evaluation blocked: " + "; ".join(decision["blockers"]), "metrics", **out)
    return out


def cmd_loop_run(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.driver import RunSpec, run_goal

    spec = RunSpec.from_dict(_read_json(a.spec))
    result = run_goal(spec, store_root=Path(a.store), root=Path(a.root), subject=a.subject, surface=a.surface, capture_flag=a.capture)
    if result.get("status") == "blocked":
        raise BlockedError("goal blocked: " + str(result.get("dependency") or result.get("outcome", {}).get("error_class")), str(result.get("dependency") or "policy"), **result)
    return result


def cmd_reward_compute(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.reward import RewardInputs, compute_reward

    return compute_reward(RewardInputs(**_read_json(a.file)))


def cmd_capture_status(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.capture import ENV_FLAG, capture_enabled

    return {"enabled": capture_enabled(flag=a.capture), "env_flag": ENV_FLAG, "default": "off"}


def cmd_forge_runners(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.forge import ForgeQueue

    q = ForgeQueue(Path(a.root), repo_allowlist=a.allow or [])
    rs = [r.to_dict() for r in q.runners()]
    if not rs:
        raise BlockedError("no Forge runner is registered", "forge_runner", runners=[])
    return {"runners": rs}


def cmd_forge_submit(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.forge import ForgeQueue, JobSpec

    q = ForgeQueue(Path(a.root), repo_allowlist=a.allow or [])
    raw = _read_json(a.file)
    raw.pop("schema", None)
    spec = JobSpec(**raw)
    if a.dry_run:
        from dottie_loop.forge import validate_job

        validate_job(spec, q.repo_allowlist)
        return {"dry_run": True, "job_id": spec.job_id, "valid": True}
    p = q.submit(spec)
    return {"job_id": spec.job_id, "queued": str(p), "status": "accepted", "note": "queued, not executed"}


def cmd_bench_smoke(a: argparse.Namespace) -> dict[str, Any]:
    from dottie_loop.bench import (
        Step,
        Workflow,
        build_report,
        golden_check,
        run_workflow,
    )
    from dottie_loop.plan import PlanGraph, PlanStep, validate_plan
    from dottie_loop.reward import RewardInputs, compute_reward

    def plan_ok() -> dict[str, Any]:
        p = PlanGraph(goal_id="g", steps=[PlanStep(id="s1", idx=0, role="check", final=True)])
        return validate_plan(p)

    def reward_ok() -> dict[str, Any]:
        return compute_reward(RewardInputs(trace_id="t", task_ok=True, feedback="accept"))

    wfs = [
        run_workflow(Workflow("plan-validate", [Step("validate", plan_ok, lambda o: o["ok"])])),
        run_workflow(Workflow("reward-compute", [Step("compute", reward_ok, lambda o: o["total"] == 1.25)])),
    ]
    goldens = [golden_check(reward_ok(), "pair-reward", ["trace_id", "components", "weights", "total"])]
    return build_report(wfs, goldens, harness_commit=a.commit or "unknown")


def cmd_spec_status(_a: argparse.Namespace) -> dict[str, Any]:
    return {
        "package": "dottie_loop",
        "version": __version__,
        "spec_version": SPEC_VERSION,
        "spec_baseline": SPEC_BASELINE,
        "capability_claim": "none",
        "note": "contracts and gates only; no model is called by this package",
    }


# --- parser -----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dottie-loop", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("goal").add_subparsers(dest="sub", required=True)
    s = g.add_parser("submit")
    s.add_argument("--store", required=True)
    s.add_argument("--surface", default="cli")
    s.add_argument("--subject", required=True, help="authenticated subject id")
    s.add_argument("--json", required=True, help="GoalEnvelope request payload")
    s.set_defaults(fn=cmd_goal_submit)
    s = g.add_parser("status")
    s.add_argument("--store", required=True)
    s.add_argument("--goal-id", required=True)
    s.set_defaults(fn=cmd_goal_status)

    pl = sub.add_parser("plan").add_subparsers(dest="sub", required=True)
    s = pl.add_parser("validate")
    s.add_argument("--file", required=True)
    s.set_defaults(fn=cmd_plan_validate)

    lo = sub.add_parser("loop").add_subparsers(dest="sub", required=True)
    s = lo.add_parser("evaluate")
    s.add_argument("--sources", required=True)
    s.add_argument("--baseline")
    s.add_argument("--last-terminal-at")
    s.add_argument("--out")
    s.add_argument("--promote", action="store_true")
    s.add_argument("--approve-prod", action="store_true")
    s.set_defaults(fn=cmd_loop_evaluate)
    s = lo.add_parser("run", help="one goal end to end: intake -> plan -> execute -> verify -> checkpoint")
    s.add_argument("--spec", required=True, help="RunSpec JSON: intent_text, steps[{kind: argv|file, ...}], capture")
    s.add_argument("--store", required=True)
    s.add_argument("--root", default=".", help="sandbox root every step is confined to")
    s.add_argument("--subject", required=True)
    s.add_argument("--surface", default="cli")
    s.add_argument("--capture", action="store_true", help="explicit opt-in switch (with spec.capture consent)")
    s.set_defaults(fn=cmd_loop_run)

    rw = sub.add_parser("reward").add_subparsers(dest="sub", required=True)
    s = rw.add_parser("compute")
    s.add_argument("--file", required=True)
    s.set_defaults(fn=cmd_reward_compute)

    ca = sub.add_parser("capture").add_subparsers(dest="sub", required=True)
    s = ca.add_parser("status")
    s.add_argument("--capture", action="store_true", help="explicit opt-in flag")
    s.set_defaults(fn=cmd_capture_status)

    fo = sub.add_parser("forge").add_subparsers(dest="sub", required=True)
    s = fo.add_parser("runners")
    s.add_argument("--root", required=True)
    s.add_argument("--allow", action="append")
    s.set_defaults(fn=cmd_forge_runners)
    s = fo.add_parser("submit")
    s.add_argument("--root", required=True)
    s.add_argument("--file", required=True)
    s.add_argument("--allow", action="append", help="repo allowlist entry owner/name")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_forge_submit)

    be = sub.add_parser("bench").add_subparsers(dest="sub", required=True)
    s = be.add_parser("smoke")
    s.add_argument("--commit")
    s.set_defaults(fn=cmd_bench_smoke)

    sp = sub.add_parser("spec").add_subparsers(dest="sub", required=True)
    s = sp.add_parser("status")
    s.set_defaults(fn=cmd_spec_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = args.fn(args)
    except (BlockedError, StaleEvidenceError) as e:
        _emit({**error_envelope(e), "status": "blocked"})
        sys.stderr.write(f"blocked: {e.message}\n")
        return EXIT_BLOCKED
    except InvalidInputError as e:
        _emit(error_envelope(e))
        sys.stderr.write(f"invalid: {e.message}\n")
        return EXIT_INVALID
    except LoopError as e:
        _emit(error_envelope(e))
        sys.stderr.write(f"error: {e.message}\n")
        return EXIT_ERROR
    _emit(ok_envelope(data))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
