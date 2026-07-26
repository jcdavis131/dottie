# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout digest` — Mailchimp replacement, fully local (openswap #32).

The per-contact newsletter subscription is deleted. A digest mailer is four
things this box already has — a list, a template, a relay and a clock — plus one
thing you should refuse to buy: open/click analytics, which are implemented as a
remote 1x1 image and every link rewritten through the vendor's domain. So the
audience lives in JSON on your disk, bigbang/core/digest.py assembles the issue
from the ledgers other adapters already write (uptime #2 incidents, logs #14
error lines, glitch #8 open issues, feeds #12 unread items), renders a
multipart/alternative message with email.mime, and this CLI owns the ONLY real
egress: smtplib.SMTP in _send_message. Tests inject a recorder, so assembly,
templating, refusal and never-repeat logic is provable with no socket.

--dry-run IS THE DEFAULT and it is a real rehearsal, not a second code path: the
same refusals fire, the same message is built (its byte length is reported), and
only the smtplib call and the ledger row are skipped. Sending requires the
explicit --send. A dry run creates no file at all, so it can never consume a
campaign and silence the real issue behind it.

Two things this adapter refuses to invent, because inventing either is worse
than failing: a From address (`digest:no-sender` — a From this box did not
configure is a forged From) and a recipient (`digest:no-recipients` — the
shipped roster is EMPTY). Both refusals fire identically on the dry-run path.

Zero reader-side egress is enforced, not promised: `preview` and `send` run
digest.tracking_findings() over the rendered HTML and report every remote
resource as `digest:tracking-beacon` (an error), so a vendor pixel pasted into a
custom template fails the gate instead of shipping. The manifest's network axis
is default-deny against the relay HOST, and `detect` proves it by asking
check_permission about smtp.mailchimp.com and printing the denial.

The native tier is named honestly: listmonk is a genuine self-hosted Mailchimp
replacement, and it is a SERVER with its own postgres that knows nothing about
this box's sqlite ledgers, so `detect` surfaces it without delegating
(`delegates: false`). msmtp/sendmail/mutt are probed for awareness and NEVER
executed — spawning a mailer would send outside the manifest's relay gate and
make delivery depend on someone's ~/.msmtprc (the links #4 doctrine).

Not duplicated from alerts #19, which also speaks smtplib: that adapter pages
ONE incident at a time with (target, severity) dedup windows and a shared To:.
This one mails a periodic, templated, per-recipient issue over four ledgers with
a list, an unsubscribe state and a never-repeat campaign id. Neither reads the
other's tables. See the core module docstring for the full reasoning.
"""

from __future__ import annotations

import json
import os
import smtplib
import sqlite3
import time
import urllib.parse
from pathlib import Path

import typer

from bigbang.core import digest, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import check_permission, enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib digest assembly is the complete product for this adapter: "
    "declarative sections over the uptime/logs/glitch/feeds ledgers (identifiers "
    "double-gated, every value a bound parameter), merge-tag templating that "
    "leaves an unresolved tag VISIBLE instead of blanking it, a text+HTML "
    "multipart/alternative built with email.mime, a deterministic campaign id so "
    "a scheduled run never repeats an issue, per-recipient messages so the roster "
    "is never published to itself, and a tracking audit that fails the gate on any "
    "remote resource; tier 'fallback' is the expected steady state (Mailchimp is "
    "SaaS and listmonk is a postgres-backed server that cannot read these ledgers)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; listmonk is an optional "
    "self-hosted newsletter SERVER if you outgrow one box and one roster"
)
NEVER_EXECUTED = (
    "msmtp/sendmail/mutt are probed for awareness and NEVER executed: a spawned "
    "mailer delivers outside this manifest's relay allowlist and its behaviour "
    "would depend on someone's ~/.msmtprc, so the smtplib path stays the only "
    "egress this plugin has"
)

app = make_plugin_app(
    "digest",
    "Mail a templated digest (Mailchimp-class) assembled from the local sqlite "
    "ledgers: dry-run by default, smtplib the only egress, no tracking pixel",
    examples=[
        "scout --json digest config",
        "scout --json digest preview --days 7",
        "scout --json digest send --config .scout/digest.json",
        "scout --json digest send --config .scout/digest.json --send",
        "scout --json digest status",
        "scout --json digest detect",
    ],
)

# The SaaS this adapter replaces. detect() asks the policy layer about it and
# prints the denial, so "the roster never reaches an ESP" is falsifiable.
_REPLACED_RELAY = "smtp.mailchimp.com"

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only when used
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    native = openswap.probe_binary("listmonk", probe_args=("--version",))
    extras = {
        "msmtp": openswap.probe_binary("msmtp", probe_args=("--version",)),
        "sendmail": openswap.probe_binary("sendmail", probe_args=("-d0.1", "-bv")),
        "mutt": openswap.probe_binary("mutt", probe_args=("-v",)),
    }
    report = openswap.capability_report(
        "digest",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    # tier is a capability report, never a dispatch switch: this adapter always
    # assembles and sends with its own core, so say so instead of implying a handoff
    report["delegates"] = False
    report["native_never_executed"] = NEVER_EXECUTED
    return report


def _policy_proof() -> dict:
    """What the manifest allows, demonstrated rather than asserted."""
    allowed, reason = check_permission(_manifest(), "network", _REPLACED_RELAY)
    return {
        "esp_probe": _REPLACED_RELAY,
        "esp_allowed": allowed,
        "esp_reason": reason,
        "allowlist": ((_manifest().get("capabilities") or {}).get("network") or {}).get(
            "domains"
        )
        or [],
        "reader_egress": "none — the HTML part loads no remote resource (audited every run)",
    }


def _config(path: str | None, command: str) -> dict:
    """Load config, turning any mistake into an actionable, NAMED envelope."""
    try:
        return digest.load_config(path)
    except digest.DigestError as e:
        fail_agent(
            f"{e.rule}: {e.message}",
            command=command,
            example="scout --json digest config --config .scout/digest.json",
            discover="scout --json digest config",
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as e:
        fail_agent(
            f"bad digest config{f' {path}' if path else ''}: {type(e).__name__}: {e}",
            command=command,
            example="scout --json digest config --config .scout/digest.json",
            discover="scout --json digest config",
        )
    raise AssertionError("unreachable: fail_agent exits")  # pragma: no cover


def _ro_uri(path: Path) -> str:
    """sqlite read-only URI for a ledger this adapter must never modify.

    as_posix() + quote keeps a Windows path (backslashes, drive letter, spaces)
    a legal URI; mode=ro makes "read-only" enforced by sqlite rather than by
    this module's good intentions.
    """
    return "file:" + urllib.parse.quote(path.as_posix(), safe="/:") + "?mode=ro"


def _open_reader(path_str: str) -> tuple[sqlite3.Connection | None, str | None]:
    """The section I/O boundary injected into digest.assemble().

    A ledger that does not exist yet is a NORMAL state on a fresh box (nobody
    ran `logs collect`), so it comes back as a labelled reason and the section
    reports count=null — never a reassuring zero.
    """
    path = Path(path_str)
    if not path.exists():
        return None, f"ledger not found: {path} (nothing has written it yet)"
    try:
        conn = sqlite3.connect(_ro_uri(path), uri=True)
        conn.row_factory = sqlite3.Row
        return conn, None
    except sqlite3.DatabaseError as e:
        return None, f"{path} is not a readable sqlite ledger: {type(e).__name__}: {e}"


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_DIGEST_DB") or digest.DB_REL)


def _open_send_ledger(
    db: str | None, *, writable: bool
) -> tuple[sqlite3.Connection | None, Path, str]:
    """The send ledger. On a dry run it is NEVER created — a rehearsal writes nothing."""
    path = _db_path(db)
    if writable:
        enforce_or_raise(_manifest(), "fs_write_arg", str(path))
        return digest.open_ledger(path), path, "open"
    if not path.exists():
        return None, path, "absent — no send history on this box yet"
    conn = sqlite3.connect(_ro_uri(path), uri=True)
    conn.row_factory = sqlite3.Row
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sends'"
    ).fetchone()
    if table is None:
        return None, path, f"{path} has no `sends` table — cannot check for repeats"
    return conn, path, "read-only"


def _relay_password(mail: dict) -> tuple[str | None, str | None]:
    """(password, denial) — the secrets axis is default-deny, by env var NAME."""
    name = mail.get("password_env")
    if not name:
        return None, None
    allowed, reason = check_permission(_manifest(), "secret", str(name))
    if not allowed:
        return None, f"policy denied: {reason}"
    return os.environ.get(str(name)), None


def _send_message(mail: dict, msg, recipient: str) -> tuple[bool, str]:
    """Hand ONE message to the relay. The only real egress in this adapter.

    A denied host or secret is a FAILED delivery, not an abort: the rest of the
    roster must still get the issue, and the failure is in the ledger and the
    diagnostics rather than swallowed.
    """
    host, port = str(mail["host"]), int(mail["port"])
    allowed, reason = check_permission(_manifest(), "network", host)
    if not allowed:
        return False, f"policy denied: {reason}"
    password, denied = _relay_password(mail)
    if denied:
        return False, denied
    try:
        with smtplib.SMTP(host, port, timeout=float(mail["timeout_s"])) as smtp:
            if mail.get("starttls"):
                smtp.starttls()
            if mail.get("user") and password:
                smtp.login(str(mail["user"]), password)
            smtp.send_message(msg)
        return True, f"smtp {host}:{port} -> {recipient}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _window(days: float, now: float | None = None) -> tuple[float, float]:
    """(since, until) for a --days window, closed at the top so it is reproducible.

    Wall clock on purpose, not perf_counter: these bounds are compared against
    epoch timestamps other adapters wrote into their ledgers. perf_counter is for
    intervals and has no epoch to compare with.
    """
    until = time.time() if now is None else float(now)
    return until - float(days) * 86400.0, until


def _assemble(cfg: dict, days: float) -> dict:
    since, until = _window(days if days > 0 else cfg["digest"]["window_days"])
    return digest.assemble(
        _open_reader,
        cfg["sections"],
        since=since,
        until=until,
        limit=int(cfg["digest"]["section_limit"]),
        body_chars=int(cfg["digest"]["body_chars"]),
    )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


def _render_preview(cfg: dict, dg: dict) -> dict:
    """Both parts plus the subject, with no recipient in scope."""
    text_values = digest.digest_values(dg, cfg, html=False)
    html_values = digest.digest_values(dg, cfg, html=True)
    text, missing_text = digest.merge(digest.TEMPLATE_TEXT, text_values)
    html, missing_html = digest.merge(digest.TEMPLATE_HTML, html_values)
    subject, missing_subject = digest.merge(str(cfg["digest"]["subject"]), text_values)
    return {
        "subject": " ".join(subject.split()),
        "text": text,
        "html": html,
        "pending": sorted(set(missing_text) | set(missing_html) | set(missing_subject)),
        "tracking": digest.tracking_findings(html),
    }


def _preview_diagnostics(dg: dict, tracking: list[dict]) -> list[dict]:
    """Section findings plus a beacon finding per remote resource in the template."""
    diags = digest.to_diagnostics(dg)
    diags.extend(
        openswap.diagnostic(
            path="preview",
            line=0,
            col=0,
            rule=digest.ERR_TRACKING,
            severity="error",
            message=f"<{h['tag']} {h['attr']}> loads {h['url']} — remote resources are read receipts",
        )
        for h in tracking
    )
    return openswap.sort_diagnostics(diags)


def _send_payload(
    dg: dict, result: dict, ledger: tuple[Path, str], diags: list[dict]
) -> dict:
    """The send envelope. Totals merge the assembly counts with the delivery ones."""
    return {
        "dry_run": result["dry_run"],
        "campaign_id": result["campaign_id"],
        "sender": result["sender"],
        "relay": result["relay"],
        "ledger": {"path": str(ledger[0]), "state": ledger[1]},
        "window": {"since": dg["since"], "until": dg["until"]},
        "totals": {**dg["totals"], **result["totals"]},
        "results": result["results"],
        "skipped": result["skipped"],
        "diagnostics": diags,
        "summary": openswap.summarize(diags),
    }


def _check_fail_on(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=f"scout --json {command} --fail-on error",
        )


@app.command("hello", epilog=examples_epilog(["scout --json digest hello"]))
def hello():
    """Smoke check — is the digest surface alive?"""
    emit(
        ok(
            {
                "ready": True,
                "plugin": "digest",
                "sections": sorted(digest.DEFAULT_SECTIONS),
            },
            command="digest hello",
            example="scout --json digest preview",
            discover="scout digest config",
        ),
        command="digest hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json digest detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    data = _capability()
    data["policy"] = _policy_proof()
    emit(
        ok(
            data,
            command="digest detect",
            example="scout --json digest preview",
            discover="scout digest config",
        ),
        command="digest detect",
    )


@app.command(
    "config",
    epilog=examples_epilog(
        [
            "scout --json digest config",
            "scout --json digest config --config .scout/digest.json",
        ]
    ),
)
def config_cmd(
    config: str | None = typer.Option(
        None, "--config", help="JSON overlay of {mail, digest, sections, recipients}"
    ),
):
    """The effective config: what WOULD be mailed, to whom, and what is missing."""
    cfg = _config(config, "digest config")
    mailable, skipped = digest.deliverable(cfg["recipients"])
    mail = cfg["mail"]
    blockers = []
    if not digest.valid_address(mail.get("from")):
        blockers.append(digest.ERR_NO_SENDER)
    if not mail.get("host"):
        blockers.append(digest.ERR_NO_RELAY)
    if not mailable:
        blockers.append(digest.ERR_NO_RECIPIENTS)
    emit(
        ok(
            {
                "overlay": config,
                "mail": {
                    "from": mail.get("from"),
                    "from_name": mail.get("from_name"),
                    "relay": mail.get("host"),
                    "port": mail.get("port"),
                    "starttls": bool(mail.get("starttls")),
                    "password_env": mail.get("password_env"),
                },
                "digest": cfg["digest"],
                "sections": {
                    name: {
                        "title": s["title"],
                        "db": s["db"],
                        "table": s["table"],
                        "cols": s["cols"],
                        "filter": s.get("filter"),
                        "order": s["order"],
                    }
                    for name, s in sorted(cfg["sections"].items())
                },
                "recipients": {
                    "mailable": [r["email"] for r in mailable],
                    "skipped": skipped,
                    "states": list(digest.RECIPIENT_STATES),
                },
                "tags": list(digest.TAGS),
                "blockers": blockers,
                "ready": not blockers,
            },
            command="digest config",
            example="scout --json digest send --config .scout/digest.json",
            discover="scout --json digest preview",
        ),
        command="digest config",
    )


@app.command(
    "preview",
    epilog=examples_epilog(
        [
            "scout --json digest preview",
            "scout --json digest preview --days 1 --fail-on error",
            "scout --json digest preview --config .scout/digest.json --html",
        ]
    ),
)
def preview(
    config: str | None = typer.Option(None, "--config", help="JSON config overlay"),
    days: float = typer.Option(
        0, "--days", help="window size (0 = digest.window_days)"
    ),
    show_html: bool = typer.Option(
        False, "--html/--no-html", help="include the HTML part"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|suggestion|info)",
    ),
):
    """Assemble and render WITHOUT a roster. Needs no sender; opens no socket.

    Recipient-scoped tags cannot resolve here, so they are listed as `pending`
    rather than blanked — a preview that silently rendered "Hello ," is exactly
    the bug this reports.
    """
    _check_fail_on(fail_on, "digest preview")
    cfg = _config(config, "digest preview")
    dg = _assemble(cfg, days)
    rendered = _render_preview(cfg, dg)
    pending, tracking = rendered["pending"], rendered["tracking"]
    diags = _preview_diagnostics(dg, tracking)
    emit(
        ok(
            {
                "campaign_id": dg["campaign_id"],
                "subject": rendered["subject"],
                "window": {"since": dg["since"], "until": dg["until"]},
                "totals": dg["totals"],
                "empty": dg["empty"],
                "sections": [
                    {k: v for k, v in s.items() if k != "items"} for s in dg["sections"]
                ],
                "text": rendered["text"],
                **({"html": rendered["html"]} if show_html else {}),
                "pending_tags": pending,
                "pending_note": (
                    "these tags resolve per recipient at send time"
                    if set(pending) <= set(digest.RECIPIENT_TAGS)
                    else "one or more tags are NOT known to this adapter — check for a typo"
                ),
                "tracking": {"clean": not tracking, "remote_resources": tracking},
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="digest preview",
            example="scout --json digest send --config .scout/digest.json",
            discover="scout --json digest config",
        ),
        command="digest preview",
    )
    _gate(diags, fail_on)


@app.command(
    "send",
    epilog=examples_epilog(
        [
            "scout --json digest send --config .scout/digest.json",
            "scout --json digest send --config .scout/digest.json --send",
            "scout --json digest send --config .scout/digest.json --send --days 1 --fail-on error",
            "scout --json digest send --config .scout/digest.json --send --force",
        ]
    ),
)
def send_cmd(
    config: str | None = typer.Option(None, "--config", help="JSON config overlay"),
    days: float = typer.Option(
        0, "--days", help="window size (0 = digest.window_days)"
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--send",
        help="DEFAULT: render every recipient's copy and send NOTHING. --send is the "
        "explicit opt-in that opens a socket",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="mail a campaign that was already delivered to this address",
    ),
    db: str | None = typer.Option(
        None, "--db", help="send ledger (default .scout/digest.db)"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity — the cron gate",
    ),
):
    """Render per recipient; send only with --send. Refuses to invent From or To."""
    _check_fail_on(fail_on, "digest send")
    cfg = _config(config, "digest send")
    dg = _assemble(cfg, days)
    ledger, ledger_path, ledger_state = _open_send_ledger(db, writable=not dry_run)
    mail, stamp = cfg["mail"], time.time()

    def lookup(campaign: str, email: str) -> bool:
        return digest.already_sent(ledger, campaign, email)

    def send_fn(msg, rcpt: str) -> tuple[bool, str]:
        return _send_message(mail, msg, rcpt)

    def record_fn(row: dict) -> None:
        digest.record_send(ledger, dg["campaign_id"], row, ts=stamp)

    try:
        result = digest.deliver(
            dg,
            cfg,
            send=not dry_run,
            send_fn=send_fn,
            sent_lookup=lookup if ledger is not None else None,
            record_fn=None if dry_run else record_fn,
            force=force,
            now=stamp,
        )
    except digest.DigestError as e:
        fail_agent(
            f"{e.rule}: {e.message}",
            command="digest send",
            example="scout --json digest config --config .scout/digest.json",
            discover="scout --json digest preview",
        )
        raise  # pragma: no cover - fail_agent exits
    diags = digest.to_diagnostics(dg, result)
    emit(
        ok(
            _send_payload(dg, result, (ledger_path, ledger_state), diags),
            command="digest send",
            example="scout --json digest send --config .scout/digest.json --send",
            discover="scout --json digest status",
        ),
        command="digest send",
    )
    _gate(diags, fail_on)


@app.command(
    "status",
    epilog=examples_epilog(
        ["scout --json digest status", "scout --json digest status --limit 5"]
    ),
)
def status(
    db: str | None = typer.Option(
        None, "--db", help="send ledger (default .scout/digest.db)"
    ),
    limit: int = typer.Option(25, "--limit", help="how many deliveries to show"),
):
    """What this box actually mailed: campaign, address, outcome, Message-ID."""
    ledger, path, state = _open_send_ledger(db, writable=False)
    rows = digest.history(ledger, limit=limit) if ledger is not None else []
    emit(
        ok(
            {
                "ledger": str(path),
                "state": state,
                "sends": rows,
                "count": len(rows),
                "statuses": list(digest.STATUSES),
                "counts_toward_repeat_guard": list(digest.SENT_STATUSES),
            },
            command="digest status",
            example="scout --json digest send --config .scout/digest.json --send",
            discover="scout --json digest config",
        ),
        command="digest status",
    )


def register(root):
    root.add_typer(app, name="digest")
