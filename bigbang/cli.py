"""
BigBang CLI - main entry
`bb` and `bigbang` both point here via pyproject.toml scripts
"""
import sys
from pathlib import Path

import typer
from rich.console import Console

from bigbang.core.plugin_loader import discover_plugins
from bigbang.core.output import set_json_mode

# Root app
app = typer.Typer(
    name="bb",
    help="BigBang CLI — personal control plane. Local-first, agent-native, continuously growing.",
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
