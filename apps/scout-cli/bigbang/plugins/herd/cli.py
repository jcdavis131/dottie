"""Herd plugin — Herdr-inspired agent session control surface.

Scout owns tools/MCP/Ava/policy. Herdr owns real PTY panes.
`scout herd` is the JSON ledger + wait/read/report API agents can drive.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import typer

from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.output import emit
from bigbang.plugins.herd import store

app = typer.Typer(
    name="herd",
    help=(
        "🐑 Herd — agent session control surface (Herdr-inspired). "
        "Track working/blocked/done; wait + read logs. Not a PTY multiplexer."
    ),
    no_args_is_help=True,
    epilog=examples_epilog(
        [
            "scout herd status",
            "scout herd create --label api --cwd ~/project",
            'scout herd start api --cmd "pytest -q"',
            "scout --json herd wait api --status done --timeout 120",
            "scout herd read api --lines 40",
            "scout herd report api --status blocked --note need secrets",
            "scout herd herdr   # detect Herdr binary / pairing notes",
        ]
    ),
)


def _emit_err(exc: Exception, *, command: str, example: str) -> None:
    fail_agent(str(exc), command=command, example=example, discover="scout herd status")


@app.command(
    "status",
    epilog=examples_epilog(["scout --json herd status", "scout herd list"]),
)
def status_cmd():
    """Glanceable herd summary — counts by idle/working/blocked/done/failed."""
    payload = store.summary()
    payload["herdr"] = store.herdr_available()
    payload["disclaimer"] = (
        "Solo personal project, no connection to employer, built with public/free-tier only"
    )
    emit(payload, command="herd status")


@app.command(
    "list",
    epilog=examples_epilog(
        ["scout --json herd list", "scout herd list --status working"]
    ),
)
def list_cmd(
    status: str | None = typer.Option(
        None, "--status", help="filter: idle|working|blocked|done|failed|unknown"
    ),
):
    """List herd sessions (refreshes process liveness)."""
    sessions = store.list_sessions(refresh=True)
    if status:
        if status not in store.STATUSES:
            fail_agent(
                f"unknown status {status}",
                command="herd list",
                example="scout herd list --status working",
            )
        sessions = [s for s in sessions if s.get("status") == status]
    emit(
        {
            "sessions": sessions,
            "count": len(sessions),
            "example": "scout herd get <id-or-label>",
        },
        command="herd list",
    )


@app.command(
    "create",
    epilog=examples_epilog(
        [
            "scout herd create --label api --cwd ~/project",
            "scout herd create --label logs",
        ]
    ),
)
def create_cmd(
    label: str = typer.Option(
        ..., "--label", "-l", help="human label e.g. api, logs, claude"
    ),
    cwd: str | None = typer.Option(
        None, "--cwd", help="working directory (default: cwd)"
    ),
    note: str = typer.Option("", "--note", help="optional note"),
):
    """Create an idle session slot (Herdr workspace-create analogue)."""
    sess = store.create_session(label=label, cwd=cwd, note=note)
    emit(
        {
            "created": sess,
            "example": f'scout herd start {sess["label"]} --cmd "pytest -q"',
            "next": f"scout herd start {sess['id']} --cmd '<command>'",
        },
        command="herd create",
    )


@app.command(
    "get",
    epilog=examples_epilog(["scout --json herd get api", "scout herd get hs_abc123"]),
)
def get_cmd(key: str = typer.Argument(..., help="session id or label")):
    """Show one session (id or label)."""
    sess = store.get_session(key, refresh=True)
    if not sess:
        fail_agent(
            f"session not found: {key}",
            command="herd get",
            example="scout herd create --label api",
            discover="scout herd list",
        )
    if sess.get("error") == "ambiguous":
        fail_agent(
            f"ambiguous label/id {key}",
            command="herd get",
            example=f"scout herd get {sess['matches'][0]}",
            discover="scout herd list",
        )
    emit({"session": sess}, command="herd get")


@app.command(
    "start",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    epilog=examples_epilog(
        [
            'scout herd start api --cmd "pytest -q"',
            "scout herd start api -- pytest -q",
            'scout herd start --label job --cmd "sleep 2"',
        ]
    ),
)
def start_cmd(
    ctx: typer.Context,
    key: str | None = typer.Argument(
        None, help="session id or label (optional if --label creates)"
    ),
    cmd: str | None = typer.Option(
        None, "--cmd", help="shell command string (shlex-split)"
    ),
    label: str | None = typer.Option(
        None, "--label", "-l", help="create+start with this label when key omitted"
    ),
    cwd: str | None = typer.Option(None, "--cwd", help="working directory override"),
):
    """Start a detached process in a herd session (logs to ~/.local/share/bigbang/herd/logs/)."""
    parts: list[str] = list(ctx.args) if ctx.args else []
    if cmd:
        parts = shlex.split(cmd)
    if not parts:
        fail_agent(
            "No command provided",
            command="herd start",
            example='scout herd start api --cmd "pytest -q"',
        )

    target = key
    if not target:
        if not label:
            fail_agent(
                "Provide session key or --label to create",
                command="herd start",
                example='scout herd start --label api --cmd "pytest -q"',
            )
        sess = store.create_session(label=label, cwd=cwd)
        target = sess["id"]

    try:
        existing = store.get_session(target, refresh=True)
        if not existing:
            sess = store.create_session(label=label or target, cwd=cwd)
            target = sess["id"]
        elif existing.get("error") == "ambiguous":
            fail_agent(
                f"ambiguous session {target}",
                command="herd start",
                example=f"scout herd start {existing['matches'][0]} --cmd '...'",
            )
        sess = store.start_session(target, parts, cwd=cwd)
    except Exception as e:
        _emit_err(
            e,
            command="herd start",
            example='scout herd start api --cmd "pytest -q"',
        )
        return
    emit(
        {
            "started": sess,
            "example": f"scout --json herd wait {sess['label']} --status done --timeout 120",
            "read": f"scout herd read {sess['id']} --lines 40",
        },
        command="herd start",
    )


@app.command(
    "report",
    epilog=examples_epilog(
        [
            "scout herd report api --status blocked --note need GITHUB_TOKEN",
            "scout herd report api --status working",
            "scout herd report api --status done",
        ]
    ),
)
def report_cmd(
    key: str = typer.Argument(..., help="session id or label"),
    status: str = typer.Option(
        ..., "--status", "-s", help="idle|working|blocked|done|failed|unknown"
    ),
    note: str | None = typer.Option(None, "--note", help="why blocked / context"),
):
    """Agent/human status report (Herdr pane.report_agent analogue)."""
    try:
        sess = store.report_status(key, status, note=note)
    except Exception as e:
        _emit_err(
            e,
            command="herd report",
            example=f"scout herd report {key} --status blocked --note '...'",
        )
        return
    emit({"reported": sess}, command="herd report")


@app.command(
    "wait",
    epilog=examples_epilog(
        [
            "scout --json herd wait api --status done --timeout 120",
            "scout herd wait api --status blocked --timeout 30",
        ]
    ),
)
def wait_cmd(
    key: str = typer.Argument(..., help="session id or label"),
    status: str = typer.Option(
        "done", "--status", "-s", help="idle|working|blocked|done|failed|unknown"
    ),
    timeout: float = typer.Option(60.0, "--timeout", help="seconds to wait"),
):
    """Block until session reaches status (Herdr wait agent-status analogue)."""
    try:
        result = store.wait_status(key, status, timeout_s=timeout)
    except Exception as e:
        _emit_err(
            e,
            command="herd wait",
            example=f"scout herd wait {key} --status done --timeout 120",
        )
        return
    emit(result, command="herd wait")
    if not result.get("matched"):
        raise typer.Exit(code=2)


@app.command(
    "read",
    epilog=examples_epilog(
        ["scout herd read api --lines 40", "scout --json herd read api --lines 20"]
    ),
)
def read_cmd(
    key: str = typer.Argument(..., help="session id or label"),
    lines: int = typer.Option(40, "--lines", "-n", help="tail N log lines"),
):
    """Tail session log (Herdr pane read analogue — file-backed, not PTY)."""
    try:
        result = store.read_log(key, lines=lines)
    except Exception as e:
        _emit_err(e, command="herd read", example=f"scout herd read {key} --lines 40")
        return
    emit(result, command="herd read")


@app.command(
    "close",
    epilog=examples_epilog(
        [
            "scout herd close api --force",
            "scout herd close api --kill --force",
            "scout herd close api --dry-run",
        ]
    ),
)
def close_cmd(
    key: str = typer.Argument(..., help="session id or label"),
    force: bool = typer.Option(False, "--force", "-f", help="required to remove"),
    kill: bool = typer.Option(False, "--kill", help="SIGTERM/SIGKILL if still running"),
    dry_run: bool = typer.Option(False, "--dry-run", help="preview only"),
):
    """Remove a session from the ledger (optionally kill the process)."""
    sess = store.get_session(key, refresh=True)
    if not sess:
        fail_agent(
            f"session not found: {key}",
            command="herd close",
            example="scout herd list",
            discover="scout herd status",
        )
    if sess.get("error") == "ambiguous":
        fail_agent(
            f"ambiguous session {key}",
            command="herd close",
            example=f"scout herd close {sess['matches'][0]} --force",
        )
    if dry_run:
        emit(
            {
                "would_close": sess["id"],
                "alive": sess.get("alive"),
                "kill": kill,
                "dry_run": True,
            },
            command="herd close",
        )
        return
    if not force:
        fail_agent(
            "Pass --force to close a session",
            command="herd close",
            example=f"scout herd close {sess['id']} --force",
        )
    try:
        result = store.close_session(sess["id"], force=force, kill=kill)
    except Exception as e:
        _emit_err(
            e,
            command="herd close",
            example=f"scout herd close {sess['id']} --kill --force",
        )
        return
    emit(result, command="herd close")


@app.command(
    "herdr",
    epilog=examples_epilog(
        [
            "scout --json herd herdr",
            "herdr workspace create --cwd ~/project --label api  # if installed",
        ]
    ),
)
def herdr_cmd():
    """Detect Herdr and explain how to pair it with Scout herd."""
    info = store.herdr_available()
    info["pairing"] = {
        "herdr": "PTY panes, mouse layout, remote attach, agent sidebar",
        "scout_herd": "JSON session ledger, wait/read/report, tools/MCP/Ava routing",
        "suggested_flow": [
            "herdr   # attach multiplexer",
            "scout herd create --label api --cwd ~/project",
            'scout herd start api --cmd "claude"   # or run agent inside herdr pane',
            "scout --json herd wait api --status done",
            'scout agent run "summarize herd status" --execute',
        ],
        "agent_skill": str(
            Path(__file__).resolve().parents[2] / "skills" / "scout-herd.md"
        ),
    }
    emit(info, command="herd herdr")


def register(root):
    root.add_typer(app, name="herd")
