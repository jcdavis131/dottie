"""cli.py — typer CLI for dottie-rlm (SPEC v1).

Commands (SPEC): run, repl, sessions, refine, rollback <id>, ledger,
status [--publish] [path].

Global options (before the command): ``--root`` (session registry root,
default %LOCALAPPDATA%/dottie-rlm/sessions) and ``--harness`` (harness dir,
default %LOCALAPPDATA%/dottie-rlm/harness). Tests pass tmp_path for both.

House rule: the backend degrades honestly — an unreachable backend refuses
with a clear error and a non-zero exit; nothing is fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import typer

from .harness import Harness, HarnessError, UnknownRefinementError
from .llm import BackendUnavailable, resolve_backend
from .loop import DEFAULT_MAX_STEPS
from .registry import SessionRegistry, default_root
from .rlm import Runtime
from .session import CorruptStateError
from .status import build_status, publish_status

__all__ = ["app", "default_harness_root"]

DEFAULT_MODEL = "ollama:qwen3:8b"

app = typer.Typer(
    name="dottie-rlm",
    help=(
        "Prime-Agent-style RLM harness: the model gets ONE tool — a "
        "persistent IPython kernel. Everything else is a function call "
        "inside it."
    ),
    no_args_is_help=True,
    add_completion=False,
)


def default_harness_root() -> Path:
    """``%LOCALAPPDATA%/dottie-rlm/harness`` (sibling of the sessions root)."""
    return default_root().parent / "harness"


# Module-level singletons: B008 forbids function calls in argument defaults,
# and typer evaluates these once at import time anyway.
ROOT_OPTION = typer.Option(
    None, "--root", help="Session registry root (default: %LOCALAPPDATA%/dottie-rlm/sessions)."
)
HARNESS_OPTION = typer.Option(
    None, "--harness", help="Harness dir (default: %LOCALAPPDATA%/dottie-rlm/harness)."
)
STATUS_PATH_ARGUMENT = typer.Argument(
    None, help="Publish target (default: <root>/rlm_status.json)."
)


@app.callback()
def main(
    ctx: typer.Context,
    root: Path | None = ROOT_OPTION,
    harness_dir: Path | None = HARNESS_OPTION,
) -> None:
    ctx.obj = {
        "root": root if root is not None else default_root(),
        "harness": harness_dir if harness_dir is not None else default_harness_root(),
    }


def _paths(ctx: typer.Context) -> tuple[Path, Path]:
    obj = ctx.obj or {}
    return (
        Path(obj.get("root") or default_root()),
        Path(obj.get("harness") or default_harness_root()),
    )


def _fail(message: str, code: int) -> NoReturn:
    typer.secho(f"error: {message}", err=True, fg=typer.colors.RED)
    raise typer.Exit(code)


def _runtime(ctx: typer.Context) -> Runtime:
    root, hdir = _paths(ctx)
    try:
        return Runtime(SessionRegistry(root), Harness(hdir))
    except (CorruptStateError, HarnessError) as exc:
        _fail(str(exc), 1)


def _echo_result(result: dict, max_steps: int) -> None:
    if result["stopped"] == "answer":
        typer.echo(result["answer"])
    else:
        typer.secho(
            f"[step-limit] hit max_steps={max_steps} without a final answer; "
            f"last model reply:",
            err=True,
            fg=typer.colors.YELLOW,
        )
        typer.echo(result.get("last_text") or "")


@app.command()
def run(
    ctx: typer.Context,
    goal: str = typer.Argument(..., help="What the agent should do."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Backend spec: fake:, ollama:<model>, openai:<base_url>:<model>."),
    max_steps: int = typer.Option(DEFAULT_MAX_STEPS, "--max-steps", min=1),
) -> None:
    """Run one goal in a fresh root session and print the answer."""
    try:
        resolve_backend(model)  # fail fast on a malformed spec
    except ValueError as exc:
        _fail(str(exc), 2)
    rt = _runtime(ctx)
    session = rt.create_root(model_spec=model)
    try:
        result = rt.run_turn(session, goal, max_steps=max_steps)
    except BackendUnavailable as exc:
        _fail(str(exc), 3)
    _echo_result(result, max_steps)
    if not rt.wait_children(timeout_s=0.0):
        typer.secho("(children still running; answers land in the inbox)", err=True)
    typer.secho(f"(session {session.id})", err=True)


@app.command()
def repl(
    ctx: typer.Context,
    model: str = typer.Option(DEFAULT_MODEL, "--model"),
    max_steps: int = typer.Option(DEFAULT_MAX_STEPS, "--max-steps", min=1),
) -> None:
    """Interactive loop: one persistent root session, turn per input line."""
    try:
        resolve_backend(model)
    except ValueError as exc:
        _fail(str(exc), 2)
    rt = _runtime(ctx)
    session = rt.create_root(model_spec=model)
    typer.secho(
        f"dottie-rlm repl — session {session.id}, model {model}. "
        f"/quit to exit.",
        err=True,
    )
    while True:
        try:
            text = input("rlm> ")
        except (EOFError, KeyboardInterrupt):
            typer.echo("")
            break
        if text.strip() in {"/quit", "/exit", "quit", "exit"}:
            break
        if not text.strip():
            continue
        try:
            result = rt.run_turn(session, text, max_steps=max_steps)
        except BackendUnavailable as exc:
            typer.secho(f"backend unavailable: {exc}", err=True, fg=typer.colors.RED)
            continue
        _echo_result(result, max_steps)


@app.command()
def sessions(ctx: typer.Context) -> None:
    """List sessions from the registry (id, role, state, turns, last_active)."""
    root, _hdir = _paths(ctx)
    try:
        registry = SessionRegistry(root)
        rows = build_status(registry)["sessions"]
    except CorruptStateError as exc:
        _fail(str(exc), 1)
    if not rows:
        typer.echo("no sessions")
        return
    for r in rows:
        typer.echo(
            f"{r['id']}  role={r['role'] or '?'}  state={r['state']}  "
            f"turns={r['turns']}  last_active={r['last_active']}"
        )


@app.command()
def refine(
    ctx: typer.Context,
    trigger: str = typer.Option(..., "--trigger", help="Why this refinement (ledgered)."),
    tail: str = typer.Option("", "--tail", help="Trajectory tail informing the edit."),
) -> None:
    """Apply the smallest relevant G/K/M edit (never rho) and ledger it."""
    _, hdir = _paths(ctx)
    try:
        harness = Harness(hdir)
        refinement = harness.refine(tail, trigger)
    except (HarnessError, ValueError) as exc:
        _fail(str(exc), 1)
    edit = refinement.edit
    typer.echo(f"{refinement.id}: {edit['op']} {edit['target']}/{edit['name']}")


@app.command()
def rollback(
    ctx: typer.Context,
    refinement_id: str = typer.Argument(..., help="Ledger id, e.g. r-1."),
) -> None:
    """Reverse a refinement's edit (idempotent; ledgered)."""
    _, hdir = _paths(ctx)
    try:
        harness = Harness(hdir)
        result = harness.rollback(refinement_id)
    except (UnknownRefinementError, HarnessError) as exc:
        _fail(str(exc), 1)
    typer.echo(result["message"])


@app.command()
def ledger(ctx: typer.Context) -> None:
    """Print the folded refinement ledger, one JSON object per line."""
    _, hdir = _paths(ctx)
    try:
        harness = Harness(hdir)
        entries = harness.ledger()
    except HarnessError as exc:
        _fail(str(exc), 1)
    if not entries:
        typer.echo("ledger empty")
        return
    for entry in entries:
        typer.echo(json.dumps(entry, ensure_ascii=False, sort_keys=True))


@app.command()
def status(
    ctx: typer.Context,
    publish: bool = typer.Option(False, "--publish", help="Atomically write rlm_status.json."),
    path: Path | None = STATUS_PATH_ARGUMENT,
) -> None:
    """Show the local status payload; with --publish, write it for the site."""
    root, hdir = _paths(ctx)
    try:
        registry = SessionRegistry(root)
        harness = Harness(hdir)
        if publish:
            target = path if path is not None else root / "rlm_status.json"
            publish_status(registry, target, harness)
            typer.echo(str(target))
        else:
            typer.echo(
                json.dumps(
                    build_status(registry, harness), ensure_ascii=False, indent=2
                )
            )
    except (CorruptStateError, HarnessError) as exc:
        _fail(str(exc), 1)


if __name__ == "__main__":  # pragma: no cover
    app()
