"""Dottie CLI: SOTA edition of prime-agent — RLM v2 + Continual Harness v2 + factory.

Prime-compatible:
  repl         — persistent IPython REPL with rlm(...) (prompt-as-variable, subagents as fns)
  harness      — continual harness (init/refine/snapshots/rollback/context)
  agent        — daemon-backed sessions (list/attach/status/goal) + messaging
  goal         — persistent goals that live across turns

Factory (Dottie-only):
  serve, run, status, climb, climb-report — closed-loop LLM factory
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dottie", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    # --- Factory core (original) ---
    sp = sub.add_parser("serve", help="run the Dottie API server")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8100)

    rp = sub.add_parser("run", help="run one task and print the trace record")
    rp.add_argument("prompt")
    rp.add_argument("--backend", default="ollama", choices=["ollama", "ava", "echo"])
    rp.add_argument("--max-steps", type=int, default=8)
    rp.add_argument("--data-dir", default=None)

    st = sub.add_parser("status", help="print the honest status JSON")
    st.add_argument("--data-dir", default=None)

    cp = sub.add_parser(
        "climb", help="run measured hill-climb iterations (gated, logged)"
    )
    cp.add_argument(
        "--families",
        default="mixed",
        help="one task family or 'mixed' (cycles all five)",
    )
    cp.add_argument("--n", type=int, default=20, help="tasks per iteration")
    cp.add_argument(
        "--seed-base",
        type=int,
        default=0,
        help="seeds are seed_base..seed_base+n-1 (the pairing key)",
    )
    cp.add_argument("--backend", default="ollama", choices=["ollama", "ava", "echo"])
    cp.add_argument("--iterations", type=int, default=1)
    cp.add_argument("--max-steps", type=int, default=8)
    cp.add_argument(
        "--evaluate",
        choices=["mock", "real"],
        default=None,
        help="also run the real harness gate in this mode",
    )
    cp.add_argument(
        "--train-step",
        action="store_true",
        help="also take ONE real GRPO update (checkpoint/torch gated)",
    )
    cp.add_argument("--use-skills", action="store_true")
    cp.add_argument(
        "--compute",
        type=float,
        default=None,
        help="labeled compute point (e.g. ckpt train steps) for the EG trend",
    )
    cp.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="per-family success-rate regression tolerance for the promote gate",
    )
    cp.add_argument("--data-dir", default=None)

    crp = sub.add_parser(
        "climb-report", help="render climb_log.jsonl as a table + paired verdicts"
    )
    crp.add_argument("--data-dir", default=None)
    crp.add_argument("--tolerance", type=float, default=0.05)

    # --- RLM / Prime SOTA ---
    repl_p = sub.add_parser("repl", help="persistent IPython REPL with rlm(...) — RLM v2")
    repl_p.add_argument("--resume", default=None, help="mission_id to resume")
    repl_p.add_argument("--mission-id", default=None, help="new mission_id")

    har_p = sub.add_parser("harness", help="Continual Harness v2 — init/refine/context/snapshots")
    har_sub = har_p.add_subparsers(dest="hsub", required=True)
    hi = har_sub.add_parser("init", help="init harness session")
    hi.add_argument("session_id")
    hr = har_sub.add_parser("refine", help="evidence-backed refine (small, reviewable)")
    hr.add_argument("session_id")
    hr.add_argument("--evidence", required=True)
    hr.add_argument("--set", dest="sets", action="append", default=[], help="key=value (use prompt:foo / skill:bar / subagent:baz / memory:id)")
    hr.add_argument("--provenance", default="manual")
    hr.add_argument("--confidence", type=float, default=0.9)
    hc = har_sub.add_parser("context", help="render supplemental context for prompt injection")
    hc.add_argument("session_id")
    hs = har_sub.add_parser("snapshots", help="list snapshots for rollback")
    hs.add_argument("session_id")
    hb = har_sub.add_parser("rollback", help="rollback to snapshot")
    hb.add_argument("session_id")
    hb.add_argument("--to", required=True)

    ap_p = sub.add_parser("agent", help="daemon-backed sessions — list/status/goal/comms (prime-compatible)")
    ap_sub = ap_p.add_subparsers(dest="asub", required=True)
    al = ap_sub.add_parser("list", help="list running/idle/saved sessions")
    aa = ap_sub.add_parser("status", help="registry + goals active")
    aa.add_argument("--session-id", default=None)
    ag = ap_sub.add_parser("goal", help="set persistent goal for session (prime /goal)")
    ag.add_argument("session_id")
    ag.add_argument("objective", nargs="+", help="goal text")
    am = ap_sub.add_parser("send", help="send message to another agent")
    am.add_argument("--to", required=True)
    am.add_argument("--from", dest="from_id", default="cli")
    am.add_argument("msg", nargs="+")

    gp = sub.add_parser("goal", help="persistent goals — set/list/active/progress/clear (prime /goal)")
    gp_sub = gp.add_subparsers(dest="gsub", required=True)
    gs = gp_sub.add_parser("set", help="set new goal")
    gs.add_argument("objective", nargs="+")
    gs.add_argument("--mission-id", default=None)
    gl = gp_sub.add_parser("list", help="list all goals (append-log)")
    ga = gp_sub.add_parser("active", help="list active goals (last-wins)")
    gu = gp_sub.add_parser("progress", help="update progress")
    gu.add_argument("goal_id")
    gu.add_argument("progress", nargs="+")
    gu.add_argument("--status", default=None)
    gc = gp_sub.add_parser("clear", help="clear goal")
    gc.add_argument("goal_id")

    args = ap.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("dottie.api:app", host=args.host, port=args.port)
        return 0

    if args.cmd == "run":
        from dottie.engine import DottieEngine
        from dottie.policy import DottiePolicyUnavailable

        engine = DottieEngine(args.data_dir)
        try:
            record = engine.run_task(
                args.prompt, backend=args.backend, max_steps=args.max_steps
            )
        except DottiePolicyUnavailable as e:
            print(
                f"[dottie] backend unavailable (honest refusal, no fake reply): {e}",
                file=sys.stderr,
            )
            return 2
        print(json.dumps(record, indent=2))
        return 0

    if args.cmd == "status":
        from dottie.engine import DottieEngine
        from dottie.status import build_status

        print(json.dumps(build_status(DottieEngine(args.data_dir)), indent=2))
        return 0

    if args.cmd == "climb":
        from dottie import climb
        from dottie.flywheel import FlywheelError
        from dottie.policy import DottiePolicyUnavailable

        cfg = climb.ClimbConfig(
            families=args.families,
            n=args.n,
            seed_base=args.seed_base,
            backend=args.backend,
            max_steps=args.max_steps,
            use_skills=args.use_skills,
            evaluate=args.evaluate,
            train_step=args.train_step,
            compute=args.compute,
            tolerance=args.tolerance,
        )
        prev = None
        try:
            for i in range(args.iterations):
                record = climb.run_iteration(cfg, args.data_dir)
                print(f"[iteration {i + 1}/{args.iterations}]")
                print(climb.render_scoreboard(record))
                if prev is not None:
                    print(
                        climb.render_verdict(
                            climb.compare_iterations(
                                prev, record, tolerance=cfg.tolerance
                            )
                        )
                    )
                prev = record
        except DottiePolicyUnavailable as e:
            print(
                f"[dottie climb] backend unavailable (honest refusal, no fake data): {e}",
                file=sys.stderr,
            )
            return 2
        except (FlywheelError, climb.ClimbError, ValueError) as e:
            print(f"[dottie climb] infrastructure failure: {e}", file=sys.stderr)
            return 2
        return 0

    if args.cmd == "climb-report":
        from dottie import climb

        records = climb.read_log(args.data_dir)
        print(climb.render_report(records, tolerance=args.tolerance))
        return 0

    if args.cmd == "repl":
        # Prime RLM pattern: persistent IPython REPL with rlm(...) built-in
        try:
            from dottie.rlm import MissionLog, make_rlm_environment
            mission_id = args.mission_id or args.resume or None
            ml = MissionLog(mission_id=mission_id)
            env = make_rlm_environment(ml)
            print(f"[dottie repl] mission_id={ml.mission_id} timeline={ml.timeline_path}")
            print(f"[dottie repl] vars: rlm(prompt, model_tier, sources, require), mission, pick_lateral_lens, VerifierWithBudget")
            # Try IPython if available, else plain python REPL with env injected
            try:
                from IPython import embed
                embed(header=f"Dottie RLM v2 — mission {ml.mission_id}\nUse rlm(...) to spawn subagents, refine_harness(evidence, update) to refine", user_ns=env)
            except ImportError:
                import code
                code.interact(local=env, banner=f"Dottie RLM v2 — mission {ml.mission_id}")
            return 0
        except Exception as e:
            print(f"[dottie repl] failed: {e}", file=sys.stderr)
            return 1

    if args.cmd == "harness":
        from dottie.harness_continual import ContinualHarness
        if args.hsub == "init":
            h = ContinualHarness(args.session_id)
            print(json.dumps({"session_id": h.session_id, "version": h.state.version, "path": str(h.session_dir)}, indent=2))
            return 0
        if args.hsub == "refine":
            h = ContinualHarness(args.session_id)
            updates = {}
            for kv in args.sets:
                if "=" not in kv:
                    print(f"bad --set {kv!r} need key=value", file=sys.stderr)
                    return 2
                k,v = kv.split("=",1)
                updates[k]=v
            try:
                diff = h.refine(evidence=args.evidence, updates=updates, provenance=args.provenance, confidence=args.confidence)
                print(json.dumps(diff, indent=2))
                return 0
            except ValueError as e:
                print(f"[harness refine] {e}", file=sys.stderr)
                return 2
        if args.hsub == "context":
            h = ContinualHarness(args.session_id)
            print(h.get_context_for_prompt() or "(no supplemental context yet)")
            return 0
        if args.hsub == "snapshots":
            h = ContinualHarness(args.session_id)
            print(json.dumps(h.list_snapshots(), indent=2))
            return 0
        if args.hsub == "rollback":
            h = ContinualHarness(args.session_id)
            try:
                state = h.rollback(args.to)
                print(json.dumps(state.to_json(), indent=2))
                return 0
            except ValueError as e:
                print(f"[harness rollback] {e}", file=sys.stderr)
                return 2

    if args.cmd == "agent":
        from dottie.sessions import SessionRegistry, send_message, read_inbox
        reg = SessionRegistry()
        if args.asub == "list":
            print(json.dumps(reg.list(), indent=2))
            return 0
        if args.asub == "status":
            if args.session_id:
                print(json.dumps(reg.get(args.session_id) or {"error": "not found"}, indent=2))
            else:
                from dottie.goals import GoalStore
                print(json.dumps({"sessions": reg.list(), "active_goals": GoalStore().active()}, indent=2))
            return 0
        if args.asub == "goal":
            obj = " ".join(args.objective)
            rec = reg.set_goal(args.session_id, obj)
            print(json.dumps(rec, indent=2))
            return 0
        if args.asub == "send":
            msg = " ".join(args.msg)
            entry = send_message(args.to, args.from_id, msg)
            print(json.dumps(entry, indent=2))
            return 0

    if args.cmd == "goal":
        from dottie.goals import GoalStore
        gs = GoalStore()
        if args.gsub == "set":
            obj = " ".join(args.objective)
            rec = gs.set(obj, mission_id=args.mission_id)
            print(json.dumps({"goal_id": rec.goal_id, "objective": rec.objective, "status": rec.status}, indent=2))
            return 0
        if args.gsub == "list":
            out = list(gs.iter_all())
            print(json.dumps(out[-20:], indent=2))
            return 0
        if args.gsub == "active":
            print(json.dumps(gs.active(), indent=2))
            return 0
        if args.gsub == "progress":
            prog = " ".join(args.progress)
            rec = gs.update_progress(args.goal_id, prog, status=args.status)
            if not rec:
                print(f"goal {args.goal_id} not found", file=sys.stderr)
                return 2
            print(json.dumps(rec, indent=2))
            return 0
        if args.gsub == "clear":
            rec = gs.clear(args.goal_id)
            print(json.dumps(rec or {"cleared": args.goal_id}, indent=2))
            return 0

    return 1  # pragma: no cover - argparse enforces choices


if __name__ == "__main__":
    raise SystemExit(main())
