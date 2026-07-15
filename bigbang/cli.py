"""
Scout CLI - main entry (formerly BigBang CLI)
`scout`, `bb`, `bigbang`, `dv`, `kitty` all point here via pyproject.toml scripts
Primary command is now `scout` — distinct from any work/meta tooling
"""
import os
import sys
from pathlib import Path

import typer
from rich.console import Console

from bigbang.core.plugin_loader import discover_plugins
from bigbang.core.output import set_json_mode

# Detect which invocation name was used for nicer help
_invoked = Path(sys.argv[0]).name if sys.argv else "scout"
_prog_name = os.path.splitext(_invoked)[0] if _invoked else "scout"
if _prog_name in ("python", "python3", ""):
    _prog_name = "scout"

# Root app - primary name scout, not bb/meta
app = typer.Typer(
    name="scout",
    help="Scout CLI 🐾 — personal control plane (ex-BigBang). Local-first, agent-native, HOME-only. Ava-brained + RTX offload.",
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

@app.callback()
def main(
    json: bool = typer.Option(False, "--json", help="Output structured JSON for agents"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logs"),
):
    set_json_mode(json)

# Auto-discover plugins
discover_plugins(app)

@app.command("doctor")
def doctor_cmd():
    """Check local environment, tools, and free-tier services."""
    # import here to avoid circular
    from bigbang.plugins.system.cli import run_doctor
    run_doctor()

if __name__ == "__main__":
    app()
