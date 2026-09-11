"""`scout loop` — the Dottie Full Ecosystem loop behind the single tool surface.

Thin wrapper over `packages/dottie-loop` (`dottie_loop`), so the harness reaches
goal intake, the end-to-end runner, the closed-loop trigger, Forge runner status
and the benchmark smoke through `scout --json loop …` like every other capability
(spec §12: one composable interface; registry, policy, execution and audit stay
outside the model).

Policy: every plugin-chosen write goes under the ONE declared root
(`~/.local/share/dottie/loop/`) and is gated by enforce_or_raise("fs_write")
before anything touches disk. No network, no secrets. If `dottie_loop` is not
importable the plugin answers with an honest structured error, never a mock.

stdlib + typer + dottie_loop. No model is called.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from bigbang.core.cli_ux import fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

PLUGIN_DIR = Path(__file__).parent
STORE_ROOT = Path.home() / ".local" / "share" / "dottie" / "loop"

app = make_plugin_app(
    "loop",
    "Dottie Full Ecosystem loop — intake, end-to-end run, trigger, forge, bench",
    examples=[
        "scout --json loop status",
        'scout --json loop goal --intent "summarize the README"',
        "scout --json loop run --spec run.json --root .",
        "scout --json loop feedback --run-id run_… --signal accept",
        "scout --json loop evaluate --sources metrics.json",
        "scout --json loop forge-runners",
        "scout --json loop bench",
    ],
)


def _manifest() -> dict[str, Any]:
    return load_manifest(PLUGIN_DIR)


def _store(sub: str) -> Path:
    """The plugin-chosen store under the declared root; gated BEFORE mkdir."""
    target = STORE_ROOT / sub
    enforce_or_raise(_manifest(), "fs_write", str(target))
    target.mkdir(parents=True, exist_ok=True)
    return target


def _dottie_loop() -> Any:
    try:
        import dottie_loop  # noqa: F401 - presence check
        from dottie_loop import cli as loop_cli
    except ImportError:
        fail_agent(
            "dottie_loop is not importable in this environment (uv sync --all-groups from the repo root)",
            command="loop status",
            example="uv sync --all-groups --frozen && scout --json loop status",
        )
    return loop_cli


def _run(loop_cli: Any, argv: list[str], command: str) -> dict[str, Any]:
    """Run a dottie_loop CLI command in-process; map its exit code to ours."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = loop_cli.main(argv)
    line = buf.getvalue().strip().splitlines()[-1] if buf.getvalue().strip() else "{}"
    envelope = json.loads(line)
    if rc != 0:
        emit({"ok": False, "command": command, "exit_code": rc, "error": envelope.get("error"), "status": envelope.get("status")}, command=command)
        raise typer.Exit(code=rc)
    return envelope.get("data", {})


@app.command("status")
def status_cmd() -> None:
    """Package + spec version; capability_claim is always none."""
    loop_cli = _dottie_loop()
    emit(ok(_run(loop_cli, ["spec", "status"], "loop status"), command="loop status"), command="loop status")


@app.command("goal")
def goal_cmd(
    intent: str = typer.Option(..., "--intent", help="verbatim goal text"),
    subject: str = typer.Option("scout-operator", "--subject", help="authenticated subject id"),
    key: str | None = typer.Option(None, "--key", help="idempotency key (default: derived from intent)"),
) -> None:
    """Submit a GoalEnvelope into the loop's goal store (received; nothing executes)."""
    loop_cli = _dottie_loop()
    from dottie_loop.hashing import digest

    store = _store("goals")
    payload = json.dumps({"idempotency_key": key or f"scout-{digest(intent)[:16]}", "intent_text": intent})
    data = _run(loop_cli, ["goal", "submit", "--store", str(store), "--surface", "cli", "--subject", subject, "--json", payload], "loop goal")
    emit(ok(data, command="loop goal", example="scout --json loop run --spec run.json --root ."), command="loop goal")


@app.command("run")
def run_cmd(
    spec: Path = typer.Option(..., "--spec", help="RunSpec JSON (intent_text, steps[])"),
    root: Path = typer.Option(Path(), "--root", help="sandbox root every step is confined to"),
    subject: str = typer.Option("scout-operator", "--subject"),
    capture: bool = typer.Option(False, "--capture", help="explicit opt-in switch for trace capture"),
) -> None:
    """One goal end to end: intake → plan → execute → verify → checkpoint (→ trace, reward)."""
    loop_cli = _dottie_loop()
    if not spec.exists():
        fail_agent(f"spec not found: {spec}", command="loop run", example="scout --json loop run --spec run.json --root .")
    store = _store("runs")
    argv = ["loop", "run", "--spec", str(spec), "--store", str(store), "--root", str(root), "--subject", subject]
    if capture:
        argv.append("--capture")
    emit(ok(_run(loop_cli, argv, "loop run"), command="loop run"), command="loop run")


@app.command("feedback")
def feedback_cmd(
    run_id: str = typer.Option(..., "--run-id", help="run_id or trace_id of a captured run (`loop run --capture`)"),
    signal: str = typer.Option(..., "--signal", help="accept | reject | edit | apply | dismiss"),
    edit_fraction: float | None = typer.Option(None, "--edit-fraction", help="for edit: fraction of the output changed, 0..1"),
    subject: str = typer.Option("scout-operator", "--subject"),
) -> None:
    """Gap 02: real feedback from this surface, bound to the run it answers; the reward is recomputed."""
    loop_cli = _dottie_loop()
    store = _store("runs")
    argv = ["feedback", "record", "--store", str(store), "--run-id", run_id, "--signal", signal, "--subject", subject]
    if edit_fraction is not None:
        argv += ["--edit-fraction", str(edit_fraction)]
    emit(ok(_run(loop_cli, argv, "loop feedback"), command="loop feedback", example="scout --json loop feedback --run-id run_… --signal accept"), command="loop feedback")


@app.command("evaluate")
def evaluate_cmd(
    sources: Path = typer.Option(..., "--sources", help="metric sources JSON"),
    baseline: Path | None = typer.Option(None, "--baseline"),
    promote: bool = typer.Option(False, "--promote"),
    approve_prod: bool = typer.Option(False, "--approve-prod"),
) -> None:
    """Closed-loop trigger: no_change | trigger | blocked (stale/missing evidence exits 2)."""
    loop_cli = _dottie_loop()
    store = _store("decisions")
    argv = ["loop", "evaluate", "--sources", str(sources), "--out", str(store / "decisions.jsonl")]
    if baseline is not None:
        argv += ["--baseline", str(baseline)]
    if promote:
        argv.append("--promote")
    if approve_prod:
        argv.append("--approve-prod")
    emit(ok(_run(loop_cli, argv, "loop evaluate"), command="loop evaluate"), command="loop evaluate")


@app.command("forge-runners")
def forge_runners_cmd(queue: Path | None = typer.Option(None, "--queue", help="forge queue root (default: under the loop store)")) -> None:
    """Registered Forge runners; exits 2 (blocked) until one is advertised."""
    loop_cli = _dottie_loop()
    root = queue if queue is not None else _store("forge")
    emit(ok(_run(loop_cli, ["forge", "runners", "--root", str(root)], "loop forge-runners"), command="loop forge-runners"), command="loop forge-runners")


@app.command("bench")
def bench_cmd() -> None:
    """Benchmark smoke: workflow inventory + goldens with reconciled accounting."""
    loop_cli = _dottie_loop()
    emit(ok(_run(loop_cli, ["bench", "smoke"], "loop bench"), command="loop bench"), command="loop bench")
