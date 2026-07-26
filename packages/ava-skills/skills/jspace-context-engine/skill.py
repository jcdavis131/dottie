# Solo personal project, no connection to employer, built with public/free-tier only
"""jspace-context-engine: build the single-CLI context payload for a local model.

Two jobs, both deliberate:

1. **No native tool-calling.** The returned payload sets ``tools: []``. Local engines
   (qwen3:32b and friends) hallucinate tool schemas readily, and a model that believes it
   has fifty function slots will invent a fifty-first. One execution path is easier to
   police than a registry, so the manifest is TEXT and the only verb is `scout`.

2. **Expansion has an address.** When a capability is missing the model must not improvise
   around it — it runs `scout forge new`, which is the loop's actual self-evolution
   mechanism. `missing_tool_guidance()` returns that instruction verbatim so the same words
   reach the model whether the gap is detected here or at call time.

Subcommands are discovered live from ``scout --json forge list`` rather than hardcoded, so
a tool forged five minutes ago is in the next prompt without anyone editing this file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def describe() -> dict[str, Any]:
    """Routing metadata read from SKILL.md frontmatter — the single source of truth."""
    here = Path(__file__).resolve().parent
    try:
        from skills.loader import describe_from_manifest
    except ImportError:  # loaded standalone without the skills package on sys.path
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_ava_skills_loader", here.parent / "loader.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        describe_from_manifest = mod.describe_from_manifest
    return describe_from_manifest(here)


def _scout_bin() -> str | None:
    """Resolve the scout entry point, or None when it is not installed."""
    return shutil.which("scout")


def fetch_forged(timeout: float = 20.0) -> dict[str, Any]:
    """Live subcommand inventory via ``scout --json forge list``.

    Returns ``{"tools": [...], "source": ..., "error": ...}``. A failure here is REPORTED,
    never silently swallowed into an empty list: an empty inventory and an unreachable CLI
    produce very different prompts, and a model told "you have no tools" when the truth is
    "we could not ask" will forge duplicates of things that already exist.
    """
    scout = _scout_bin()
    if scout is None:
        return {
            "tools": [],
            "source": None,
            "error": "scout not on PATH — cannot enumerate forged subcommands",
        }
    try:
        proc = subprocess.run(
            [scout, "--json", "forge", "list"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.environ.get("DOTTIE_ROOT") or None,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"tools": [], "source": scout, "error": f"{type(e).__name__}: {e}"}
    if proc.returncode != 0:
        return {
            "tools": [],
            "source": scout,
            "error": f"scout forge list exited {proc.returncode}: {proc.stderr[-300:]}",
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return {
            "tools": [],
            "source": scout,
            "error": f"unparseable JSON from scout forge list: {e}",
        }

    # Verified against the live CLI 2026-07-20: the envelope is
    #   {"ok": true, "command": "forge list", "data": {"plugins": [{name, forged_by, ...}]}}
    # An earlier guess at this ({"tools": [...]}) matched nothing, and the explicit
    # "unrecognised payload shape" error is what surfaced that — returning [] would have
    # reported an empty toolbox as fact. Keep the fallbacks for older/other shapes.
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("plugins"), list):
            return {"tools": data["plugins"], "source": scout, "error": None}
        for key in ("tools", "forged", "result", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return {"tools": val, "source": scout, "error": None}
        if isinstance(data, list):
            return {"tools": data, "source": scout, "error": None}
    if isinstance(payload, list):
        return {"tools": payload, "source": scout, "error": None}
    keys = list(payload)[:6] if isinstance(payload, dict) else type(payload).__name__
    return {
        "tools": [],
        "source": scout,
        "error": f"unrecognised payload shape: keys={keys}",
    }


def _tool_names(tools: list[Any]) -> list[str]:
    names: list[str] = []
    for t in tools:
        if isinstance(t, str):
            names.append(t)
        elif isinstance(t, dict):
            n = t.get("name") or t.get("command") or t.get("tool")
            if n:
                names.append(str(n))
    return names


def missing_tool_guidance(want: str) -> str:
    """The exact words handed to the model when a capability does not exist yet."""
    return (
        f"No `scout` subcommand provides '{want}'.\n"
        f"Do NOT approximate it with shell commands and do NOT invent a function call.\n"
        f"Create it, then use it:\n"
        f"    scout forge new {want} --description '<what it does>'\n"
        f"    scout --json forge list          # confirm it registered\n"
        f"    scout {want} --help              # then call it\n"
        f"Forging is the only sanctioned way to gain a capability."
    )


def build_manifest(tools: list[Any], error: str | None = None) -> str:
    """The structural text manifest injected as the system prompt."""
    names = _tool_names(tools)
    lines = [
        "# EXECUTION ENVIRONMENT",
        "",
        "You have exactly ONE way to affect the world: the `scout` CLI.",
        "There is no function-calling interface. There are no tool objects. If you emit a",
        "JSON tool call, nothing runs. Emit a shell command that begins with `scout`.",
        "",
        "Rules:",
        "  1. Every action is `scout <subcommand> [args]`.",
        "  2. Add `--json` for machine-readable output: `scout --json <sub> <cmd>`.",
        "  3. Discover before guessing: `scout --help`, then `scout <sub> --help`.",
        "  4. If no subcommand does what you need, FORGE one (see EXPANSION below).",
        "     Do not substitute raw shell, curl or python for a missing subcommand.",
        "",
        "# AVAILABLE SUBCOMMANDS",
    ]
    if error:
        lines += [
            f"  UNKNOWN — could not enumerate: {error}",
            "  Treat this as 'inventory unavailable', NOT as 'no tools exist'.",
            "  Run `scout --json forge list` yourself before forging anything, or you will",
            "  create a duplicate of something that already works.",
        ]
    elif names:
        lines += [f"  - scout {n}" for n in sorted(names)]
    else:
        lines += [
            "  (none forged yet — the base subcommands from `scout --help` still apply)"
        ]
    lines += [
        "",
        "# EXPANSION (the only self-evolution path)",
        "",
        "    scout forge new <name> --description '<what it does>'",
        "",
        "That scaffolds a real subcommand, registers it, and makes it available to the next",
        "turn. This is how the system grows a capability it lacks. Nothing else counts.",
    ]
    return "\n".join(lines)


def build_context(
    tools: list[Any] | None = None, error: str | None = None, fetch: bool = True
) -> dict[str, Any]:
    """The payload handed to a local engine: an empty tool registry plus the manifest."""
    if tools is None and fetch:
        found = fetch_forged()
        tools, error = found["tools"], found["error"]
    tools = tools or []
    return {
        # Empty ON PURPOSE. See the module docstring: the manifest is the interface.
        "tools": [],
        "system": build_manifest(tools, error),
        "forged_count": len(_tool_names(tools)),
        "inventory_error": error,
        "disclaimer": "Solo personal project, no connection to employer, "
        "built with public/free-tier only",
    }


def run(mode: str = "real", want: str | None = None, **kw) -> dict[str, Any]:
    """Skill entry point.

    ``mode="mock"`` builds the payload from a fixed inventory so the shape can be asserted
    without a live CLI. ``want=<name>`` additionally returns the forge instruction for a
    capability the inventory does not cover.
    """
    if mode == "mock":
        ctx = build_context(tools=["weather", "linear"], fetch=False)
    else:
        ctx = build_context()
    ctx["mode"] = mode
    if want:
        have = set(
            _tool_names(
                ["weather", "linear"] if mode == "mock" else fetch_forged()["tools"]
            )
        )
        ctx["requested"] = want
        ctx["available"] = want in have
        if want not in have:
            ctx["guidance"] = missing_tool_guidance(want)
    return ctx
