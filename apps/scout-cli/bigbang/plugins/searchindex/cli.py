# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout searchindex` — Algolia DocSearch replacement, unhosted (openswap #23).

Algolia sells a hosted index plus a JS widget: you upload every page, hold an API
key, and their CDN answers your visitors' keystrokes (and logs them). This
adapter keeps the widget and deletes the cluster: `build` reads the pages you own
and writes a STATIC ARTIFACT — a manifest, first-character-routed JSON shards,
and one dependency-free client — that you deploy next to the site. The browser
fetches the manifest plus the one shard a query routes to, both from your own
origin, and ranks locally. No key, no dashboard, no query telemetry.

Not a duplicate of search #20: that adapter is a sqlite3 FTS5 database only this
box can query (it needs Python + sqlite + the .db file and cannot ship). This one
emits deployable bytes a browser executes with zero runtime. They deliberately
share a corpus layer — `search.iter_files` and `search.read_document` do the walk
and the read here too, rather than this plugin growing a second walker.

All deterministic logic lives in bigbang/core/searchindex.py (fold/tokenize/
stem, field weighting, route planning, artifact rendering, ranking, verify). This
surface adds only path resolution, argument parsing, the fs_write policy gate,
and the two real I/O acts: reading the corpus and writing the artifact
(write_bytes — write_text would emit CRLF on Windows and every file would then
fail its own recorded sha256).

Policy: no network call, no socket. The manifest disables the network axis
outright, so "no query and no page ever left the box" is architectural.
`pagefind`/`lunr` are surfaced by `detect` as optional local alternatives;
Algolia's own CLI is named but NEVER executed — its whole job is uploading your
corpus to the paid SaaS (the forbidden network tier).
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from bigbang.core import openswap, search, searchindex
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib build-time index is the complete product for this adapter: "
    "tokenizer + stopwords + guarded light stemmer, weighted per-field postings, "
    "first-character-routed JSON shards (a prefix query costs ONE fetch), a "
    "dependency-free JS client, sha256-verifiable artifacts and a Python "
    "ranker that mirrors the client; tier 'fallback' is the expected steady "
    "state (Algolia's product is the hosted cluster — there is no local native "
    "binary that is a superset of this core to prefer)"
)
INSTALL_HINT = (
    "nothing to install — the artifact is stdlib JSON plus one vanilla JS file; "
    "install pagefind only if you also want its WASM chunked-index format, or "
    "node if you want to unit-test the generated client yourself"
)

app = make_plugin_app(
    "searchindex",
    "Build-time site-search index (Algolia DocSearch-class): sharded JSON + a "
    "dependency-free JS client for pages you own, zero egress",
    examples=[
        "scout --json searchindex build public --out public/search --ext html",
        "scout --json searchindex build docs --out dist/search --base-url https://example.com/",
        'scout --json searchindex query "release notes" --out public/search',
        "scout --json searchindex verify --out public/search --fail-on error",
        "scout --json searchindex detect",
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
    # No local native binary is a superset of this core (Algolia's product is the
    # hosted index). pagefind and lunr are benign optional local alternatives and
    # node an optional way to test the emitted client; the algolia CLI is
    # surfaced for awareness but NEVER executed — its whole job is uploading the
    # corpus to the paid SaaS.
    native = openswap.probe_binary("pagefind", probe_args=("--version",))
    extras = {
        "node": openswap.probe_binary("node", probe_args=("--version",)),
        "lunr": openswap.probe_binary("lunr", probe_args=("--version",)),
        "algolia": openswap.probe_binary("algolia", probe_args=("--version",)),
    }
    report = openswap.capability_report(
        "searchindex",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    report["artifact"] = {
        "manifest": searchindex.INDEX_NAME,
        "client": searchindex.CLIENT_NAME,
        "client_sha256": searchindex.sha256_bytes(searchindex.client_js()),
        "stopwords": searchindex.stopword_provenance()["sha256"],
        "page_extensions": list(searchindex.PAGE_EXTS),
    }
    return report


def _out_dir(out: str | None) -> Path:
    return Path(out or os.environ.get("SCOUT_SEARCHINDEX_OUT") or "searchindex-out")


def _check_fail_on(value: str | None, command: str, example: str) -> None:
    if value is not None and value not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {value!r}",
            command=command,
            example=example,
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    """Exit 1 when any diagnostic is at/above the requested severity."""
    if fail_on is None:
        return
    gate_rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
        raise typer.Exit(code=1)


def _weights(values: list[str] | None) -> dict[str, int]:
    """--weight title=8 (repeatable) -> {"title": 8}. A typo is an error."""
    out: dict[str, int] = {}
    for raw in values or []:
        field, sep, number = str(raw).partition("=")
        if not sep or not number.strip().lstrip("-").isdigit():
            fail_agent(
                f"--weight wants field=INT, got {raw!r}",
                command="searchindex build",
                example="scout --json searchindex build docs --out out --weight title=12",
            )
        out[field.strip()] = int(number)
    return out


def _read_corpus(
    roots: list[str],
    *,
    include: list[str] | None,
    exclude: list[str] | None,
    exclude_dirs: list[str] | None,
    max_kb: int,
    base_url: str | None,
    strip_index: bool,
    clean_urls: bool,
    keep_boilerplate: bool,
) -> tuple[list[dict], list[dict]]:
    """The real read: corpus files -> extracted page dicts, sorted by rel path.

    One root at a time, because a page's URL is its path RELATIVE TO ITS ROOT —
    walking all roots at once would lose which root a file came from and produce
    URLs with the CWD baked in. Two roots contributing the same site-relative
    path is reported as `duplicate-path` rather than silently overwritten.
    """
    docs: list[dict] = []
    skipped: list[dict] = []
    claimed: dict[str, str] = {}
    for root in roots:
        rp = Path(root)
        if not rp.exists():
            skipped.append({"path": search.norm_path(rp), "reason": "missing-root"})
            continue
        for stored, real in search.iter_files(
            [rp], include=include, exclude=exclude, exclude_dirs=exclude_dirs
        ):
            rel = real.name if rp.is_file() else real.relative_to(rp).as_posix()
            if rel in claimed:
                skipped.append({"path": stored, "reason": "duplicate-path"})
                continue
            text, reason, _meta = search.read_document(real, max_kb=max_kb)
            if reason is not None:
                skipped.append({"path": stored, "reason": reason})
                continue
            claimed[rel] = stored
            url, _kind = searchindex.url_for_rel(
                rel, base_url=base_url, strip_index=strip_index, clean_urls=clean_urls
            )
            doc = searchindex.extract_document(
                text, rel=rel, url=url, keep_boilerplate=keep_boilerplate
            )
            doc["source"] = stored
            docs.append(doc)
    docs.sort(key=lambda d: d["path"])
    return docs, skipped


def _load_artifact(out: Path, command: str) -> tuple[dict, dict[str, bytes]]:
    """Read a built artifact back off disk: (manifest, {name: bytes})."""
    index_path = out / searchindex.INDEX_NAME
    if not index_path.exists():
        fail_agent(
            f"no search index at {index_path} — build one first",
            command=command,
            example="scout --json searchindex build public --out public/search",
            discover="scout searchindex detect",
        )
    files: dict[str, bytes] = {}
    for child in sorted(out.iterdir()):
        if child.is_file() and searchindex.is_artifact_name(child.name):
            files[child.name] = child.read_bytes()
    try:
        manifest = searchindex.load_manifest_bytes(files[searchindex.INDEX_NAME])
    except ValueError as exc:
        fail_agent(
            str(exc),
            command=command,
            example="scout --json searchindex build public --out public/search",
        )
    return manifest, files


@app.command("hello", epilog=examples_epilog(["scout --json searchindex hello"]))
def hello():
    """Smoke check — is the searchindex surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "searchindex"},
            command="searchindex hello",
            example="scout --json searchindex build public --out public/search",
            discover="scout searchindex detect",
        ),
        command="searchindex hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json searchindex detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="searchindex detect",
            example="scout --json searchindex build public --out public/search",
            discover="scout searchindex verify --out public/search",
        ),
        command="searchindex detect",
    )


@app.command(
    "build",
    epilog=examples_epilog(
        [
            "scout --json searchindex build public --out public/search --ext html",
            "scout --json searchindex build docs --out dist/search --ext md --base-url https://example.com/docs/",
            "scout --json searchindex build public --out public/search --shards 16 --clean-urls",
            "scout --json searchindex build public --out out --weight title=12 --weight body=1",
            "scout --json searchindex build public --out out --dry-run --fail-on warning",
        ]
    ),
)
def build(
    roots: list[str] = typer.Argument(..., help="page directories and/or files to index (no implicit default)"),
    out: str | None = typer.Option(None, "--out", help="artifact directory (default $SCOUT_SEARCHINDEX_OUT or ./searchindex-out)"),
    ext: list[str] = typer.Option(None, "--ext", help=f"only index this extension, repeatable (html / .html / *.html all mean *.html; default {', '.join(searchindex.PAGE_EXTS)}) — wildcard-free, so prefer it over --glob on Windows"),
    glob: list[str] = typer.Option(None, "--glob", help="include glob, repeatable (Windows: click may expand a bare *.html against the CWD first)"),
    exclude: list[str] = typer.Option(None, "--exclude", help="exclude glob, repeatable (wins over --glob)"),
    exclude_dir: list[str] = typer.Option(None, "--exclude-dir", help="directory names to prune (default: the shared vendor/VCS set)"),
    base_url: str | None = typer.Option(None, "--base-url", help="absolute site base; without it result URLs are root-relative and labelled url_kind=relative (no domain is invented)"),
    shards: int = typer.Option(searchindex.DEFAULT_SHARDS, "--shards", help="target shard count (capped by the number of distinct first characters)"),
    max_kb: int = typer.Option(1024, "--max-kb", help="skip pages larger than this"),
    weight: list[str] = typer.Option(None, "--weight", help="field=INT, repeatable (title/heading/description/path/body; defaults 8/4/3/2/1)"),
    stemming: bool = typer.Option(True, "--stem/--no-stem", help="light stemming (plurals, -ing/-ed)"),
    keep_stopwords: bool = typer.Option(False, "--keep-stopwords", help="index function words too (bigger shards, exact phrases reachable)"),
    keep_boilerplate: bool = typer.Option(False, "--keep-nav", help="index <nav>/<footer> text (it repeats on every page)"),
    clean_urls: bool = typer.Option(False, "--clean-urls", help="drop .html from result URLs (Vercel/Netlify style)"),
    strip_index: bool = typer.Option(True, "--strip-index/--keep-index", help="index.html -> its directory URL"),
    dry_run: bool = typer.Option(False, "--dry-run", help="build and report, write nothing"),
    fail_on: str | None = typer.Option(None, "--fail-on", help="exit 1 if any finding is at/above this severity (empty index / missing root = error) — the pre-deploy gate hook"),
):
    """Build the deployable index: read the pages, write manifest + shards + client."""
    _check_fail_on(
        fail_on, "searchindex build", "scout --json searchindex build p --out o --fail-on error"
    )
    out_dir = _out_dir(out)
    include = [*searchindex.ext_globs(ext), *(glob or [])] or None
    docs, skipped = _read_corpus(
        roots,
        include=include,
        exclude=exclude or None,
        exclude_dirs=exclude_dir or None,
        max_kb=max_kb,
        base_url=base_url,
        strip_index=strip_index,
        clean_urls=clean_urls,
        keep_boilerplate=keep_boilerplate,
    )
    try:
        index = searchindex.build_index(
            docs,
            shards=shards,
            weights=_weights(weight),
            stemming=stemming,
            stopwords=frozenset() if keep_stopwords else None,
            site=base_url,
            url_kind="absolute" if base_url else "relative",
        )
        rendered = searchindex.render_files(index)
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="searchindex build",
            example="scout --json searchindex build public --out public/search",
        )
    index["report"]["skipped"] = sorted(
        [*skipped, *index["report"]["skipped"]], key=lambda s: (s["path"], s["reason"])
    )
    written = [] if dry_run else _write_artifact(out_dir, rendered["files"])
    _emit_build(
        out_dir,
        index["report"],
        rendered,
        written=written,
        dry_run=dry_run,
        include=include,
        fail_on=fail_on,
    )


def _emit_build(
    out_dir: Path,
    report: dict,
    rendered: dict,
    *,
    written: list[str],
    dry_run: bool,
    include: list[str] | None,
    fail_on: str | None,
) -> None:
    """Emit the build envelope and apply the gate (kept out of build() so the
    command reads as the pipeline it is: read -> index -> render -> write)."""
    diags = searchindex.to_diagnostics(report)
    emit(
        ok(
            {
                "out": str(out_dir),
                "written": written,
                "dry_run": dry_run,
                # what was ACTUALLY applied — provenance beats assuming the
                # shell handed us the patterns we typed
                "include": include or searchindex.default_include(),
                "fingerprint": rendered["manifest"]["fingerprint"],
                "generated_utc": rendered["manifest"]["generated_utc"],
                "url_kind": rendered["manifest"]["url_kind"],
                "shards": rendered["manifest"]["shards"],
                "bytes": rendered["sizes"],
                **report,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="searchindex build",
            example=f'scout --json searchindex query "your terms" --out {out_dir}',
            discover="scout searchindex verify --out " + str(out_dir),
        ),
        command="searchindex build",
    )
    _gate(diags, fail_on)


def _write_artifact(out_dir: Path, files: dict[str, bytes]) -> list[str]:
    """The one write: every artifact file, byte-exact. Policy-gated at call site."""
    enforce_or_raise(_manifest(), "fs_write", str(out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, data in sorted(files.items()):
        (out_dir / name).write_bytes(data)
    return sorted(files)


@app.command(
    "query",
    epilog=examples_epilog(
        [
            'scout --json searchindex query "release notes" --out public/search',
            'scout --json searchindex query "pricing" --out public/search --limit 3',
            'scout --json searchindex query "tok" --out public/search --no-prefix',
            'scout --json searchindex query "widget pricing" --out out --any',
            'scout --json searchindex query "nothing here" --out out --fail-empty',
        ]
    ),
)
def query(
    text: str = typer.Argument(..., help="what a visitor would type"),
    out: str | None = typer.Option(None, "--out", help="artifact directory"),
    limit: int = typer.Option(searchindex.DEFAULT_LIMIT, "--limit", help="max hits"),
    prefix: bool = typer.Option(
        True,
        "--prefix/--no-prefix",
        help="expand the LAST term as a prefix (as-you-type), capped and "
        "confined to the shard already loaded",
    ),
    match_all: bool = typer.Option(
        True, "--all/--any", help="every term must match (default) or any may"
    ),
    fail_empty: bool = typer.Option(
        False, "--fail-empty", help="exit 1 when nothing matched — the CI assertion"
    ),
):
    """Rank the BUILT artifact exactly as the shipped client would. No network.

    This is the honesty check on a deploy: it reads the same JSON files the
    browser downloads and runs the same algorithm, so "the search box works" is
    verified against the artifact rather than assumed from a green build.
    """
    out_dir = _out_dir(out)
    manifest, files = _load_artifact(out_dir, "searchindex query")
    absent = [s["name"] for s in manifest.get("shards") or [] if s["name"] not in files]
    if absent:
        # answering from a partial artifact would silently under-report hits
        fail_agent(
            f"manifest names {len(absent)} shard file(s) that are not here: {absent}",
            command="searchindex query",
            example=f"scout --json searchindex verify --out {out_dir}",
            discover="scout searchindex verify --out " + str(out_dir),
        )
    try:
        result = searchindex.rank(
            manifest,
            lambda name: searchindex.load_shard_bytes(files.get(name)),
            text,
            limit=limit,
            prefix=prefix,
            match_all=match_all,
        )
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="searchindex query",
            example=f"scout --json searchindex verify --out {out_dir}",
        )
    emit(
        ok(
            {
                "out": str(out_dir),
                "fingerprint": manifest.get("fingerprint"),
                "doc_count": manifest.get("doc_count"),
                "term_count": manifest.get("term_count"),
                **result,
            },
            command="searchindex query",
            example=f"scout --json searchindex verify --out {out_dir}",
            discover="scout searchindex verify --out " + str(out_dir),
        ),
        command="searchindex query",
    )
    if fail_empty and not result["hits"]:
        raise typer.Exit(code=1)


@app.command(
    "verify",
    epilog=examples_epilog(
        [
            "scout --json searchindex verify --out public/search",
            "scout --json searchindex verify --out public/search --fail-on error",
            "scout --json searchindex verify --out public/search --fail-on suggestion",
        ]
    ),
)
def verify(
    out: str | None = typer.Option(None, "--out", help="artifact directory"),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any finding is at/above this severity (missing or "
        "mismatched file = error) — the post-deploy gate hook",
    ),
):
    """Re-hash the artifact on disk against its manifest. Read-only, no network."""
    _check_fail_on(fail_on, "searchindex verify", "scout --json searchindex verify --fail-on error")
    out_dir = _out_dir(out)
    manifest, files = _load_artifact(out_dir, "searchindex verify")
    report = searchindex.verify(manifest, files, listing=sorted(files))
    diags = searchindex.to_diagnostics(report)
    emit(
        ok(
            {
                "out": str(out_dir),
                "generated_utc": manifest.get("generated_utc"),
                **report,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="searchindex verify",
            example='scout --json searchindex query "your terms" --out ' + str(out_dir),
            discover="scout searchindex detect",
        ),
        command="searchindex verify",
    )
    _gate(diags, fail_on)


def register(root):
    root.add_typer(app, name="searchindex")
