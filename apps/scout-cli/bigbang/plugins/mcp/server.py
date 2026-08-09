"""Real MCP server exposing scout-cli plugins as MCP tools.

Primary names: scout_<plugin>. Legacy aliases: bb_<plugin>.
Each tool dispatches `python -m bigbang.cli --json <plugin> <args...>` so the
MCP surface stays as capable (and as policy/audit constrained) as the CLI.

Meta mode (`namespace=`): additionally proxies the enabled tools of every
registered downstream MCP server in the namespace as `<server>__<tool>`,
MetaMCP-style. Proxied tools take a single JSON `args` string — the same
convention as the scout_* tools — rather than mirroring the downstream input
schema; the downstream schema is embedded in the tool description so callers
can still construct correct arguments. Skipped servers (policy-denied or
unreachable at startup) are reported by the meta_status tool, never silently
dropped, and each proxied CALL re-checks the URL policy at call time so a
revoked allowlist entry takes effect without a restart.
"""

from __future__ import annotations

import json
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


def _make_proxy_tool(url: str, server: str, tool: str):
    def proxy_fn(args: str = "{}") -> str:
        """Proxy to a downstream MCP tool. `args` is a JSON object string."""
        from bigbang.core.mcp_client import call_mcp_tool_sync
        from bigbang.core.policy import check_user_url

        ok, reason = check_user_url(url)
        if not ok:
            return json.dumps(
                {"ok": False, "error": f"policy denied [{url}]: {reason}"}
            )
        try:
            parsed = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"args is not valid JSON: {e}"})
        try:
            result = call_mcp_tool_sync(url, tool, parsed)
        except Exception as e:
            return json.dumps({"ok": False, "error": f"downstream call failed: {e}"})
        return json.dumps({"ok": True, "server": server, "tool": tool, "result": result},
                          default=str)

    proxy_fn.__name__ = f"{server}__{tool}"
    return proxy_fn


def _register_namespace_tools(server_obj: FastMCP, namespace: str) -> None:
    """Attach `<server>__<tool>` proxies for the namespace's enabled tools."""
    from bigbang.core.mcp_client import list_mcp_tools_sync
    from bigbang.core.policy import check_user_url
    from bigbang.plugins.mcp import meta

    ns_db = meta.load_namespaces()
    ns_cfg = ns_db.get(namespace)
    if ns_cfg is None:
        raise KeyError(
            f"namespace {namespace!r} not found — scout mcp ns create {namespace}"
        )
    agg = meta.aggregate_tools(
        ns_cfg, meta.load_servers(), list_mcp_tools_sync, check_user_url
    )
    exposed = 0
    for t in agg["tools"]:
        if not t["enabled"]:
            continue
        url = meta.load_servers()[t["server"]]["url"]
        desc = (
            f"[{namespace}] downstream '{t['tool']}' on MCP server '{t['server']}'. "
            f"{t['description']} Pass a JSON object string in `args` matching: "
            f"{json.dumps(t['inputSchema'])}"
        )
        server_obj.tool(name=t["name"], description=desc)(
            _make_proxy_tool(url, t["server"], t["tool"])
        )
        exposed += 1
    status = {
        "namespace": namespace,
        "servers": ns_cfg.get("servers", []),
        "tools_exposed": exposed,
        "tools_disabled": sum(1 for t in agg["tools"] if not t["enabled"]),
        "servers_skipped": agg["errors"],
    }

    def meta_status() -> str:
        """Report which downstream servers were aggregated or skipped."""
        return json.dumps(status)

    server_obj.tool(
        name="meta_status",
        description=(
            "Meta-MCP aggregation status: servers aggregated, tools exposed, "
            "and any servers skipped (policy-denied/unreachable) at startup."
        ),
    )(meta_status)


def build_server(port: int = 8787, namespace: str | None = None) -> FastMCP:
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
    if namespace:
        _register_namespace_tools(server, namespace)
    return server


def run_server(
    transport: str = "stdio", port: int = 8787, namespace: str | None = None
) -> None:
    build_server(port=port, namespace=namespace).run(
        transport="sse" if transport == "sse" else "stdio"
    )


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8787
    namespace_arg = sys.argv[3] if len(sys.argv) > 3 else None
    run_server(transport, port, namespace_arg)
