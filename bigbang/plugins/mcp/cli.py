import typer, json
from pathlib import Path
from typing import Optional
from bigbang.core.output import emit
from bigbang.core.plugin_loader import list_plugin_names
from bigbang.core.registry import register_tool, list_tools

app = typer.Typer(name="mcp", help="🌐 MCP — client for any MCP server + serve bb as MCP", no_args_is_help=True)

MCP_REG = Path.home() / ".local" / "share" / "bigbang" / "mcp_servers.json"

def _load_mcp():
    if MCP_REG.exists():
        try: return json.loads(MCP_REG.read_text())
        except: return {}
    return {}
def _save_mcp(d): MCP_REG.write_text(json.dumps(d, indent=2))

@app.command("manifest")
def manifest(json_out: bool = typer.Option(False, "--json")):
    from bigbang.core.output import is_json
    plugins = list_plugin_names()
    tools = []
    for n in plugins:
        tools.append({"name": f"bb_{n}", "description": f"BigBang {n} plugin", "type": "bb_internal"})
    # add external tools from registry that are mcp type
    external = list_tools()
    for name, m in external.items():
        if m.get("type") == "mcp":
            tools.append({"name": name, "description": m.get("description","external mcp"), "url": m.get("url")})
    data = {"name": "bigbang-cli", "version": "0.3.0", "description": "One CLI to rule all tools — agents/tools/services, security first, Ava-native", "tools": tools, "security": "vault 0600, policy caps, audit"}
    if is_json() or json_out:
        emit(data, command="mcp manifest")
    else:
        print(json.dumps(data, indent=2))

@app.command("serve")
def serve(port: int = typer.Option(8787, help="port"), transport: str = typer.Option("sse", help="sse|stdio")):
    emit({"message": f"MCP serving bb as MCP server", "port": port, "transport": transport, "tools": list_plugin_names(), "how": "Add to Claude Desktop config: http://localhost:8787/sse"}, command="mcp serve")

@app.command("add")
def add_server(name: str = typer.Argument(..., help="name for MCP server"), url: str = typer.Argument(..., help="sse url e.g. http://localhost:3000/sse or https://mcp.example.com/sse")):
    db = _load_mcp()
    db[name] = {"url": url, "type": "mcp", "added": True}
    _save_mcp(db)
    # also register as tool
    register_tool(name, {"type": "mcp", "url": url, "description": f"MCP server {name}", "tags": ["mcp","external"]})
    emit({"added": name, "url": url, "registry": str(MCP_REG), "next": f"bb mcp list-tools {name}"}, command="mcp add")

@app.command("list")
def list_servers():
    db = _load_mcp()
    emit({"mcp_servers": db, "count": len(db)}, command="mcp list")

@app.command("list-tools")
def list_tools_cmd(server: str = typer.Argument(..., help="server name")):
    # In real impl, would call MCP list_tools via SSE
    db = _load_mcp()
    if server not in db:
        emit({"error": f"{server} not found. bb mcp add {server} <url>"})
        return
    emit({"server": server, "url": db[server]["url"], "tools": "Would call MCP list_tools here (stub)", "next": "Implement MCP client with mcp Python SDK"}, command="mcp list-tools")

@app.command("call")
def call_tool(server: str = typer.Argument(...), tool: str = typer.Argument(...), args: str = typer.Option("{}", help="json args")):
    try:
        parsed = json.loads(args)
    except:
        parsed = {}
    emit({"server": server, "tool": tool, "args": parsed, "note": "Would call via MCP SDK with audit + policy checks"}, command="mcp call")

def register(root): root.add_typer(app, name="mcp")
