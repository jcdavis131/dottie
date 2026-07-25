# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout smoke` — Checkly replacement, fully local (openswap #5).

Post-deploy smoke doctrine as a gate with zero install: a per-site smoke.json
maps each deployed URL to an expected string; urllib GETs (redirects followed —
smoke asserts on what a visitor receives) poll under a bounded retry/backoff
budget, and `run` exits nonzero with a per-URL pass/fail report — wire it right
after every `vercel deploy`. Everything deterministic lives in
bigbang/core/smoke.py (manifest parsing, backoff schedule, attempt
classification, retry loop, family diagnostics); the only real I/O — the fetch
and the optional deploy-marker write into the uptime ledger (#2) — lives here.

There is no native binary tier to prefer: Checkly's own CLI is the paid enemy's
SaaS client, and open native runners (hurl) are surfaced by `detect` for manual
use but never executed — a spawned binary fetches outside the per-URL policy
gate (the links #4 doctrine). So the stdlib core IS the product and tier
'fallback' is the expected steady state.

Policy: every manifest check URL is gated by enforce_or_raise against this
plugin's manifest domain allowlist (default-deny — a smoke.json naming a new
host means adding its domain to manifest.yaml too); an ad-hoc --url/--expect
check is user-typed and is instead gated by the persisted user allowlist
(enforce_user_url_or_raise). `plan` makes no network calls at all.
"""

from __future__ import annotations

import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import typer

from bigbang.core import openswap, smoke, uptime
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
    "pure-stdlib smoke gate is the complete product for this adapter: JSON "
    "manifest of URL->expected-string checks, urllib polling under a bounded "
    "retry/backoff budget, optional max_ms latency assertions, nonzero exit "
    "with a per-URL pass/fail report, and deploy markers into the shared "
    "uptime ledger; tier 'fallback' is the expected steady state — Checkly's "
    "CLI is a SaaS client (a forbidden network tier) and native runners "
    "(hurl) are surfaced for manual use but never executed, because a spawned "
    "binary fetches outside the per-URL policy gate"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; hurl on PATH is "
    "surfaced for manual use only, never executed by scout"
)

app = make_plugin_app(
    "smoke",
    "Post-deploy smoke gate (Checkly-class), fully local: expected-string checks under a bounded retry budget",
    examples=[
        "scout --json smoke run --manifest smoke.json",
        'scout --json smoke run --manifest smoke.json --mark "deploy bhenre 4009c52"',
        'scout --json smoke run --url https://www.bhenre.com --expect "bhenre"',
        "scout --json smoke plan --manifest smoke.json",
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
    # Probes are truthful; execution stays stdlib regardless (module doc).
    native = openswap.probe_binary("hurl", probe_args=("--version",))
    extras = {"curl": openswap.probe_binary("curl", probe_args=("--version",))}
    return openswap.capability_report(
        "smoke",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _checks_or_fail(manifest_file: str, command: str) -> dict:
    if not Path(manifest_file).exists():
        fail_agent(
            f"no smoke manifest at {manifest_file} — write one next to the site"
            ' (e.g. {"https://www.bhenre.com": "bhenre"})',
            command=command,
            example="scout --json smoke run --manifest smoke.json",
        )
    try:
        return smoke.load_checks(manifest_file)
    except Exception as e:
        fail_agent(
            f"bad smoke manifest: {e}",
            command=command,
            example='echo {"https://www.bhenre.com": "bhenre"} > smoke.json',
        )


def _ledger(db: str | None) -> tuple:
    path = Path(db or os.environ.get("SCOUT_UPTIME_DB") or uptime.DB_REL)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return uptime.open_ledger(path), path


def _fetch(url: str, *, timeout: float = 10.0, read_cap: int = 262144) -> dict:
    """One GET via urllib. Returns {http, latency_ms, error, body_head}.

    Redirects ARE followed (unlike uptime's liveness probe) — smoke asserts on
    the content a visitor receives, so the final status must be 2xx. HTTPError
    is an answer, not an outage: a 404 must classify as http-fail, never
    unreachable. The body is read only up to read_cap bytes — enough for the
    expected-string check without pulling whole pages.
    """
    # S310 (file:/custom schemes): closed upstream — load_checks admits http(s)
    # only and every URL is policy-gated before this fetch runs
    req = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": "scout-smoke", "Accept": "*/*"}, method="GET"
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(  # noqa: S310
            req, timeout=timeout, context=ssl.create_default_context()
        ) as r:
            body = r.read(read_cap)
            ms = round((time.perf_counter() - t0) * 1000.0, 1)
            return {
                "http": int(r.status),
                "latency_ms": ms,
                "error": None,
                "body_head": body.decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as e:
        body = e.read(read_cap)
        ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "http": int(e.code),
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


@app.command("hello", epilog=examples_epilog(["scout --json smoke hello"]))
def hello():
    """Smoke check — is the smoke surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "smoke"},
            command="smoke hello",
            example="scout --json smoke plan --manifest smoke.json",
            discover="scout smoke detect",
        ),
        command="smoke hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json smoke detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="smoke detect",
            example="scout --json smoke run --manifest smoke.json",
            discover="scout smoke plan --manifest smoke.json",
        ),
        command="smoke detect",
    )


@app.command(
    "plan",
    epilog=examples_epilog(
        [
            "scout --json smoke plan --manifest smoke.json",
            "scout --json smoke plan --manifest smoke.json --attempts 8 --budget 300",
        ]
    ),
)
def plan(
    manifest_file: str = typer.Option(
        smoke.MANIFEST_REL, "--manifest", help="per-site smoke manifest (JSON)"
    ),
    attempts: int = typer.Option(
        smoke.DEFAULT_ATTEMPTS, "--attempts", help="max polls per URL"
    ),
    initial_delay: float = typer.Option(
        smoke.DEFAULT_INITIAL_DELAY_S, "--initial-delay", help="first retry delay, s"
    ),
    multiplier: float = typer.Option(
        smoke.DEFAULT_MULTIPLIER, "--backoff", help="delay multiplier per retry"
    ),
    max_delay: float = typer.Option(
        smoke.DEFAULT_MAX_DELAY_S, "--max-delay", help="per-retry delay cap, s"
    ),
    budget: float = typer.Option(
        smoke.DEFAULT_BUDGET_S, "--budget", help="per-check wall-clock budget, s"
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="per-fetch socket timeout, s"
    ),
):
    """Parse the manifest and show the resolved retry plan — no network, no writes."""
    checks = _checks_or_fail(manifest_file, "smoke plan")
    delays = smoke.backoff_delays(
        attempts, initial=initial_delay, multiplier=multiplier, max_delay=max_delay
    )
    emit(
        ok(
            {
                "manifest": manifest_file,
                "count": len(checks),
                "checks": checks,
                "retry": {
                    "attempts": attempts,
                    "delays": delays,
                    "budget_s": budget,
                    # what CI should reserve per check before giving up
                    "worst_case_s": round(
                        min(sum(delays), budget) + attempts * timeout, 1
                    ),
                },
            },
            command="smoke plan",
            example=f"scout --json smoke run --manifest {manifest_file}",
            discover="scout smoke detect",
        ),
        command="smoke plan",
    )


@app.command(
    "run",
    epilog=examples_epilog(
        [
            "scout --json smoke run --manifest smoke.json",
            'scout --json smoke run --manifest smoke.json --mark "deploy bhenre 4009c52"',
            'scout --json smoke run --url https://www.bhenre.com --expect "bhenre"',
            "scout --json smoke run --manifest smoke.json --no-fail  # report only",
        ]
    ),
)
def run(
    manifest_file: str = typer.Option(
        smoke.MANIFEST_REL, "--manifest", help="per-site smoke manifest (JSON)"
    ),
    url: str | None = typer.Option(
        None, "--url", help="check one ad-hoc URL instead of the manifest"
    ),
    expect: str | None = typer.Option(
        None, "--expect", help="expected string for --url"
    ),
    attempts: int = typer.Option(
        smoke.DEFAULT_ATTEMPTS, "--attempts", help="max polls per URL"
    ),
    initial_delay: float = typer.Option(
        smoke.DEFAULT_INITIAL_DELAY_S, "--initial-delay", help="first retry delay, s"
    ),
    multiplier: float = typer.Option(
        smoke.DEFAULT_MULTIPLIER, "--backoff", help="delay multiplier per retry"
    ),
    max_delay: float = typer.Option(
        smoke.DEFAULT_MAX_DELAY_S, "--max-delay", help="per-retry delay cap, s"
    ),
    budget: float = typer.Option(
        smoke.DEFAULT_BUDGET_S, "--budget", help="per-check wall-clock budget, s"
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="per-fetch socket timeout, s"
    ),
    fail: bool = typer.Option(
        True,
        "--fail/--no-fail",
        help="exit 1 when any check fails — the post-deploy gate (default on)",
    ),
    mark: str | None = typer.Option(
        None,
        "--mark",
        help='deploy marker for the uptime ledger timeline (e.g. "deploy bhenre <sha>")',
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"uptime ledger path for --mark (default {uptime.DB_REL} or $SCOUT_UPTIME_DB)",
    ),
):
    """Poll every check until its expected string matches or the budget exhausts."""
    sanitize_no_proxy_env()
    if attempts < 1 or budget <= 0 or initial_delay <= 0 or multiplier < 1:
        fail_agent(
            "need --attempts >= 1, --budget > 0, --initial-delay > 0, --backoff >= 1",
            command="smoke run",
            example="scout --json smoke run --manifest smoke.json --attempts 5",
        )
    if url or expect:
        if not (url and expect):
            fail_agent(
                "--url and --expect go together",
                command="smoke run",
                example='scout --json smoke run --url https://www.bhenre.com --expect "bhenre"',
            )
        # user-typed URL: gated by the persisted user allowlist, never by a
        # manifest widened to match the URL being checked (policy doctrine)
        enforce_user_url_or_raise(url, context="smoke run")
        checks = {urlsplit(url).hostname or "adhoc": {"url": url, "expect": expect}}
        source = "--url"
    else:
        checks = _checks_or_fail(manifest_file, "smoke run")
        for cfg in checks.values():
            enforce_or_raise(_manifest(), "network", cfg["url"])
        source = manifest_file
    marked = None
    if mark:
        conn, path = _ledger(db)
        deploy_id = uptime.record_event(conn, kind="deploy", message=mark)
        marked = {"db": str(path), "deploy_event_id": deploy_id}

    def fetch(u: str, cfg: dict) -> dict:
        return _fetch(u, timeout=timeout)

    res = smoke.run_suite(
        checks,
        fetch,
        attempts=attempts,
        initial_delay=initial_delay,
        multiplier=multiplier,
        max_delay=max_delay,
        budget_s=budget,
    )
    diags = smoke.to_diagnostics(res["results"])
    if mark:
        verdict = "pass" if res["ok"] else "fail"
        outcome_id = uptime.record_event(
            conn,
            kind="smoke",
            message=f"{mark} — smoke {verdict} {res['passed']}/{res['total']}",
        )
        marked["smoke_event_id"] = outcome_id
    emit(
        ok(
            {
                "manifest": source,
                "gate": "fail" if fail else "report-only",
                "passed": res["passed"],
                "failed": res["failed"],
                "total": res["total"],
                "results": res["results"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
                "marked": marked,
            },
            command="smoke run",
            example="scout --json uptime status",
            discover="scout uptime status",
        ),
        command="smoke run",
    )
    if fail and not res["ok"]:
        raise typer.Exit(code=1)


def register(root):
    root.add_typer(app, name="smoke")
