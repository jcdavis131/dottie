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

class ScoutTyper(typer.Typer):
    """Typer app that accepts --json in any position.

    `scout --json tools list` and `scout tools list --json` both work: any
    `--json` found after a subcommand is hoisted to the front so the shared
    root callback (which owns the option) always sees it.
    """

    def __call__(self, *args, **kwargs):
        argv = sys.argv[1:]
        if "--json" in argv:
            sys.argv = [sys.argv[0], "--json"] + [a for a in argv if a != "--json"]
        return super().__call__(*args, **kwargs)


# Root app - primary name scout, not bb/meta
app = ScoutTyper(
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
