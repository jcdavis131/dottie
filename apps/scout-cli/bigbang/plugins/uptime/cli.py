# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout uptime` — UptimeRobot/Pingdom replacement, fully local (openswap #2).

Uptime Kuma pattern with zero install: http.client/ssl GETs under strict
timeouts (the only real I/O, and it lives here), everything deterministic in
bigbang/core/uptime.py (targets, classification, flap-damped incident state
machine, sqlite ledger — the monitoring family's shared substrate). There is
no native binary tier to prefer: Uptime Kuma ships as a node server, not a
CLI, so the stdlib core IS the product and `detect` reports tier=fallback as
the expected steady state (scope honesty, not degradation).

Policy: every configured probe URL is gated by enforce_or_raise against this
plugin's manifest domain allowlist (default-deny — adding a monitored host
means adding its domain to manifest.yaml too); an ad-hoc --url probe is
user-typed and is instead gated by the persisted user allowlist
(enforce_user_url_or_raise), never by a manifest widened to match it. Reading
the ledger (status/history) makes no network calls at all.
"""

from __future__ import annotations

import http.client
import os
import sched
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit

import typer

from bigbang.core import openswap, uptime
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.http_utils import sanitize_no_proxy_env
from bigbang.core.output import emit
from bigbang.core.policy import (
    enforce_or_raise,
    enforce_user_url_or_raise,
    load_manifest,
)

FALLBACK_SCOPE = (
    "pure-stdlib probe loop is the complete product for this adapter: "
    "http.client/ssl GETs under timeouts, sqlite incident ledger, flap-damped "
    "state machine, latency percentiles; tier 'fallback' is the expected "
    "steady state (Uptime Kuma ships as a node server — no CLI binary exists "
    "to prefer)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; run Uptime Kuma "
    "separately only if you want its web dashboard"
)

app = make_plugin_app(
    "uptime",
    "Monitor the fleet (UptimeRobot-class), fully local: stdlib probes + sqlite incident ledger",
    examples=[
        "scout --json uptime check",
        "scout --json uptime watch --interval 60 --count 10",
        "scout --json uptime status",
        "scout --json uptime history bhenre",
        'scout --json uptime mark "deploy bhenre 4009c52" --target bhenre',
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
    # No binary distribution of Uptime Kuma exists, so `native` stays a
    # truthful probe that reports absent; curl is surfaced as an extra (a
    # possible alternate probe engine) without ever being required.
    native = openswap.probe_binary("uptime-kuma", probe_args=("--version",))
    extras = {"curl": openswap.probe_binary("curl", probe_args=("--version",))}
    return openswap.capability_report(
        "uptime",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_UPTIME_DB") or uptime.DB_REL)


def _open_ledger(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write", str(path))
    return uptime.open_ledger(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no uptime ledger at {path} — run a probe pass first",
            command=command,
            example="scout --json uptime check",
        )
    return uptime.open_ledger(path), path


def _targets_or_fail(targets_file: str | None, command: str) -> dict:
    try:
        return uptime.load_targets(targets_file)
    except Exception as e:
        fail_agent(
            f"bad targets file: {e}",
            command=command,
            example="scout --json uptime check --targets org-targets.json",
        )


def _probe(url: str, *, timeout: float = 10.0, read_cap: int = 65536) -> dict:
    """One GET via http.client/ssl. Returns {http, latency_ms, error, body_head}.

    Redirects are not followed (<400 already proves liveness to classify());
    the body is read only up to read_cap bytes — enough for the expected-string
    check without pulling whole pages. Failures return http=None with the
    exception class visible so DNS vs TLS vs timeout stays distinguishable in
    trends (same doctrine as the gist feed's probe rows).
    """
    u = urlsplit(url)
    host = u.hostname or ""
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    conn: http.client.HTTPConnection | None = None
    t0 = time.perf_counter()
    try:
        if u.scheme == "https":
            conn = http.client.HTTPSConnection(
                host,
                u.port or 443,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
        else:
            conn = http.client.HTTPConnection(host, u.port or 80, timeout=timeout)
        conn.request(
            "GET", path, headers={"User-Agent": "scout-uptime", "Accept": "*/*"}
        )
        r = conn.getresponse()
        body = r.read(read_cap)
        ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "http": int(r.status),
            "latency_ms": ms,
            "error": None,
            "body_head": body.decode("utf-8", errors="replace"),
        }
    except Exception as e:
        ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "http": None,
            "latency_ms": ms,
            "error": f"{type(e).__name__}: {e}",
            "body_head": "",
        }
    finally:
        if conn is not None:
            conn.close()


@app.command("hello", epilog=examples_epilog(["scout --json uptime hello"]))
def hello():
    """Smoke check — is the uptime surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "uptime"},
            command="uptime hello",
            example="scout --json uptime check",
            discover="scout uptime detect",
        ),
        command="uptime hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json uptime detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="uptime detect",
            example="scout --json uptime check",
            discover="scout uptime targets",
        ),
        command="uptime detect",
    )


@app.command(
    "targets",
    epilog=examples_epilog(
        [
            "scout --json uptime targets",
            "scout --json uptime targets --targets org-targets.json",
        ]
    ),
)
def targets_cmd(
    targets_file: str | None = typer.Option(
        None, "--targets", help="JSON targets overlay (policy-as-config)"
    ),
):
    """Show the effective monitored set (defaults + optional JSON overlay)."""
    targets = _targets_or_fail(targets_file, "uptime targets")
    emit(
        ok(
            {"targets": targets, "count": len(targets), "overlay": targets_file},
            command="uptime targets",
            example="scout --json uptime check",
            discover="scout uptime check",
        ),
        command="uptime targets",
    )


@app.command(
    "check",
    epilog=examples_epilog(
        [
            "scout --json uptime check",
            "scout --json uptime check --url https://dumbmodel.com",
            "scout --json uptime check --targets org-targets.json --fail-down",
        ]
    ),
)
def check(
    targets_file: str | None = typer.Option(
        None, "--targets", help="JSON targets overlay (policy-as-config)"
    ),
    url: str | None = typer.Option(
        None, "--url", help="probe one ad-hoc URL instead of the target set"
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"sqlite ledger path (default {uptime.DB_REL} or $SCOUT_UPTIME_DB)",
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="per-probe socket timeout, seconds"
    ),
    damping: int = typer.Option(
        uptime.DEFAULT_DAMPING,
        "--damping",
        help="consecutive identical observations required to change a confirmed state",
    ),
    record: bool = typer.Option(
        True,
        "--record/--no-record",
        help="persist to the ledger (off = probe-and-report only)",
    ),
    fail_down: bool = typer.Option(
        False,
        "--fail-down",
        help="exit 1 if any target is confirmed down — the cron/CI gate hook",
    ),
):
    """One probe pass over the fleet: record, damp, report transitions."""
    sanitize_no_proxy_env()
    if url:
        # user-typed URL: gated by the persisted user allowlist, never by a
        # manifest widened to match the URL being checked (policy doctrine)
        enforce_user_url_or_raise(url, context="uptime check")
        targets = {urlsplit(url).hostname or "adhoc": {"url": url}}
    else:
        targets = _targets_or_fail(targets_file, "uptime check")
        for cfg in targets.values():
            enforce_or_raise(_manifest(), "network", cfg["url"])
    if record:
        conn, path = _open_ledger(db)
    else:
        conn, path = uptime.open_ledger(":memory:"), None  # dry-run, same pipeline

    def probe(u: str, cfg: dict) -> dict:
        return _probe(u, timeout=timeout)

    res = uptime.run_pass(conn, targets, probe, damping=damping)
    diags = uptime.to_diagnostics(res["results"])
    by_state: dict[str, int] = {}
    for r in res["results"]:
        by_state[r["confirmed"]] = by_state.get(r["confirmed"], 0) + 1
    emit(
        ok(
            {
                "db": str(path) if path else None,
                "recorded": record,
                "damping": damping,
                "by_state": by_state,
                "results": res["results"],
                "transitions": res["transitions"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="uptime check",
            example="scout --json uptime status",
            discover="scout uptime status",
        ),
        command="uptime check",
    )
    if fail_down and by_state.get(uptime.STATE_DOWN):
        raise typer.Exit(code=1)


@app.command(
    "watch",
    epilog=examples_epilog(
        [
            "scout uptime watch --interval 60 --count 10",
            "scout --json uptime watch --interval 300 --count 0  # forever, Ctrl+C stops",
        ]
    ),
)
def watch(
    interval: float = typer.Option(
        60.0, "--interval", help="seconds between passes (min 1)"
    ),
    count: int = typer.Option(
        10, "--count", help="passes to run; 0 = run until Ctrl+C (daemon mode)"
    ),
    targets_file: str | None = typer.Option(
        None, "--targets", help="JSON targets overlay (policy-as-config)"
    ),
    db: str | None = typer.Option(None, "--db", help="sqlite ledger path"),
    timeout: float = typer.Option(
        10.0, "--timeout", help="per-probe socket timeout, seconds"
    ),
    damping: int = typer.Option(
        uptime.DEFAULT_DAMPING, "--damping", help="flap-damping window"
    ),
):
    """sched-loop daemon: repeated passes into the ledger; transitions on stderr."""
    sanitize_no_proxy_env()
    if interval < 1:
        fail_agent(
            "--interval must be >= 1 second",
            command="uptime watch",
            example="scout uptime watch --interval 60 --count 10",
        )
    targets = _targets_or_fail(targets_file, "uptime watch")
    for cfg in targets.values():
        enforce_or_raise(_manifest(), "network", cfg["url"])
    conn, path = _open_ledger(db)

    def probe(u: str, cfg: dict) -> dict:
        return _probe(u, timeout=timeout)

    stats = {"passes": 0, "checks": 0, "transitions": 0}
    scheduler = sched.scheduler(time.time, time.sleep)

    def _tick():
        res = uptime.run_pass(conn, targets, probe, damping=damping)
        stats["passes"] += 1
        stats["checks"] += len(res["results"])
        stats["transitions"] += len(res["transitions"])
        line = ", ".join(f"{r['target']}:{r['confirmed']}" for r in res["results"])
        # stderr keeps --json stdout a single envelope while staying tailable
        typer.secho(f"[uptime] pass {stats['passes']}: {line}", err=True)
        for tr in res["transitions"]:
            typer.secho(
                f"[uptime] TRANSITION {tr['target']}: {tr['prev']} -> {tr['state']}"
                f" (incident: {tr['incident']})",
                fg=typer.colors.YELLOW,
                err=True,
            )
        if count == 0 or stats["passes"] < count:
            scheduler.enter(interval, 1, _tick)

    scheduler.enter(0, 1, _tick)
    try:
        scheduler.run()
    except KeyboardInterrupt:
        pass  # daemon stop is a normal exit: emit the summary we have
    emit(
        ok(
            {"db": str(path), **stats, "board": uptime.board(conn, targets)},
            command="uptime watch",
            example="scout --json uptime status",
            discover="scout uptime status",
        ),
        command="uptime watch",
    )


@app.command(
    "status",
    epilog=examples_epilog(
        ["scout --json uptime status", "scout --json uptime status --hours 168"]
    ),
)
def status(
    targets_file: str | None = typer.Option(
        None, "--targets", help="JSON targets overlay (policy-as-config)"
    ),
    db: str | None = typer.Option(None, "--db", help="sqlite ledger path"),
    hours: float = typer.Option(
        24.0, "--hours", help="availability/latency rollup window"
    ),
):
    """Status board from the ledger — no probes, no network."""
    targets = _targets_or_fail(targets_file, "uptime status")
    conn, path = _open_existing(db, "uptime status")
    since = time.time() - hours * 3600.0
    rows = uptime.board(conn, targets)
    for row in rows:
        row["rollup"] = uptime.rollup(conn, row["target"], since=since)
    emit(
        ok(
            {
                "db": str(path),
                "window_hours": hours,
                "board": rows,
                "open_incidents": uptime.list_incidents(conn, open_only=True),
                "events": uptime.recent_events(conn, limit=5),
            },
            command="uptime status",
            example="scout --json uptime history bhenre",
            discover="scout uptime history <target>",
        ),
        command="uptime status",
    )


@app.command(
    "history",
    epilog=examples_epilog(
        [
            "scout --json uptime history bhenre",
            "scout --json uptime history ollama --limit 50 --hours 168",
        ]
    ),
)
def history(
    target: str = typer.Argument(..., help="target name (see: scout uptime targets)"),
    db: str | None = typer.Option(None, "--db", help="sqlite ledger path"),
    limit: int = typer.Option(20, "--limit", help="checks to return (newest first)"),
    hours: float = typer.Option(24.0, "--hours", help="rollup window"),
):
    """Recent checks + percentile rollup + incidents for one target."""
    conn, path = _open_existing(db, "uptime history")
    checks = uptime.recent_checks(conn, target, limit=limit)
    if not checks:
        fail_agent(
            f"no checks recorded for target {target!r}",
            command="uptime history",
            example="scout --json uptime check",
            discover="scout uptime targets",
        )
    since = time.time() - hours * 3600.0
    emit(
        ok(
            {
                "db": str(path),
                "target": target,
                "checks": checks,
                "rollup": uptime.rollup(conn, target, since=since),
                "incidents": uptime.list_incidents(conn, target=target, limit=10),
                "events": uptime.recent_events(conn, target=target, limit=10),
            },
            command="uptime history",
            example="scout --json uptime status",
            discover="scout uptime status",
        ),
        command="uptime history",
    )


@app.command(
    "mark",
    epilog=examples_epilog(
        [
            'scout --json uptime mark "deploy bhenre 4009c52" --target bhenre',
            'scout --json uptime mark "WSL GPU stack degraded" --kind note',
        ]
    ),
)
def mark(
    message: str = typer.Argument(..., help="what happened (e.g. deploy sha, ops note)"),
    kind: str = typer.Option("deploy", "--kind", help="event kind (deploy|note|...)"),
    target: str | None = typer.Option(
        None, "--target", help="scope to one target (default: global)"
    ),
    db: str | None = typer.Option(None, "--db", help="sqlite ledger path"),
):
    """Drop a marker event on the monitoring timeline (deploys, ops notes)."""
    conn, path = _open_ledger(db)
    event_id = uptime.record_event(conn, kind=kind, message=message, target=target)
    emit(
        ok(
            {"event_id": event_id, "kind": kind, "target": target, "db": str(path)},
            command="uptime mark",
            example="scout --json uptime history " + (target or "<target>"),
            discover="scout uptime status",
        ),
        command="uptime mark",
    )


def register(root):
    root.add_typer(app, name="uptime")
