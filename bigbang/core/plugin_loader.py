"""Auto plugin discovery"""
from pathlib import Path
import importlib
import pkgutil
import typer
from rich.console import Console

console = Console()

def discover_plugins(app: typer.Typer):
    plugins_pkg = Path(__file__).parent.parent / "plugins"
    # iterate subfolders
    for pkg_path in plugins_pkg.iterdir():
        if not pkg_path.is_dir():
            continue
        # look for cli.py or __init__.py that registers
        for mod_name in ["cli", "__init__"]:
            mod_file = pkg_path / f"{mod_name}.py"
            # For __init__ we handle package import
            try:
                full_mod = f"bigbang.plugins.{pkg_path.name}.{mod_name}" if mod_name != "__init__" else f"bigbang.plugins.{pkg_path.name}"
                module = importlib.import_module(full_mod)
                # If module exposes typer app as `app` or `plugin_app`
                if hasattr(module, "app") and isinstance(getattr(module, "app"), typer.Typer):
                    sub_app = getattr(module, "app")
                    app.add_typer(sub_app, name=pkg_path.name)
                    console.print(f"[dim]loaded plugin: {pkg_path.name}[/dim]", highlight=False) if False else None
                elif hasattr(module, "register"):
                    getattr(module, "register")(app)
            except Exception as e:
                # Don't fail whole CLI for one broken plugin - agent friendly
                if "--json" not in __import__("sys").argv:
                    # silent unless verbose
                    pass

def list_plugin_names():
    plugins_pkg = Path(__file__).parent.parent / "plugins"
    return [p.name for p in plugins_pkg.iterdir() if p.is_dir()]
