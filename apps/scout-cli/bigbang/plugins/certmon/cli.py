# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout certmon` — SSL Labs/TrackSSL replacement, fully local (openswap #9).

Certificate monitoring with the SaaS scanner deleted: the TLS handshake happens
on THIS box (ssl.create_default_context() + getpeercert() under a strict
timeout — the only real I/O, and it lives here in _fetch), and every judgment
(days-to-expiry, SAN/CN host match, chain/self-signed, weak protocol, HSTS)
runs deterministically in bigbang/core/certmon.py. Observations land on the
shared monitoring ledger (#2 uptime's sqlite file — open_cert_ledger adds one
`certs` table and records non-ok findings as kind="cert" events on the same
timeline as uptime incidents). There is no native binary tier to prefer: SSL
Labs' Server Test and TrackSSL are both SaaS, so the stdlib ssl core IS the
product and `detect` reports tier=fallback as the expected steady state (scope
honesty, not degradation).

Policy: every default target is gated by enforce_or_raise against this plugin's
manifest domain allowlist (the SAME domains as uptime — certmon watches the
same https hosts); an ad-hoc --host is user-typed and is instead gated by the
persisted user allowlist (enforce_user_url_or_raise), never by a manifest
widened to match it. Reading the ledger (status) makes no network calls at all.
openssl is surfaced by `detect` as an optional local helper; ssllabs-scan is
surfaced for awareness but NEVER executed — its whole job is querying the SSL
Labs SaaS (the forbidden network tier).
"""

from __future__ import annotations

import socket
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import typer

from bigbang.core import certmon, openswap, uptime
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import (
    enforce_or_raise,
    enforce_user_url_or_raise,
    load_manifest,
)

FALLBACK_SCOPE = (
    "pure-stdlib ssl handshake is the complete product for this adapter: "
    "local getpeercert() under a timeout, days-to-expiry, SAN/CN host match, "
    "chain/self-signed detection, weak-protocol and HSTS checks, sqlite cert "
    "history on the shared uptime ledger; tier 'fallback' is the expected "
    "steady state (SSL Labs' Server Test and TrackSSL are SaaS — no local "
    "native binary exists to prefer)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib ssl core is complete; openssl is an "
    "optional local helper for manual spot-checks (never required)"
)

app = make_plugin_app(
    "certmon",
    "Monitor the fleet's TLS certificates (SSL Labs-class), fully local: "
    "stdlib ssl handshake + expiry/host/chain analysis on the shared uptime ledger",
    examples=[
        "scout --json certmon check",
        "scout --json certmon check --host www.bhenre.com",
        "scout --json certmon check --fail-on warning",
        "scout --json certmon status",
        "scout --json certmon detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only on probes
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # No local native cert-monitor CLI is a superset of this core (SSL Labs and
    # TrackSSL are SaaS), so `native` stays a truthful probe that reports
    # absent. openssl is a benign optional helper; ssllabs-scan is surfaced but
    # NEVER executed — it queries the SSL Labs SaaS (the forbidden network tier).
    native = openswap.probe_binary("ssl-cert-check", probe_args=("-h",))
    extras = {
        "openssl": openswap.probe_binary("openssl", probe_args=("version",)),
        "ssllabs-scan": openswap.probe_binary("ssllabs-scan", probe_args=("-version",)),
    }
    return openswap.capability_report(
        "certmon",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    # the SHARED monitoring ledger (#2): same default, same env override
    import os

    return Path(db or os.environ.get("SCOUT_UPTIME_DB") or uptime.DB_REL)


def _open_ledger(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return certmon.open_cert_ledger(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no monitoring ledger at {path} — run a cert check first",
            command=command,
            example="scout --json certmon check",
        )
    return certmon.open_cert_ledger(path), path


def _read_hsts(ss: ssl.SSLSocket, host: str, timeout: float) -> bool | None:
    """Best-effort HSTS probe: HEAD over the open TLS socket, scan headers.

    Not under test (the core is what's tested with injected observations); a
    failure to read the header returns None (unknown), never an exception.
    """
    try:
        ss.settimeout(timeout)
        req = (
            f"HEAD / HTTP/1.1\r\nHost: {host}\r\n"
            "User-Agent: scout-certmon\r\nConnection: close\r\n\r\n"
        )
        ss.sendall(req.encode("ascii", "ignore"))
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = ss.recv(4096)
            if not chunk:
                break
            data += chunk
        return "strict-transport-security:" in data.decode("latin-1", "replace").lower()
    except Exception:
        return None


def _fetch(host: str, *, port: int = certmon.DEFAULT_PORT, timeout: float = 10.0) -> dict:
    """One real TLS handshake -> the observation dict the core analyzes.

    Verified first (create_default_context validates chain + hostname). On a
    verification failure we retry once with hostname checking off, so a merely
    mismatched host still yields a cert dict for the core to flag precisely
    (rather than a bare "handshake failed"); the original verify error is kept.
    Any hard failure returns cert=None with the exception class visible so
    DNS vs TLS vs timeout stays distinguishable in the history.
    """
    obs = {"cert": None, "protocol": None, "hsts": None, "error": None, "verified": None}
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                obs["cert"] = ss.getpeercert()
                obs["protocol"] = ss.version()
                obs["verified"] = True
                obs["hsts"] = _read_hsts(ss, host, timeout)
        return obs
    except ssl.SSLCertVerificationError as e:
        obs["error"] = f"{type(e).__name__}: {e}"
        obs["verified"] = False
        try:
            ctx2 = ssl.create_default_context()
            ctx2.check_hostname = False
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with ctx2.wrap_socket(sock, server_hostname=host) as ss:
                    obs["cert"] = ss.getpeercert()
                    obs["protocol"] = ss.version()
        except Exception:
            pass  # cert stays None; the core flags "unreachable" with obs["error"]
        return obs
    except Exception as e:
        obs["error"] = f"{type(e).__name__}: {e}"
        return obs


def _adhoc_host(value: str) -> str:
    """Accept either a bare host or an https URL; return the host."""
    if "://" in value:
        return urlsplit(value).hostname or value
    return urlsplit(f"//{value}").hostname or value


@app.command("hello", epilog=examples_epilog(["scout --json certmon hello"]))
def hello():
    """Smoke check — is the certmon surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "certmon"},
            command="certmon hello",
            example="scout --json certmon check",
            discover="scout certmon detect",
        ),
        command="certmon hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json certmon detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="certmon detect",
            example="scout --json certmon check",
            discover="scout certmon status",
        ),
        command="certmon detect",
    )


@app.command(
    "check",
    epilog=examples_epilog(
        [
            "scout --json certmon check",
            "scout --json certmon check --host www.bhenre.com",
            "scout --json certmon check --fail-on error --warn-days 30",
        ]
    ),
)
def check(
    host: str | None = typer.Option(
        None, "--host", help="probe one ad-hoc host instead of the default fleet"
    ),
    port: int = typer.Option(certmon.DEFAULT_PORT, "--port", help="TLS port"),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"shared ledger path (default {uptime.DB_REL} or $SCOUT_UPTIME_DB)",
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="per-handshake socket timeout, seconds"
    ),
    warn_days: float = typer.Option(
        certmon.EXPIRY_WARN_DAYS, "--warn-days", help="warn when fewer days remain"
    ),
    error_days: float = typer.Option(
        certmon.EXPIRY_ERROR_DAYS, "--error-days", help="error when fewer days remain"
    ),
    record: bool = typer.Option(
        True,
        "--record/--no-record",
        help="persist to the ledger (off = probe-and-report only)",
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any host maps at/above this severity (error|warning) "
        "— the pre-expiry cron/CI gate hook",
    ),
):
    """One handshake pass over the fleet: analyze, record, report. Real TLS I/O."""
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command="certmon check",
            example="scout --json certmon check --fail-on error",
        )
    if host:
        # user-typed host: gated by the persisted user allowlist, never by a
        # manifest widened to match the host being checked (policy doctrine)
        h = _adhoc_host(host)
        enforce_user_url_or_raise(f"https://{h}", context="certmon check")
        targets = [h]
    else:
        targets = certmon.default_targets()
        for t in targets:
            enforce_or_raise(_manifest(), "network", f"https://{t}")

    if record:
        conn, path = _open_ledger(db)
    else:
        conn, path = certmon.open_cert_ledger(":memory:"), None  # dry-run, same pipeline

    def fetch(h: str) -> dict:
        return _fetch(h, port=port, timeout=timeout)

    res = certmon.run_pass(
        conn, targets, fetch, record=record, warn_days=warn_days, error_days=error_days
    )
    diags = certmon.to_diagnostics(res["results"])
    by_severity: dict[str, int] = {}
    for r in res["results"]:
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1
    emit(
        ok(
            {
                "db": str(path) if path else None,
                "recorded": record,
                "by_severity": by_severity,
                "results": res["results"],
                "problems": res["problems"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="certmon check",
            example="scout --json certmon status",
            discover="scout certmon status",
        ),
        command="certmon check",
    )
    if fail_on is not None:
        gate_rank = openswap.severity_rank(fail_on)
        if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
            raise typer.Exit(code=1)


@app.command(
    "status",
    epilog=examples_epilog(
        ["scout --json certmon status", "scout --json certmon status --db x.db"]
    ),
)
def status(
    db: str | None = typer.Option(None, "--db", help="shared ledger path"),
    host: str | None = typer.Option(
        None, "--host", help="one host's recent cert history instead of the board"
    ),
    limit: int = typer.Option(20, "--limit", help="history rows when --host is set"),
):
    """Cert posture board from the ledger — no handshakes, no network."""
    conn, path = _open_existing(db, "certmon status")
    if host:
        h = _adhoc_host(host)
        hist = certmon.cert_history(conn, h, limit=limit)
        if not hist:
            fail_agent(
                f"no cert observations recorded for host {h!r}",
                command="certmon status",
                example="scout --json certmon check",
            )
        emit(
            ok(
                {"db": str(path), "host": h, "history": hist},
                command="certmon status",
                example="scout --json certmon check",
                discover="scout certmon check",
            ),
            command="certmon status",
        )
        return
    rows = certmon.board(conn, certmon.default_targets())
    emit(
        ok(
            {
                "db": str(path),
                "board": rows,
                "events": uptime.recent_events(conn, limit=10),
            },
            command="certmon status",
            example="scout --json certmon check --fail-on warning",
            discover="scout certmon check",
        ),
        command="certmon status",
    )


def register(root):
    root.add_typer(app, name="certmon")
