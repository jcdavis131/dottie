# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout seo` — Screaming Frog + Semrush + Yoast replacement, fully local
(openswap #3, the merged SEO category).

The stdlib core is 100% of the product: urllib fetches (the only real I/O,
and it lives here) feed the deterministic pipeline in bigbang/core/seo.py —
polite same-host crawl (robots honored, resumable sqlite frontier), on-page
audit, duplicate-title detection, SF-shaped CSV. There is no native binary
tier to prefer: Screaming Frog is the paid JVM GUI being replaced and SEOnaut
ships as a Go web server, not a CLI, so `detect` reports tier=fallback as the
expected steady state (scope honesty, not degradation). Deliberately out of
scope: JS rendering (the fleet is static) and SERP rank tracking (scraping
Google is a ToS/network liability, the exact thing this family forbids).

Policy: a named site's start URL is gated by enforce_or_raise against this
plugin's manifest domain allowlist (default-deny); an ad-hoc --url crawl is
user-typed and is instead gated by the persisted user allowlist
(enforce_user_url_or_raise). Every subsequent fetch is same-host with the
start URL by construction AND re-checked at the I/O boundary. `audit`, `lint`
and CSV export make no network calls at all.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import typer

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
    "pure-stdlib crawler + on-page audit is the complete product for this "
    "adapter: polite same-host crawl (robots honored, resumable sqlite "
    "frontier), title/description windows, canonicals, single-h1, noindex, "
    "OG/Twitter completeness, alt coverage, JSON-LD parseability, hashlib "
    "duplicate titles, Screaming Frog-shaped CSV; tier 'fallback' is the "
    "expected steady state (no open CLI binary exists in this category — "
    "SEOnaut is a web server, Screaming Frog is the paid enemy)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; lychee on PATH is "
    "surfaced as an extra for the broken-link build (#4), never required"
)

app = make_plugin_app(
    "seo",
    "Audit sites (Screaming Frog-class), fully local: polite stdlib crawler + on-page checks",
    examples=[
        "scout --json seo crawl bhenre",
        "scout --json seo audit bhenre --csv bhenre.csv",
        "scout --json seo audit bhenre --fail-on error",
        "scout --json seo lint site/index.html --fail-on warning",
        "scout --json seo sites",
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
    # No CLI distribution exists in this category, so `native` stays a
    # truthful probe that reports absent; lychee is surfaced as an extra (the
    # broken-link build's accelerator) without ever being required.
    native = openswap.probe_binary("seonaut", probe_args=("--version",))
    extras = {"lychee": openswap.probe_binary("lychee", probe_args=("--version",))}
    return openswap.capability_report(
        "seo",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_SEO_DB") or seo.DB_REL)


def _open_store(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return seo.open_store(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no seo crawl store at {path} — run a crawl first",
            command=command,
            example="scout --json seo crawl bhenre",
        )
    return seo.open_store(path), path


def _resolve_site(site: str | None, url: str | None, command: str) -> tuple[str, bool]:
    """(start_url, named) — exactly one of site-name / --url must be given."""
    if bool(site) == bool(url):
        fail_agent(
            "give a site name OR --url (see: scout seo sites)",
            command=command,
            example=f"scout --json {command} bhenre",
            discover="scout seo sites",
        )
    if site:
        if site not in seo.DEFAULT_SITES:
            fail_agent(
                f"unknown site {site!r} — one of: "
                + ", ".join(sorted(seo.DEFAULT_SITES)),
                command=command,
                example=f"scout --json {command} bhenre",
                discover="scout seo sites",
            )
        return seo.DEFAULT_SITES[site], True
    return url, False


def _fail_on_or_fail(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=f"scout --json {command} bhenre --fail-on warning",
        )


def _config_or_fail(config_file: str | None, command: str) -> dict:
    try:
        return seo.load_config(config_file)
    except Exception as e:
        fail_agent(
            f"bad config file: {e}",
            command=command,
            example=f"scout --json {command} bhenre --config seo.json",
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    gate_rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
        raise typer.Exit(code=1)


class _RedirectRecorder(urllib.request.HTTPRedirectHandler):
    """Follow redirects normally while recording each hop for the audit."""

    def __init__(self) -> None:
        super().__init__()
        self.hops: list[dict] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops.append({"code": int(code), "to": newurl})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url: str, *, timeout: float = 10.0, read_cap: int = 2_000_000) -> dict:
    """One GET via urllib. Returns the seo.crawl() fetch-contract dict.

    4xx/5xx is still an answer (the audit wants the real status code); only
    transport failures return status=None, with the exception class visible
    so DNS vs TLS vs timeout stays distinguishable. Bodies are capped at
    read_cap bytes — plenty for on-page facts without pulling huge assets.
    """
    rec = _RedirectRecorder()
    opener = urllib.request.build_opener(rec)
    req = urllib.request.Request(
        url, headers={"User-Agent": seo.USER_AGENT, "Accept": "text/html,*/*"}
    )
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read(read_cap)
            charset = r.headers.get_content_charset() or "utf-8"
            return {
                "status": int(r.status),
                "final_url": r.geturl(),
                "redirects": rec.hops,
                "content_type": r.headers.get_content_type(),
                "headers": dict(r.headers.items()),
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
            "final_url": rec.hops[-1]["to"] if rec.hops else url,
            "redirects": rec.hops,
            "content_type": e.headers.get_content_type() if e.headers else None,
            "headers": dict(e.headers.items()) if e.headers else {},
            "body": body,
            "error": None,
        }
    except Exception as e:
        return {
            "status": None,
            "final_url": url,
            "redirects": rec.hops,
            "content_type": None,
            "headers": {},
            "body": "",
            "error": f"{type(e).__name__}: {e}",
        }


def _collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        pth = Path(p)
        if pth.is_file():
            files.append(pth)
        elif pth.is_dir():
            for ext in seo.HTML_EXTS:
                files.extend(pth.rglob(f"*{ext}"))
        else:
            fail_agent(
                f"path not found: {p}",
                command="seo lint",
                example="scout --json seo lint site/index.html",
            )
    return sorted(set(files))


@app.command("hello", epilog=examples_epilog(["scout --json seo hello"]))
def hello():
    """Smoke check — is the seo surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "seo"},
            command="seo hello",
            example="scout --json seo crawl bhenre",
            discover="scout seo detect",
        ),
        command="seo hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json seo detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="seo detect",
            example="scout --json seo crawl bhenre",
            discover="scout seo sites",
        ),
        command="seo detect",
    )


@app.command("sites", epilog=examples_epilog(["scout --json seo sites"]))
def sites_cmd():
    """Show the crawlable named sites (the 8-site public fleet, manifest-gated)."""
    emit(
        ok(
            {"sites": seo.DEFAULT_SITES, "count": len(seo.DEFAULT_SITES)},
            command="seo sites",
            example="scout --json seo crawl bhenre",
            discover="scout seo crawl <site>",
        ),
        command="seo sites",
    )


@app.command(
    "crawl",
    epilog=examples_epilog(
        [
            "scout --json seo crawl bhenre",
            "scout --json seo crawl hub --max-pages 50 --delay 2",
            "scout --json seo crawl --url https://example.com --max-pages 10",
        ]
    ),
)
def crawl_cmd(
    site: str | None = typer.Argument(
        None, help="site name (see: scout seo sites) — or use --url"
    ),
    url: str | None = typer.Option(
        None, "--url", help="crawl one ad-hoc site instead of a named one"
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"sqlite crawl store (default {seo.DB_REL} or $SCOUT_SEO_DB)",
    ),
    max_pages: int = typer.Option(
        25, "--max-pages", help="fetch budget for this pass (re-run to resume)"
    ),
    max_depth: int = typer.Option(
        3, "--max-depth", help="link depth from the start URL"
    ),
    delay: float = typer.Option(
        1.0, "--delay", help="seconds between requests (politeness floor)"
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="per-request socket timeout, seconds"
    ),
):
    """One polite crawl pass: same-host, robots honored, resumable frontier."""
    sanitize_no_proxy_env()
    start, named = _resolve_site(site, url, "seo crawl")
    if named:
        enforce_or_raise(_manifest(), "network", start)
    else:
        # user-typed URL: gated by the persisted user allowlist, never by a
        # manifest widened to match the site being crawled (policy doctrine)
        enforce_user_url_or_raise(start, context="seo crawl")
    host = (urlsplit(start).hostname or "").lower()
    state = {"last": 0.0}

    def fetch(u: str) -> dict:
        # the core already restricts the frontier to the start host; this
        # re-check makes the same-host guarantee falsifiable at the I/O edge
        if (urlsplit(u).hostname or "").lower() != host:
            raise RuntimeError(f"crawler tried to leave {host}: {u}")
        if named:
            enforce_or_raise(_manifest(), "network", u)
        wait = state["last"] + max(delay, 0.0) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        state["last"] = time.monotonic()
        return _fetch(u, timeout=timeout)

    robots_url = urljoin(seo.site_key(start), "/robots.txt")
    rr = fetch(robots_url)
    # only a 200 body constrains the crawl; a missing robots.txt allows all
    robots = None
    if rr.get("status") == 200 and rr.get("body"):
        robots = seo.robots_parser(start, rr["body"])
    conn, path = _open_store(db)
    res = seo.crawl(
        conn, start, fetch, max_pages=max_pages, max_depth=max_depth, robots=robots
    )
    audit_ref = site if named else f"--url {start}"
    emit(
        ok(
            {
                "db": str(path),
                "robots": {
                    "url": robots_url,
                    "status": rr.get("status"),
                    "applied": robots is not None,
                },
                "delay_s": max(delay, 0.0),
                **res,
            },
            command="seo crawl",
            example=f"scout --json seo audit {audit_ref}",
            discover=f"scout seo audit {audit_ref}",
        ),
        command="seo crawl",
    )


@app.command(
    "audit",
    epilog=examples_epilog(
        [
            "scout --json seo audit bhenre",
            "scout --json seo audit bhenre --csv bhenre.csv --fail-on error",
            "scout --json seo audit --url https://example.com --config seo.json",
        ]
    ),
)
def audit_cmd(
    site: str | None = typer.Argument(
        None, help="site name (see: scout seo sites) — or use --url"
    ),
    url: str | None = typer.Option(
        None, "--url", help="audit an ad-hoc site already in the store"
    ),
    db: str | None = typer.Option(None, "--db", help="sqlite crawl store path"),
    config_file: str | None = typer.Option(
        None, "--config", help="JSON audit-config overlay (policy-as-config)"
    ),
    csv_path: str | None = typer.Option(
        None, "--csv", help="also write the Screaming Frog-shaped per-URL CSV here"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|"
        "suggestion|info) — the pre-deploy gate hook",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
):
    """Audit the stored crawl — no probes, no network."""
    _fail_on_or_fail(fail_on, "seo audit")
    cfg = _config_or_fail(config_file, "seo audit")
    start, named = _resolve_site(site, url, "seo audit")
    key = seo.site_key(start)
    conn, path = _open_existing(db, "seo audit")
    rows = seo.site_rows(conn, key)
    if not rows:
        fail_agent(
            f"no crawled pages for {key} in {path} — crawl first",
            command="seo audit",
            example="scout --json seo crawl " + (site if named else f"--url {start}"),
            discover="scout seo sites",
        )
    diags = seo.audit_crawl(conn, key, config=cfg)
    cap = _capability()
    data = {
        "db": str(path),
        "site": key,
        "pages": len(rows),
        "tier": cap["tier"],
        "diagnostics": diags[:max_findings],
        "truncated": len(diags) > max_findings,
        "summary": openswap.summarize(diags),
    }
    if cap["tier"] != openswap.TIER_NATIVE:
        data["scope_note"] = FALLBACK_SCOPE
    if csv_path:
        enforce_or_raise(_manifest(), "fs_write_arg", csv_path)
        n = seo.export_csv(conn, key, csv_path, config=cfg)
        data["csv"] = {"path": csv_path, "rows": n}
    emit(
        ok(
            data,
            command="seo audit",
            example="scout --json seo audit bhenre --csv bhenre.csv",
            discover="scout seo detect",
        ),
        command="seo audit",
    )
    _gate(diags, fail_on)


@app.command(
    "lint",
    epilog=examples_epilog(
        [
            "scout --json seo lint site/index.html",
            "scout --json seo lint public --fail-on warning",
            "scout --json seo lint page.html --config seo.json",
        ]
    ),
)
def lint(
    paths: list[str] = typer.Argument(
        ...,
        help="local HTML files or directories (dirs walked for "
        + ", ".join(seo.HTML_EXTS)
        + ")",
    ),
    config_file: str | None = typer.Option(
        None, "--config", help="JSON audit-config overlay (policy-as-config)"
    ),
    base_url: str = typer.Option(
        "http://localhost/",
        "--base-url",
        help="base for resolving relative links in the parsed facts",
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity — the pre-publish gate hook",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
):
    """Audit local HTML files offline (the Yoast-style pre-publish gate)."""
    _fail_on_or_fail(fail_on, "seo lint")
    cfg = _config_or_fail(config_file, "seo lint")
    files = _collect_files(paths)
    if not files:
        fail_agent(
            f"no HTML files found (looking for {', '.join(seo.HTML_EXTS)})",
            command="seo lint",
            example="scout --json seo lint site/index.html",
        )
    diags: list[dict] = []
    titles: list[tuple[str, str | None]] = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        facts = seo.parse_page(text, urljoin(base_url, f.name))
        diags.extend(seo.audit_page(str(f), status=200, facts=facts, config=cfg))
        titles.append((str(f), facts.get("title")))
    diags.extend(seo.duplicate_titles(titles))
    diags = openswap.sort_diagnostics(diags)
    emit(
        ok(
            {
                "files": [str(f) for f in files],
                "diagnostics": diags[:max_findings],
                "truncated": len(diags) > max_findings,
                "summary": openswap.summarize(diags),
                "scope_note": FALLBACK_SCOPE,
            },
            command="seo lint",
            example="scout --json seo lint public --fail-on warning",
            discover="scout seo crawl <site>",
        ),
        command="seo lint",
    )
    _gate(diags, fail_on)


def register(root):
    root.add_typer(app, name="seo")
