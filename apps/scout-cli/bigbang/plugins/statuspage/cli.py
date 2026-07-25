# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout statuspage` — StatusPage.io/Atlassian replacement, fully local (openswap #18).

The hosted page and the feed you pay for, both deleted: this adapter renders one
self-contained HTML file (inline CSS, zero JavaScript, zero external assets —
it works from file://) out of the ledgers that ALREADY exist on this box. It is
the first monitoring-family adapter that performs NO collection whatsoever:
there is no probe, no handshake, no socket, and the manifest disables the
network axis entirely, so "nothing on this page left the box" is architectural.

Read-only is enforced, not promised: bigbang/core/statuspage.py opens the shared
monitoring ledger with sqlite `mode=ro`, so this plugin physically cannot
INSERT, CREATE or take the write lock that uptime's probe loop holds. Every
figure on the page was recorded by uptime (#2, `checks`/`state`/`incidents`/
`events`), certmon (#9, `certs`) or heartbeat (#6, `beats` + `hb:`-namespaced
state) — read back through the read contracts those modules document.

Honesty is the product here, so this CLI deliberately breaks one family habit:
`status` and `render` do NOT fail when the ledger is missing. A status page
whose data source vanished must SAY so — that is the moment a status page
matters most — so an absent ledger renders the no-data state (overall
"no_data", no percentage anywhere, an explicit block naming the missing file)
and reports `sources.ledger.present: false` in JSON. Fabricating 100% uptime
from an empty database would be the one unforgivable bug in this adapter.
`--fail-on warning` still turns that into a nonzero exit for cron/CI.

There is no native binary tier to prefer: Atlassian Statuspage is SaaS, cState
is a Hugo theme (no CLI), and statping-ng is a server that does its own
collecting — the opposite of this design. `detect` reports tier=fallback as the
expected steady state (scope honesty, not degradation); hugo and statping are
surfaced as optional local tools and NEVER executed beyond a version probe.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import typer

from bigbang.core import openswap, statuspage
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib read-and-render is the complete product for this adapter: "
    "sqlite mode=ro reads of the shared uptime/certmon/heartbeat ledger, "
    "per-service state, windowed availability + latency percentiles, "
    "last-incident and cert-expiry rollups, staleness flags, and a "
    "self-contained html.escape'd HTML page with inline CSS and no JavaScript; "
    "tier 'fallback' is the expected steady state (Atlassian Statuspage is "
    "SaaS, cState is a Hugo theme with no CLI, and statping-ng is a collecting "
    "server — no native binary is a superset of a page that collects nothing)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib renderer is complete; hugo is an optional "
    "local static-site builder if you want to theme the page further"
)

app = make_plugin_app(
    "statuspage",
    "Publish the fleet's status (StatusPage.io-class) as one static HTML file, "
    "read-only over the shared uptime/certmon/heartbeat ledger — collects nothing",
    examples=[
        "scout --json statuspage sources",
        "scout --json statuspage status",
        "scout --json statuspage status --hours 168 --fail-on warning",
        "scout statuspage render --out public/status.html",
        "scout --json statuspage detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only when used
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # No native binary is a superset of this core: Atlassian Statuspage is SaaS,
    # cState ships as a Hugo theme (nothing to put on PATH), so `native` stays a
    # truthful probe that reports absent. hugo and statping are surfaced as
    # optional local tools; statping is NEVER executed beyond --version because
    # it is a server that would start collecting on its own.
    native = openswap.probe_binary("cstate", probe_args=("--version",))
    extras = {
        "hugo": openswap.probe_binary("hugo", probe_args=("version",)),
        "statping": openswap.probe_binary("statping", probe_args=("version",)),
    }
    return openswap.capability_report(
        "statuspage",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _ledger_path(db: str | None) -> Path:
    # the SHARED monitoring ledger (#2): same default, same env override as
    # uptime/certmon/heartbeat — one file, four adapters, no parallel store
    return Path(db or os.environ.get("SCOUT_UPTIME_DB") or statuspage.LEDGER_REL)


def _unreadable(path: Path, exc: Exception, command: str) -> None:
    """A --db that is not a sqlite ledger at all: actionable, not a traceback.

    Distinct from the missing-file case on purpose — an absent ledger is the
    honest no-data state, but a file that exists and cannot be read is a wrong
    --db, and guessing "no data" there would hide the mistake.
    """
    fail_agent(
        f"{path} exists but is not a readable sqlite ledger: {exc}",
        command=command,
        example="scout --json statuspage status --db .scout/uptime.db",
        discover="scout statuspage sources",
    )


def _snapshot(
    db: str | None,
    *,
    hours: float,
    stale_after: float,
    events: int,
    title: str,
    command: str,
) -> tuple[dict, Path]:
    """Read the ledger read-only. A missing file is no-data, never an error."""
    path = _ledger_path(db)
    try:
        snap = statuspage.read_snapshot(
            path,
            window_hours=hours,
            stale_after_s=stale_after,
            events=events,
            title=title,
        )
    except sqlite3.DatabaseError as e:
        _unreadable(path, e, command)
    return snap, path


def _validate(hours: float, fail_on: str | None, command: str) -> None:
    if hours <= 0:
        fail_agent(
            f"--hours must be > 0, got {hours}",
            command=command,
            example="scout --json statuspage status --hours 168",
        )
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json statuspage status --fail-on warning",
        )


@app.command("hello", epilog=examples_epilog(["scout --json statuspage hello"]))
def hello():
    """Smoke check — is the statuspage surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "statuspage", "collects": False},
            command="statuspage hello",
            example="scout --json statuspage status",
            discover="scout statuspage sources",
        ),
        command="statuspage hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json statuspage detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="statuspage detect",
            example="scout --json statuspage render",
            discover="scout statuspage sources",
        ),
        command="statuspage detect",
    )


@app.command(
    "sources",
    epilog=examples_epilog(
        [
            "scout --json statuspage sources",
            "scout --json statuspage sources --db .scout/uptime.db",
        ]
    ),
)
def sources_cmd(
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"shared ledger path (default {statuspage.LEDGER_REL} or $SCOUT_UPTIME_DB)",
    ),
):
    """What this page can actually see — provenance before publication."""
    path = _ledger_path(db)
    conn = statuspage.open_readonly(path)
    try:
        src = statuspage.sources(conn, path)
    except sqlite3.DatabaseError as e:
        _unreadable(path, e, "statuspage sources")
    finally:
        if conn is not None:
            conn.close()
    emit(
        ok(
            {
                "db": str(path),
                "read_only": True,
                "collects": False,
                "sources": src,
            },
            command="statuspage sources",
            example="scout --json statuspage status",
            discover="scout statuspage status",
        ),
        command="statuspage sources",
    )


@app.command(
    "status",
    epilog=examples_epilog(
        [
            "scout --json statuspage status",
            "scout --json statuspage status --hours 168",
            "scout --json statuspage status --fail-on warning",
        ]
    ),
)
def status(
    db: str | None = typer.Option(None, "--db", help="shared ledger path"),
    hours: float = typer.Option(
        statuspage.DEFAULT_WINDOW_HOURS, "--hours", help="availability window"
    ),
    stale_after: float = typer.Option(
        statuspage.DEFAULT_STALE_AFTER_S,
        "--stale-after",
        help="seconds before a service's newest check stops counting as current",
    ),
    events: int = typer.Option(
        statuspage.DEFAULT_EVENTS, "--events", help="timeline events to include"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if the page maps at/above this severity (error|warning) "
        "— fires on outages AND on stale/absent data",
    ),
):
    """The page's data as JSON — read-only, no probes, no network."""
    _validate(hours, fail_on, "statuspage status")
    snap, path = _snapshot(
        db,
        hours=hours,
        stale_after=stale_after,
        events=events,
        title="Status",
        command="statuspage status",
    )
    diags = statuspage.to_diagnostics(snap)
    emit(
        ok(
            {
                "db": str(path),
                "read_only": True,
                "overall": snap["overall"],
                "generated_ts": snap["generated_ts"],
                "window_hours": snap["window_hours"],
                "counts": snap["counts"],
                "sources": snap["sources"],
                "services": snap["services"],
                "certs": snap["certs"],
                "daemons": snap["daemons"],
                "events": snap["events"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="statuspage status",
            example="scout statuspage render --out public/status.html",
            discover="scout statuspage render",
        ),
        command="statuspage status",
    )
    if fail_on is not None:
        gate_rank = openswap.severity_rank(fail_on)
        if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
            raise typer.Exit(code=1)


@app.command(
    "render",
    epilog=examples_epilog(
        [
            "scout statuspage render",
            "scout statuspage render --out public/status.html --title 'dumbmodel status'",
            "scout --json statuspage render --hours 168 --fail-on warning",
        ]
    ),
)
def render(
    out: str | None = typer.Option(
        None, "--out", help=f"HTML output path (default {statuspage.PAGE_REL})"
    ),
    db: str | None = typer.Option(None, "--db", help="shared ledger path"),
    title: str = typer.Option("Status", "--title", help="page heading"),
    hours: float = typer.Option(
        statuspage.DEFAULT_WINDOW_HOURS, "--hours", help="availability window"
    ),
    stale_after: float = typer.Option(
        statuspage.DEFAULT_STALE_AFTER_S,
        "--stale-after",
        help="seconds before a service's newest check stops counting as current",
    ),
    events: int = typer.Option(
        statuspage.DEFAULT_EVENTS, "--events", help="timeline events to include"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 after writing if the page maps at/above this severity",
    ),
):
    """Write the static status page — the hosted dashboard, deleted.

    Succeeds with an absent ledger on purpose: the page then states that nothing
    was recorded instead of publishing an invented 100%.
    """
    _validate(hours, fail_on, "statuspage render")
    snap, path = _snapshot(
        db,
        hours=hours,
        stale_after=stale_after,
        events=events,
        title=title,
        command="statuspage render",
    )
    out_path = Path(out or statuspage.PAGE_REL)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(out_path))
    page = statuspage.render_html(snap, title=title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    diags = statuspage.to_diagnostics(snap)
    emit(
        ok(
            {
                "db": str(path),
                "ledger_present": snap["sources"]["ledger"]["present"],
                "out": str(out_path),
                "bytes": len(page),
                "overall": snap["overall"],
                "counts": snap["counts"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="statuspage render",
            example="scout --json statuspage status --fail-on warning",
            discover="scout statuspage sources",
        ),
        command="statuspage render",
    )
    if fail_on is not None:
        gate_rank = openswap.severity_rank(fail_on)
        if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
            raise typer.Exit(code=1)


def register(root):
    root.add_typer(app, name="statuspage")
