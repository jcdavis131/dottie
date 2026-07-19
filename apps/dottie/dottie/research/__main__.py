# Solo personal project, no connection to employer, built with public/free-tier only
"""CLI for the research loop: `python -m dottie.research {seed-baseline,ideate,implement,train,
evaluate,loop,status}`.

The ideate/implement commands drive the real Ollama model and refuse honestly (non-zero exit +
true reason) when it is unreachable. train/evaluate need no network. `loop` runs one full pass of
all four workers in order — handy for a single local cycle; the cron scripts run each worker on
its own schedule with flock.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

from dottie.policy import OllamaPolicy, DottiePolicyUnavailable
from dottie.research import evaluate, ideation, implementation, logger, paths, prompts, train
from dottie.research.ledger import Baseline, Ledger


def _ledger(args) -> Ledger:
    return Ledger(paths.ledger_path(args.data_dir))


def _emit(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _refresh_status(led: Ledger, args) -> None:
    try:
        logger.write_status(led, data_dir=args.data_dir)
    except Exception:  # status is a convenience mirror; never let it mask the real result
        pass


def cmd_seed_baseline(args) -> int:
    led = _ledger(args)
    b = Baseline(metric_name=args.metric, metric_value=args.value,
                 higher_is_better=args.higher_is_better, architecture=args.architecture,
                 experiment_id=None, updated_ts=__import__("time").time(), notes=args.notes)
    eff = led.seed_baseline(b, overwrite=args.overwrite)
    _refresh_status(led, args)
    _emit({"baseline": {"metric_name": eff.metric_name, "metric_value": eff.metric_value,
                        "higher_is_better": eff.higher_is_better,
                        "architecture": eff.architecture, "notes": eff.notes}})
    return 0


def _policy(args):
    """Research workers get a plain JSON-completion callable, not the CodeAct agent protocol."""
    pol = OllamaPolicy()  # reads DOTTIE_OLLAMA_URL / DOTTIE_OLLAMA_MODEL from the env
    return lambda prompt: pol.complete(prompt, system=prompts.RESEARCH_SYSTEM_PROMPT)


def cmd_ideate(args) -> int:
    led = _ledger(args)
    try:
        out = ideation.run_ideation(led, _policy(args), bottleneck=args.bottleneck,
                                    n_ideas=args.n)
    except DottiePolicyUnavailable as e:
        _emit({"error": "ollama_unavailable", "detail": str(e)})
        return 3
    except ValueError as e:
        _emit({"error": "unparseable_ideation", "detail": str(e)})
        return 4
    _refresh_status(led, args)
    _emit(out)
    return 0


def cmd_implement(args) -> int:
    led = _ledger(args)
    try:
        out = implementation.run_implementation(led, _policy(args),
                                                workspace_root=paths.workspace_root(args.data_dir),
                                                max_retries=args.max_retries)
    except DottiePolicyUnavailable as e:
        _emit({"error": "ollama_unavailable", "detail": str(e)})
        return 3
    if out is None:
        _emit({"note": "no pending experiments to implement"})
        return 0
    _refresh_status(led, args)
    _emit(out)
    return 0


def cmd_train(args) -> int:
    led = _ledger(args)
    cfg: Dict[str, Any] = {"steps": args.steps}
    if args.seeds:
        cfg["seeds"] = [int(s) for s in args.seeds.split(",")]
    out = train.run_training(led, config=cfg)
    if out is None:
        _emit({"note": "no experiments ready for training"})
        return 0
    _refresh_status(led, args)
    _emit(out)
    return 0


def cmd_evaluate(args) -> int:
    led = _ledger(args)
    out = evaluate.run_evaluation(led)
    if out is None:
        _emit({"note": "no experiments pending evaluation"})
        return 0
    _refresh_status(led, args)
    _emit(out)
    return 0


def cmd_loop(args) -> int:
    """One full pass: ideate -> implement -> train -> evaluate. Ollama gaps degrade honestly."""
    led = _ledger(args)
    steps: Dict[str, Any] = {}
    try:
        steps["ideate"] = ideation.run_ideation(led, _policy(args), bottleneck=args.bottleneck,
                                                 n_ideas=args.n)
    except (DottiePolicyUnavailable, ValueError) as e:
        steps["ideate"] = {"skipped": str(e)}
    try:
        steps["implement"] = implementation.run_implementation(
            led, _policy(args), workspace_root=paths.workspace_root(args.data_dir),
            max_retries=args.max_retries)
    except DottiePolicyUnavailable as e:
        steps["implement"] = {"skipped": str(e)}
    steps["train"] = train.run_training(led, config={"steps": args.steps})
    steps["evaluate"] = evaluate.run_evaluation(led)
    _refresh_status(led, args)
    _emit(steps)
    return 0


def cmd_status(args) -> int:
    led = _ledger(args)
    _emit(logger.build_status(led))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m dottie.research", description=__doc__)
    p.add_argument("--data-dir", default=None, help="Dottie data dir (default: DOTTIE_DATA_DIR)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sb = sub.add_parser("seed-baseline", help="install/overwrite the global baseline")
    sb.add_argument("--metric", default="proxy_loss")
    sb.add_argument("--value", type=float, required=True)
    sb.add_argument("--higher-is-better", action="store_true")
    sb.add_argument("--architecture", default="ava-nano")
    sb.add_argument("--notes", default="")
    sb.add_argument("--overwrite", action="store_true")
    sb.set_defaults(func=cmd_seed_baseline)

    for name, fn, extra in (("ideate", cmd_ideate, True), ("loop", cmd_loop, True)):
        sp = sub.add_parser(name, help=f"{name} worker")
        sp.add_argument("--bottleneck", default="loss spikes during early pre-training")
        sp.add_argument("--n", type=int, default=1)
        sp.add_argument("--steps", type=int, default=60)
        sp.add_argument("--max-retries", type=int, default=3)
        sp.set_defaults(func=fn)

    im = sub.add_parser("implement", help="implementation worker")
    im.add_argument("--max-retries", type=int, default=3)
    im.set_defaults(func=cmd_implement)

    tr = sub.add_parser("train", help="training worker (proxy micro-benchmark)")
    tr.add_argument("--steps", type=int, default=60)
    tr.add_argument("--seeds", default="")
    tr.set_defaults(func=cmd_train)

    ev = sub.add_parser("evaluate", help="evaluator & hill-climber")
    ev.set_defaults(func=cmd_evaluate)

    st = sub.add_parser("status", help="print the research status snapshot")
    st.set_defaults(func=cmd_status)
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
