# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout links` — Ahrefs broken-link / Dr. Link Check replacement, fully
local (openswap #4), riding the seo crawl store.

The stdlib core is 100% of the product: internal links verify against the
CRAWL RESULTS (zero refetches — `check` is offline by default), the graph /
orphan / redirect reports read the same store, and the local docs checker
(`files`) never touches the network at all. The ONLY outbound calls are the
opt-in `check --external` HEAD/GET probes, and every candidate URL must pass
the manifest domain allowlist OR the persisted user allowlist first; a denied
URL is recorded as unverified (policy-denied) and never fetched — default-deny
converts into an honest report row, not a crashed run. Native link crawlers
(linkchecker, lychee) are probed and surfaced by `detect` but never executed:
a spawned binary would fetch outside the per-URL policy gate, the exact thing
this family forbids.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path

import typer

from bigbang.core import links, openswap, seo
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.http_utils import sanitize_no_proxy_env
from bigbang.core.output import emit
from bigbang.core.policy import (
    check_permission,
    check_user_url,
    enforce_or_raise,
    load_manifest,
)

FALLBACK_SCOPE = (
    "pure-stdlib link verifier is the complete product for this adapter: "
    "internal links checked against the seo crawl store (zero refetches), "
    "dict-adjacency graph with orphan/redirect reports, opt-in HEAD-then-GET "
    "external verification under per-domain rate limiting + retry/backoff + "
    "a wall-clock budget (every URL policy-gated first), offline docs/README "
    "cross-link + anchor-fragment checking, and a diffable sqlite status "
    "ledger; tier 'fallback' is the expected steady state — native crawlers "
    "(linkchecker, lychee) are surfaced for manual use but never executed, "
    "because a spawned binary fetches outside the per-URL policy gate"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; linkchecker/lychee on "
    "PATH are surfaced for manual use only, never executed by scout"
)

app = make_plugin_app(
    "links",
    "Verify links (Ahrefs broken-link-class), fully local: crawl-store checks + polite external probes",
    examples=[
        "scout --json links check bhenre",
        "scout --json links check bhenre --external --fail-on error",
        "scout --json links files docs README.md",
        "scout --json links graph bhenre",
        "scout --json links diff bhenre --fail-on-new",
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
    # Probes are truthful; execution stays stdlib regardless (module doc).
    native = openswap.probe_binary("linkchecker", probe_args=("--version",))
    extras = {"lychee": openswap.probe_binary("lychee", probe_args=("--version",))}
    return openswap.capability_report(
        "links",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _seo_db(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_SEO_DB") or seo.DB_REL)


def _links_db(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_LINKS_DB") or links.DB_REL)


def _open_seo_existing(db: str | None, command: str) -> tuple:
    path = _seo_db(db)
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
        return links.load_config(config_file)
    except Exception as e:
        fail_agent(
            f"bad config file: {e}",
            command=command,
            example=f"scout --json {command} bhenre --config links.json",
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    gate_rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
        raise typer.Exit(code=1)


def _survey_from_store(conn, key: str) -> dict:
    rows = seo.site_rows(conn, key)
    if not rows:
        return {}
    frontier = {
        r["url"]: (r["state"] + (f": {r['reason']}" if r["reason"] else ""))
        for r in conn.execute(
            "SELECT url, state, reason FROM frontier WHERE site = ?", (key,)
        )
    }
    return {"rows": rows, "survey": links.link_survey(rows, frontier=frontier)}


def _urlprobe(timeout: float):
    """The injected external prober: one HEAD or GET, redirects followed,
    body never read (status is the verdict). Never raises — the verifier's
    contract; transport failures surface as status=None with the exception
    class visible so DNS vs TLS vs timeout stays distinguishable."""

    opener = urllib.request.build_opener()

    def probe(url: str, method: str) -> dict:
        # every url here is manifest/user-allowlist gated AND http(s)-only by
        # construction (seo.resolve_link drops every other scheme)
        req = urllib.request.Request(
            url, method=method,
            headers={"User-Agent": links.USER_AGENT, "Accept": "*/*"},
        )
        try:
            with opener.open(req, timeout=timeout) as r:
                return {"status": int(r.status), "error": None}
        except urllib.error.HTTPError as e:
            return {"status": int(e.code), "error": None}
        except Exception as e:
            return {"status": None, "error": f"{type(e).__name__}: {e}"}

    return probe


@app.command("hello", epilog=examples_epilog(["scout --json links hello"]))
def hello():
    """Smoke check — is the links surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "links"},
            command="links hello",
            example="scout --json links check bhenre",
            discover="scout links detect",
        ),
        command="links hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json links detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="links detect",
            example="scout --json links check bhenre",
            discover="scout seo sites",
        ),
        command="links detect",
    )


@app.command(
    "check",
    epilog=examples_epilog(
        [
            "scout --json links check bhenre",
            "scout --json links check bhenre --external --fail-on error",
            "scout --json links check --url https://example.com --config links.json",
        ]
    ),
)
def check_cmd(
    site: str | None = typer.Argument(
        None, help="site name (see: scout seo sites) — or use --url"
    ),
    url: str | None = typer.Option(
        None, "--url", help="check an ad-hoc site already in the crawl store"
    ),
    db: str | None = typer.Option(
        None, "--db", help=f"seo crawl store (default {seo.DB_REL} or $SCOUT_SEO_DB)"
    ),
    links_db: str | None = typer.Option(
        None,
        "--links-db",
        help=f"link-status store (default {links.DB_REL} or $SCOUT_LINKS_DB)",
    ),
    config_file: str | None = typer.Option(
        None, "--config", help="JSON config overlay (external_allow, politeness)"
    ),
    external: bool = typer.Option(
        False,
        "--external",
        help="also verify external links with HEAD-then-GET (policy-gated "
        "per URL; without this flag the check is fully offline)",
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="per-request socket timeout, seconds"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|"
        "suggestion|info) — the per-deploy / weekly-cron gate hook",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
):
    """Verify the stored crawl's links; internal checks never refetch."""
    _fail_on_or_fail(fail_on, "links check")
    cfg = _config_or_fail(config_file, "links check")
    start, named = _resolve_site(site, url, "links check")
    key = seo.site_key(start)
    conn, path = _open_seo_existing(db, "links check")
    got = _survey_from_store(conn, key)
    if not got:
        fail_agent(
            f"no crawled pages for {key} in {path} — crawl first",
            command="links check",
            example="scout --json seo crawl " + (site if named else f"--url {start}"),
            discover="scout seo sites",
        )
    survey = got["survey"]
    ext_urls = sorted(survey["external"])
    ext_results: dict[str, dict] = {}
    policy_denied: list[str] = []
    if external:
        sanitize_no_proxy_env()
        verifiable: list[str] = []
        for u in ext_urls:
            # default-deny, recorded not raised: one off-allowlist link on a
            # page must not kill the whole verification pass
            if check_permission(_manifest(), "network", u)[0] or check_user_url(u)[0]:
                verifiable.append(u)
            else:
                policy_denied.append(u)
                ext_results[u] = {
                    "state": "unverified", "status": None, "method": None,
                    "detail": "policy-denied (manifest + user allowlist)",
                    "attempts": 0,
                }
        ext_results.update(
            links.verify_external(verifiable, _urlprobe(timeout), config=cfg)
        )
    else:
        ext_results = {
            u: {"state": "unverified", "status": None, "method": None,
                "detail": "external verification off — pass --external",
                "attempts": 0}
            for u in ext_urls
        }
    diags = links.to_diagnostics(survey, ext_results)
    ldb = _links_db(links_db)
    enforce_or_raise(_manifest(), "fs_write", str(ldb))
    lconn = links.open_store(ldb)
    run_id = links.record_run(lconn, key, survey, ext_results)
    cap = _capability()
    audit_ref = site if named else f"--url {start}"
    data = {
        "db": str(path),
        "links_db": str(ldb),
        "site": key,
        "run_id": run_id,
        "pages": len(got["rows"]),
        "tier": cap["tier"],
        "external_checked": external,
        "counts": links.state_counts(survey, ext_results),
        "orphans": survey["orphans"],
        "policy_denied": policy_denied,
        "diagnostics": diags[:max_findings],
        "truncated": len(diags) > max_findings,
        "summary": openswap.summarize(diags),
    }
    if cap["tier"] != openswap.TIER_NATIVE:
        data["scope_note"] = FALLBACK_SCOPE
    emit(
        ok(
            data,
            command="links check",
            example=f"scout --json links diff {audit_ref} --fail-on-new",
            discover=f"scout links graph {audit_ref}",
        ),
        command="links check",
    )
    _gate(diags, fail_on)


@app.command(
    "files",
    epilog=examples_epilog(
        [
            "scout --json links files README.md docs",
            "scout --json links files site --root site --fail-on error",
            "scout --json links files docs/guide.md --fail-on warning",
        ]
    ),
)
def files_cmd(
    paths: list[str] = typer.Argument(
        ...,
        help="local docs or directories (dirs walked for "
        + ", ".join(links.DOC_EXTS)
        + ")",
    ),
    root: str | None = typer.Option(
        None,
        "--root",
        help='resolve root-absolute ("/x") targets against this directory '
        "(skipped and counted otherwise)",
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
    """Check README/docs cross-links + anchors offline (zero network)."""
    _fail_on_or_fail(fail_on, "links files")
    files: list[Path] = []
    for p in paths:
        pth = Path(p)
        if pth.is_file():
            files.append(pth)
        elif pth.is_dir():
            for ext in links.DOC_EXTS:
                files.extend(pth.rglob(f"*{ext}"))
        else:
            fail_agent(
                f"path not found: {p}",
                command="links files",
                example="scout --json links files README.md docs",
            )
    files = sorted(set(files))
    if not files:
        fail_agent(
            f"no docs found (looking for {', '.join(links.DOC_EXTS)})",
            command="links files",
            example="scout --json links files README.md docs",
        )
    diags, stats = links.check_files(files, root=Path(root) if root else None)
    emit(
        ok(
            {
                "files": [str(f) for f in files],
                "stats": stats,
                "diagnostics": diags[:max_findings],
                "truncated": len(diags) > max_findings,
                "summary": openswap.summarize(diags),
                "scope_note": "external http(s) refs are counted, never "
                "fetched — files mode is the offline pre-publish gate",
            },
            command="links files",
            example="scout --json links files docs --fail-on error",
            discover="scout links check <site>",
        ),
        command="links files",
    )
    _gate(diags, fail_on)


@app.command(
    "graph",
    epilog=examples_epilog(
        [
            "scout --json links graph bhenre",
            "scout --json links graph bhenre --dot bhenre.dot",
        ]
    ),
)
def graph_cmd(
    site: str | None = typer.Argument(
        None, help="site name (see: scout seo sites) — or use --url"
    ),
    url: str | None = typer.Option(
        None, "--url", help="graph an ad-hoc site already in the crawl store"
    ),
    db: str | None = typer.Option(None, "--db", help="seo crawl store path"),
    dot: str | None = typer.Option(
        None, "--dot", help="also write a Graphviz DOT export here"
    ),
):
    """Emit the internal link graph (dict adjacency) + orphan report — offline."""
    start, named = _resolve_site(site, url, "links graph")
    key = seo.site_key(start)
    conn, path = _open_seo_existing(db, "links graph")
    got = _survey_from_store(conn, key)
    if not got:
        fail_agent(
            f"no crawled pages for {key} in {path} — crawl first",
            command="links graph",
            example="scout --json seo crawl " + (site if named else f"--url {start}"),
            discover="scout seo sites",
        )
    survey = got["survey"]
    graph = survey["graph"]
    inbound: dict[str, int] = {}
    for src, targets in graph.items():
        for t in targets:
            if t != src:
                inbound[t] = inbound.get(t, 0) + 1
    data = {
        "db": str(path),
        "site": key,
        "nodes": len(graph),
        "edges": sum(len(v) for v in graph.values()),
        "adjacency": graph,
        "inbound_top": sorted(
            inbound.items(), key=lambda kv: (-kv[1], kv[0])
        )[:10],
        "orphans": survey["orphans"],
    }
    if dot:
        enforce_or_raise(_manifest(), "fs_write", dot)
        lines = ["digraph links {"]
        for src, targets in sorted(graph.items()):
            for t in targets:
                lines.append(f'  "{src}" -> "{t}";')
        lines.append("}")
        Path(dot).write_text("\n".join(lines) + "\n", encoding="utf-8")
        data["dot"] = {"path": dot, "edges": data["edges"]}
    emit(
        ok(
            data,
            command="links graph",
            example="scout --json links graph bhenre --dot bhenre.dot",
            discover="scout links check " + (site if named else f"--url {start}"),
        ),
        command="links graph",
    )


@app.command(
    "diff",
    epilog=examples_epilog(
        [
            "scout --json links diff bhenre",
            "scout --json links diff bhenre --run-a 1 --run-b 3",
            "scout --json links diff bhenre --fail-on-new",
        ]
    ),
)
def diff_cmd(
    site: str | None = typer.Argument(
        None, help="site name (see: scout seo sites) — or use --url"
    ),
    url: str | None = typer.Option(
        None, "--url", help="diff an ad-hoc site's recorded runs"
    ),
    links_db: str | None = typer.Option(
        None, "--links-db", help="link-status store path"
    ),
    run_a: int | None = typer.Option(None, "--run-a", help="older run id"),
    run_b: int | None = typer.Option(None, "--run-b", help="newer run id"),
    fail_on_new: bool = typer.Option(
        False,
        "--fail-on-new",
        help="exit 1 when links broke between the runs — the CI regression gate",
    ),
):
    """Diff two recorded runs: new-broken / fixed / still-broken — offline."""
    start, _named = _resolve_site(site, url, "links diff")
    key = seo.site_key(start)
    ldb = _links_db(links_db)
    if not ldb.exists():
        fail_agent(
            f"no link-status store at {ldb} — run a check first",
            command="links diff",
            example="scout --json links check bhenre",
        )
    lconn = links.open_store(ldb)
    try:
        res = links.diff_runs(lconn, key, run_a=run_a, run_b=run_b)
    except ValueError as e:
        fail_agent(
            str(e),
            command="links diff",
            example="scout --json links check bhenre",
        )
    regressions = len(res["new_broken"]) + len(res["appeared_broken"])
    emit(
        ok(
            {"links_db": str(ldb), "regressions": regressions, **res},
            command="links diff",
            example="scout --json links diff bhenre --fail-on-new",
            discover="scout links check bhenre --external",
        ),
        command="links diff",
    )
    if fail_on_new and regressions:
        raise typer.Exit(code=1)


def register(root):
    root.add_typer(app, name="links")
