import json, typer
from bigbang.core.plugin_loader import list_plugin_names
from bigbang.core.output import emit

app = typer.Typer(name="mcp", help="MCP server — expose bb as tools", no_args_is_help=True)

@app.command("manifest")
def manifest(json_out: bool = typer.Option(False, "--json")):
    from bigbang.core.output import is_json
    plugins = list_plugin_names()
    data = {"name": "bigbang-cli", "version": "0.2.0", "description": "agents/tools/services control plane", "tools": [{"name": f"bb_{n}"} for n in plugins]}
    if is_json() or json_out:
        emit(data)
    else:
        print(json.dumps(data, indent=2))

@app.command("serve")
def serve(port: int = typer.Option(8787)):
    plugins = list_plugin_names()
    emit({"message": f"MCP serving on :{port}", "tools": plugins})

def register(root):
    root.add_typer(app, name="mcp")
