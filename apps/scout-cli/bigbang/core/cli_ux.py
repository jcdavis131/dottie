"""Agent-first CLI helpers — non-interactive paths, examples, actionable errors.

Follows the cli-for-agents skill: flags over prompts, layered help with
copy-pasteable Examples, fail-fast with example invocations, dry-run / force.
"""
from __future__ import annotations

import sys
from typing import Optional, Sequence

import typer

from bigbang.core.output import emit, is_json


def is_interactive() -> bool:
    """True only when both stdin and stdout are TTYs (safe to prompt)."""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def examples_epilog(lines: Sequence[str]) -> str:
    """Build a Typer/Click epilog block with an Examples section."""
    body = "\n".join(f"  {line}" if line else "" for line in lines)
    return f"\nExamples:\n{body}\n"


def fail_agent(
    error: str,
    *,
    command: str,
    example: str,
    discover: Optional[str] = None,
    code: int = 1,
) -> None:
    """Emit a structured error with a correct example invocation, then exit."""
    payload = {
        "error": error,
        "example": example,
    }
    if discover:
        payload["discover"] = discover
    emit(payload, command=command)
    raise typer.Exit(code=code)


def read_stdin_text(*, strip: bool = True) -> str:
    """Read all of stdin; raise if empty."""
    data = sys.stdin.read()
    if strip:
        data = data.strip()
    if not data:
        raise ValueError("stdin was empty")
    return data


def require_secret_value(
    *,
    positional: Optional[str],
    flag_value: Optional[str],
    use_stdin: bool,
    command: str,
    example: str,
) -> str:
    """Resolve a secret/token from flag > stdin > positional; never hang."""
    if flag_value is not None and str(flag_value).strip():
        return str(flag_value).strip()
    if use_stdin:
        try:
            return read_stdin_text()
        except ValueError:
            fail_agent(
                "No value on stdin",
                command=command,
                example=example,
                discover=f"{command.split()[0]} --help" if command else None,
            )
    if positional is not None and str(positional).strip():
        return str(positional).strip()
    # Flags/stdin/positional missing → prompt only on a TTY; never hang headless.
    if not is_interactive():
        fail_agent(
            "No value provided (non-interactive; refusing to prompt)",
            command=command,
            example=example,
        )
    try:
        typed = typer.prompt("Enter value (hidden)", hide_input=True, confirmation_prompt=False)
    except Exception:
        fail_agent("Could not read hidden prompt", command=command, example=example)
    typed = (typed or "").strip()
    if not typed:
        fail_agent("Empty value", command=command, example=example)
    return typed


def prompt_secret_or_fail(
    prompt: str,
    *,
    command: str,
    example: str,
    flag_value: Optional[str] = None,
) -> str:
    """Use --flag when set; else prompt only on a TTY; else fail with example."""
    if flag_value is not None and str(flag_value).strip():
        return str(flag_value).strip()
    if not is_interactive():
        fail_agent(
            "No token provided (non-interactive; refusing to prompt)",
            command=command,
            example=example,
        )
    try:
        token = typer.prompt(prompt, hide_input=True, confirmation_prompt=False)
    except Exception:
        fail_agent(
            "Could not read hidden prompt",
            command=command,
            example=example,
        )
    token = (token or "").strip()
    if not token:
        fail_agent("Empty token", command=command, example=example)
    return token


def human_note(msg: str) -> None:
    """Print a dim note for humans; stay silent in --json mode."""
    if is_json():
        return
    try:
        from rich.console import Console

        Console().print(f"[dim]{msg}[/dim]")
    except Exception:
        print(msg, file=sys.stderr)
