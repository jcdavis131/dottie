# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie CLI: ``python -m dottie serve|run|status|climb|climb-report``.

serve        — uvicorn on the FastAPI app (default port 8100)
run          — one task through the engine, JSON record to stdout (honest error + exit 2
               when the backend is unavailable)
status       — the same honest status JSON the /status endpoint serves (without a task store)
climb        — measured hill-climb iterations (verified batch -> scoreboard -> real
               flywheel -> optional evaluate/train-step -> climb_log.jsonl). Exits nonzero
               only on infrastructure failure — low scores are honest data, not errors.
climb-report — renders climb_log.jsonl as a table + paired promote/hold/insufficient
               verdicts between consecutive iterations
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

    return 1  # pragma: no cover - argparse enforces choices


if __name__ == "__main__":
    raise SystemExit(main())
