"""Foundation plugin contract — clean, extensible, agent-teachable.

New Scout surfaces should:
- build apps with `make_plugin_app`
- emit success via `ok(...)` and failures via `fail_agent` / `err(...)`
- declare capabilities in manifest.yaml (default deny)
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import typer

from bigbang.core.cli_ux import examples_epilog


def ok(
    data: Any = None,
    *,
    command: str,
    example: Optional[str] = None,
    discover: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Standard success envelope for new/migrating commands."""
    payload: Dict[str, Any] = {"ok": True, "command": command}
    if data is not None:
        payload["data"] = data
    if example:
        payload["example"] = example
    if discover:
        payload["discover"] = discover
    payload.update(extra)
    return payload


def err(
    error: str,
    *,
    command: str,
    example: Optional[str] = None,
    discover: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Standard error envelope (pair with typer.Exit(1) or fail_agent)."""
    payload: Dict[str, Any] = {"ok": False, "command": command, "error": error}
    if example:
        payload["example"] = example
    if discover:
        payload["discover"] = discover
    payload.update(extra)
    return payload


def make_plugin_app(
    name: str,
    help_text: str,
    *,
    examples: Optional[Sequence[str]] = None,
    no_args_is_help: bool = True,
) -> typer.Typer:
    """Create a Typer sub-app with foundation defaults (layered help + Examples)."""
    kwargs: Dict[str, Any] = {
        "name": name,
        "help": help_text,
        "no_args_is_help": no_args_is_help,
    }
    if examples:
        kwargs["epilog"] = examples_epilog(examples)
    return typer.Typer(**kwargs)
