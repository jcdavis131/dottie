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
import os
import sys
from pathlib import Path
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
        led, out_root=paths.workspace_root(args.data_dir).parent / "promotions",
        rebuild=bool(getattr(args, "rebuild", False)))
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


def _boot_provenance() -> Dict[str, Any]:
    """What code is actually running, recorded at start.

    This daemon never live-reloads: a module edited while it runs takes effect only at
    the next restart, and nothing recycles a forever-daemon on its own. So "which prompt
    version produced this experiment?" is not answerable from commit timestamps — it
    depends on when the process last started, which was previously only recoverable by
    catching the PID's creation time before it died. Measured 2026-07-20: a before/after
    comparison of the constraint-8 prompt refinement could not be scoped without it.
    Recording the SHA and a prompts hash at boot makes every later comparison checkable
    against the log instead of reconstructed from process tables."""
    import hashlib
    import subprocess
    info: Dict[str, Any] = {}
    try:
        info["git_sha"] = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
            timeout=10, cwd=str(Path(__file__).resolve().parent),
        ).stdout.strip() or None
    except Exception:                                  # git absent / not a checkout
        info["git_sha"] = None
    try:
        src = Path(prompts.__file__).read_bytes()
        info["prompts_sha256"] = hashlib.sha256(src).hexdigest()[:12]
    except Exception:
        info["prompts_sha256"] = None
    return info


#: Refuse to start a heavy stage below this much free RAM. Overridable with
#: DOTTIE_RESEARCH_MIN_FREE_MB; set 0 to disable the guard entirely.
#:
#: This is HEADROOM the stage needs *on top of* whatever it is about to allocate — see
#: ``_model_load_cost_mb`` for the part that is not a constant.
_MIN_FREE_MB_DEFAULT = 1200

#: Stages that call the LLM. Unlike train/validate, these do not just *use* memory — if the
#: configured model is not already resident they PULL IT IN first, and on this box
#: (``NUM_GPU=0``) that lands in system RAM, not VRAM.
_LLM_ACTIONS = frozenset({"ideate", "implement"})


def _available_mb() -> Optional[int]:
    """Physical RAM available right now, or None if it cannot be determined.

    None means UNKNOWN, and the caller proceeds — a guard that blocks on an unreadable
    reading would be worse than no guard. psutil is not installed on this box, so the
    Windows path uses GlobalMemoryStatusEx directly (verified against
    `\Memory\Available MBytes`, which is the counter that actually reflects what a new
    allocation can get; `FreePhysicalMemory` excludes standby and misleads)."""
    try:
        import psutil                                  # optional, not a dependency
        return int(psutil.virtual_memory().available / 1024 / 1024)
    except Exception:
        pass
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = _MS()
        m.dwLength = ctypes.sizeof(_MS)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None
        return int(m.ullAvailPhys / 1024 / 1024)
    except Exception:
        return None


def _model_load_cost_mb() -> tuple[Optional[int], Optional[str]]:
    """``(MB an LLM stage will ADD, model name)`` — ``(None, …)`` when it cannot be known.

    Returns ``0`` when the configured model is already resident, because Ollama reuses it and
    the stage allocates nothing extra. Returns its footprint when it is NOT resident, because
    the stage must load the whole thing before the first token.

    That distinction is the whole point. With ``DOTTIE_OLLAMA_KEEP_ALIVE=30s`` the model
    unloads between stages, so the common case on this box is "not resident" — and a flat
    floor then says GO at 3,051 MB free and lets a 5.2 GB load run the box to zero. Measured
    2026-07-20 (TODOS 5.3.R77) with the daemon down: 3,051 MB free, nothing resident.

    Never raises and never blocks for long: unknown is returned as None and the caller
    proceeds, matching ``_available_mb``. A down Ollama lands here as None, and the stage
    then refuses honestly on its own (DottiePolicyUnavailable) — which is the correct error
    to show, not a memory one."""
    try:
        import httpx

        pol = OllamaPolicy()                        # constructor is pure: env only, no I/O
        want = pol.model
        timeout = httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=2.0)
        with httpx.Client(timeout=timeout) as client:
            resident = client.get(f"{pol.base_url}/api/ps").json()
            for m in resident.get("models") or []:
                if want in (m.get("name"), m.get("model")):
                    return 0, want
            catalog = client.get(f"{pol.base_url}/api/tags").json()
            for m in catalog.get("models") or []:
                if want in (m.get("name"), m.get("model")):
                    size = int(m.get("size") or 0)
                    return (int(size / 1024 / 1024) or None), want
        return None, want                           # model not pulled; `ollama pull` will say so
    except Exception:
        return None, None


def _memory_refusal(action: str) -> Optional[Dict[str, Any]]:
    """A refusal record when RAM is too low to start ``action``, else None.

    Measured 2026-07-20 (TODOS 5.3.R51): the daemon died mid-`implement` with **110 MB**
    available — below the 281 MB that had already killed the WSL VM — leaving no traceback,
    no exit code and no log line. The scheduler's 15-minute trigger then restarted it into
    the same wall, so it crash-looped while its own log looked merely quiet.

    torch allocations are what actually fail, so the honest behaviour is to REFUSE the
    stage, say why in run.log, and let the backoff sleep — a visible refusal beats an
    invisible death. This does not free memory; it makes running out of it legible."""
    try:
        floor = int(os.environ.get("DOTTIE_RESEARCH_MIN_FREE_MB", _MIN_FREE_MB_DEFAULT))
    except ValueError:
        floor = _MIN_FREE_MB_DEFAULT
    if floor <= 0:
        return None
    avail = _available_mb()
    if avail is None:
        return None
    # An LLM stage has to load the model before it does any work, so the honest requirement
    # is headroom PLUS that load. Without this the guard passes at 3 GB free and the loop
    # dies inside the pull it just authorised (TODOS 5.3.R77).
    required = floor
    model_mb, model = (None, None)
    if action in _LLM_ACTIONS:
        model_mb, model = _model_load_cost_mb()
        if model_mb:
            required = floor + model_mb
    if avail >= required:
        return None
    rec = {"error": "insufficient_memory", "action": action,
           "available_mb": avail, "required_mb": required, "floor_mb": floor,
           "detail": (f"refusing to start '{action}': {avail} MB free, need {required} MB. "
                      "A torch stage here would be OOM-killed mid-run with no traceback "
                      "(see TODOS 5.3.R51). Free memory or lower "
                      "DOTTIE_RESEARCH_MIN_FREE_MB.")}
    if model_mb:
        rec["model_load_mb"] = model_mb
        rec["model"] = model
        rec["detail"] = (
            f"refusing to start '{action}': {avail} MB free, need {required} MB "
            f"({floor} MB headroom + {model_mb} MB to load '{model}', which is not resident "
            "and goes to SYSTEM RAM at NUM_GPU=0). Loading it here would run the box to zero "
            "and take the WSL fleet with it (TODOS 5.3.R77). Free memory, or pre-load the "
            "model while the box is quiet.")
    return rec


def cmd_run(args) -> int:
    """Continuous chained runner: the moment one stage finishes, the next eligible
    stage starts — no hourly cadence. Honest refusals (Ollama down, unparseable
    ideation) back off exponentially instead of spinning; five CONSECUTIVE
    unexpected errors exit non-zero so the scheduler heartbeat can restart clean."""
    import time
    led = _ledger(args)
    print(json.dumps({"ts": time.time(), "action": "boot", "pid": os.getpid(),
                      "trainer": getattr(args, "trainer", None),
                      "max_retries": getattr(args, "max_retries", None),
                      **_boot_provenance()}), flush=True)
    last_ideate = 0.0
    backoff = float(args.idle_seconds)
    consecutive_errors = 0
    actions = 0
    idle_passes = 0
    while args.max_actions == 0 or actions < args.max_actions:
        actions += 1
        action = _choose_action(led.counts(), now=time.time(), last_ideate_ts=last_ideate,
                                ideate_cooldown_s=args.ideate_cooldown)
        rec: Dict[str, Any] = {"ts": time.time(), "action": action}
        try:
            if action == "idle":
                # Heartbeat every ~5 min of idling. Without this an idle daemon is
                # indistinguishable from a STALLED one in run.log: both print nothing.
                # (Measured 2026-07-20: 40 min of silence cost an hour of diagnosis —
                # stdout was never the problem, every print already flushes.)
                idle_passes += 1
                if idle_passes % max(1, int(300 / max(args.idle_seconds, 1))) == 0:
                    print(json.dumps({"ts": time.time(), "action": "idle",
                                      "idle_s": round(idle_passes * args.idle_seconds),
                                      "counts": led.counts()}), flush=True)
                time.sleep(float(args.idle_seconds))
                continue
            idle_passes = 0
            # Refuse rather than die: a torch stage started under memory pressure is
            # OOM-killed with no traceback and no exit code, and the scheduler restarts it
            # into the same wall every 15 minutes (TODOS 5.3.R51 — measured at 110 MB free).
            refusal = _memory_refusal(action)
            if refusal is not None:
                print(json.dumps({"ts": time.time(), **refusal}), flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, 300.0)
                continue
            backoff = float(args.idle_seconds)
            # A start line makes a BLOCKED action visible: a "start" with no matching
            # completion is the signature of the stall this loop hit tonight (an Ollama
            # generate that never returned inside the 1800 s read timeout).
            print(json.dumps({"ts": time.time(), "action": action, "phase": "start"}),
                  flush=True)
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
            # rec["ts"] is when the action STARTED, so a reader cannot tell how long it
            # took without diffing against the next line. Stamp the duration explicitly.
            rec["dur_s"] = round(time.time() - rec["ts"], 1)
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
    pr.add_argument("--rebuild", action="store_true",
                    help="regenerate bundles that already exist (bundle-format fixes do "
                         "NOT reach existing bundles otherwise)")
    pr.set_defaults(func=cmd_promote)

    st = sub.add_parser("status", help="print the research status snapshot")
    st.set_defaults(func=cmd_status)
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    # os._exit, not sys.exit: MEASURED 2026-07-20 — worker processes finished their work
    # and committed it, then never terminated. sys.exit raises SystemExit and interpreter
    # shutdown then JOINS non-daemon threads; the factory trainer's torch/OpenMP pool never
    # releases (PID 8524: 10,747 CPU-s of real work done, then 53 threads parked in Wait
    # forever). Task Scheduler therefore kept the task "Running", and MultipleInstances=
    # IgnoreNew silently refused the next hourly trigger — two ticks were lost that way
    # tonight (02:05 0x800710E0, and the 03:05 run had to be stopped by hand).
    #
    # Safe here because the process is DONE: every ledger write commits inside its own
    # `with self._conn()` block, and this package registers no atexit/__del__ cleanup
    # (both verified). The explicit flush also gets the JSON result line out of Python's
    # block-buffered stdout, which is what made run.log useless as a liveness signal.
    _code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code if isinstance(_code, int) else 0)
