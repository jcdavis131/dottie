"""tennis — a BOOKMARK, not an analysis tool.

Replaces remembering where the serve-analysis repo lives. The DINOv3 pipeline is not
implemented in this CLI and this plugin does not pretend otherwise; all it does is resolve
the repo and say whether it is present.

Because that is its ONLY job, getting the location wrong makes it useless in the one way it
can be — and it was. `TENNIS_REPO = Path.home() / "workspace" / "vector-tennis"` was
hardcoded, and on this box the repo is at ~/vector-tennis, so `scout tennis serve` reported

    "status": "bookmark — repo not present"
    "repo":   "C:\\Users\\jcdav\\workspace\\vector-tennis"

while the checkout sat one directory up. Third instance of the same shape this session,
after ava/cli.py (0c89edd, resolved to a superseded tree) and rtx/cli.py (6063da7, resolved
to a directory that did not exist): a single hardcoded location, no alternative candidate,
no override.
"""

import os
from pathlib import Path

import typer

from bigbang.core.output import emit

app = typer.Typer(
    name="tennis",
    help="Tennis serve coach (bookmark — analysis repo lives outside this CLI)",
    no_args_is_help=True,
)


def _tennis_repo() -> Path:
    """Where vector-tennis lives. SCOUT_TENNIS_REPO, then the two real layouts.

    Resolved per CALL, not bound at import: a module-level constant cannot be redirected by
    a test or by an env var set afterwards, which is the shape that bit telemetry's
    _LOGS_DIR (53c5c60) and brain's `sync --out` (2556dee).

    Both sibling layouts are checked because both are real in this estate — the vector-*
    repos sit directly under ~ on this box, while the ~/workspace/ prefix is the convention
    brain, lab, ava and rtx use. When neither exists the FIRST candidate is returned, so the
    "not present" message names the location the operator most likely wants rather than
    whichever one happened to be listed last.
    """
    env = os.environ.get("SCOUT_TENNIS_REPO")
    if env:
        return Path(env).expanduser()
    candidates = [
        Path.home() / "vector-tennis",
        Path.home() / "workspace" / "vector-tennis",
    ]
    for cand in candidates:
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return candidates[0]


@app.command("serve")
def serve(video: str = typer.Argument(None, help="video path or live")):
    repo = _tennis_repo()
    if not repo.exists():
        emit(
            {
                "status": "bookmark — repo not present",
                "repo": str(repo),
                "video": video or "live cam",
                "planned": "DINOv3-based serve analysis (not implemented in this CLI)",
                "hint": "set SCOUT_TENNIS_REPO if the checkout lives elsewhere",
            },
            command="tennis serve",
        )
        return
    emit(
        {
            "status": "repo present",
            "repo": str(repo),
            "video": video or "live cam",
            "note": "run the analysis pipeline from the tennis repo directly",
        },
        command="tennis serve",
    )


def register(root):
    root.add_typer(app, name="tennis")
