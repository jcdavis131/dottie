# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout heartbeat` — Healthchecks.io/Cronitor replacement, fully local (openswap #6).

Dead-man's-switch with the SaaS inverted out: daemons beat into the shared
monitoring ledger (`scout heartbeat beat trainer` — or just touch a file), and
the watcher sweep flags anything silent past its per-daemon grace period from
JSON config. All the deterministic logic (registry, staleness verdicts, the
shared #2 state machine/incidents/alert events) lives in
bigbang/core/heartbeat.py; the only real I/O here is the optional LOOPBACK
http.server check-in endpoint for processes that prefer HTTP beats. There is
no native binary tier to prefer: Healthchecks' open-source release is a Django
web app, not a CLI, so the stdlib core IS the product and `detect` reports
tier=fallback as the expected steady state (scope honesty, not degradation).

Policy: this plugin never makes an outbound call — a dead-man's-switch that
phones out is the paid enemy's architecture. The manifest's network axis
allows loopback only, and `serve` refuses any non-loopback bind before
enforce_or_raise even sees it. runitor (the healthchecks.io SaaS pinger) is
probed and surfaced by `detect` for awareness but never executed: its whole
job is the forbidden network tier.
"""

from __future__ import annotations

import http.server
import json
import os
import sched
import time
from pathlib import Path

import typer

from bigbang.core import heartbeat, openswap, uptime
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib registry is the complete product for this adapter: one-line "
    "beats (sqlite row, file mtime, or loopback HTTP), per-daemon grace "
    "periods as JSON config, stale watcher writing alerts/incidents into the "
    "shared uptime ledger; tier 'fallback' is the expected steady state "
    "(Healthchecks' open-source release is a Django server — no CLI binary "
    "exists to prefer)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; self-host the "
    "Healthchecks Django app separately only if you want its web dashboard"
)

app = make_plugin_app(
    "heartbeat",
    "Dead-man's-switch for the org daemons (Healthchecks-class), fully local: "
    "stdlib beats + stale watcher on the shared uptime ledger",
    examples=[
        "scout --json heartbeat beat trainer",
        "scout --json heartbeat sweep --fail-stale",
        "scout --json heartbeat status",
        "scout heartbeat watch --interval 300 --count 12",
        "scout heartbeat serve --port 8043",
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
    # No CLI distribution of Healthchecks exists, so `native` stays a truthful
    # probe that reports absent; runitor is surfaced as an extra but NEVER
    # executed — it exists to ping the paid SaaS (the forbidden network tier).
    native = openswap.probe_binary("healthchecks", probe_args=("--version",))
    extras = {"runitor": openswap.probe_binary("runitor", probe_args=("-version",))}
    return openswap.capability_report(
        "heartbeat",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    # the SHARED monitoring ledger (#2): same default, same env override
    return Path(db or os.environ.get("SCOUT_UPTIME_DB") or uptime.DB_REL)


def _open_registry(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return heartbeat.open_registry(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no monitoring ledger at {path} — record a beat or sweep first",
            command=command,
            example="scout --json heartbeat beat trainer",
        )
    return heartbeat.open_registry(path), path


def _daemons_or_fail(daemons_file: str | None, command: str) -> dict:
    try:
        return heartbeat.load_daemons(daemons_file)
    except Exception as e:
        fail_agent(
            f"bad daemons file: {e}",
            command=command,
            example="scout --json heartbeat sweep --daemons org-daemons.json",
        )


@app.command("hello", epilog=examples_epilog(["scout --json heartbeat hello"]))
def hello():
    """Smoke check — is the heartbeat surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "heartbeat"},
            command="heartbeat hello",
            example="scout --json heartbeat beat trainer",
            discover="scout heartbeat detect",
        ),
        command="heartbeat hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json heartbeat detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="heartbeat detect",
            example="scout --json heartbeat beat trainer",
            discover="scout heartbeat daemons",
        ),
        command="heartbeat detect",
    )


@app.command(
    "daemons",
    epilog=examples_epilog(
        [
            "scout --json heartbeat daemons",
            "scout --json heartbeat daemons --daemons org-daemons.json",
        ]
    ),
)
def daemons_cmd(
    daemons_file: str | None = typer.Option(
        None, "--daemons", help="JSON daemons overlay (policy-as-config)"
    ),
):
    """Show the effective watched set (defaults + optional JSON overlay)."""
    daemons = _daemons_or_fail(daemons_file, "heartbeat daemons")
    emit(
        ok(
            {"daemons": daemons, "count": len(daemons), "overlay": daemons_file},
            command="heartbeat daemons",
            example="scout --json heartbeat sweep",
            discover="scout heartbeat sweep",
        ),
        command="heartbeat daemons",
    )


@app.command(
    "beat",
    epilog=examples_epilog(
        [
            "scout --json heartbeat beat trainer",
            'scout --json heartbeat beat research-loop --note "cycle 42 done"',
        ]
    ),
)
def beat_cmd(
    daemon: str = typer.Argument(..., help="daemon name ([a-z0-9][a-z0-9._-]*)"),
    note: str | None = typer.Option(
        None, "--note", help="freeform status note kept on the registry row"
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"shared ledger path (default {uptime.DB_REL} or $SCOUT_UPTIME_DB)",
    ),
):
    """The one-line check-in: record a beat for one daemon. No network."""
    conn, path = _open_registry(db)
    try:
        b = heartbeat.beat(conn, daemon, note=note)
    except ValueError as e:
        fail_agent(
            str(e),
            command="heartbeat beat",
            example="scout --json heartbeat beat trainer",
        )
    emit(
        ok(
            {**b, "db": str(path)},
            command="heartbeat beat",
            example="scout --json heartbeat status",
            discover="scout heartbeat status",
        ),
        command="heartbeat beat",
    )


@app.command(
    "sweep",
    epilog=examples_epilog(
        [
            "scout --json heartbeat sweep",
            "scout --json heartbeat sweep --daemons org-daemons.json --fail-stale",
        ]
    ),
)
def sweep_cmd(
    daemons_file: str | None = typer.Option(
        None, "--daemons", help="JSON daemons overlay (policy-as-config)"
    ),
    db: str | None = typer.Option(None, "--db", help="shared ledger path"),
    fail_stale: bool = typer.Option(
        False,
        "--fail-stale",
        help="exit 1 if any daemon is stale — the cron/CI gate hook",
    ),
):
    """One watcher pass: verdicts, incidents, alert records. No network."""
    daemons = _daemons_or_fail(daemons_file, "heartbeat sweep")
    conn, path = _open_registry(db)
    res = heartbeat.sweep(conn, daemons)
    diags = heartbeat.to_diagnostics(res["results"])
    by_status: dict[str, int] = {}
    for r in res["results"]:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    emit(
        ok(
            {
                "db": str(path),
                "by_status": by_status,
                "results": res["results"],
                "alerts": res["alerts"],
                "transitions": res["transitions"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="heartbeat sweep",
            example="scout --json heartbeat status",
            discover="scout heartbeat status",
        ),
        command="heartbeat sweep",
    )
    if fail_stale and by_status.get(heartbeat.STATUS_STALE):
        raise typer.Exit(code=1)


@app.command(
    "watch",
    epilog=examples_epilog(
        [
            "scout heartbeat watch --interval 300 --count 12",
            "scout heartbeat watch --interval 300 --count 0  # forever, Ctrl+C stops",
        ]
    ),
)
def watch(
    interval: float = typer.Option(
        300.0, "--interval", help="seconds between sweeps (min 1)"
    ),
    count: int = typer.Option(
        12, "--count", help="sweeps to run; 0 = run until Ctrl+C (daemon mode)"
    ),
    daemons_file: str | None = typer.Option(
        None, "--daemons", help="JSON daemons overlay (policy-as-config)"
    ),
    db: str | None = typer.Option(None, "--db", help="shared ledger path"),
):
    """sched-loop watcher: repeated sweeps into the ledger; alerts on stderr."""
    if interval < 1:
        fail_agent(
            "--interval must be >= 1 second",
            command="heartbeat watch",
            example="scout heartbeat watch --interval 300 --count 12",
        )
    daemons = _daemons_or_fail(daemons_file, "heartbeat watch")
    conn, path = _open_registry(db)
    stats = {"sweeps": 0, "daemons": len(daemons), "alerts": 0}
    scheduler = sched.scheduler(time.time, time.sleep)

    def _tick():
        res = heartbeat.sweep(conn, daemons)
        stats["sweeps"] += 1
        stats["alerts"] += len(res["alerts"])
        line = ", ".join(f"{r['daemon']}:{r['status']}" for r in res["results"])
        # stderr keeps --json stdout a single envelope while staying tailable
        typer.secho(f"[heartbeat] sweep {stats['sweeps']}: {line}", err=True)
        for a in res["alerts"]:
            typer.secho(
                f"[heartbeat] {a['kind'].upper()} {a['message']}",
                fg=typer.colors.YELLOW,
                err=True,
            )
        if count == 0 or stats["sweeps"] < count:
            scheduler.enter(interval, 1, _tick)

    scheduler.enter(0, 1, _tick)
    try:
        scheduler.run()
    except KeyboardInterrupt:
        pass  # daemon stop is a normal exit: emit the summary we have
    emit(
        ok(
            {"db": str(path), **stats, "board": heartbeat.board(conn, daemons)},
            command="heartbeat watch",
            example="scout --json heartbeat status",
            discover="scout heartbeat status",
        ),
        command="heartbeat watch",
    )


@app.command(
    "status",
    epilog=examples_epilog(
        ["scout --json heartbeat status", "scout --json heartbeat status --db x.db"]
    ),
)
def status(
    daemons_file: str | None = typer.Option(
        None, "--daemons", help="JSON daemons overlay (policy-as-config)"
    ),
    db: str | None = typer.Option(None, "--db", help="shared ledger path"),
):
    """Liveness board from the ledger — read-only, no sweeps, no network."""
    daemons = _daemons_or_fail(daemons_file, "heartbeat status")
    conn, path = _open_existing(db, "heartbeat status")
    rows = heartbeat.board(conn, daemons)
    emit(
        ok(
            {
                "db": str(path),
                "board": rows,
                "open_incidents": uptime.list_incidents(conn, open_only=True),
                "events": uptime.recent_events(conn, limit=5),
            },
            command="heartbeat status",
            example="scout --json heartbeat sweep",
            discover="scout heartbeat sweep",
        ),
        command="heartbeat status",
    )


@app.command(
    "serve",
    epilog=examples_epilog(
        [
            "scout heartbeat serve --port 8043",
            "scout heartbeat serve --port 8043 --max-requests 100",
        ]
    ),
)
def serve(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="bind address — loopback only, by design"
    ),
    port: int = typer.Option(8043, "--port", help="TCP port for GET /beat/<daemon>"),
    db: str | None = typer.Option(None, "--db", help="shared ledger path"),
    max_requests: int = typer.Option(
        0, "--max-requests", help="requests to serve; 0 = run until Ctrl+C"
    ),
):
    """Optional LOOPBACK check-in endpoint for daemons that prefer HTTP beats."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        # architectural privacy: refuse before policy even looks at it — a
        # dead-man's-switch reachable off-box is the paid enemy's shape
        fail_agent(
            f"refusing non-loopback bind {host!r} — heartbeat serves 127.0.0.1 only",
            command="heartbeat serve",
            example="scout heartbeat serve --port 8043",
        )
    enforce_or_raise(_manifest(), "network", f"http://{host}:{port}/")
    conn, path = _open_registry(db)
    stats = {"requests": 0, "beats": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # http.server's required method casing
            code, payload = heartbeat.route_request(conn, self.path)
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            stats["requests"] += 1
            if code == 200 and payload.get("daemon"):
                stats["beats"] += 1

        def log_message(self, fmt, *args):
            typer.secho(f"[heartbeat] {fmt % args}", err=True)

    server = http.server.HTTPServer((host, port), Handler)
    typer.secho(
        f"[heartbeat] serving http://{host}:{port}/beat/<daemon> -> {path}", err=True
    )
    try:
        while max_requests == 0 or stats["requests"] < max_requests:
            server.handle_request()
    except KeyboardInterrupt:
        pass  # daemon stop is a normal exit: emit the summary we have
    finally:
        server.server_close()
    emit(
        ok(
            {"db": str(path), "host": host, "port": port, **stats},
            command="heartbeat serve",
            example="scout --json heartbeat status",
            discover="scout heartbeat status",
        ),
        command="heartbeat serve",
    )


def register(root):
    root.add_typer(app, name="heartbeat")
