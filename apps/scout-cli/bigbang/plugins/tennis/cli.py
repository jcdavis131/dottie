from pathlib import Path

import typer

from bigbang.core.output import emit

app = typer.Typer(
    name="tennis",
    help="Tennis serve coach (bookmark — analysis repo lives outside this CLI)",
    no_args_is_help=True,
)

TENNIS_REPO = Path.home() / "workspace" / "vector-tennis"


@app.command("serve")
def serve(video: str = typer.Argument(None, help="video path or live")):
    if not TENNIS_REPO.exists():
        emit(
            {
                "status": "bookmark — repo not present",
                "repo": str(TENNIS_REPO),
                "video": video or "live cam",
                "planned": "DINOv3-based serve analysis (not implemented in this CLI)",
            },
            command="tennis serve",
        )
        return
    emit(
        {
            "status": "repo present",
            "repo": str(TENNIS_REPO),
            "video": video or "live cam",
            "note": "run the analysis pipeline from the tennis repo directly",
        },
        command="tennis serve",
    )


def register(root):
    root.add_typer(app, name="tennis")
