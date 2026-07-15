import typer
from typing import Optional
from bigbang.core.output import emit
from bigbang.core.registry import register_tool, list_tools, get_tool, unregister_tool, search_tools
from bigbang.core.policy import check_permission
import httpx
import json

app = typer.Typer(name="tools", help="🧰 Universal tool registry — one CLI to rule all internet tools", no_args_is_help=True)

@app.command("list")
def list_cmd(tag: Optional[str] = typer.Option(None, help="filter by tag")):
    tools = list_tools()
    if tag:
        tools = {k:v for k,v in tools.items() if tag in v.get("tags",[])}
    emit({"tools": tools, "count": len(tools), "hint": "bb tools search <query> or bb mcp manifest"}, command="tools list")

@app.command("add")
def add_cmd(
    name: str = typer.Argument(..., help="tool name e.g. github, notion, stripe"),
    type: str = typer.Option("openapi", help="openapi|mcp|cli|docker|python"),
    url: Optional[str] = typer.Option(None, help="OpenAPI spec URL or MCP server URL"),
    description: str = typer.Option("", help="what it does"),
    tags: str = typer.Option("", help="comma-separated tags e.g. api,work,ai")
):
    manifest = {
        "type": type,
        "url": url,
        "description": description,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "capabilities": {
            "network": {"enabled": True, "domains": [url] if url else []},
            "filesystem": {"write": False}
        }
    }
    # If openapi, try to fetch and validate
    if type == "openapi" and url:
        try:
            r = httpx.get(url, timeout=8, follow_redirects=True)
            manifest["openapi_status"] = r.status_code
            manifest["openapi_size"] = len(r.text)
        except Exception as e:
            manifest["openapi_error"] = str(e)

    register_tool(name, manifest)
    emit({"message": f"tool {name} registered", "manifest": manifest, "next": f"bb tools call {name} --help or bb agent run 'use {name} to ...'"}, command="tools add")

@app.command("get")
def get_cmd(name: str):
    t = get_tool(name)
    if not t:
        emit({"error": f"{name} not found"})
    else:
        emit({"name": name, **t}, command="tools get")

@app.command("rm")
def rm_cmd(name: str):
    ok = unregister_tool(name)
    emit({"removed": name, "ok": ok}, command="tools rm")

@app.command("search")
def search_cmd(query: str = typer.Argument(..., help="search e.g. 'translate', 'github'")):
    results = search_tools(query)
    emit({"query": query, "results": results, "count": len(results)}, command="tools search")

@app.command("call")
def call_cmd(name: str = typer.Argument(...), action: str = typer.Argument(None, help="action"), args: str = typer.Argument(None, help="json args")):
    tool = get_tool(name)
    if not tool:
        emit({"error": f"{name} not registered. bb tools add {name}"})
        return
    # Policy check
    # For demo, allow
    emit({"tool": name, "action": action, "args": args, "manifest": tool, "note": "execution would happen here with capability checks + audit"}, command="tools call")

@app.command("import-openapi")
def import_openapi(url: str = typer.Argument(..., help="OpenAPI JSON URL"), name: str = typer.Option(None)):
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True)
        spec = r.json()
        derived_name = name or spec.get("info",{}).get("title","api").lower().replace(" ","-")
        manifest = {
            "type": "openapi",
            "url": url,
            "description": spec.get("info",{}).get("description","")[:200],
            "openapi_version": spec.get("openapi",""),
            "paths_count": len(spec.get("paths",{})),
            "tags": ["openapi","auto-imported"]
        }
        register_tool(derived_name, manifest)
        emit({"imported": derived_name, "paths": list(spec.get("paths",{}).keys())[:10], "manifest": manifest}, command="tools import-openapi")
    except Exception as e:
        emit({"error": str(e), "url": url})

def register(root): root.add_typer(app, name="tools")
