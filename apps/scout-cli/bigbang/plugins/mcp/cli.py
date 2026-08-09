"""
Real MCP SDK client implementation — bigbang/plugins/mcp/cli.py
Uses mcp Python SDK 1.28.1 with SSE -> streamable HTTP fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from bigbang.core.http_utils import sanitize_no_proxy_env
from bigbang.core.output import emit
from bigbang.core.plugin_loader import list_plugin_names
from bigbang.core.policy import enforce_user_url_or_raise
from bigbang.core.registry import list_tools, register_tool

sanitize_no_proxy_env()

try:
    from bigbang.core.mcp_client import call_mcp_tool_sync, list_mcp_tools_sync

    _CORE_CLIENT = True

    def _check_sdk():
        return True
except ImportError:
    list_mcp_tools_sync = None  # type: ignore
    call_mcp_tool_sync = None  # type: ignore
    _CORE_CLIENT = False

    def _check_sdk():  # type: ignore
        raise RuntimeError("mcp SDK not installed. pip install mcp")


app = typer.Typer(
    name="mcp",
    help="🌐 MCP — client for any MCP server + serve bb as MCP",
    no_args_is_help=True,
)

MCP_REG = Path.home() / ".local" / "share" / "bigbang" / "mcp_servers.json"
MCP_REG.parent.mkdir(parents=True, exist_ok=True)


def _load_mcp() -> dict[str, Any]:
    if MCP_REG.exists():
        try:
            return json.loads(MCP_REG.read_text())
        except Exception:
            return {}
    return {}


def _save_mcp(d: dict[str, Any]) -> None:
    MCP_REG.write_text(json.dumps(d, indent=2))


@app.command("manifest")
def manifest():
    plugins = list_plugin_names()
    tools = []
    for n in plugins:
        tools.append(
            {
                "name": f"bb_{n}",
                "description": f"BigBang {n} plugin",
                "type": "bb_internal",
            }
        )
    external = list_tools()
    for name, m in external.items():
        if m.get("type") == "mcp":
            tools.append(
                {
                    "name": name,
                    "description": m.get("description", "external mcp"),
                    "url": m.get("url"),
                }
            )
    data = {
        "name": "bigbang-cli",
        "version": "0.4.0",
        "description": "One CLI to rule all tools — agents/tools/services, security first, Ava-native",
        "tools": tools,
        "security": "vault 0600, policy caps, audit",
    }
    emit(data, command="mcp manifest")


@app.command("serve")
def serve(
    sse: bool = typer.Option(
        False, "--sse", help="Serve over SSE/HTTP instead of stdio"
    ),
    port: int = typer.Option(8787, "--port", help="Port for --sse transport"),
    namespace: str = typer.Option(
        "",
        "--namespace",
        help="Meta mode: also proxy this namespace's downstream MCP tools "
        "as <server>__<tool> (scout mcp ns list)",
    ),
):
    """Serve scout-cli plugins as a real MCP server (stdio by default)."""
    try:
        from bigbang.plugins.mcp.server import run_server
    except ImportError as e:
        emit(
            {"error": f"mcp SDK not installed ({e}). Run: pip install 'mcp>=1.28.1'"},
            command="mcp serve",
        )
        raise typer.Exit(1) from e
    # Blocks until the client disconnects (stdio) or the process is stopped (sse).
    run_server(
        transport="sse" if sse else "stdio", port=port, namespace=namespace or None
    )


@app.command("add")
def add_server(
    name: str = typer.Argument(..., help="name for MCP server"),
    url: str = typer.Argument(..., help="sse url"),
):
    # Real check against the persisted user allowlist (default-deny), not a
    # manifest constructed to allow the exact URL being checked.
    enforce_user_url_or_raise(url, context="mcp add")
    db = _load_mcp()
    db[name] = {"url": url, "type": "mcp", "added": True}
    _save_mcp(db)
    register_tool(
        name,
        {
            "type": "mcp",
            "url": url,
            "description": f"MCP server {name}",
            "tags": ["mcp", "external"],
            "capabilities": {"network": {"enabled": True, "domains": [url]}},
        },
    )
    emit(
        {
            "added": name,
            "url": url,
            "registry": str(MCP_REG),
            "next": f"bb mcp list-tools {name}",
        },
        command="mcp add",
    )


@app.command("list")
def list_servers():
    db = _load_mcp()
    emit({"mcp_servers": db, "count": len(db)}, command="mcp list")


@app.command("list-tools")
def list_tools_cmd(server: str = typer.Argument(..., help="server name")):
    db = _load_mcp()
    if server not in db:
        emit({"error": f"{server} not found. bb mcp add {server} <url>"})
        return
    url = db[server]["url"]
    enforce_user_url_or_raise(url, context="mcp list-tools")
    sanitize_no_proxy_env()
    try:
        _check_sdk()
        tools = list_mcp_tools_sync(url) if _CORE_CLIENT else []
        emit(
            {"server": server, "url": url, "tools": tools, "count": len(tools)},
            command="mcp list-tools",
        )
    except Exception as e:
        emit(
            {
                "server": server,
                "url": url,
                "error": str(e),
                "hint": "Is the MCP server running? Try curl <url>",
            },
            command="mcp list-tools",
        )


@app.command("call")
def call_tool(
    server: str = typer.Argument(...),
    tool: str = typer.Argument(...),
    args: str = typer.Option("{}", help="json args"),
):
    db = _load_mcp()
    if server not in db:
        emit({"error": f"{server} not found"})
        return
    url = db[server]["url"]
    enforce_user_url_or_raise(url, context="mcp call")
    try:
        parsed = json.loads(args)
    except Exception:
        parsed = {}
    sanitize_no_proxy_env()
    try:
        _check_sdk()
        result = call_mcp_tool_sync(url, tool, parsed) if _CORE_CLIENT else {}
        emit(
            {"server": server, "tool": tool, "args": parsed, "result": result},
            command="mcp call",
        )
    except Exception as e:
        emit(
            {"server": server, "tool": tool, "args": parsed, "error": str(e)},
            command="mcp call",
        )


# ---------------------------------------------------------------------------
# Meta-MCP namespaces — group registered servers, filter tools, serve unified.
# ---------------------------------------------------------------------------

ns_app = typer.Typer(
    name="ns",
    help="🗂  Meta-MCP namespaces — group servers, enable/disable tools, "
    "then `scout mcp serve --namespace <ns>`",
    no_args_is_help=True,
)
app.add_typer(ns_app, name="ns")


def _ns_or_exit(db: dict, name: str) -> dict:
    if name not in db:
        emit({"error": f"namespace {name!r} not found", "have": sorted(db)})
        raise typer.Exit(1)
    return db[name]


@ns_app.command("create")
def ns_create(name: str = typer.Argument(..., help="namespace name")):
    from bigbang.plugins.mcp import meta

    if not meta.valid_name(name):
        emit({"error": f"invalid namespace name {name!r} (alnum/_/-, no '__')"})
        raise typer.Exit(1)
    db = meta.load_namespaces()
    if name in db:
        emit({"error": f"namespace {name!r} already exists"})
        raise typer.Exit(1)
    db[name] = meta.new_namespace()
    meta.save_namespaces(db)
    emit(
        {"created": name, "next": f"scout mcp ns add-server {name} <server>"},
        command="mcp ns create",
    )


@ns_app.command("list")
def ns_list():
    from bigbang.plugins.mcp import meta

    db = meta.load_namespaces()
    emit({"namespaces": db, "count": len(db)}, command="mcp ns list")


@ns_app.command("delete")
def ns_delete(name: str = typer.Argument(...)):
    from bigbang.plugins.mcp import meta

    db = meta.load_namespaces()
    _ns_or_exit(db, name)
    del db[name]
    meta.save_namespaces(db)
    emit({"deleted": name}, command="mcp ns delete")


@ns_app.command("add-server")
def ns_add_server(
    name: str = typer.Argument(..., help="namespace"),
    server: str = typer.Argument(..., help="registered server (scout mcp list)"),
):
    from bigbang.plugins.mcp import meta

    db = meta.load_namespaces()
    cfg = _ns_or_exit(db, name)
    if not meta.valid_name(server):
        emit({"error": f"invalid server name {server!r} (alnum/_/-, no '__')"})
        raise typer.Exit(1)
    if server not in meta.load_servers():
        emit({"error": f"{server!r} not registered — scout mcp add {server} <url>"})
        raise typer.Exit(1)
    if server in cfg["servers"]:
        emit({"error": f"{server!r} already in namespace {name!r}"})
        raise typer.Exit(1)
    cfg["servers"].append(server)
    meta.save_namespaces(db)
    emit(
        {"namespace": name, "added": server, "servers": cfg["servers"]},
        command="mcp ns add-server",
    )


@ns_app.command("remove-server")
def ns_remove_server(
    name: str = typer.Argument(...), server: str = typer.Argument(...)
):
    from bigbang.plugins.mcp import meta

    db = meta.load_namespaces()
    cfg = _ns_or_exit(db, name)
    if server not in cfg["servers"]:
        emit({"error": f"{server!r} not in namespace {name!r}"})
        raise typer.Exit(1)
    cfg["servers"].remove(server)
    meta.save_namespaces(db)
    emit(
        {"namespace": name, "removed": server, "servers": cfg["servers"]},
        command="mcp ns remove-server",
    )


@ns_app.command("disable-tool")
def ns_disable_tool(
    name: str = typer.Argument(..., help="namespace"),
    qualified: str = typer.Argument(..., help="<server>__<tool>"),
):
    from bigbang.plugins.mcp import meta

    db = meta.load_namespaces()
    cfg = _ns_or_exit(db, name)
    if meta.split_qualified(qualified) is None:
        emit({"error": f"{qualified!r} is not <server>{meta.SEP}<tool>"})
        raise typer.Exit(1)
    if qualified in cfg["disabled_tools"]:
        emit({"error": f"{qualified!r} already disabled in {name!r}"})
        raise typer.Exit(1)
    cfg["disabled_tools"].append(qualified)
    meta.save_namespaces(db)
    emit(
        {"namespace": name, "disabled": qualified,
         "disabled_tools": cfg["disabled_tools"]},
        command="mcp ns disable-tool",
    )


@ns_app.command("enable-tool")
def ns_enable_tool(
    name: str = typer.Argument(...), qualified: str = typer.Argument(...)
):
    from bigbang.plugins.mcp import meta

    db = meta.load_namespaces()
    cfg = _ns_or_exit(db, name)
    if qualified not in cfg["disabled_tools"]:
        emit({"error": f"{qualified!r} is not disabled in {name!r}"})
        raise typer.Exit(1)
    cfg["disabled_tools"].remove(qualified)
    meta.save_namespaces(db)
    emit(
        {"namespace": name, "enabled": qualified,
         "disabled_tools": cfg["disabled_tools"]},
        command="mcp ns enable-tool",
    )


@ns_app.command("tools")
def ns_tools(name: str = typer.Argument(..., help="namespace")):
    """Live-aggregate tools across the namespace's servers (with enabled flags)."""
    from bigbang.core.policy import check_user_url
    from bigbang.plugins.mcp import meta

    db = meta.load_namespaces()
    cfg = _ns_or_exit(db, name)
    _check_sdk()
    agg = meta.aggregate_tools(
        cfg, meta.load_servers(), list_mcp_tools_sync, check_user_url
    )
    emit(
        {
            "namespace": name,
            "tools": agg["tools"],
            "count": len(agg["tools"]),
            "errors": agg["errors"],
        },
        command="mcp ns tools",
    )


@ns_app.command("call")
def ns_call(
    name: str = typer.Argument(..., help="namespace"),
    qualified: str = typer.Argument(..., help="<server>__<tool>"),
    args: str = typer.Option("{}", help="json args"),
):
    """Call a namespaced downstream tool, honoring per-namespace disables."""
    from bigbang.plugins.mcp import meta

    db = meta.load_namespaces()
    cfg = _ns_or_exit(db, name)
    parts = meta.split_qualified(qualified)
    if parts is None:
        emit({"error": f"{qualified!r} is not <server>{meta.SEP}<tool>"})
        raise typer.Exit(1)
    server, tool = parts
    if server not in cfg["servers"]:
        emit({"error": f"{server!r} not in namespace {name!r}"})
        raise typer.Exit(1)
    if not meta.tool_enabled(cfg, qualified):
        emit({"error": f"{qualified!r} is disabled in {name!r} — "
              f"scout mcp ns enable-tool {name} {qualified}"})
        raise typer.Exit(1)
    entry = meta.load_servers().get(server)
    if not entry or not entry.get("url"):
        emit({"error": f"{server!r} not registered — scout mcp add {server} <url>"})
        raise typer.Exit(1)
    url = entry["url"]
    enforce_user_url_or_raise(url, context="mcp ns call")
    try:
        parsed = json.loads(args) if args.strip() else {}
    except json.JSONDecodeError as e:
        emit({"error": f"args is not valid JSON: {e}"})
        raise typer.Exit(1) from e
    _check_sdk()
    try:
        result = call_mcp_tool_sync(url, tool, parsed)
    except Exception as e:
        emit(
            {"namespace": name, "tool": qualified, "args": parsed, "error": str(e)},
            command="mcp ns call",
        )
        return
    emit(
        {"namespace": name, "tool": qualified, "args": parsed, "result": result},
        command="mcp ns call",
    )


def register(root):
    root.add_typer(app, name="mcp")


# Solo personal project, no connection to employer, built with public/free-tier only
