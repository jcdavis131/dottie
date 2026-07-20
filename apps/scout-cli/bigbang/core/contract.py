"""Foundation plugin contract — clean, extensible, agent-teachable.

New Scout surfaces should:
- build apps with `make_plugin_app`
- emit success via `ok(...)` and failures via `fail_agent` / `err(...)`
- declare capabilities in manifest.yaml (default deny)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

from bigbang.core.cli_ux import examples_epilog

if TYPE_CHECKING:
    from collections.abc import Sequence


def ok(
    data: Any = None,
    *,
    command: str,
    example: str | None = None,
    discover: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Standard success envelope for new/migrating commands."""
    payload: dict[str, Any] = {"ok": True, "command": command}
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
    example: str | None = None,
    discover: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Standard error envelope (pair with typer.Exit(1) or fail_agent)."""
    payload: dict[str, Any] = {"ok": False, "command": command, "error": error}
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
    examples: Sequence[str] | None = None,
    no_args_is_help: bool = True,
) -> typer.Typer:
    """Create a Typer sub-app with foundation defaults (layered help + Examples)."""
    kwargs: dict[str, Any] = {
        "name": name,
        "help": help_text,
        "no_args_is_help": no_args_is_help,
    }
    if examples:
        kwargs["epilog"] = examples_epilog(examples)
    return typer.Typer(**kwargs)
