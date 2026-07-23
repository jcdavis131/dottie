# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout glitch` — Sentry replacement, fully local (openswap #8: GlitchTip-lite).

Capture -> fingerprint-group -> sqlite -> static HTML browser, with the wire
protocol deleted: everything this box runs (scout-cli, factory daemons, the
bluehenre API, the /app console) can `glitch.install()` in-process or pipe a
crash log through `scout glitch ingest`, and the stack traces never leave the
machine. All deterministic logic (normalization, grouping, the issue store,
retention, the HTML renderer) lives in bigbang/core/glitch.py; this surface
adds only path resolution and the fs_write policy gate. There is no native
binary tier to prefer: GlitchTip's open-source release is a Django web app,
not a CLI, so `detect` reports tier=fallback as the expected steady state
(scope honesty, not degradation).

Policy: this plugin never makes an outbound call and never opens a socket —
the manifest's network axis is fully disabled, so "zero stack-trace egress"
stays falsifiable rather than a ToS promise. sentry-cli is probed and
surfaced by `detect` for awareness but never executed: its whole job is
uploading events to the paid SaaS — the forbidden network tier.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from bigbang.core import glitch, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent, read_stdin_text
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

REPORT_REL = Path(".scout") / "glitch-report.html"

FALLBACK_SCOPE = (
    "pure-stdlib pipeline is the complete product for this adapter: "
    "logging.Handler + sys.excepthook + crash-log ingest capture, sha256 "
    "frame fingerprinting for issue grouping, a sqlite issue store with "
    "first/last-seen timestamps, counts and open/resolved/ignored triage "
    "(resolved reopens on regression), per-project retention, and a static "
    "HTML issue browser; tier 'fallback' is the expected steady state "
    "(GlitchTip's open-source release is a Django server — no CLI binary "
    "exists to prefer)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; self-host the "
    "GlitchTip Django app separately only if you want its web dashboard"
)

app = make_plugin_app(
    "glitch",
    "Error tracking (Sentry-class), fully local: stdlib capture + fingerprint "
    "grouping + sqlite issues + static HTML browser, zero stack-trace egress",
    examples=[
        'scout --json glitch log "backup failed" --level error --project cron',
        "scout --json glitch ingest crash.log --project trainer",
        "scout --json glitch issues --fail-on error",
        "scout --json glitch report --out .scout/glitch-report.html",
        "scout --json glitch detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only on writes
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # No CLI distribution of GlitchTip exists, so `native` stays a truthful
    # probe that reports absent; sentry-cli is surfaced as an extra but NEVER
    # executed — its whole job is uploading stack traces to the paid SaaS
    # (the forbidden network tier).
    native = openswap.probe_binary("glitchtip", probe_args=("--version",))
    extras = {
        "sentry-cli": openswap.probe_binary("sentry-cli", probe_args=("--version",))
    }
    return openswap.capability_report(
        "glitch",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_GLITCH_DB") or glitch.DB_REL)


def _open_new(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write", str(path))
    return glitch.open_store(path), path


def _open_existing(db: str | None, command: str, *, write: bool = False) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no issue store at {path} — capture something first",
            command=command,
            example='scout --json glitch log "boom" --project demo',
        )
    if write:
        enforce_or_raise(_manifest(), "fs_write", str(path))
    return glitch.open_store(path), path


@app.command("hello", epilog=examples_epilog(["scout --json glitch hello"]))
def hello():
    """Smoke check — is the glitch surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "glitch"},
            command="glitch hello",
            example='scout --json glitch log "boom" --project demo',
            discover="scout glitch detect",
        ),
        command="glitch hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json glitch detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="glitch detect",
            example='scout --json glitch log "boom" --project demo',
            discover="scout glitch issues",
        ),
        command="glitch detect",
    )


@app.command(
    "log",
    epilog=examples_epilog(
        [
            'scout --json glitch log "backup failed" --level error --project cron',
            'scout --json glitch log "step 42 slow" --template "step N slow"'
            " --level warning",
        ]
    ),
)
def log_cmd(
    message: str = typer.Argument(..., help="event message"),
    level: str = typer.Option(
        "error", "--level", help="one of " + "|".join(glitch.LEVELS)
    ),
    project: str = typer.Option(
        "default", "--project", help="project/daemon bucket issues group under"
    ),
    logger: str | None = typer.Option(
        None, "--logger", help="logical source name (part of the grouping key)"
    ),
    template: str | None = typer.Option(
        None,
        "--template",
        help="grouping key when the message embeds varying values (Sentry's "
        "unformatted-template trick, from the shell)",
    ),
    context: str | None = typer.Option(
        None, "--context", help="JSON object stored on the occurrence"
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"issue store path (default {glitch.DB_REL} or $SCOUT_GLITCH_DB)",
    ),
):
    """Record one message-level event from a shell — cron/script check-ins."""
    if level not in glitch.LEVELS:
        fail_agent(
            f"--level must be one of {'|'.join(glitch.LEVELS)}, got {level!r}",
            command="glitch log",
            example='scout --json glitch log "boom" --level error',
        )
    ctx = None
    if context:
        try:
            ctx = json.loads(context)
        except ValueError as exc:
            fail_agent(
                f"--context must be valid JSON: {exc}",
                command="glitch log",
                example='scout --json glitch log "boom" --context "{\\"step\\": 42}"',
            )
        if not isinstance(ctx, dict):
            fail_agent(
                "--context must be a JSON object",
                command="glitch log",
                example='scout --json glitch log "boom" --context "{\\"step\\": 42}"',
            )
    event = glitch.log_event(message, level=level, logger=logger, template=template)
    conn, path = _open_new(db)
    res = glitch.capture(conn, event, project=project, context=ctx)
    emit(
        ok(
            {**res, "db": str(path)},
            command="glitch log",
            example="scout --json glitch issues",
            discover="scout glitch issues",
        ),
        command="glitch log",
    )


@app.command(
    "ingest",
    epilog=examples_epilog(
        [
            "scout --json glitch ingest crash.log --project trainer",
            "docker logs trainer 2>&1 | scout --json glitch ingest --stdin"
            " --project trainer",
        ]
    ),
)
def ingest(
    file: str | None = typer.Argument(
        None, help="log/crash file to scan (omit with --stdin)"
    ),
    stdin: bool = typer.Option(
        False, "--stdin", help="read the log text from stdin instead of a file"
    ),
    project: str = typer.Option(
        "default", "--project", help="project/daemon bucket issues group under"
    ),
    db: str | None = typer.Option(None, "--db", help="issue store path"),
):
    """Parse the LAST traceback out of a crash log and record it. No network."""
    example = "scout --json glitch ingest crash.log --project trainer"
    if stdin == bool(file):
        fail_agent(
            "pass exactly one input: a file argument OR --stdin",
            command="glitch ingest",
            example=example,
        )
    if stdin:
        try:
            text = read_stdin_text()
        except ValueError:
            fail_agent("stdin was empty", command="glitch ingest", example=example)
    else:
        p = Path(file)
        if not p.is_file():
            fail_agent(
                f"no such file: {file}", command="glitch ingest", example=example
            )
        text = p.read_text(encoding="utf-8", errors="replace")
    event = glitch.parse_traceback_text(text)
    if event is None:
        fail_agent(
            "no complete Python traceback found in the input (a block needs "
            "frames plus a final ExcType: message line)",
            command="glitch ingest",
            example=example,
        )
    conn, path = _open_new(db)
    res = glitch.capture(
        conn, event, project=project, context={"source": "ingest", "file": file}
    )
    emit(
        ok(
            {
                **res,
                "kind": event["kind"],
                "culprit": event["culprit"],
                "db": str(path),
            },
            command="glitch ingest",
            example="scout --json glitch issues",
            discover="scout glitch issues",
        ),
        command="glitch ingest",
    )


@app.command(
    "issues",
    epilog=examples_epilog(
        [
            "scout --json glitch issues",
            "scout --json glitch issues --project trainer --fail-on error",
            "scout --json glitch issues --status all --limit 100",
        ]
    ),
)
def issues_cmd(
    project: str | None = typer.Option(None, "--project", help="filter by project"),
    status: str = typer.Option(
        "open", "--status", help="open|resolved|ignored|all (default open)"
    ),
    level: str | None = typer.Option(None, "--level", help="filter by exact level"),
    limit: int = typer.Option(50, "--limit", help="max issues returned"),
    db: str | None = typer.Option(None, "--db", help="issue store path"),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any OPEN issue maps at/above this severity "
        "(error|warning|info) — the cron/CI gate hook",
    ),
):
    """List grouped issues, newest activity first — read-only. No network."""
    if status != "all" and status not in glitch.STATUSES:
        fail_agent(
            f"--status must be one of {'|'.join(glitch.STATUSES)}|all, got {status!r}",
            command="glitch issues",
            example="scout --json glitch issues --status all",
        )
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command="glitch issues",
            example="scout --json glitch issues --fail-on error",
        )
    conn, path = _open_existing(db, "glitch issues")
    rows = glitch.list_issues(
        conn,
        project=project,
        status=None if status == "all" else status,
        level=level,
        limit=limit,
    )
    diags = glitch.to_diagnostics(rows)
    emit(
        ok(
            {
                "db": str(path),
                "issues": rows,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="glitch issues",
            example="scout --json glitch show 1",
            discover="scout glitch report",
        ),
        command="glitch issues",
    )
    if fail_on is not None:
        gate_rank = openswap.severity_rank(fail_on)
        blocking = sum(
            1 for d in diags if openswap.severity_rank(d["severity"]) <= gate_rank
        )
        if blocking:
            raise typer.Exit(code=1)


@app.command(
    "show",
    epilog=examples_epilog(
        ["scout --json glitch show 1", "scout --json glitch show 1 --limit 25"]
    ),
)
def show(
    issue_id: int = typer.Argument(..., help="issue id from `glitch issues`"),
    limit: int = typer.Option(10, "--limit", help="occurrences returned, newest first"),
    db: str | None = typer.Option(None, "--db", help="issue store path"),
):
    """One issue with its recent occurrences (traceback + context) — read-only."""
    conn, path = _open_existing(db, "glitch show")
    issue = glitch.get_issue(conn, issue_id)
    if issue is None:
        fail_agent(
            f"no issue #{issue_id} in {path}",
            command="glitch show",
            example="scout --json glitch issues",
        )
    emit(
        ok(
            {
                "db": str(path),
                "issue": issue,
                "occurrences": glitch.occurrences_of(conn, issue_id, limit=limit),
            },
            command="glitch show",
            example=f"scout --json glitch mark {issue_id} resolved",
            discover="scout glitch issues",
        ),
        command="glitch show",
    )


@app.command(
    "mark",
    epilog=examples_epilog(
        ["scout --json glitch mark 1 resolved", "scout --json glitch mark 2 ignored"]
    ),
)
def mark(
    issue_id: int = typer.Argument(..., help="issue id from `glitch issues`"),
    status: str = typer.Argument(..., help="open|resolved|ignored"),
    db: str | None = typer.Option(None, "--db", help="issue store path"),
):
    """Triage: resolved reopens on regression; ignored stays ignored."""
    if status not in glitch.STATUSES:
        fail_agent(
            f"status must be one of {'|'.join(glitch.STATUSES)}, got {status!r}",
            command="glitch mark",
            example="scout --json glitch mark 1 resolved",
        )
    conn, path = _open_existing(db, "glitch mark", write=True)
    row = glitch.set_status(conn, issue_id, status)
    if row is None:
        fail_agent(
            f"no issue #{issue_id} in {path}",
            command="glitch mark",
            example="scout --json glitch issues",
        )
    emit(
        ok(
            {"db": str(path), "issue": row},
            command="glitch mark",
            example="scout --json glitch issues",
            discover="scout glitch report",
        ),
        command="glitch mark",
    )


@app.command(
    "report",
    epilog=examples_epilog(
        [
            "scout --json glitch report",
            "scout --json glitch report --out .scout/glitch-report.html"
            " --project trainer",
        ]
    ),
)
def report(
    out: str | None = typer.Option(
        None, "--out", help=f"HTML output path (default {REPORT_REL})"
    ),
    project: str | None = typer.Option(None, "--project", help="filter by project"),
    limit: int = typer.Option(200, "--limit", help="max issues on the page"),
    db: str | None = typer.Option(None, "--db", help="issue store path"),
):
    """Generate the static HTML issue browser — the hosted dashboard, deleted."""
    conn, path = _open_existing(db, "glitch report")
    out_path = Path(out or REPORT_REL)
    enforce_or_raise(_manifest(), "fs_write", str(out_path))
    page = glitch.render_html(conn, project=project, limit=limit)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    open_issues = glitch.list_issues(
        conn, project=project, status=glitch.STATUS_OPEN, limit=limit
    )
    emit(
        ok(
            {
                "db": str(path),
                "out": str(out_path),
                "bytes": len(page),
                "open_issues": len(open_issues),
            },
            command="glitch report",
            example="scout --json glitch issues --fail-on error",
            discover="scout glitch prune",
        ),
        command="glitch report",
    )


@app.command(
    "prune",
    epilog=examples_epilog(
        [
            "scout --json glitch prune",
            "scout --json glitch prune --retention retention.json",
        ]
    ),
)
def prune_cmd(
    retention_file: str | None = typer.Option(
        None, "--retention", help="JSON per-project retention overlay "
        "(policy-as-config; false exempts a project)"
    ),
    db: str | None = typer.Option(None, "--db", help="issue store path"),
):
    """Apply per-project retention: occurrences age out, issue counters survive."""
    try:
        retention = glitch.load_retention(retention_file)
    except Exception as exc:
        fail_agent(
            f"bad retention file: {exc}",
            command="glitch prune",
            example="scout --json glitch prune --retention retention.json",
        )
    conn, path = _open_existing(db, "glitch prune", write=True)
    res = glitch.prune(conn, retention)
    emit(
        ok(
            {"db": str(path), **res, "retention": retention},
            command="glitch prune",
            example="scout --json glitch issues",
            discover="scout glitch report",
        ),
        command="glitch prune",
    )


def register(root):
    root.add_typer(app, name="glitch")
