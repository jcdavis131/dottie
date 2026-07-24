
# Solo personal project, no connection to employer, built with public/free-tier only
"""
dev_loop plugin — auto-generated from shell history toil.

Toil source: ~/.zsh_history + ~/.bash_history cluster analysis
Top workflow: git status -> pytest -q -> git add -A -> git commit -m -> git push
Frequency: ~22/week (90 occurrences over 30 days, >5/week threshold)
Steps: 5

Maps shell args to flags, no secrets, redacted.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from bigbang.core.cli_ux import examples_epilog
from bigbang.core.contract import err, make_plugin_app, ok
from bigbang.core.output import emit

app = make_plugin_app(
    "dev_loop",
    "🔁 Dev Loop — automate git status → pytest → add → commit → push (from toil)",
    examples=[
        "scout dev_loop status",
        "scout dev_loop status --path apps/scout-cli",
        "scout dev_loop test --path apps/scout-cli -q",
        "scout dev_loop ship --message 'feat: ship' --yes",
        "scout --json dev_loop status",
        "scout --json dev_loop ship --message 'feat: update' --no-push",
    ],
)

console = Console()

def _resolve_repo(path: Optional[str]) -> Path:
    if path:
        p = Path(os.path.expanduser(os.path.expandvars(path))).resolve()
        if p.exists():
            return p
        # relative to scout-cli root
        # bigbang/plugins/dev_loop/cli.py -> parents[3] = scout-cli
        here = Path(__file__).resolve()
        try:
            candidate = here.parents[3] / path
            if candidate.exists():
                return candidate
        except Exception:
            pass
        return p
    # default: scout-cli repo
    here = Path(__file__).resolve()
    try:
        candidate = here.parents[3]
        if (candidate / "bigbang" / "cli.py").exists():
            return candidate
    except Exception:
        pass
    return Path.cwd()

def _run(cmd: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

def _is_truthy_env(val: Optional[str]) -> bool:
    return bool(val and val.strip().lower() in {"1","true","yes","y","on"})

@app.command(
    "status",
    epilog=examples_epilog(["scout dev_loop status", "scout --json dev_loop status --path ."]),
)
def status_cmd(
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
):
    """git status — first step of the dev loop."""
    repo = _resolve_repo(path)
    if not (repo / ".git").exists() and not (repo.parent / ".git").exists():
        # allow non-git but warn
        pass
    result = _run(["git", "status", "--porcelain", "-b"], cwd=repo)
    short_status = _run(["git", "status"], cwd=repo)
    emit(
        ok(
            {
                "repo": str(repo),
                "branch_status": result.stdout.strip()[:2000],
                "full_status": short_status.stdout.strip()[:5000],
                "stderr": result.stderr[:1000],
                "ok": result.returncode == 0,
            },
            command="dev_loop status",
            example="scout dev_loop status --path apps/scout-cli",
            discover="scout dev_loop --help",
        ),
        command="dev_loop status",
    )

@app.command(
    "test",
    epilog=examples_epilog(["scout dev_loop test", "scout dev_loop test --path apps/scout-cli -- -k todos"]),
)
def test_cmd(
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
    pytest_args: Optional[str] = typer.Option(None, "--args", "-a", help="Extra pytest args string, e.g. '-k todos'"),
    quiet: bool = typer.Option(True, "--quiet", "-q", help="Use -q"),
):
    """pytest -q — second step, test-gated."""
    repo = _resolve_repo(path)
    cmd = ["pytest"]
    if quiet:
        cmd.append("-q")
    if pytest_args:
        # naive split but safe for simple -k filters
        cmd.extend(pytest_args.split())
    else:
        # default to tests dir if exists
        if (repo / "tests").exists():
            cmd.append("tests")
    result = _run(cmd, cwd=repo)
    emit(
        ok(
            {
                "repo": str(repo),
                "cmd": " ".join(cmd),
                "returncode": result.returncode,
                "passed": result.returncode == 0,
                "stdout_tail": result.stdout[-4000:],
                "stderr_tail": result.stderr[-2000:],
            },
            command="dev_loop test",
            example="scout dev_loop test --path apps/scout-cli",
            discover="scout dev_loop ship --help",
        ),
        command="dev_loop test",
    )

@app.command(
    "ship",
    epilog=examples_epilog([
        "scout dev_loop ship --message 'feat: update' --yes",
        "scout dev_loop ship --path apps/scout-cli --message 'fix: thing' --no-push",
        "scout --json dev_loop ship --message 'chore: nightly' --yes",
    ]),
)
def ship_cmd(
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
    message: str = typer.Option(..., "--message", "-m", help="Commit message"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation (also env SCOUT_YES=1)"),
    no_push: bool = typer.Option(False, "--no-push", help="Do not push"),
    run_tests: bool = typer.Option(True, "--run-tests/--no-tests", help="Run pytest -q before commit"),
    add_all: bool = typer.Option(True, "--add-all/--no-add-all", help="git add -A"),
):
    """Full dev loop: status → optional test → add → commit → push.

    Automates the >5/week workflow found in shell history:
    git status; pytest -q; git add -A; git commit -m; git push
    """
    repo = _resolve_repo(path)
    env_yes = _is_truthy_env(os.environ.get("SCOUT_YES"))
    effective_yes = yes or env_yes

    # Safety: require message
    if not message or len(message.strip()) < 3:
        emit(
            err(
                "Commit message required (--message) min 3 chars",
                command="dev_loop ship",
                example="scout dev_loop ship --message 'feat: my change' --yes",
                discover="scout dev_loop ship --help",
            ),
            command="dev_loop ship",
        )
        raise typer.Exit(1)

    # 1. status
    status_res = _run(["git", "status", "--porcelain"], cwd=repo)
    # 2. tests if requested
    test_passed = True
    test_output = ""
    if run_tests:
        test_res = _run(["pytest", "-q"], cwd=repo)
        test_passed = test_res.returncode == 0
        test_output = (test_res.stdout + test_res.stderr)[-3000:]
        if not test_passed:
            emit(
                err(
                    f"Tests failed, aborting ship (use --no-tests to skip). Output: {test_output[-800:]}",
                    command="dev_loop ship",
                    example="scout dev_loop ship --message 'feat: x' --no-tests --yes",
                    discover="scout dev_loop test --help",
                ),
                command="dev_loop ship",
            )
            raise typer.Exit(1)

    if not effective_yes:
        # interactive confirm if tty
        try:
            is_tty = sys.stdin.isatty()
        except Exception:
            is_tty = False
        if is_tty:
            console.print(f"[bold]Repo:[/bold] {repo}")
            console.print(f"[bold]Message:[/bold] {message}")
            console.print(f"[bold]Status:[/bold]\n{status_res.stdout[:2000] or '(clean)'}")
            if not typer.confirm("Proceed with add/commit/push?"):
                emit(
                    ok({"cancelled": True, "repo": str(repo)}, command="dev_loop ship", example="scout dev_loop ship --message 'feat: x' --yes"),
                    command="dev_loop ship",
                )
                raise typer.Exit(0)
        else:
            emit(
                err(
                    "Non-interactive without --yes. Use --yes/-y or SCOUT_YES=1",
                    command="dev_loop ship",
                    example="scout dev_loop ship --message 'feat: x' --yes",
                    discover="scout dev_loop ship --help",
                ),
                command="dev_loop ship",
            )
            raise typer.Exit(1)

    # 3. add
    if add_all:
        add_res = _run(["git", "add", "-A"], cwd=repo)
        if add_res.returncode != 0:
            emit(
                err(f"git add -A failed: {add_res.stderr[:1000]}", command="dev_loop ship", example="scout dev_loop ship --message 'fix' --yes"),
                command="dev_loop ship",
            )
            raise typer.Exit(1)

    # 4. commit
    # Check if anything to commit
    diff_cached = _run(["git", "diff", "--cached", "--quiet"], cwd=repo)
    if diff_cached.returncode == 0:
        # nothing staged
        emit(
            ok(
                {"repo": str(repo), "message": "Nothing to commit, working tree clean", "pushed": False},
                command="dev_loop ship",
                example="scout dev_loop status",
                discover="scout dev_loop status",
            ),
            command="dev_loop ship",
        )
        return

    commit_res = _run(["git", "commit", "-m", message], cwd=repo)
    if commit_res.returncode != 0:
        emit(
            err(f"git commit failed: {commit_res.stderr[:1000]} {commit_res.stdout[:1000]}", command="dev_loop ship", example="scout dev_loop ship --message 'feat: x' --yes"),
            command="dev_loop ship",
        )
        raise typer.Exit(1)

    sha_proc = _run(["git", "rev-parse", "--short", "HEAD"], cwd=repo)
    sha = sha_proc.stdout.strip()

    pushed = False
    push_output = ""
    if not no_push:
        push_res = _run(["git", "push"], cwd=repo)
        pushed = push_res.returncode == 0
        push_output = (push_res.stdout + push_res.stderr)[-2000:]
        if not pushed:
            # still consider ship partial success
            emit(
                ok(
                    {
                        "repo": str(repo),
                        "committed": True,
                        "sha": sha,
                        "pushed": False,
                        "push_output": push_output,
                        "test_passed": test_passed,
                        "message": message,
                    },
                    command="dev_loop ship",
                    example="scout dev_loop status",
                    discover="scout system audit",
                ),
                command="dev_loop ship",
            )
            return

    emit(
        ok(
            {
                "repo": str(repo),
                "committed": True,
                "sha": sha,
                "pushed": pushed,
                "test_passed": test_passed,
                "message": message,
            },
            command="dev_loop ship",
            example="scout dev_loop status",
            discover="scout dev_loop ship --help",
        ),
        command="dev_loop ship",
    )

@app.command(
    "run",
    epilog=examples_epilog(["scout dev_loop run --message 'feat: quick ship' --yes"]),
)
def run_cmd(
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
    message: str = typer.Option("chore: dev loop auto-ship", "--message", "-m", help="Commit message"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirm"),
    no_push: bool = typer.Option(False, "--no-push", help="Do not push"),
):
    """Alias for ship with defaults — fastest toil killer."""
    # delegate to ship_cmd via typer context would be messy, so duplicate logic via direct call
    # We'll just call ship logic inline by invoking underlying function
    # Using same parameters, but allow default message
    ship_cmd(path=path, message=message, yes=yes, no_push=no_push, run_tests=True, add_all=True)

def register(root):
    root.add_typer(app, name="dev_loop")

# TODO: review toil PR https://github.com/jcdavis131/dottie/pull/6 — 41.9/week dev_loop plugin review (scout todos verification)
