import json, typer
from bigbang.core.plugin_loader import list_plugin_names
app = typer.Typer(name="mcp", help="MCP server exposing bb as tools", no_args_is_help=True)

def get_manifest():
    plugins = list_plugin_names()
    return {"name": "bigbang-cli", "version": "0.1.0", "tools": [{"name": f"bb_{n}"} for n in plugins]}

@app.command("manifest")
def manifest():
    print(json.dumps(get_manifest(), indent=2))

@app.command("serve")
def serve(port: int = typer.Option(8787)):
    print(f"MCP serving on {port} - manifest: {get_manifest()}")

def register(root):
    root.add_typer(app, name="mcp")
