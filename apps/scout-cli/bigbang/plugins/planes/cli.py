"""Planes plugin — differentiated Scout cockpit (judgment plane, not multiplexer)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bigbang.core.cli_ux import examples_epilog
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.plugins.planes import cockpit

if TYPE_CHECKING:
    import typer

app = make_plugin_app(
    "planes",
    "🧭 Planes — Scout judgment cockpit (Trust · World · Herd · Judgment · Memory). Not a TUI multiplexer.",
    examples=[
        "scout --json planes status",
        "scout --json planes compare",
        "scout --json planes loop",
        "scout planes thesis",
    ],
    no_args_is_help=False,  # bare `scout planes` → status cockpit
)


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context):
    """Default: show five-plane status (same as `planes status`)."""
    if ctx.invoked_subcommand is None:
        status_cmd()


@app.command(
    "status",
    epilog=examples_epilog(
        [
            "scout --json planes status",
            "scout planes status",
        ]
    ),
)
def status_cmd():
    """Five-plane cockpit — what makes Scout different from Herdr."""
    data = cockpit.cockpit_status()
    emit(
        ok(
            data,
            command="planes status",
            example="scout --json planes compare",
            discover="scout skill show scout",
        ),
        command="planes status",
    )


@app.command(
    "compare",
    epilog=examples_epilog(
        [
            "scout --json planes compare",
            "scout planes compare",
        ]
    ),
)
def compare_cmd():
    """Honest matrix vs tmux / agent apps / Herdr — Scout wins on judgment, not PTYs."""
    data = cockpit.compare_matrix()
    emit(
        ok(
            data,
            command="planes compare",
            example="scout --json planes loop",
            discover="docs/DIFFERENTIATION.md",
        ),
        command="planes compare",
    )


@app.command(
    "loop",
    epilog=examples_epilog(
        [
            "scout --json planes loop",
            "scout planes loop",
        ]
    ),
)
def loop_cmd():
    """Learning flywheel health: act → audit → rft → ava → memory."""
    data = cockpit.loop_health()
    emit(
        ok(
            data,
            command="planes loop",
            example="scout --json rft export",
            discover="scout --json system audit --n 20",
        ),
        command="planes loop",
    )


@app.command(
    "thesis",
    epilog=examples_epilog(["scout --json planes thesis", "scout planes thesis"]),
)
def thesis_cmd():
    """One-liner positioning + taglines for humans and Dottie-claw."""
    emit(
        ok(
            {
                "thesis": cockpit.THESIS,
                "taglines": cockpit.TAGLINES,
                "herdr": "WHERE agents live (PTY multiplexer)",
                "scout": "HOW agents decide (judgment plane)",
                "refuse_the_trap": [
                    "Do not build a responsive TUI multiplexer",
                    "Do not market as 'tmux for AI agents'",
                    "Do not compete on SSH thin-client attach",
                ],
                "docs": "docs/DIFFERENTIATION.md",
                "teach": "scout skill teach --target dottie",
            },
            command="planes thesis",
            example="scout skill teach --target dottie",
        ),
        command="planes thesis",
    )


def register(root):
    root.add_typer(app, name="planes")
