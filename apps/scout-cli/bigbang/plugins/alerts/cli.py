# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout alerts` — PagerDuty/Opsgenie replacement, fully local (openswap #19).

The per-seat pager is deleted. Everything a routing SaaS does with your
monitoring data is pure logic over data this box already has, so the decision
moves onto the box: bigbang/core/alerts.py reads the shared monitoring ledger
(uptime #2 `incidents`, plus the kind="alert"/"cert"/"recovery" events that
heartbeat #6 and certmon #9 write to the same timeline), applies severity rules
from JSON config, damps repeats with per-rule dedup windows, and this CLI owns
the ONLY real I/O — smtplib for mail and urllib for an outbound webhook, both
in _send_email/_send_webhook. Tests inject a recorder instead, so the routing
brain is provable offline.

A router's failure mode is silence, so this adapter refuses to let silence look
like health. The shipped channels carry no endpoint on purpose: a first `route`
reports every alert `failed` with "channel not configured" and raises
`alerts:undeliverable` (an error even when the fleet is green), because a
default that quietly wrote pages to sqlite and notified nobody would be
indistinguishable from a working pager. `route --dry-run` writes nothing at all
— no dispatch, no ledger row — so a rehearsal can never start a dedup window
and silence the real page behind it. `test` proves the wiring before an outage
needs it.

Policy: the network axis is enabled but default-deny, and BOTH senders check the
manifest allowlist against the configured endpoint (webhook URL, SMTP host)
before touching a socket — adding a channel host means editing manifest.yaml,
which is the point. A denied endpoint comes back as a failed delivery rather
than an abort, so one bad channel cannot stop the email that would have woken
someone up. The SMTP password is read from an env var named in the config and
only if that name is also in the manifest's secrets allowlist (default-deny);
the value never reaches the ledger or the JSON envelope.

There is a native tier to name honestly: Prometheus Alertmanager is a real local
binary that does routing, grouping and silences better than this ever will. It
is a SERVER that speaks Prometheus alert JSON and knows nothing about this box's
sqlite ledger, so `detect` surfaces it without delegating to it (`delegates:
false`), and `pd` — PagerDuty's own CLI — is surfaced but NEVER executed, since
its whole job is talking to the SaaS this adapter replaces.
"""

from __future__ import annotations

import json
import os
import smtplib
import sqlite3
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

import typer

from bigbang.core import alerts, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import check_permission, enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib routing is the complete product for this adapter: severity "
    "rules and channel fan-out as JSON config, (target, severity) dedup "
    "windows that double as the re-notify cadence, collapsing of the duplicate "
    "signals one incident produces, smtplib + urllib delivery, and an alert "
    "ledger on the shared uptime sqlite file; tier 'fallback' is the expected "
    "steady state (Alertmanager is a Prometheus-shaped server that cannot read "
    "this ledger, and PagerDuty's own CLI is the SaaS being replaced)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib router is complete; alertmanager is an "
    "optional local daemon if you outgrow one box and want its silence UI"
)

app = make_plugin_app(
    "alerts",
    "Route the fleet's alerts (PagerDuty-class), fully local: severity rules + "
    "dedup windows over the shared uptime/certmon/heartbeat ledger, delivered "
    "by smtplib/urllib from this box",
    examples=[
        "scout --json alerts rules",
        "scout --json alerts route --dry-run",
        "scout --json alerts route --config .scout/alerts.json --fail-on error",
        "scout --json alerts status",
        "scout --json alerts test --severity warning",
        "scout --json alerts detect",
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
    # Alertmanager IS a superset of the routing logic, so it is named as the
    # native probe rather than hidden — but it is a server that ingests
    # Prometheus alert JSON, so this plugin never delegates to it (`delegates`).
    # `pd` is PagerDuty's official CLI: surfaced for awareness, NEVER executed,
    # because running it is the forbidden SaaS network tier.
    native = openswap.probe_binary("alertmanager", probe_args=("--version",))
    extras = {
        "amtool": openswap.probe_binary("amtool", probe_args=("--version",)),
        "pd": openswap.probe_binary("pd", probe_args=("version",)),
    }
    report = openswap.capability_report(
        "alerts",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    # tier is a capability report, never a dispatch switch: this adapter always
    # routes with its own core, so say so instead of implying a handoff
    report["delegates"] = False
    return report


def _db_path(db: str | None) -> Path:
    # the SHARED monitoring ledger (#2): same default, same env override as
    # uptime/certmon/heartbeat/statuspage — one file, five adapters
    return Path(db or os.environ.get("SCOUT_UPTIME_DB") or alerts.LEDGER_REL)


def _open_ledger(db: str | None, command: str) -> tuple:
    """Open (creating if needed) the shared ledger + the router's alerts table.

    A --db that exists but is not sqlite is a wrong flag, not a crash: it gets an
    actionable envelope instead of a DatabaseError traceback.
    """
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write", str(path))
    try:
        return alerts.open_alert_ledger(path), path
    except sqlite3.DatabaseError as e:
        fail_agent(
            f"{path} exists but is not a readable sqlite ledger: {e}",
            command=command,
            example="scout --json alerts route --db .scout/uptime.db",
            discover="scout alerts status",
        )


def _config(path: str | None, command: str) -> dict:
    """Load rules/channels, turning any config mistake into an actionable error."""
    try:
        return alerts.load_config(path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        fail_agent(
            f"bad alerts config{f' {path}' if path else ''}: {e}",
            command=command,
            example="scout --json alerts rules --config .scout/alerts.json",
            discover="scout --json alerts rules",
        )


def _validate(command: str, **flags: str | None) -> None:
    """Every severity-shaped flag, checked against the family severity ladder."""
    for name, value in flags.items():
        if value is not None and value not in openswap.SEVERITIES:
            flag = "--" + name.replace("_", "-")
            fail_agent(
                f"{flag} must be one of {'|'.join(openswap.SEVERITIES)}, got {value!r}",
                command=command,
                example=f"scout --json {command} {flag} error",
            )


def _policy_ok(resource: str) -> str | None:
    """None when the manifest allows this endpoint, else the denial reason.

    A denied channel must NOT abort the pass (the other channel may be the one
    that wakes someone up), so this returns a reason for the delivery record
    instead of raising like enforce_or_raise does.
    """
    allowed, reason = check_permission(_manifest(), "network", resource)
    return None if allowed else f"policy denied: {reason}"


def _send_webhook(cfg: dict, alert: dict) -> dict:
    """POST the alert as JSON. Real egress — the outbound half of this adapter."""
    url = str(cfg["url"])
    denied = _policy_ok(url)
    if denied:
        return {"ok": False, "detail": denied}
    body = json.dumps(alerts.wire_payload(alert)).encode("utf-8")
    # S310 (file:/custom schemes): closed upstream — load_config admits http(s)
    # only, and the URL is policy-gated against the manifest just above
    req = urllib.request.Request(  # noqa: S310
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "scout-alerts"},
    )
    try:
        with urllib.request.urlopen(req, timeout=float(cfg["timeout_s"])) as r:  # noqa: S310
            code = int(getattr(r, "status", 0) or 0)
            return {"ok": 200 <= code < 400, "detail": f"http {code} {url}"}
    except urllib.error.HTTPError as e:
        return {"ok": False, "detail": f"http {e.code} {url}"}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def _smtp_password(cfg: dict) -> tuple[str | None, str | None]:
    """(password, denial) — the secrets axis is default-deny, by env var NAME."""
    name = cfg.get("password_env")
    if not name:
        return None, None
    allowed, reason = check_permission(_manifest(), "secret", str(name))
    if not allowed:
        return None, f"policy denied: {reason}"
    return os.environ.get(str(name)), None


def _send_email(cfg: dict, alert: dict) -> dict:
    """Hand the page to an SMTP relay. Real egress; the password never leaves here."""
    host, port = str(cfg["host"]), int(cfg["port"])
    denied = _policy_ok(host)
    if denied:
        return {"ok": False, "detail": denied}
    password, secret_denied = _smtp_password(cfg)
    if secret_denied:
        return {"ok": False, "detail": secret_denied}
    msg = EmailMessage()
    msg["Subject"] = alerts.email_subject(alert)
    msg["From"] = str(cfg["from"])
    msg["To"] = ", ".join(str(a) for a in cfg["to"])
    msg.set_content(alerts.email_body(alert))
    try:
        with smtplib.SMTP(host, port, timeout=float(cfg["timeout_s"])) as smtp:
            if cfg.get("starttls"):
                smtp.starttls()
            if cfg.get("user") and password:
                smtp.login(str(cfg["user"]), password)
            smtp.send_message(msg)
        return {"ok": True, "detail": f"smtp {host}:{port} -> {len(cfg['to'])} rcpt"}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


# One sender per channel kind. test_alerts asserts this map covers
# alerts.CHANNEL_KINDS exactly — a kind added to the core without a sender here
# would otherwise drop pages in silence.
_SENDERS = {"email": _send_email, "webhook": _send_webhook}


def _dispatch(name: str, cfg: dict, alert: dict) -> dict:
    """The injected dispatch boundary: kind -> real sender (tests replace this)."""
    return _SENDERS[str(cfg["kind"])](cfg, alert)


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json alerts hello"]))
def hello():
    """Smoke check — is the alerts surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "alerts", "channel_kinds": list(alerts.CHANNEL_KINDS)},
            command="alerts hello",
            example="scout --json alerts route --dry-run",
            discover="scout alerts rules",
        ),
        command="alerts hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json alerts detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="alerts detect",
            example="scout --json alerts route --dry-run",
            discover="scout alerts rules",
        ),
        command="alerts detect",
    )


@app.command(
    "rules",
    epilog=examples_epilog(
        [
            "scout --json alerts rules",
            "scout --json alerts rules --config .scout/alerts.json",
        ]
    ),
)
def rules(
    config: str | None = typer.Option(
        None, "--config", help="JSON overlay of {rules, channels} (e.g. .scout/alerts.json)"
    ),
):
    """The effective ruleset and channel readiness — what WOULD page, and how."""
    cfg = _config(config, "alerts rules")
    channels = {
        name: {
            "kind": ch["kind"],
            "ready": alerts.channel_ready(ch)[0],
            "why": alerts.channel_ready(ch)[1],
        }
        for name, ch in sorted(cfg["channels"].items())
    }
    emit(
        ok(
            {
                "config": config,
                "rules": cfg["rules"],
                "channels": channels,
                "routed": sorted(r for r, v in cfg["rules"].items() if v.get("route")),
                "ignored": sorted(
                    r for r, v in cfg["rules"].items() if not v.get("route")
                ),
                "deliverable": [n for n, c in channels.items() if c["ready"]],
            },
            command="alerts rules",
            example="scout --json alerts route --dry-run",
            discover="scout alerts route --dry-run",
        ),
        command="alerts rules",
    )


@app.command(
    "route",
    epilog=examples_epilog(
        [
            "scout --json alerts route --dry-run",
            "scout --json alerts route --config .scout/alerts.json",
            "scout --json alerts route --min-severity warning --fail-on error",
        ]
    ),
)
def route(
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"shared ledger path (default {alerts.LEDGER_REL} or $SCOUT_UPTIME_DB)",
    ),
    config: str | None = typer.Option(None, "--config", help="JSON rules/channels overlay"),
    lookback: float = typer.Option(
        alerts.DEFAULT_LOOKBACK_S,
        "--lookback",
        help="how far back events count as current (open incidents always do)",
    ),
    min_severity: str | None = typer.Option(
        None, "--min-severity", help="only dispatch at/above this severity"
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="decide and report, dispatch nothing, write nothing (no dedup clock)",
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if the pass maps at/above this severity (error|warning) "
        "— fires on pages AND on undeliverable channels",
    ),
):
    """One routing pass over the ledger: decide, dedup, dispatch, record.

    Real egress when a channel is configured (smtplib / urllib). The dedup
    window is also the re-notify cadence, so a still-open incident pages again
    once its window lapses.
    """
    _validate("alerts route", min_severity=min_severity, fail_on=fail_on)
    if lookback <= 0:
        fail_agent(
            f"--lookback must be > 0, got {lookback}",
            command="alerts route",
            example="scout --json alerts route --lookback 3600",
        )
    cfg = _config(config, "alerts route")
    conn, path = _open_ledger(db, "alerts route")
    result = alerts.route(
        conn,
        cfg,
        _dispatch,
        lookback_s=lookback,
        min_severity=min_severity,
        dry_run=dry_run,
    )
    conn.close()
    diags = alerts.to_diagnostics(result)
    emit(
        ok(
            {
                "db": str(path),
                "dry_run": result["dry_run"],
                "counts": result["counts"],
                "alerts": result["alerts"],
                "unrouted": result["unrouted"],
                "filtered": result["filtered"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="alerts route",
            example="scout --json alerts status",
            discover="scout alerts status",
        ),
        command="alerts route",
    )
    _gate(diags, fail_on)


@app.command(
    "status",
    epilog=examples_epilog(
        ["scout --json alerts status", "scout --json alerts status --limit 5"]
    ),
)
def status(
    db: str | None = typer.Option(None, "--db", help="shared ledger path"),
    config: str | None = typer.Option(None, "--config", help="JSON rules/channels overlay"),
    limit: int = typer.Option(20, "--limit", help="delivery records to include"),
    lookback: float = typer.Option(
        alerts.DEFAULT_LOOKBACK_S, "--lookback", help="event window for the source counts"
    ),
):
    """Delivery history + what is muted right now + what the router can see.

    Answers "why did I not get paged?" from the ledger and the live rules: the
    window in effect per (target, severity) and the seconds left on it.
    """
    cfg = _config(config, "alerts status")
    conn, path = _open_ledger(db, "alerts status")
    now = time.time()
    payload = {
        "db": str(path),
        "board": alerts.board(conn, cfg["rules"], now=now, limit=limit),
        "history": alerts.history(conn, limit=limit),
        "sources": alerts.source_summary(conn, now=now, lookback_s=lookback),
        "deliverable": [
            n for n, c in cfg["channels"].items() if alerts.channel_ready(c)[0]
        ],
    }
    conn.close()
    emit(
        ok(
            payload,
            command="alerts status",
            example="scout --json alerts route --dry-run",
            discover="scout alerts rules",
        ),
        command="alerts status",
    )


@app.command(
    "test",
    epilog=examples_epilog(
        [
            "scout --json alerts test --dry-run",
            "scout --json alerts test --channel webhook",
            "scout --json alerts test --severity error --note 'pager drill'",
        ]
    ),
)
def test(
    db: str | None = typer.Option(None, "--db", help="shared ledger path"),
    config: str | None = typer.Option(None, "--config", help="JSON rules/channels overlay"),
    channel: str | None = typer.Option(
        None, "--channel", help="one channel by name (default: every configured channel)"
    ),
    severity: str = typer.Option("info", "--severity", help="severity to stamp on the drill"),
    note: str | None = typer.Option(None, "--note", help="message body override"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="show what would be sent, send nothing, write nothing"
    ),
):
    """Send one synthetic page — prove the channels work BEFORE an outage needs them.

    Exits 1 when nothing was delivered: an unwired router is a real finding, not
    a quiet success. The drill's sentinel target keeps it out of every real
    alert's dedup window.
    """
    _validate("alerts test", severity=severity)
    cfg = _config(config, "alerts test")
    if channel is not None and channel not in cfg["channels"]:
        fail_agent(
            f"unknown channel {channel!r} — have {sorted(cfg['channels'])}",
            command="alerts test",
            example="scout --json alerts test --channel webhook",
            discover="scout --json alerts rules",
        )
    names = [channel] if channel else sorted(cfg["channels"])
    conn, path = _open_ledger(db, "alerts test")
    now = time.time()
    alert = alerts.probe_alert(severity=severity, channels=names, ts=now, note=note)
    if dry_run:
        sent = dict(alert, status=alerts.STATUS_DRY_RUN, results={})
    else:
        sent = alerts.send_one(conn, alert, cfg["channels"], _dispatch, ts=now)
    conn.close()
    emit(
        ok(
            {
                "db": str(path),
                "status": sent["status"],
                "channels": names,
                "results": sent["results"],
                "payload": alerts.wire_payload(alert),
                "subject": alerts.email_subject(alert),
            },
            command="alerts test",
            example="scout --json alerts route",
            discover="scout alerts status",
        ),
        command="alerts test",
    )
    if sent["status"] in (alerts.STATUS_FAILED, alerts.STATUS_PARTIAL):
        raise typer.Exit(code=1)


def register(root):
    root.add_typer(app, name="alerts")
