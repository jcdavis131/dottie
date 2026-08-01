# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout headers` — Detectify / Burp Suite Pro (surface) replacement, fully
local (openswap #22).

The hosted scanner is deleted: one urllib GET happens on THIS box (the only real
I/O, and it lives here in _fetch), and every judgment — CSP, HSTS, X-Frame-
Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, CORS
exposure, Set-Cookie flags, directory-listing signatures, http:// mixed content —
runs deterministically in bigbang/core/headers.py, which never opens a socket.
There is no native binary tier to prefer: Detectify is SaaS and Burp Suite Pro is
the paid GUI being replaced, so the stdlib core IS the product and `detect`
reports tier=fallback as the expected steady state (scope honesty, not
degradation). nuclei is surfaced as an optional local helper but NEVER executed
beyond a version probe — it fetches its template pack from the network, which is
the tier this family forbids.

Substrate reuse, not a parallel store: `scan` history lands in ONE additive
`header_scans` table on the shared #3 crawl store (.scout/seo.db), and `audit`
re-reads the `pages` rows `seo crawl` already wrote — the extension point the seo
core documents ("audit CSP/HSTS from the store, zero refetches"). So the cheap
fleet-wide sweep costs no requests at all, and its two honest limits (no body in
the store, and seo collapses repeated Set-Cookie headers into one) are reported
in every payload as `caveats` rather than being quietly graded as clean.

Policy: a named site's URLs are gated by enforce_or_raise against this plugin's
manifest domain allowlist (the SAME domains as seo — same fleet, same store); an
ad-hoc --url scan is user-typed and is instead gated by the persisted user
allowlist (enforce_user_url_or_raise), never by a manifest widened to match the
target. Every probe URL is re-checked at the I/O boundary, and `audit`/`status`
make no network calls whatsoever.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import typer

from bigbang.core import headers as hdr
from bigbang.core import openswap, seo
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
    "pure-stdlib response auditing is the complete product for this adapter: "
    "urllib GET with the redirect chain recorded, CSP parse (default-src "
    "fallback, unsafe-inline/eval, wildcard sources, Report-Only, duplicates), "
    "HSTS max-age/includeSubDomains/preload, X-Frame-Options + frame-ancestors, "
    "nosniff, Referrer-Policy, Permissions-Policy, CORS wildcard, Server banner, "
    "per-cookie Secure/HttpOnly/SameSite and __Host-/__Secure- prefixes, "
    "directory-listing signatures, active/passive mixed content, A+..F grade and "
    "sqlite scan history on the shared crawl store; tier 'fallback' is the "
    "expected steady state (Detectify is SaaS and Burp Suite Pro is the paid GUI "
    "— no local native binary is a superset of this core)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; nuclei on PATH is "
    "surfaced as an optional local helper (never required, never executed)"
)

app = make_plugin_app(
    "headers",
    "Audit response security headers and exposed surface (Detectify-class), "
    "fully local: stdlib GET + CSP/HSTS/cookie/mixed-content analysis on the "
    "shared seo crawl store",
    examples=[
        "scout --json headers scan bhenre",
        "scout --json headers scan bhenre --dirs --fail-on error",
        "scout --json headers audit bhenre",
        "scout --json headers status",
        "scout --json headers detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only on use
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # No native CLI is a superset of this core (Detectify is SaaS, Burp Suite Pro
    # is a paid GUI), so `native` stays a truthful probe that reports absent.
    # shcheck is the closest open header checker; nuclei is surfaced for
    # awareness but NEVER executed beyond --version (it pulls its template pack
    # over the network — the forbidden tier).
    native = openswap.probe_binary("shcheck", probe_args=("--help",))
    extras = {
        "curl": openswap.probe_binary("curl", probe_args=("--version",)),
        "nuclei": openswap.probe_binary("nuclei", probe_args=("-version",)),
    }
    return openswap.capability_report(
        "headers",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    # the SHARED crawl store (#3): same default, same env override as seo
    return Path(db or os.environ.get("SCOUT_SEO_DB") or seo.DB_REL)


def _open_store(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return hdr.open_headers_store(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no crawl store at {path} — scan or crawl first",
            command=command,
            example="scout --json headers scan bhenre",
            discover="scout headers sites",
        )
    return hdr.open_headers_store(path), path


def _resolve_site(site: str | None, url: str | None, command: str) -> tuple[str, bool]:
    """(start_url, named) — exactly one of site-name / --url must be given."""
    if bool(site) == bool(url):
        fail_agent(
            "give a site name OR --url (see: scout headers sites)",
            command=command,
            example=f"scout --json {command} bhenre",
            discover="scout headers sites",
        )
    sites = hdr.default_sites()
    if site:
        if site not in sites:
            fail_agent(
                f"unknown site {site!r} — one of: " + ", ".join(sorted(sites)),
                command=command,
                example=f"scout --json {command} bhenre",
                discover="scout headers sites",
            )
        return sites[site], True
    return url, False


def _config_or_fail(config_file: str | None, command: str) -> dict:
    try:
        return hdr.load_config(config_file)
    except Exception as e:
        fail_agent(
            f"bad config file: {e}",
            command=command,
            example=f"scout --json {command} bhenre --config headers.json",
        )


def _fail_on_or_fail(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=f"scout --json {command} bhenre --fail-on error",
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    gate_rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
        raise typer.Exit(code=1)


class _RedirectRecorder(urllib.request.HTTPRedirectHandler):
    """Follow redirects normally while recording each hop for the verdict."""

    def __init__(self) -> None:
        super().__init__()
        self.hops: list[dict] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops.append({"code": int(code), "to": newurl})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url: str, *, timeout: float = 10.0, read_cap: int = 1_000_000) -> dict:
    """One GET via urllib -> the observation dict headers.analyze() consumes.

    Headers are captured as a LIST of pairs, never a dict: collapsing them would
    silently drop every Set-Cookie but the last, and per-cookie flags are half
    this adapter's job. Redirects are followed because the visitor's security
    posture is the FINAL response's; 4xx/5xx is still an answer (an error page
    leaks banners too), so only transport failures return status=None, with the
    exception class visible so DNS vs TLS vs timeout stays distinguishable.
    """
    rec = _RedirectRecorder()
    opener = urllib.request.build_opener(rec)
    # S310 suppressed on the line below: the `file:`/custom-scheme risk this rule names is already closed
    # upstream — per this module's Policy docstring, a named site's URLs are gated by
    # enforce_or_raise against the manifest domain allowlist (default-deny) and an
    # ad-hoc --url is gated by enforce_user_url_or_raise. The check exists; it just
    # is not on this line.
    req = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": hdr.USER_AGENT, "Accept": "text/html,*/*"}
    )
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read(read_cap)
            charset = r.headers.get_content_charset() or "utf-8"
            return {
                "status": int(r.status),
                "final_url": r.geturl(),
                "redirects": rec.hops,
                "headers": [[k, v] for k, v in r.headers.items()],
                "body": raw.decode(charset, errors="replace"),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        try:
            body = (e.read(read_cap) or b"").decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return {
            "status": int(e.code),
            "final_url": e.geturl() if hasattr(e, "geturl") else url,
            "redirects": rec.hops,
            "headers": [[k, v] for k, v in (e.headers or {}).items()],
            "body": body,
            "error": None,
        }
    except Exception as e:
        return {
            "status": None,
            "final_url": url,
            "redirects": rec.hops,
            "headers": [],
            "body": None,
            "error": f"{type(e).__name__}: {e}",
        }


def _polite_fetcher(*, named: bool, host: str, timeout: float, delay: float):
    """The injected fetcher: same-origin re-check, policy re-check, rate floor.

    The URL set is built same-origin by headers.probe_urls, and this re-check
    makes that guarantee falsifiable at the I/O edge rather than trusting the
    builder — the same doctrine as the seo crawler's fetch closure.
    """
    state = {"last": 0.0}

    def fetch(u: str) -> dict:
        if (urlsplit(u).hostname or "").lower() != host:
            raise RuntimeError(f"scan tried to leave {host}: {u}")
        if named:
            enforce_or_raise(_manifest(), "network", u)
        wait = state["last"] + max(delay, 0.0) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        state["last"] = time.monotonic()
        return _fetch(u, timeout=timeout)

    return fetch


def _report(results: list[dict], *, extra: dict) -> dict:
    """The shared payload shape for scan/audit: grades, findings, gate summary."""
    diags = hdr.to_diagnostics(results)
    by_grade: dict[str, int] = {}
    for r in results:
        key = r.get("grade") or "ungraded"
        by_grade[key] = by_grade.get(key, 0) + 1
    return {
        **extra,
        "urls": len(results),
        "by_grade": dict(sorted(by_grade.items())),
        "results": results,
        "problems": [r for r in results if r.get("severity") != hdr.SEV_OK],
        "diagnostics": diags,
        "summary": openswap.summarize(diags),
    }


@app.command("hello", epilog=examples_epilog(["scout --json headers hello"]))
def hello():
    """Smoke check — is the headers surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "headers", "rules": len(hdr.RULES)},
            command="headers hello",
            example="scout --json headers scan bhenre",
            discover="scout headers detect",
        ),
        command="headers hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json headers detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="headers detect",
            example="scout --json headers scan bhenre",
            discover="scout headers sites",
        ),
        command="headers detect",
    )


@app.command("sites", epilog=examples_epilog(["scout --json headers sites"]))
def sites_cmd():
    """Show the scannable named sites and the rule table this adapter enforces."""
    emit(
        ok(
            {
                "sites": hdr.default_sites(),
                "rules": {
                    code: {"severity": sev, "remedy": remedy}
                    for code, (sev, remedy) in sorted(hdr.RULES.items())
                },
                "db": str(_db_path(None)),
            },
            command="headers sites",
            example="scout --json headers scan bhenre",
            discover="scout headers scan <site>",
        ),
        command="headers sites",
    )


@app.command(
    "scan",
    epilog=examples_epilog(
        [
            "scout --json headers scan bhenre",
            "scout --json headers scan bhenre --dirs --fail-on error",
            "scout --json headers scan --url https://example.com --no-record",
        ]
    ),
)
def scan(
    site: str | None = typer.Argument(
        None, help="site name (see: scout headers sites) — or use --url"
    ),
    url: str | None = typer.Option(
        None, "--url", help="scan one ad-hoc URL instead of a named site"
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"shared crawl store (default {seo.DB_REL} or $SCOUT_SEO_DB)",
    ),
    config_file: str | None = typer.Option(
        None, "--config", help="JSON policy overlay (severities, ignores, HSTS floor)"
    ),
    dirs: bool = typer.Option(
        False,
        "--dirs/--no-dirs",
        help="also GET the configured directory paths (directory-listing probe)",
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="per-request socket timeout, seconds"
    ),
    delay: float = typer.Option(
        1.0, "--delay", help="seconds between requests (politeness floor)"
    ),
    record: bool = typer.Option(
        True, "--record/--no-record", help="persist to the store (off = report only)"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any finding is at/above this severity (error|warning|"
        "suggestion|info) — the pre-deploy gate hook",
    ),
):
    """One live pass: GET each URL, grade the response, record, report. Real I/O."""
    _fail_on_or_fail(fail_on, "headers scan")
    cfg = _config_or_fail(config_file, "headers scan")
    sanitize_no_proxy_env()
    start, named = _resolve_site(site, url, "headers scan")
    urls = hdr.probe_urls(start, cfg["dir_probe_paths"] if dirs else [])
    if named:
        for u in urls:
            enforce_or_raise(_manifest(), "network", u)
    else:
        # user-typed URL: gated by the persisted user allowlist, never by a
        # manifest widened to match the target (policy doctrine)
        enforce_user_url_or_raise(start, context="headers scan")
    host = (urlsplit(start).hostname or "").lower()
    fetch = _polite_fetcher(named=named, host=host, timeout=timeout, delay=delay)
    if record:
        conn, path = _open_store(db)
    else:
        conn, path = hdr.open_headers_store(":memory:"), None  # dry-run, same pipeline
    res = hdr.run_pass(conn, urls, fetch, record=record, config=cfg)
    emit(
        ok(
            _report(
                res["results"],
                extra={"db": str(path) if path else None, "recorded": record,
                       "probed_dirs": dirs, "delay_s": max(delay, 0.0)},
            ),
            command="headers scan",
            example="scout --json headers status",
            discover="scout headers audit " + (site if named else f"--url {start}"),
        ),
        command="headers scan",
    )
    _gate(hdr.to_diagnostics(res["results"]), fail_on)


@app.command(
    "audit",
    epilog=examples_epilog(
        [
            "scout --json headers audit bhenre",
            "scout --json headers audit bhenre --fail-on warning",
            "scout --json headers audit --url https://example.com",
        ]
    ),
)
def audit_cmd(
    site: str | None = typer.Argument(
        None, help="site name (see: scout headers sites) — or use --url"
    ),
    url: str | None = typer.Option(
        None, "--url", help="audit an ad-hoc site already in the store"
    ),
    db: str | None = typer.Option(None, "--db", help="shared crawl store path"),
    config_file: str | None = typer.Option(
        None, "--config", help="JSON policy overlay (severities, ignores, HSTS floor)"
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 if any finding is at/above this severity"
    ),
):
    """Audit the stored crawl's headers — zero refetches, no network at all."""
    _fail_on_or_fail(fail_on, "headers audit")
    cfg = _config_or_fail(config_file, "headers audit")
    start, named = _resolve_site(site, url, "headers audit")
    key = seo.site_key(start)
    conn, path = _open_existing(db, "headers audit")
    results = hdr.audit_rows(conn, key, config=cfg)
    if not results:
        fail_agent(
            f"no crawled pages for {key} in {path} — run `seo crawl` (or "
            "`headers scan`) first",
            command="headers audit",
            example="scout --json seo crawl " + (site if named else f"--url {start}"),
            discover="scout headers scan " + (site if named else f"--url {start}"),
        )
    emit(
        ok(
            _report(
                results,
                extra={
                    "db": str(path),
                    "site": key,
                    "network_calls": 0,
                    "caveats": [
                        "no response bodies in the crawl store: mixed-content and "
                        "directory-listing checks are SKIPPED, not passed (see "
                        "each verdict's checks_skipped)",
                        "the crawl store keeps headers as one object per URL, so "
                        "repeated Set-Cookie headers collapsed to the last one "
                        "before this audit saw them — cookie findings can "
                        "undercount; `headers scan` sees every cookie",
                    ],
                },
            ),
            command="headers audit",
            example="scout --json headers scan " + (site if named else f"--url {start}"),
            discover="scout headers status",
        ),
        command="headers audit",
    )
    _gate(hdr.to_diagnostics(results), fail_on)


@app.command(
    "status",
    epilog=examples_epilog(
        [
            "scout --json headers status",
            "scout --json headers status bhenre",
            "scout --json headers status --url https://www.bhenre.com/ --limit 5",
        ]
    ),
)
def status(
    site: str | None = typer.Argument(None, help="narrow the board to one named site"),
    url: str | None = typer.Option(
        None, "--url", help="one URL's scan history instead of the board"
    ),
    db: str | None = typer.Option(None, "--db", help="shared crawl store path"),
    limit: int = typer.Option(20, "--limit", help="history rows when --url is set"),
):
    """Header posture board from the store — no requests, no network."""
    conn, path = _open_existing(db, "headers status")
    if url:
        history = hdr.scan_history(conn, url, limit=limit)
        if not history:
            fail_agent(
                f"no scans recorded for {url!r}",
                command="headers status",
                example="scout --json headers scan --url " + url,
                discover="scout headers status",
            )
        emit(
            ok(
                {"db": str(path), "url": url, "history": history},
                command="headers status",
                example="scout --json headers scan bhenre",
                discover="scout headers status",
            ),
            command="headers status",
        )
        return
    prefix = None
    if site:
        start, _named = _resolve_site(site, None, "headers status")
        prefix = seo.site_key(start)
    urls = hdr.scanned_urls(conn, prefix=prefix)
    emit(
        ok(
            {
                "db": str(path),
                "site": prefix,
                "scanned": len(urls),
                "board": hdr.board(conn, urls),
            },
            command="headers status",
            example="scout --json headers status --url https://www.bhenre.com/",
            discover="scout headers scan <site>",
        ),
        command="headers status",
    )


def register(root):
    root.add_typer(app, name="headers")
