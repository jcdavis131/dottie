"""scout router — the router training loop over dottie_loop.router_training.

    scout router probe     benchmark goals through real executors, cheapest tier first -> labels
    scout router pack      real traces (production + benchmark-verified) -> strict jev records
    scout router train     --mlp: the orchestrator MLP on CPU; else jev-v0 pointer-LoRA (GPU, --go)
    scout router eval      checkpoint vs the heuristic on both holdouts -> eval_summary.json
    scout router spotcheck sample N labels beside the candidate; a human marks each ok/bad
    scout router promote   the human stamp (--i-have-reviewed, needs a marked spot-check)
    scout router status    traces on disk, stamps, what is authoritative now

The heuristic stays authoritative until a checkpoint's eval says gate_passed
(>= 50 production rows, beats the heuristic on the production holdout, no
regression on the benchmark holdout), a human marks its spot-check, AND a
human stamps those exact bytes. This plugin never stamps on its own.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import typer

from bigbang.core.contract import err, make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

app = make_plugin_app(
    "router",
    "Router training loop: pack traces, train (GPU host), eval vs heuristic, human promote",
    examples=[
        "scout --json router status",
        "scout --json router probe --bench packages/dottie-loop/dottie_loop/benchmarks/router_bench_v1.jsonl --limit 20",
        "scout --json router pack --out ~/dottie-packs/router-001",
        "scout --json router train --mlp --pack ~/dottie-packs/router-001 --out runs/router-mlp.json",
        "scout --json router spotcheck runs/router-mlp.json --pack ~/dottie-packs/router-001",
        "scout --json router train --pack ~/dottie-packs/router-001",
        "scout --json router eval --pack ~/dottie-packs/router-001 --checkpoint runs/router-001",
        "scout --json router promote runs/router-001 --i-have-reviewed --by cam",
        "scout --json router bench --n 50",
    ],
)


def _manifest() -> dict:
    return load_manifest(Path(__file__).parent)


def _fail(command: str, error: str, **extra) -> None:
    emit(err(error, command=command, **extra), command)
    raise typer.Exit(1)


def _trace_files(traces: str) -> list[Path]:
    from dottie_loop.traces import trace_dir

    if traces:
        p = Path(traces).expanduser()
        return sorted(p.glob("route-*.jsonl")) if p.is_dir() else [p]
    base = trace_dir()
    return sorted(base.glob("route-*.jsonl")) if base is not None and base.is_dir() else []


@app.command("status")
def status_cmd():
    """Trace files, stamps, and which backend is authoritative right now."""
    from dottie_loop.router_artifacts import stamp_dir
    from dottie_loop.traces import trace_dir, trace_source

    files = _trace_files("")
    stamps = sorted(stamp_dir().glob("*.json")) if stamp_dir().is_dir() else []
    emit(ok({
        "trace_dir": str(trace_dir()) if trace_dir() is not None else None,
        "trace_source": trace_source(),
        "trace_files": [str(p) for p in files],
        "stamps": [p.stem for p in stamps],
        "authority": "heuristic unless a backend answer is gate_passed and stamped",
    }, command="router status"), "router status")


@app.command("pack")
def pack_cmd(
    out: str = typer.Option(..., "--out", help="pack directory to write (train/holdout/provenance/MANIFEST)"),
    traces: str = typer.Option("", "--traces", help="trace file or directory (default: the trace dir)"),
    corrections: str = typer.Option("", "--corrections", help="label_corrections.jsonl from `scout harness correct`"),
    seed: int = typer.Option(20260923, "--seed"),
    version: str = typer.Option("", "--version", help="pack id (default router-pack-<utc stamp>)"),
    bench: list[str] = typer.Option(None, "--bench", help="benchmark goal set(s) the probe ran (default: the committed one)"),
    eval_set: list[str] = typer.Option(None, "--eval-set", help="external eval set jsonl whose goals must never train (repeatable)"),
    allow_upper_bound: bool = typer.Option(False, "--allow-upper-bound", help="also pack probe labels that are upper bounds (a cheaper tier was unavailable)"),
):
    """Real traces -> strict jev records. Trains production + benchmark-verified; refuses test/teacher/synthetic."""
    from dottie_loop.errors import LoopError
    from dottie_loop.router_training import pack

    enforce_or_raise(_manifest(), "fs_write_arg", str(Path(out).expanduser()))
    files = _trace_files(traces)
    if not files:
        _fail("router pack", "no trace files found", hint="route and run real goals first; traces land in ~/.dottie/traces")
    try:
        manifest = pack(files, Path(out).expanduser(), seed=seed,
                        corrections_path=Path(corrections).expanduser() if corrections else None,
                        version=version or None, allow_upper_bound=allow_upper_bound,
                        bench_files=[Path(b).expanduser() for b in bench] if bench else [_default_bench()],
                        eval_sets=[Path(e).expanduser() for e in eval_set or []])
    except LoopError as exc:
        _fail("router pack", str(exc))
    emit(ok(manifest, command="router pack"), "router pack")


@app.command("train")
def train_cmd(
    pack_dir: str = typer.Option(..., "--pack", help="a `scout router pack` directory"),
    out: str = typer.Option("", "--out", help="checkpoint directory (with --go)"),
    go: bool = typer.Option(False, "--go", help="actually train (GPU host: torch+transformers+peft)"),
    steps: int = typer.Option(200, "--steps"),
    base_model: str = typer.Option("", "--base-model"),
    mlp: bool = typer.Option(False, "--mlp", help="train the orchestrator MLP router on CPU (numpy) to --out <weights.json>"),
    epochs: int = typer.Option(300, "--epochs", help="--mlp: full-batch epochs"),
    seed: int = typer.Option(0, "--seed", help="--mlp: init seed"),
):
    """Train on the pack. --mlp: the orchestrator MLP on CPU; else jev-v0's pointer-LoRA (dry-run unless --go)."""
    from dottie_loop.errors import LoopError
    from dottie_loop.router_training import refuse_synthetic_pack, train_command

    p = Path(pack_dir).expanduser()
    try:
        refuse_synthetic_pack(p)
    except LoopError as exc:
        _fail("router train", str(exc))
    if mlp:
        _train_mlp(p, out, epochs=epochs, seed=seed)
        return
    if go and not out:
        _fail("router train", "--go needs --out <checkpoint dir>")
    if go:
        enforce_or_raise(_manifest(), "fs_write_arg", str(Path(out).expanduser()))
    cmd = train_command(p, Path(out).expanduser() if out else p / "checkpoint", go=go, steps=steps,
                        base_model=base_model or None)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    report = None
    try:
        report = json.loads(proc.stdout)
    except ValueError:
        report = None
    payload = {"go": go, "command": cmd, "returncode": proc.returncode, "report": report,
               "stderr_tail": proc.stderr[-2000:], "next": "scout router eval --pack ... --checkpoint <out>" if go else
               "re-run with --go --out <dir> on the GPU host"}
    if proc.returncode != 0:
        _fail("router train", "trainer exited non-zero", **payload)
    emit(ok(payload, command="router train"), "router train")


@app.command("eval")
def eval_cmd(
    pack_dir: str = typer.Option(..., "--pack", help="the pack the checkpoint was trained on"),
    checkpoint: str = typer.Option(..., "--checkpoint", help="checkpoint dir (or weights file) to evaluate"),
    predictions: str = typer.Option("", "--predictions", help="jsonl of {id, tier}: precomputed answers instead of running the checkpoint"),
    commit: str = typer.Option("unknown", "--commit", help="evaluator git commit, recorded in the bundle"),
    approved_cost_ratio: float = typer.Option(1.5, "--approved-cost-ratio", help="max candidate/heuristic mean tier cost"),
    min_production_rows: int = typer.Option(50, "--min-production-rows", help="the gate refuses below this many production rows"),
):
    """Score a checkpoint vs the heuristic on the holdout; write eval_summary.json. Never stamps."""
    from dottie_loop.errors import LoopError
    from dottie_loop.router_training import (
        checkpoint_predictions,
        eval_items,
        evaluate,
        write_eval_summary,
    )

    p = Path(pack_dir).expanduser()
    ck = Path(checkpoint).expanduser()
    if not ck.exists():
        _fail("router eval", f"checkpoint not found: {ck}")
    enforce_or_raise(_manifest(), "fs_write_arg", str(ck / "eval_summary.json" if ck.is_dir() else ck.with_name("eval_summary.json")))
    try:
        if predictions:
            pred_path = Path(predictions).expanduser()
            preds = {}
            for line in pred_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    preds[str(row["id"])] = str(row["tier"])
            source = f"file:{pred_path}"
        else:
            preds = checkpoint_predictions(ck, eval_items(p))
            source = "checkpoint"
        summary = evaluate(p, ck, preds, predictions_source=source, evaluator_commit=commit,
                           approved_cost_ratio=approved_cost_ratio, min_production_rows=min_production_rows)
    except (LoopError, OSError, ValueError, KeyError) as exc:
        _fail("router eval", f"{type(exc).__name__}: {exc}")
    path = write_eval_summary(ck, summary)
    emit(ok({"eval_summary": str(path), "gate_passed": summary["gate_passed"], "metrics": summary["metrics"],
             "refusals": summary["refusals"], "failed_gates": summary["gates"]["failed"],
             "promotion": summary["promotion"]},
            command="router eval"), "router eval")


@app.command("bench")
def bench_cmd(
    n: int = typer.Option(50, "--n", help="samples per warm scenario"),
    cold_n: int = typer.Option(10, "--cold-n", help="samples for the cold `scout route` subprocess"),
    only: list[str] = typer.Option(None, "--only", help="run only these scenarios (repeatable)"),
):
    """Decision latency, measured on this box: cold `scout route`, in-process, jarvisd warm, System One.

    Starts its own jarvisd and serve_decide on loopback with temp state; writes nothing real.
    """
    from dottie_loop import bench_decide

    chosen = tuple(only) if only else bench_decide.SCENARIOS
    unknown = sorted(set(chosen) - set(bench_decide.SCENARIOS))
    if unknown:
        _fail("router bench", f"unknown scenario(s) {unknown}; one of {list(bench_decide.SCENARIOS)}")
    report = bench_decide.run(n, cold_n, chosen)
    report["table"] = bench_decide.format_table(report)
    emit(ok(report, command="router bench"), "router bench")


@app.command("promote")
def promote_cmd(
    artifact: str = typer.Argument(..., help="the evaluated checkpoint dir (or weights file)"),
    reviewed: bool = typer.Option(False, "--i-have-reviewed", help="I read eval_summary.json and accept this artifact"),
    by: str = typer.Option("", "--by", help="who reviewed it"),
    note: str = typer.Option("", "--note"),
):
    """Stamp a gate_passed, spot-checked artifact as human-reviewed. The ONLY way a learned answer becomes authoritative."""
    from dottie_loop.errors import LoopError
    from dottie_loop.router_artifacts import stamp_dir, write_stamp

    # plugin-chosen default -> fs_write (declared path); an env override is the operator's choice
    action = "fs_write_arg" if os.environ.get("DOTTIE_ROUTER_STAMPS") else "fs_write"
    enforce_or_raise(_manifest(), action, str(stamp_dir() / "stamp.json"))
    if not reviewed:
        _fail("router promote", "refused: pass --i-have-reviewed after reading the artifact's eval_summary.json")
    try:
        stamp = write_stamp(Path(artifact).expanduser(), reviewed=reviewed, reviewer=by, note=note)
    except LoopError as exc:
        _fail("router promote", str(exc))
    emit(ok(stamp, command="router promote"), "router promote")


def _default_bench() -> Path:
    import dottie_loop

    return Path(dottie_loop.__file__).parent / "benchmarks" / "router_bench_v1.jsonl"


def _train_mlp(pack_dir: Path, out: str, *, epochs: int, seed: int) -> None:
    from dottie_loop.errors import LoopError
    from dottie_loop.mlp_train import train_pack

    if not out:
        _fail("router train", "--mlp needs --out <weights.json>")
    target = Path(out).expanduser()
    enforce_or_raise(_manifest(), "fs_write_arg", str(target))
    try:
        report = train_pack(pack_dir, target, epochs=epochs, seed=seed)
    except (LoopError, OSError, ValueError, ImportError) as exc:
        _fail("router train", f"{type(exc).__name__}: {exc}")
    report["next"] = f"scout router eval --pack {pack_dir} --checkpoint {target}"
    emit(ok(report, command="router train"), "router train")


@app.command("probe")
def probe_cmd(
    bench: str = typer.Option("", "--bench", help="benchmark goal set jsonl (default: the committed router_bench_v1)"),
    limit: int = typer.Option(0, "--limit", help="probe at most N goals (0 = all)"),
    offset: int = typer.Option(0, "--offset", help="skip the first N goals"),
    max_tier: str = typer.Option("deep_research", "--max-tier", help="highest tier to try: deterministic|llm|deep_research"),
    past_unavailable: bool = typer.Option(False, "--past-unavailable", help="keep escalating past an unavailable tier (labels become upper bounds)"),
    only: list[str] = typer.Option(None, "--id", help="probe only these goal ids (repeatable)"),
):
    """Run benchmark goals through REAL executors, cheapest tier first; write benchmark-verified traces.

    A goal is labelled with the cheapest tier whose answer passes its verifier.
    An unreachable backend stops the probe for that goal (no label).
    """
    from bigbang.plugins.harness.executors.probe import run_probe

    path = Path(bench).expanduser() if bench else _default_bench()
    if not path.is_file():
        _fail("router probe", f"benchmark not found: {path}")
    try:
        summary = run_probe(path, limit=limit, offset=offset, max_tier=max_tier, past_unavailable=past_unavailable,
                            ids=list(only) if only else None)
    except ValueError as exc:
        _fail("router probe", str(exc))
    emit(ok(summary, command="router probe"), "router probe")


@app.command("spotcheck")
def spotcheck_cmd(
    artifact: str = typer.Argument(..., help="the candidate checkpoint dir or weights file"),
    pack_dir: str = typer.Option("", "--pack", help="sample a new sheet from this pack"),
    n: int = typer.Option(20, "--n", help="labels to sample"),
    seed: int = typer.Option(0, "--seed"),
    mark: list[str] = typer.Option(None, "--mark", help="<id>=ok|bad (repeatable); `all=ok` marks every item"),
    by: str = typer.Option("", "--by", help="who marked them"),
):
    """Sample N labels into <artifact>.spotcheck.json (with --pack), or record a human's ok/bad marks (--mark --by)."""
    from dottie_loop.errors import LoopError
    from dottie_loop.router_artifacts import (
        load_spotcheck,
        spotcheck_mark,
        spotcheck_path,
        spotcheck_sample,
    )

    ck = Path(artifact).expanduser()
    enforce_or_raise(_manifest(), "fs_write_arg", str(spotcheck_path(ck)))
    try:
        if pack_dir:
            sheet = spotcheck_sample(Path(pack_dir).expanduser(), ck, n=n, seed=seed)
        else:
            sheet = load_spotcheck(ck)
        if mark:
            pairs = dict(m.split("=", 1) for m in mark if "=" in m)
            if "all" in pairs:
                every = pairs.pop("all")
                pairs = {it["id"]: every for it in sheet["items"]} | pairs
            sheet = spotcheck_mark(ck, pairs, reviewer=by)
    except LoopError as exc:
        _fail("router spotcheck", str(exc))
    marks = [it["mark"] for it in sheet["items"]]
    emit(ok({"spotcheck": str(spotcheck_path(ck)), "n": len(marks), "ok": marks.count("ok"), "bad": marks.count("bad"),
             "unmarked": marks.count(None), "reviewer": sheet.get("reviewer"), "items": sheet["items"]},
            command="router spotcheck"), "router spotcheck")
