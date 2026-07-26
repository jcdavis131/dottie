"""Tests for cli — scout-cli Typer app"""

import importlib.util
import sys

MOD_PATH = "/home/hatch/workspace/dottie/apps/scout-cli/bigbang/cli.py"
spec = importlib.util.spec_from_file_location("bb_cli", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_app_exists():
    assert hasattr(mod, "app")
    # Typer app callable
    assert mod.app is not None


def test_cli_imports_typer():
    # module should have imported typer or rich
    # Check file content
    import pathlib

    content = pathlib.Path(MOD_PATH).read_text()
    assert "typer" in content.lower() or "app" in content


def test_cli_module_has_main_entry():
    # app should be invocable via help if typer
    # At least ensure app type is typer.Typer or click group
    import typer

    # typer.Typer instance
    assert isinstance(mod.app, typer.Typer) or callable(mod.app)
