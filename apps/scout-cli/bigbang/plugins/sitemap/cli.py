# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout sitemap` — XML-Sitemaps.com Pro replacement, fully local (openswap
rank 10; build slot 11, since W&B took slot 10 — see docs/OPENSWAP.md).

The paid product is a remote crawler: it fetches your deployed site from
someone else's datacenter to discover URLs you already know. This adapter
deletes the crawl and the SaaS both — the built `public/` tree IS the URL set
and its mtimes ARE the lastmods, so a sorted os.walk plus xml.etree emits the
same sitemap in milliseconds, offline, from the deploy pipeline. Three sources
feed one pipeline: `--root` (the walk), `--urls` (an explicit list, absolute or
site-relative), and `--from-crawl` (the #3 seo crawl store, filtered to the
rows seo itself calls Indexable — submitting a noindex URL is the classic
sitemap own-goal). Over 50,000 URLs, `--out` becomes a sitemapindex and the
URLs move into `-1..-N` shard siblings, so an already-submitted sitemap URL
never has to change.

Output is deterministic by construction (sorted locs, two-space indent, UTF-8
LF bytes, no generation timestamp anywhere), which is what makes `check` a real
deploy gate: drift means the site's content changed, never that the generator
ran again. All deterministic logic lives in bigbang/core/sitemap.py; this
surface adds path resolution, argument parsing, the fs_write policy gate, and
the one read of the seo store.

Policy: this plugin makes no network call and opens no socket — the manifest
disables the network axis entirely (nothing to allowlist, which is the point).
Writes are gated at the call site by enforce_or_raise(fs_write) on the resolved
`--out`, and shard paths are derived from `--out` rather than from input, so a
URL list can never redirect a write. `check` and `lint` write nothing at all.
Native binaries in this category (npm's sitemap-generator, python-sitemap) are
probed for awareness but NEVER executed: every one of them works by crawling a
live site, i.e. by doing the network I/O this manifest denies.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import typer

from bigbang.core import openswap, seo, sitemap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib xml.etree writer is the complete product for this adapter: "
    "sorted os.walk of the built site (mtimes as lastmod), explicit URL lists, "
    "the #3 seo crawl store's Indexable rows, 50k-URL sitemapindex sharding, "
    "protocol validation (off-base locs, 2048-char locs, duplicate locs, 50MB "
    "files) as normalized diagnostics, and byte-identical diffable output; "
    "tier 'fallback' is the expected steady state (XML-Sitemaps.com Pro is "
    "SaaS, and every open alternative is a live-site crawler — the network I/O "
    "this adapter deliberately does not do)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib writer is complete; xmllint on PATH is "
    "surfaced as an optional local validator for the emitted XML, never required"
)

LASTMOD_CHOICES = (*sitemap.LASTMOD_PRECISIONS, "none")

app = make_plugin_app(
    "sitemap",
    "Generate sitemap.xml (XML-Sitemaps.com-class), fully local: deterministic "
    "xml.etree writer over a public/ walk, a URL list, or the seo crawl store",
    examples=[
        "scout --json sitemap gen --root public --base-url https://dumbmodel.com",
        "scout --json sitemap gen --root public --base-url https://dumbmodel.com "
        '--exclude "drafts/*" --exclude "404.html"',
        "scout --json sitemap gen --urls routes.txt --base-url https://arxiviq.com "
        "--out public/sitemap.xml",
        "scout --json sitemap gen --from-crawl bhenre",
        "scout --json sitemap check --root public --base-url https://dumbmodel.com",
        "scout --json sitemap lint public/sitemap.xml --fail-on error",
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
    # Every open generator in this category discovers URLs by CRAWLING a live
    # site, so none of them is a superset of a walk over the build output and
    # none can run under a manifest with the network axis disabled: `native`
    # stays a truthful PATH report and this adapter never delegates to it.
    # xmllint is a benign optional local validator for the emitted XML.
    native = openswap.probe_binary("sitemap-generator", probe_args=("--help",))
    extras = {
        "xmllint": openswap.probe_binary("xmllint", probe_args=("--version",)),
        "python-sitemap": openswap.probe_binary("python-sitemap", probe_args=("-h",)),
    }
    return openswap.capability_report(
        "sitemap",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _seo_db_path(db: str | None) -> Path:
    # read-only use of the #3 adapter's store; same default + env override
    return Path(db or os.environ.get("SCOUT_SEO_DB") or seo.DB_REL)


def _lastmod_mode(value: str, command: str) -> str | None:
    if value not in LASTMOD_CHOICES:
        fail_agent(
            f"--lastmod must be one of {'|'.join(LASTMOD_CHOICES)}, got {value!r}",
            command=command,
            example="scout --json sitemap gen --root public "
            "--base-url https://dumbmodel.com --lastmod second",
        )
    return None if value == "none" else value


def _crawl_site_url(name: str, command: str) -> str:
    """A named fleet site or an explicit start URL -> the seo store's site key."""
    url = seo.DEFAULT_SITES.get(name, name)
    if "://" not in url:
        fail_agent(
            f"--from-crawl wants a site name (see: scout seo sites) or a start "
            f"URL, got {name!r}",
            command=command,
            example="scout --json sitemap gen --from-crawl bhenre",
            discover="scout seo sites",
        )
    return seo.site_key(url)


def _collect(
    *,
    command: str,
    root: str | None,
    urls: str | None,
    from_crawl: str | None,
    base_url: str | None,
    exclude: list[str] | None,
    ext: list[str] | None,
    lastmod: str,
    changefreq: str | None,
    priority: float | None,
    strip_index: bool,
    clean_urls: bool,
    db: str | None,
) -> dict:
    """Resolve one URL source into deduped, sorted entries + the base URL.

    Exactly one source is accepted: silently merging a walk with a crawl would
    make the output depend on invocation history, and this generator's contract
    is that the same inputs give the same bytes.
    """
    chosen = [n for n, v in (("--root", root), ("--urls", urls),
                             ("--from-crawl", from_crawl)) if v]
    if len(chosen) != 1:
        fail_agent(
            f"give exactly one URL source (--root, --urls or --from-crawl), got "
            f"{', '.join(chosen) if chosen else 'none'}",
            command=command,
            example="scout --json sitemap gen --root public "
            "--base-url https://dumbmodel.com",
        )
    mode = _lastmod_mode(lastmod, command)
    exts = tuple(ext) if ext else sitemap.DEFAULT_EXTS
    common = {"changefreq": changefreq, "priority": priority}
    try:
        if root:
            if not base_url:
                fail_agent(
                    "--base-url is required with --root (the walk knows paths, "
                    "not your domain)",
                    command=command,
                    example="scout --json sitemap gen --root public "
                    "--base-url https://dumbmodel.com",
                )
            src = sitemap.walk_entries(
                root,
                base_url,
                exts=exts,
                excludes=exclude or [],
                lastmod=mode,
                strip_index=strip_index,
                clean_urls=clean_urls,
                **common,
            )
            base = src["base"]
        elif urls:
            text = Path(urls).read_text(encoding="utf-8")
            src = sitemap.parse_url_list(text, base_url, **common)
            base = src["base"] or sitemap.normalize_base(
                base_url or _origin_of(src["entries"], command)
            )
        else:
            site = _crawl_site_url(from_crawl or "", command)
            path = _seo_db_path(db)
            if not path.exists():
                fail_agent(
                    f"no seo crawl store at {path} — crawl the site first",
                    command=command,
                    example=f"scout --json seo crawl {from_crawl}",
                    discover="scout seo sites",
                )
            conn = seo.open_store(path)
            rows = seo.to_rows(conn, site)
            if not rows:
                fail_agent(
                    f"no crawled pages for {site} in {path}",
                    command=command,
                    example=f"scout --json seo crawl {from_crawl}",
                    discover="scout seo sites",
                )
            src = sitemap.entries_from_crawl_rows(rows, **common)
            base = sitemap.normalize_base(base_url or site)
    except (ValueError, OSError) as exc:
        fail_agent(
            f"{type(exc).__name__}: {exc}",
            command=command,
            example="scout --json sitemap gen --root public "
            "--base-url https://dumbmodel.com",
        )
    collapsed = sitemap.dedupe(src["entries"])
    return {
        "base": base,
        "entries": collapsed["entries"],
        "duplicates": collapsed["duplicates"],
        "skipped": src.get("skipped", []),
        "source": "root" if root else ("urls" if urls else "crawl"),
    }


def _origin_of(entries: list[dict], command: str) -> str:
    """First entry's origin — the implicit base when only a URL list is given."""
    if not entries:
        fail_agent(
            "no URLs found and no --base-url to validate against",
            command=command,
            example="scout --json sitemap gen --urls routes.txt "
            "--base-url https://arxiviq.com",
        )
    u = urlsplit(entries[0]["loc"])
    return f"{u.scheme}://{u.netloc}/"


def _out_path(out: str | None, root: str | None) -> Path:
    """--out, else <root>/sitemap.xml, else ./sitemap.xml."""
    if out:
        return Path(out)
    return (Path(root) if root else Path()) / "sitemap.xml"


def _gate(diags: list[dict], fail_on: str | None, command: str) -> None:
    if fail_on is None:
        return
    if fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json sitemap gen --root public "
            "--base-url https://x.com --fail-on error",
        )
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json sitemap hello"]))
def hello():
    """Smoke check — is the sitemap surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "sitemap"},
            command="sitemap hello",
            example="scout --json sitemap gen --root public --base-url https://x.com",
            discover="scout sitemap detect",
        ),
        command="sitemap hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json sitemap detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="sitemap detect",
            example="scout --json sitemap gen --root public --base-url https://x.com",
            discover="scout sitemap gen --help",
        ),
        command="sitemap detect",
    )


@app.command(
    "gen",
    epilog=examples_epilog(
        [
            "scout --json sitemap gen --root public --base-url https://dumbmodel.com",
            'scout --json sitemap gen --root public --base-url https://dumbmodel.com '
            '--exclude "drafts/*" --clean-urls',
            "scout --json sitemap gen --urls routes.txt --base-url https://arxiviq.com",
            "scout --json sitemap gen --from-crawl bhenre --out public/sitemap.xml",
            "scout --json sitemap gen --root public --base-url https://x.com --dry-run",
        ]
    ),
)
def gen(
    root: str | None = typer.Option(
        None, "--root", help="built site directory to walk (e.g. public)"
    ),
    urls: str | None = typer.Option(
        None, "--urls", help="file of `loc [lastmod]` lines (# comments ok)"
    ),
    from_crawl: str | None = typer.Option(
        None,
        "--from-crawl",
        help="site name or start URL: use the #3 seo crawl store's Indexable rows",
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="site origin (+ optional path prefix) for every loc"
    ),
    out: str | None = typer.Option(
        None, "--out", help="output file (default <root>/sitemap.xml)"
    ),
    exclude: list[str] = typer.Option(
        None,
        "--exclude",
        help="glob to skip, repeatable — matched against the relative path, the "
        "basename, and ancestor dirs (dot-paths and node_modules always skipped)",
    ),
    ext: list[str] = typer.Option(
        None,
        "--ext",
        help=f"extensions to include, repeatable (default {' '.join(sitemap.DEFAULT_EXTS)})",
    ),
    lastmod: str = typer.Option(
        "date", "--lastmod", help=f"lastmod precision: {'|'.join(LASTMOD_CHOICES)}"
    ),
    changefreq: str | None = typer.Option(
        None, "--changefreq", help=f"one of {'|'.join(sitemap.CHANGEFREQS)}"
    ),
    priority: float | None = typer.Option(
        None, "--priority", help="0.0-1.0 applied to every URL"
    ),
    strip_index: bool = typer.Option(
        True,
        "--strip-index/--keep-index",
        help="index.html -> the directory URL (what a static host serves)",
    ),
    clean_urls: bool = typer.Option(
        False,
        "--clean-urls/--no-clean-urls",
        help="drop .html from locs (Vercel/Netlify-style extensionless routes)",
    ),
    max_urls: int = typer.Option(
        sitemap.MAX_URLS_PER_FILE,
        "--max-urls",
        help="URLs per file; over this, --out becomes a sitemapindex + shards",
    ),
    db: str | None = typer.Option(
        None, "--db", help=f"seo crawl store for --from-crawl (default {seo.DB_REL})"
    ),
    write: bool = typer.Option(
        True, "--write/--dry-run", help="dry-run reports the plan and writes nothing"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any diagnostic is at/above this severity (error|warning|"
        "suggestion|info) — the pre-deploy gate hook",
    ),
):
    """Emit sitemap.xml (+ a sitemapindex over --max-urls). Deterministic bytes."""
    src = _collect(
        command="sitemap gen",
        root=root,
        urls=urls,
        from_crawl=from_crawl,
        base_url=base_url,
        exclude=exclude,
        ext=ext,
        lastmod=lastmod,
        changefreq=changefreq,
        priority=priority,
        strip_index=strip_index,
        clean_urls=clean_urls,
        db=db,
    )
    out_path = _out_path(out, root)
    try:
        files = sitemap.render_files(
            src["entries"], out_path.name, src["base"], max_urls=max_urls
        )
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="sitemap gen",
            example="scout --json sitemap gen --root public --base-url https://x.com "
            "--max-urls 50000",
        )
    diags = sitemap.validate(
        src["entries"],
        src["base"],
        duplicates=src["duplicates"],
        max_urls=max_urls,
    ) + sitemap.validate_files(files)
    diags = openswap.sort_diagnostics(diags)
    written: list[str] = []
    if write:
        # call-site enforcement: the plugin loader does not check fs_write for us
        enforce_or_raise(_manifest(), "fs_write", str(out_path))
        try:
            written = sitemap.write_files(files, out_path.parent)
        except OSError as exc:
            fail_agent(
                f"could not write {out_path}: {exc}",
                command="sitemap gen",
                example="scout --json sitemap gen --root public "
                "--base-url https://x.com --out public/sitemap.xml",
            )
    emit(
        ok(
            {
                "source": src["source"],
                "base": src["base"],
                "out": str(out_path),
                "written": written,
                "wrote": bool(written),
                **sitemap.summarize_files(files),
                "skipped": src["skipped"],
                "duplicates": src["duplicates"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="sitemap gen",
            example=f"scout --json sitemap lint {out_path}",
            discover="scout sitemap check --help",
        ),
        command="sitemap gen",
    )
    _gate(diags, fail_on, "sitemap gen")


@app.command(
    "check",
    epilog=examples_epilog(
        [
            "scout --json sitemap check --root public --base-url https://dumbmodel.com",
            "scout --json sitemap check --from-crawl bhenre --out public/sitemap.xml",
        ]
    ),
)
def check(
    root: str | None = typer.Option(None, "--root", help="built site directory to walk"),
    urls: str | None = typer.Option(None, "--urls", help="file of `loc [lastmod]` lines"),
    from_crawl: str | None = typer.Option(
        None, "--from-crawl", help="site name or start URL (the #3 seo crawl store)"
    ),
    base_url: str | None = typer.Option(None, "--base-url", help="site origin for locs"),
    out: str | None = typer.Option(
        None, "--out", help="sitemap to compare against (default <root>/sitemap.xml)"
    ),
    exclude: list[str] = typer.Option(None, "--exclude", help="glob to skip, repeatable"),
    ext: list[str] = typer.Option(None, "--ext", help="extensions to include, repeatable"),
    lastmod: str = typer.Option(
        "date", "--lastmod", help=f"lastmod precision: {'|'.join(LASTMOD_CHOICES)}"
    ),
    changefreq: str | None = typer.Option(None, "--changefreq", help="protocol hint"),
    priority: float | None = typer.Option(None, "--priority", help="0.0-1.0"),
    strip_index: bool = typer.Option(True, "--strip-index/--keep-index", help="see gen"),
    clean_urls: bool = typer.Option(
        False, "--clean-urls/--no-clean-urls", help="see gen"
    ),
    max_urls: int = typer.Option(
        sitemap.MAX_URLS_PER_FILE, "--max-urls", help="URLs per file"
    ),
    db: str | None = typer.Option(None, "--db", help="seo crawl store for --from-crawl"),
    context: int = typer.Option(3, "--context", help="unified-diff context lines"),
):
    """Is the committed sitemap current? Regenerate, diff, exit 1 on drift.

    Writes nothing. Because the output carries no timestamp, drift can only
    mean the site's URL set or lastmods changed — the exact CI signal "you
    deployed content without regenerating the sitemap".
    """
    src = _collect(
        command="sitemap check",
        root=root,
        urls=urls,
        from_crawl=from_crawl,
        base_url=base_url,
        exclude=exclude,
        ext=ext,
        lastmod=lastmod,
        changefreq=changefreq,
        priority=priority,
        strip_index=strip_index,
        clean_urls=clean_urls,
        db=db,
    )
    out_path = _out_path(out, root)
    files = sitemap.render_files(
        src["entries"], out_path.name, src["base"], max_urls=max_urls
    )
    res = sitemap.diff_files(files, out_path.parent, context=context)
    diff_lines = res["diff"][:200]
    emit(
        ok(
            {
                "source": src["source"],
                "base": src["base"],
                "out": str(out_path),
                **sitemap.summarize_files(files),
                "drift": res["drift"],
                "missing": res["missing"],
                "changed": res["changed"],
                "unchanged": res["unchanged"],
                "stale": res["stale"],
                "diff": diff_lines,
                "diff_truncated": len(res["diff"]) > len(diff_lines),
            },
            command="sitemap check",
            example="scout --json sitemap gen --root public --base-url https://x.com",
            discover="scout sitemap gen --help",
        ),
        command="sitemap check",
    )
    if res["drift"]:
        raise typer.Exit(code=1)


@app.command(
    "lint",
    epilog=examples_epilog(
        [
            "scout --json sitemap lint public/sitemap.xml",
            "scout --json sitemap lint public/sitemap.xml "
            "--base-url https://dumbmodel.com --fail-on error",
        ]
    ),
)
def lint(
    path: str = typer.Argument(..., help="an existing sitemap.xml or sitemapindex"),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="origin every loc must sit under (default: the first loc's origin, "
        "so a mixed-host sitemap is still flagged)",
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 at/above this severity (error|warning|...)"
    ),
):
    """Validate a sitemap someone else wrote (or an older build). Fully offline."""
    p = Path(path)
    if not p.exists():
        fail_agent(
            f"no such file: {p}",
            command="sitemap lint",
            example="scout --json sitemap lint public/sitemap.xml",
        )
    try:
        parsed = sitemap.parse_sitemap(p.read_bytes().decode("utf-8", errors="replace"))
    except ValueError as exc:
        fail_agent(
            f"{p} is not a sitemap: {exc}",
            command="sitemap lint",
            example="scout --json sitemap lint public/sitemap.xml",
        )
    try:
        base = (
            sitemap.normalize_base(base_url)
            if base_url
            else _origin_of(parsed["entries"], "sitemap lint")
        )
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="sitemap lint",
            example="scout --json sitemap lint public/sitemap.xml "
            "--base-url https://x.com",
        )
    collapsed = sitemap.dedupe(parsed["entries"])
    size = p.stat().st_size
    diags = openswap.sort_diagnostics(
        sitemap.validate(
            collapsed["entries"], base, duplicates=collapsed["duplicates"]
        )
        + sitemap.validate_files([{"name": p.name, "bytes": size}])
    )
    emit(
        ok(
            {
                "path": str(p),
                "kind": parsed["kind"],
                "base": base,
                "urls": parsed["count"],
                "unique_urls": len(collapsed["entries"]),
                "bytes": size,
                "duplicates": collapsed["duplicates"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="sitemap lint",
            example="scout --json sitemap gen --root public --base-url https://x.com",
            discover="scout sitemap check --help",
        ),
        command="sitemap lint",
    )
    _gate(diags, fail_on, "sitemap lint")


def register(root):
    root.add_typer(app, name="sitemap")
