"""Real MCP server exposing scout-cli plugins as MCP tools.

One tool per plugin (bb_<plugin>). Each tool dispatches
`python -m bigbang.cli --json <plugin> <args...>` in a subprocess and returns
its output, so the MCP surface stays exactly as capable (and as policy/audit
constrained) as the CLI itself.
"""
from __future__ import annotations

import shlex
import subprocess
import sys

from mcp.server.fastmcp import FastMCP

from bigbang.core.plugin_loader import list_plugin_names

_SUBPROCESS_TIMEOUT = 120


def _dispatch(plugin: str, args: str) -> str:
    argv = [sys.executable, "-m", "bigbang.cli", "--json", plugin]
    if args.strip():
        argv += shlex.split(args)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return f'{{"error": "timed out after {_SUBPROCESS_TIMEOUT}s", "argv": "{plugin} {args}"}}'
    out = proc.stdout.strip()
    if proc.returncode != 0:
        err = proc.stderr.strip()
        return out or f'{{"error": "exit {proc.returncode}", "stderr": {err!r}}}'
    return out or '{"result": "(no output)"}'


def _make_tool(plugin: str):
    def tool_fn(args: str = "") -> str:
        """Dispatch to the plugin CLI. `args` is the subcommand + flags, e.g. "list"."""
        return _dispatch(plugin, args)

    tool_fn.__name__ = f"bb_{plugin}"
    return tool_fn


def build_server(port: int = 8787) -> FastMCP:
    server = FastMCP(
        "scout-cli",
        instructions=(
            "Scout CLI plugins exposed as MCP tools. Each bb_<plugin> tool takes a "
            "single `args` string: the plugin subcommand plus flags "
            "(e.g. bb_tools with args='list'). Output is the CLI's JSON."
        ),
        port=port,
    )
    for name in sorted(list_plugin_names()):
        server.tool(
            name=f"bb_{name}",
            description=(
                f"Run the scout-cli '{name}' plugin. Pass subcommand and flags in "
                f"`args` (e.g. args='list'). Returns the command's JSON output."
            ),
        )(_make_tool(name))
    return server


def run_server(transport: str = "stdio", port: int = 8787) -> None:
    build_server(port=port).run(transport="sse" if transport == "sse" else "stdio")


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8787
    run_server(transport, port)
