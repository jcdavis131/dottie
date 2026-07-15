"""Auto plugin discovery"""
from pathlib import Path
import importlib
import typer

def discover_plugins(app: typer.Typer):
    plugins_pkg = Path(__file__).parent.parent / "plugins"
    for pkg_path in plugins_pkg.iterdir():
        if not pkg_path.is_dir():
            continue
        if pkg_path.name.startswith("__") or pkg_path.name.startswith("."):
            continue
        try:
            full_mod = f"bigbang.plugins.{pkg_path.name}.cli"
            module = importlib.import_module(full_mod)
            if hasattr(module, "app") and isinstance(getattr(module, "app"), typer.Typer):
                sub_app = getattr(module, "app")
                app.add_typer(sub_app, name=pkg_path.name)
            elif hasattr(module, "register"):
                getattr(module, "register")(app)
        except ModuleNotFoundError:
            # try __init__
            try:
                full_mod2 = f"bigbang.plugins.{pkg_path.name}"
                module = importlib.import_module(full_mod2)
                if hasattr(module, "app"):
                    app.add_typer(getattr(module, "app"), name=pkg_path.name)
                elif hasattr(module, "register"):
                    getattr(module, "register")(app)
            except Exception:
                pass
        except Exception:
            pass

def list_plugin_names():
    plugins_pkg = Path(__file__).parent.parent / "plugins"
    return [p.name for p in plugins_pkg.iterdir() if p.is_dir() and not p.name.startswith("__") and not p.name.startswith(".")]
