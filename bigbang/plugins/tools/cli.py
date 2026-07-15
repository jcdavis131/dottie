import typer
from typing import Optional
from bigbang.core.output import emit
from bigbang.core.registry import register_tool, list_tools, get_tool, unregister_tool, search_tools
from bigbang.core.policy import enforce_or_raise
from bigbang.core.http_utils import sanitize_no_proxy_env
sanitize_no_proxy_env()
from bigbang.core.openapi import fetch_spec, generate_typer_plugin, call_openapi, parse_operations
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
    sanitize_no_proxy_env()
    from urllib.parse import urlparse as _up
    domain_guess = ""
    if url:
        try:
            parsed = _up(url)
            domain_guess = parsed.netloc or url
        except Exception:
            domain_guess = url
    manifest = {
        "type": type,
        "url": url,
        "description": description,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "capabilities": {
            "network": {"enabled": True, "domains": [domain_guess] if domain_guess else []},
            "filesystem": {"write": False}
        }
    }
    if type == "openapi" and url:
        try:
            spec = fetch_spec(url)
            manifest["openapi_status"] = 200
            manifest["openapi_size"] = len(json.dumps(spec))
            manifest["paths_count"] = len(spec.get("paths", {}))
            if not description:
                manifest["description"] = (spec.get("info", {}).get("description") or spec.get("info", {}).get("title", ""))[:200]
        except Exception as e:
            manifest["openapi_error"] = str(e)

    register_tool(name, manifest)
    emit({"message": f"tool {name} registered", "manifest": manifest, "next": f"bb tools generate {name} or bb tools call {name} <operation>"}, command="tools add")

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
def call_cmd(name: str = typer.Argument(...), action: Optional[str] = typer.Argument(None, help="action / operationId"), args: Optional[str] = typer.Argument(None, help="json args")):
    tool = get_tool(name)
    if not tool:
        emit({"error": f"{name} not registered. bb tools add {name}"})
        return
    caps_manifest = {"name": name, "capabilities": tool.get("capabilities", {})}
    url = tool.get("url") or ""
    if url:
        enforce_or_raise(caps_manifest, "network", url)
    if tool.get("type") == "openapi" and action:
        try:
            parsed_args: dict = {}
            if args:
                try:
                    parsed_args = json.loads(args)
                    if not isinstance(parsed_args, dict):
                        parsed_args = {"value": parsed_args}
                except json.JSONDecodeError:
                    emit({"warning": f"args not valid JSON", "hint": "Use '{\"param\": \"value\"}'"})
                    parsed_args = {}
            result = call_openapi(tool, action, parsed_args)
            emit(result, command="tools call")
            return
        except Exception as e:
            emit({"tool": name, "action": action, "args": args, "manifest": tool, "policy": "checked ✓", "error": str(e), "note": "real call attempted and failed"}, command="tools call")
            return
    emit({"tool": name, "action": action, "args": args, "manifest": tool, "policy": "checked ✓ — network allowed", "note": "use bb tools generate for per-operation commands"}, command="tools call")

@app.command("import-openapi")
def import_openapi(url: str = typer.Argument(..., help="OpenAPI JSON URL"), name: Optional[str] = typer.Option(None)):
    sanitize_no_proxy_env()
    dummy_manifest = {"name": "tools-import", "capabilities": {"network": {"enabled": True}}}
    enforce_or_raise(dummy_manifest, "network", url)
    try:
        spec = fetch_spec(url)
        import re
        derived_name = name or spec.get("info",{}).get("title","api").lower().replace(" ","-")
        derived_name = re.sub(r'[^0-9A-Za-z_-]+', '-', derived_name).strip('-') or "api"
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        manifest = {
            "type": "openapi",
            "url": url,
            "description": (spec.get("info",{}).get("description","") or spec.get("info",{}).get("title",""))[:200],
            "openapi_version": spec.get("openapi",""),
            "paths_count": len(spec.get("paths",{})),
            "tags": ["openapi","auto-imported"],
            "capabilities": {"network": {"enabled": True, "domains": [domain or url]}}
        }
        register_tool(derived_name, manifest)
        emit({"imported": derived_name, "paths": list(spec.get("paths",{}).keys())[:10], "manifest": manifest}, command="tools import-openapi")
    except Exception as e:
        emit({"error": str(e), "url": url})

@app.command("generate")
def generate_cmd(name: str = typer.Argument(..., help="tool name already in registry")):
    tool = get_tool(name)
    if not tool:
        emit({"error": f"{name} not found"})
        return
    if tool.get("type") != "openapi":
        emit({"error": "only openapi tools can be codegen'd currently"})
        return
    url = tool.get("url")
    if not url:
        emit({"error": f"tool {name} has no url"})
        return
    try:
        sanitize_no_proxy_env()
        spec = fetch_spec(url)
        ops = parse_operations(spec)
        files = generate_typer_plugin(name, spec, url)
        emit({"name": name, "url": url, "generated": files, "operations": len(ops), "next": f"bb {name} --help"}, command="tools generate")
    except Exception as e:
        emit({"error": str(e), "url": url})

def register(root): root.add_typer(app, name="tools")

# Solo personal project, no connection to employer, built with public/free-tier only
