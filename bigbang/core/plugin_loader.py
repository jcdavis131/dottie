"""Auto plugin discovery with manifest + capability awareness"""
from pathlib import Path
import importlib
import typer
import yaml

def _load_manifest(pkg_path: Path):
    mf = pkg_path / "manifest.yaml"
    if mf.exists():
        try:
            return yaml.safe_load(mf.read_text()) or {}
        except Exception:
            return {}
    return {}

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
            # attach manifest if present
            manifest = _load_manifest(pkg_path)
            if hasattr(module, "app") and isinstance(getattr(module, "app"), typer.Typer):
                sub_app = getattr(module, "app")
                # store manifest on app for policy checks
                sub_app._bb_manifest = manifest
                app.add_typer(sub_app, name=pkg_path.name)
            elif hasattr(module, "register"):
                getattr(module, "register")(app)
        except ModuleNotFoundError:
            try:
                full_mod2 = f"bigbang.plugins.{pkg_path.name}"
                module = importlib.import_module(full_mod2)
                if hasattr(module, "app"):
                    app.add_typer(getattr(module, "app"), name=pkg_path.name)
                elif hasattr(module, "register"):
                    getattr(module, "register")(app)
            except Exception as e:
                # fail silent but log
                pass
        except Exception as e:
            # allow other plugins to load
            pass

def list_plugin_names():
    plugins_pkg = Path(__file__).parent.parent / "plugins"
    return [p.name for p in plugins_pkg.iterdir() if p.is_dir() and not p.name.startswith("__") and not p.name.startswith(".")]

def get_all_manifests():
    plugins_pkg = Path(__file__).parent.parent / "plugins"
    out = {}
    for p in plugins_pkg.iterdir():
        if not p.is_dir() or p.name.startswith("__"):
            continue
        mf = p / "manifest.yaml"
        if mf.exists():
            try:
                import yaml
                out[p.name] = yaml.safe_load(mf.read_text())
            except Exception:
                out[p.name] = {}
        else:
            out[p.name] = {}
    return out
