"""Real MCP server exposing scout-cli plugins as MCP tools.

Primary names: scout_<plugin>. Legacy aliases: bb_<plugin>.
Each tool dispatches `python -m bigbang.cli --json <plugin> <args...>` so the
MCP surface stays as capable (and as policy/audit constrained) as the CLI.
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
        # stdin=DEVNULL is load-bearing: without it the child inherits the MCP stdio
        # transport pipe (an overlapped Proactor pipe on Windows), and child Python
        # never finishes runtime init — measured live 2026-07-20: piped-stdio child
        # never ran; DEVNULL child completed in 0.11s. It also must never be possible
        # for the child to read MCP protocol bytes.
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return (
            f'{{"ok": false, "error": "timed out after {_SUBPROCESS_TIMEOUT}s", '
            f'"example": "scout --json {plugin} {args}"}}'
        )
    out = proc.stdout.strip()
    if proc.returncode != 0:
        err = proc.stderr.strip()
        return out or (
            f'{{"ok": false, "error": "exit {proc.returncode}", "stderr": {err!r}, '
            f'"example": "scout --json {plugin} --help"}}'
        )
    return out or '{"ok": true, "result": "(no output)"}'


def _make_tool(plugin: str):
    def tool_fn(args: str = "") -> str:
        """Dispatch to the plugin CLI. `args` is the subcommand + flags, e.g. "list"."""
        return _dispatch(plugin, args)

    tool_fn.__name__ = f"scout_{plugin}"
    tool_fn.__doc__ = (
        f"Run the scout-cli '{plugin}' plugin. Pass subcommand and flags in "
        f"`args` (e.g. args='list'). Returns JSON. Prefer scout_* over bb_*."
    )
    return tool_fn


def build_server(port: int = 8787) -> FastMCP:
    server = FastMCP(
        "scout-cli",
        instructions=(
            "Scout CLI — local-first orchestration control plane for Dottie-claw and "
            "other agents. Use scout_<plugin> tools with an `args` string "
            "(subcommand + flags). Example: scout_herd args='status'. "
            "bb_<plugin> aliases remain for compatibility. Prefer --json semantics; "
            "read error.example fields. See skill 'scout' via scout_skill args='show scout'."
        ),
        port=port,
    )
    for name in sorted(list_plugin_names()):
        fn = _make_tool(name)
        desc = (
            f"Run scout '{name}' plugin. Pass subcommand/flags in args "
            f"(e.g. args='list'). Returns JSON."
        )
        server.tool(name=f"scout_{name}", description=desc)(fn)
        # Legacy alias — same callable
        server.tool(
            name=f"bb_{name}",
            description=f"[legacy alias] {desc} Prefer scout_{name}.",
        )(_make_tool(name))
    return server


def run_server(transport: str = "stdio", port: int = 8787) -> None:
    build_server(port=port).run(transport="sse" if transport == "sse" else "stdio")


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8787
    run_server(transport, port)
