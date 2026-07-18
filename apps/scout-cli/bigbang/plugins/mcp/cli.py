"""
Real MCP SDK client implementation — bigbang/plugins/mcp/cli.py
Uses mcp Python SDK 1.28.1 with SSE -> streamable HTTP fallback.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import typer

from bigbang.core.output import emit
from bigbang.core.plugin_loader import list_plugin_names
from bigbang.core.registry import register_tool, list_tools
from bigbang.core.policy import enforce_user_url_or_raise
from bigbang.core.http_utils import sanitize_no_proxy_env
sanitize_no_proxy_env()

try:
    from bigbang.core.mcp_client import list_mcp_tools_sync, call_mcp_tool_sync
    _CORE_CLIENT = True
    def _check_sdk():
        return True
except ImportError:
    list_mcp_tools_sync = None  # type: ignore
    call_mcp_tool_sync = None  # type: ignore
    _CORE_CLIENT = False
    def _check_sdk():  # type: ignore
        raise RuntimeError("mcp SDK not installed. pip install mcp")

app = typer.Typer(name="mcp", help="🌐 MCP — client for any MCP server + serve bb as MCP", no_args_is_help=True)

MCP_REG = Path.home() / ".local" / "share" / "bigbang" / "mcp_servers.json"
MCP_REG.parent.mkdir(parents=True, exist_ok=True)

def _load_mcp() -> Dict[str, Any]:
    if MCP_REG.exists():
        try:
            return json.loads(MCP_REG.read_text())
        except Exception:
            return {}
    return {}

def _save_mcp(d: Dict[str, Any]) -> None:
    MCP_REG.write_text(json.dumps(d, indent=2))

@app.command("manifest")
def manifest():
    plugins = list_plugin_names()
    tools = []
    for n in plugins:
        tools.append({"name": f"bb_{n}", "description": f"BigBang {n} plugin", "type": "bb_internal"})
    external = list_tools()
    for name, m in external.items():
        if m.get("type") == "mcp":
            tools.append({"name": name, "description": m.get("description","external mcp"), "url": m.get("url")})
    data = {"name": "bigbang-cli", "version": "0.4.0", "description": "One CLI to rule all tools — agents/tools/services, security first, Ava-native", "tools": tools, "security": "vault 0600, policy caps, audit"}
    emit(data, command="mcp manifest")

@app.command("serve")
def serve(
    sse: bool = typer.Option(False, "--sse", help="Serve over SSE/HTTP instead of stdio"),
    port: int = typer.Option(8787, "--port", help="Port for --sse transport"),
):
    """Serve scout-cli plugins as a real MCP server (stdio by default)."""
    try:
        from bigbang.plugins.mcp.server import run_server
    except ImportError as e:
        emit({"error": f"mcp SDK not installed ({e}). Run: pip install 'mcp>=1.28.1'"},
             command="mcp serve")
        raise typer.Exit(1)
    # Blocks until the client disconnects (stdio) or the process is stopped (sse).
    run_server(transport="sse" if sse else "stdio", port=port)

@app.command("add")
def add_server(name: str = typer.Argument(..., help="name for MCP server"), url: str = typer.Argument(..., help="sse url")):
    # Real check against the persisted user allowlist (default-deny), not a
    # manifest constructed to allow the exact URL being checked.
    enforce_user_url_or_raise(url, context="mcp add")
    db = _load_mcp()
    db[name] = {"url": url, "type": "mcp", "added": True}
    _save_mcp(db)
    register_tool(name, {"type": "mcp", "url": url, "description": f"MCP server {name}", "tags": ["mcp","external"], "capabilities": {"network": {"enabled": True, "domains": [url]}}})
    emit({"added": name, "url": url, "registry": str(MCP_REG), "next": f"bb mcp list-tools {name}"}, command="mcp add")

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
        emit({"server": server, "url": url, "tools": tools, "count": len(tools)}, command="mcp list-tools")
    except Exception as e:
        emit({"server": server, "url": url, "error": str(e), "hint": "Is the MCP server running? Try curl <url>"}, command="mcp list-tools")

@app.command("call")
def call_tool(server: str = typer.Argument(...), tool: str = typer.Argument(...), args: str = typer.Option("{}", help="json args")):
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
        emit({"server": server, "tool": tool, "args": parsed, "result": result}, command="mcp call")
    except Exception as e:
        emit({"server": server, "tool": tool, "args": parsed, "error": str(e)}, command="mcp call")

def register(root): root.add_typer(app, name="mcp")

# Solo personal project, no connection to employer, built with public/free-tier only
