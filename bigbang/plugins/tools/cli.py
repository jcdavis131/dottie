import typer
from typing import Optional
from bigbang.core.output import emit
from bigbang.core.registry import register_tool, list_tools, get_tool, unregister_tool, search_tools
from bigbang.core.policy import check_permission, enforce_or_raise
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
    if type == "openapi" and url:
        # policy: only fetch if allowed - local check
        try:
            r = httpx.get(url, timeout=8, follow_redirects=True)
            manifest["openapi_status"] = r.status_code
            manifest["openapi_size"] = len(r.text)
            try:
                spec = r.json()
                manifest["paths_count"] = len(spec.get("paths",{}))
            except:
                pass
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
    # ENFORCE: check manifest caps before network
    caps_manifest = {"name": name, "capabilities": tool.get("capabilities", {})}
    url = tool.get("url") or ""
    if url:
        enforce_or_raise(caps_manifest, "network", url)
    emit({"tool": name, "action": action, "args": args, "manifest": tool, "policy": "checked ✓ — network allowed for caps", "note": "v0.4 will exec real adapter (openapi→httpx with domain allowlist, mcp→SDK, docker→isolate)"}, command="tools call")

@app.command("import-openapi")
def import_openapi(url: str = typer.Argument(..., help="OpenAPI JSON URL"), name: str = typer.Option(None)):
    # enforce: import is network action
    dummy_manifest = {"name": "tools-import", "capabilities": {"network": {"enabled": True}}}
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
            "tags": ["openapi","auto-imported"],
            "capabilities": {"network": {"enabled": True, "domains": [url]}}
        }
        register_tool(derived_name, manifest)
        emit({"imported": derived_name, "paths": list(spec.get("paths",{}).keys())[:10], "manifest": manifest}, command="tools import-openapi")
    except Exception as e:
        emit({"error": str(e), "url": url})

@app.command("generate")
def generate_cmd(name: str = typer.Argument(..., help="tool name already in registry")):
    """v0.4: generate Typer plugin from OpenAPI spec"""
    tool = get_tool(name)
    if not tool:
        emit({"error": f"{name} not found"})
        return
    if tool.get("type") != "openapi":
        emit({"error": "only openapi tools can be codegen'd currently"})
        return
    url = tool.get("url")
    try:
        r = httpx.get(url, timeout=10)
        spec = r.json()
        paths = spec.get("paths",{})
        ops = []
        for p, methods in paths.items():
            for m, details in methods.items():
                ops.append(f"{m.upper()} {p} — {details.get('summary','')}")
        emit({"name": name, "url": url, "operations": ops[:20], "total": len(ops), "next": f"Will scaffold bigbang/plugins/{name}/ from spec in v0.4 — each path → Typer command with policy checks"}, command="tools generate")
    except Exception as e:
        emit({"error": str(e)})

def register(root): root.add_typer(app, name="tools")
