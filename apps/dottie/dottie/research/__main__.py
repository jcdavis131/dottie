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


def _policy(args, *, temperature: float = prompts.IMPLEMENTATION_TEMPERATURE):
    """Research workers get a plain JSON-completion callable, not the CodeAct agent protocol."""
    pol = OllamaPolicy()  # reads DOTTIE_OLLAMA_URL / DOTTIE_OLLAMA_MODEL from the env
    return lambda prompt: pol.complete(prompt, system=prompts.RESEARCH_SYSTEM_PROMPT,
                                       temperature=temperature)


def cmd_ideate(args) -> int:
    led = _ledger(args)
    try:
        out = ideation.run_ideation(led, _policy(args, temperature=prompts.IDEATION_TEMPERATURE),
                                    bottleneck=args.bottleneck, n_ideas=args.n)
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


def _trainer(args):
    """None -> the default proxy micro-benchmark; 'factory' -> the real-Ava factory trainer."""
    if getattr(args, "trainer", "proxy") == "factory":
        from dottie.research.factory_trainer import factory_nano_trainer
        return factory_nano_trainer
    return None


def cmd_train(args) -> int:
    led = _ledger(args)
    cfg: Dict[str, Any] = {"steps": args.steps}
    if getattr(args, "device", None):
        cfg["device"] = args.device
    if args.seeds:
        cfg["seeds"] = [int(s) for s in args.seeds.split(",")]
    out = train.run_training(led, trainer=_trainer(args), config=cfg)
    if out is None:
        _emit({"note": "no experiments ready for training"})
        return 0
    _refresh_status(led, args)
    _emit(out)
    return 0


def cmd_calibrate_baseline(args) -> int:
    """Measure the UNMODIFIED factory model and seed the baseline from that real number."""
    from dottie.research.factory_trainer import FACTORY_METRIC, run_baseline_calibration
    led = _ledger(args)
    try:
        measured = run_baseline_calibration({"steps": args.steps})
    except Exception as e:
        _emit({"error": "calibration_failed", "detail": str(e)})
        return 3
    b = Baseline(metric_name=FACTORY_METRIC, metric_value=measured[FACTORY_METRIC],
                 higher_is_better=False, architecture=measured["preset"],
                 experiment_id=None, updated_ts=__import__("time").time(),
                 notes=f"measured baseline calibration: steps={measured['steps']} "
                       f"seq={measured['seq_len']} batch={measured['batch']} "
                       f"lr={measured['lr']} seed={measured['seed']} device={measured['device']}")
    eff = led.seed_baseline(b, overwrite=args.overwrite)
    _refresh_status(led, args)
    _emit({"measured": measured,
           "baseline": {"metric_name": eff.metric_name, "metric_value": eff.metric_value,
                        "architecture": eff.architecture, "notes": eff.notes},
           "note": ("baseline updated from this real measurement" if args.overwrite or
                    eff.metric_value == measured[FACTORY_METRIC]
                    else "existing baseline kept (pass --overwrite to replace)")})
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
        steps["ideate"] = ideation.run_ideation(
            led, _policy(args, temperature=prompts.IDEATION_TEMPERATURE),
            bottleneck=args.bottleneck, n_ideas=args.n)
    except (DottiePolicyUnavailable, ValueError) as e:
        steps["ideate"] = {"skipped": str(e)}
    try:
        steps["implement"] = implementation.run_implementation(
            led, _policy(args), workspace_root=paths.workspace_root(args.data_dir),
            max_retries=args.max_retries)
    except DottiePolicyUnavailable as e:
        steps["implement"] = {"skipped": str(e)}
    tcfg: Dict[str, Any] = {"steps": args.steps}
    if getattr(args, "device", None):
        tcfg["device"] = args.device
    steps["train"] = train.run_training(led, trainer=_trainer(args), config=tcfg)
    steps["evaluate"] = evaluate.run_evaluation(led)
    _refresh_status(led, args)
    _emit(steps)
    return 0


def cmd_promote(args) -> int:
    from dottie.research import promote
    led = _ledger(args)
    out = promote.build_pending_promotions(
        led, out_root=paths.workspace_root(args.data_dir).parent / "promotions")
    _emit(out)
    return 0


def cmd_status(args) -> int:
    led = _ledger(args)
    _emit(logger.build_status(led))
    return 0


# --------------------------------------------------------------------------- continuous runner

def _choose_action(counts: Dict[str, int], *, now: float, last_ideate_ts: float,
                   ideate_cooldown_s: float) -> str:
    """Pure stage-selection policy for the continuous runner (testable without
    Ollama/GPU). Drain order: evaluate (instant, finalizes verdicts) -> train
    (~seconds on GPU) -> implement (Ollama minutes) -> ideate (only on an empty
    pipeline, rate-limited) -> idle."""
    if counts.get("evaluation_pending", 0):
        return "evaluate"
    if counts.get("ready_for_training", 0):
        return "train"
    if counts.get("pending", 0):
        return "implement"
    if now - last_ideate_ts >= ideate_cooldown_s:
        return "ideate"
    return "idle"


def cmd_run(args) -> int:
    """Continuous chained runner: the moment one stage finishes, the next eligible
    stage starts — no hourly cadence. Honest refusals (Ollama down, unparseable
    ideation) back off exponentially instead of spinning; five CONSECUTIVE
    unexpected errors exit non-zero so the scheduler heartbeat can restart clean."""
    import time
    led = _ledger(args)
    last_ideate = 0.0
    backoff = float(args.idle_seconds)
    consecutive_errors = 0
    actions = 0
    while args.max_actions == 0 or actions < args.max_actions:
        actions += 1
        action = _choose_action(led.counts(), now=time.time(), last_ideate_ts=last_ideate,
                                ideate_cooldown_s=args.ideate_cooldown)
        rec: Dict[str, Any] = {"ts": time.time(), "action": action}
        try:
            if action == "idle":
                time.sleep(float(args.idle_seconds))
                continue
            if action == "evaluate":
                rec["result"] = evaluate.run_evaluation(led)
                if rec["result"] and rec["result"].get("state") == "sota":
                    from dottie.research import promote
                    rec["promotion"] = promote.build_promotion(
                        led, rec["result"]["experiment"],
                        out_root=paths.workspace_root(args.data_dir).parent / "promotions")
            elif action == "train":
                tcfg: Dict[str, Any] = {"steps": args.steps}
                if getattr(args, "device", None):
                    tcfg["device"] = args.device
                rec["result"] = train.run_training(led, trainer=_trainer(args), config=tcfg)
            elif action == "implement":
                rec["result"] = implementation.run_implementation(
                    led, _policy(args), workspace_root=paths.workspace_root(args.data_dir),
                    max_retries=args.max_retries)
            else:  # ideate
                last_ideate = time.time()
                rec["result"] = ideation.run_ideation(
                    led, _policy(args, temperature=prompts.IDEATION_TEMPERATURE),
                    bottleneck=args.bottleneck, n_ideas=args.n)
            consecutive_errors = 0
            backoff = float(args.idle_seconds)
            _refresh_status(led, args)
            print(json.dumps(rec, default=str), flush=True)
        except (DottiePolicyUnavailable, ValueError) as e:
            # Honest refusal path: state the reason, back off, try again later.
            rec["refusal"] = str(e)[:300]
            print(json.dumps(rec, default=str), flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 900.0)
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            consecutive_errors += 1
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
            print(json.dumps(rec, default=str), flush=True)
            if consecutive_errors >= 5:
                print(json.dumps({"fatal": "5 consecutive unexpected errors — exiting "
                                           "for a clean scheduler restart"}), flush=True)
                return 5
            time.sleep(backoff)
            backoff = min(backoff * 2, 900.0)
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
        sp.add_argument("--trainer", choices=["proxy", "factory"], default="proxy",
                        help="proxy micro-benchmark, or the real factory nano model")
        sp.add_argument("--device", default=None, choices=[None, "cpu", "cuda"])
        sp.set_defaults(func=fn)

    im = sub.add_parser("implement", help="implementation worker")
    im.add_argument("--max-retries", type=int, default=3)
    im.set_defaults(func=cmd_implement)

    tr = sub.add_parser("train", help="training worker")
    tr.add_argument("--steps", type=int, default=60)
    tr.add_argument("--seeds", default="")
    tr.add_argument("--device", default=None, choices=[None, "cpu", "cuda"],
                    help="cpu keeps the research trainer off a GPU another run owns")
    tr.add_argument("--trainer", choices=["proxy", "factory"], default="proxy",
                    help="proxy micro-benchmark, or the real factory nano model")
    tr.set_defaults(func=cmd_train)

    cb = sub.add_parser("calibrate-baseline",
                        help="measure the UNMODIFIED factory model and seed the baseline "
                             "from that real number")
    cb.add_argument("--steps", type=int, default=150)
    cb.add_argument("--overwrite", action="store_true")
    cb.set_defaults(func=cmd_calibrate_baseline)

    ev = sub.add_parser("evaluate", help="evaluator & hill-climber")
    ev.set_defaults(func=cmd_evaluate)

    rn = sub.add_parser("run", help="continuous chained runner (replaces hourly cadence)")
    rn.add_argument("--bottleneck", default="loss spikes during early pre-training")
    rn.add_argument("--n", type=int, default=3, help="ideas per refill when the queue empties")
    rn.add_argument("--steps", type=int, default=60)
    rn.add_argument("--max-retries", type=int, default=3)
    rn.add_argument("--trainer", choices=["proxy", "factory"], default="proxy")
    rn.add_argument("--device", default=None, choices=[None, "cpu", "cuda"],
                    help="cpu keeps the research trainer off a GPU another run owns")
    rn.add_argument("--idle-seconds", type=float, default=30.0)
    rn.add_argument("--ideate-cooldown", type=float, default=600.0,
                    help="min seconds between ideations on an empty pipeline — dedup "
                         "regenerates mostly dupes faster than this")
    rn.add_argument("--max-actions", type=int, default=0, help="0 = run forever")
    rn.set_defaults(func=cmd_run)

    pr = sub.add_parser("promote", help="build review bundles for sota experiments")
    pr.set_defaults(func=cmd_promote)

    st = sub.add_parser("status", help="print the research status snapshot")
    st.set_defaults(func=cmd_status)
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
