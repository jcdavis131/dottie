"""scout router — the router training loop over dottie_loop.router_training.

    scout router pack      real production traces -> strict jev records + provenance
    scout router train     jev-v0 pointer-LoRA trainer on the pack (dry-run unless --go)
    scout router eval      checkpoint vs the heuristic on the holdout -> eval_summary.json
    scout router promote   the human stamp (--i-have-reviewed); never automatic
    scout router status    traces on disk, stamps, what is authoritative now

The heuristic stays authoritative until a checkpoint's eval says gate_passed
AND a human stamps those exact bytes. This plugin never stamps on its own.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer

from bigbang.core.contract import err, make_plugin_app, ok
from bigbang.core.output import emit

app = make_plugin_app(
    "router",
    "Router training loop: pack traces, train (GPU host), eval vs heuristic, human promote",
    examples=[
        "scout --json router status",
        "scout --json router pack --out ~/dottie-packs/router-001",
        "scout --json router train --pack ~/dottie-packs/router-001",
        "scout --json router eval --pack ~/dottie-packs/router-001 --checkpoint runs/router-001",
        "scout --json router promote runs/router-001 --i-have-reviewed --by cam",
    ],
)


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
):
    """Real production traces -> strict jev records. Refuses test/synthetic rows."""
    from dottie_loop.errors import LoopError
    from dottie_loop.router_training import pack

    files = _trace_files(traces)
    if not files:
        _fail("router pack", "no trace files found", hint="route and run real goals first; traces land in ~/.dottie/traces")
    try:
        manifest = pack(files, Path(out).expanduser(), seed=seed,
                        corrections_path=Path(corrections).expanduser() if corrections else None,
                        version=version or None)
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
):
    """Run jev-v0's pointer-LoRA trainer on the pack. Dry-run (torch-free validation) by default."""
    from dottie_loop.errors import LoopError
    from dottie_loop.router_training import refuse_synthetic_pack, train_command

    p = Path(pack_dir).expanduser()
    try:
        refuse_synthetic_pack(p)
    except LoopError as exc:
        _fail("router train", str(exc))
    if go and not out:
        _fail("router train", "--go needs --out <checkpoint dir>")
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
):
    """Score a checkpoint vs the heuristic on the holdout; write eval_summary.json. Never stamps."""
    from dottie_loop.errors import LoopError
    from dottie_loop.router_training import (
        _tier_items,
        checkpoint_predictions,
        evaluate,
        write_eval_summary,
    )

    p = Path(pack_dir).expanduser()
    ck = Path(checkpoint).expanduser()
    if not ck.exists():
        _fail("router eval", f"checkpoint not found: {ck}")
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
            preds = checkpoint_predictions(ck, _tier_items(p))
            source = "checkpoint"
        summary = evaluate(p, ck, preds, predictions_source=source, evaluator_commit=commit,
                           approved_cost_ratio=approved_cost_ratio)
    except (LoopError, OSError, ValueError, KeyError) as exc:
        _fail("router eval", f"{type(exc).__name__}: {exc}")
    path = write_eval_summary(ck, summary)
    emit(ok({"eval_summary": str(path), "gate_passed": summary["gate_passed"], "metrics": summary["metrics"],
             "failed_gates": summary["gates"]["failed"], "promotion": summary["promotion"]},
            command="router eval"), "router eval")


@app.command("promote")
def promote_cmd(
    artifact: str = typer.Argument(..., help="the evaluated checkpoint dir (or weights file)"),
    reviewed: bool = typer.Option(False, "--i-have-reviewed", help="I read eval_summary.json and accept this artifact"),
    by: str = typer.Option("", "--by", help="who reviewed it"),
    note: str = typer.Option("", "--note"),
):
    """Stamp a gate_passed artifact as human-reviewed. The ONLY way a learned answer becomes authoritative."""
    from dottie_loop.errors import LoopError
    from dottie_loop.router_artifacts import write_stamp

    if not reviewed:
        _fail("router promote", "refused: pass --i-have-reviewed after reading the artifact's eval_summary.json")
    try:
        stamp = write_stamp(Path(artifact).expanduser(), reviewed=reviewed, reviewer=by, note=note)
    except LoopError as exc:
        _fail("router promote", str(exc))
    emit(ok(stamp, command="router promote"), "router promote")
