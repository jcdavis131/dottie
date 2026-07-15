import json, typer
from pathlib import Path
from bigbang.core.plugin_loader import list_plugin_names

app = typer.Typer(name="mcp", help="MCP server — expose bb as tools for agents", no_args_is_help=True)

@app.command("manifest")
def manifest():
    plugins = list_plugin_names()
    print(json.dumps({"name": "bigbang-cli", "version": "0.1.0", "tools": [{"name": f"bb_{n}"} for n in plugins]}, indent=2))

@app.command("serve")
def serve(port: int = typer.Option(8787, help="port")):
    plugins = list_plugin_names()
    print(f"MCP serving on :{port} - {plugins} - Solo personal project disclaimer")

def register(root):
    root.add_typer(app, name="mcp")
