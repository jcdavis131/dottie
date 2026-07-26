# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout extract` — Diffbot / Mercury Parser replacement, fully local (openswap #11).

Readability with the API bill deleted: the DOM walk, the text-vs-link-density
scoring that strips nav/footer/aside/script boilerplate, and the title/byline/
date heuristics all run deterministically in bigbang/core/extract.py. The ONLY
real I/O lives here — a urllib GET under a strict timeout and a byte cap, a
local file read, or stdin — plus the sqlite corpus ledger (.scout/extract.db).
That split is why the entire extraction pipeline is unit-testable offline.

This sits on the daily research-ingestion path, so `batch` is the primary
surface and throughput beats latency: the ledger is keyed by sha256 of the raw
HTML, so bytes already parsed come back as a cache hit and are never parsed
twice; URL fetches can run concurrently (--jobs) while the extraction loop still
consumes sources in input order, keeping runs diffable.

There is no native binary tier to prefer: Diffbot is a paid SaaS API and the
surviving Mercury fork (postlight-parser) is a node CLI that does its own
fetching — a spawned extractor would fetch outside the per-URL policy gate, the
exact thing this family forbids (the links #4 doctrine). So `detect` reports
tier=fallback as the expected steady state and surfaces postlight-parser /
readable / trafilatura for manual use only, never executing them.

Policy: local hosts come from this plugin's manifest allowlist; every other
user-typed URL is gated by the persisted user allowlist
(enforce_user_url_or_raise), never by a manifest widened to match the URL being
read. File/stdin input and `corpus` make no network calls at all.
"""

from __future__ import annotations

import os
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import typer

from bigbang.core import extract, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.http_utils import sanitize_no_proxy_env
from bigbang.core.output import emit, is_json
from bigbang.core.policy import (
    check_permission,
    enforce_or_raise,
    enforce_user_url_or_raise,
    load_manifest,
)

FALLBACK_SCOPE = (
    "pure-stdlib article extractor is the complete product for this adapter: "
    "html.parser DOM walk with Readability text-vs-link-density scoring, "
    "nav/footer/aside/script boilerplate stripping, title/byline/date "
    "heuristics (JSON-LD, og:/dc:/twitter: meta, rel=author, <time>), plain "
    "text or JSON output, and a content-hash-deduped sqlite corpus ledger for "
    "batch ingestion; tier 'fallback' is the expected steady state — Diffbot "
    "is a paid SaaS API and postlight-parser/readable/trafilatura are "
    "surfaced for manual use but never executed, because a spawned extractor "
    "fetches outside the per-URL policy gate"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; postlight-parser, "
    "readable or trafilatura on PATH are surfaced for manual use only, never "
    "executed by scout"
)

USER_AGENT = "scout-extract"

app = make_plugin_app(
    "extract",
    "Extract the article out of a page (Diffbot-class), fully local: "
    "Readability-style scoring + title/byline/date, plain text or JSON",
    examples=[
        "scout --json extract read article.html",
        "scout extract read https://example.com/post --text",
        "curl -s https://example.com/post | scout --json extract read -",
        "scout --json extract batch --glob '**/*.html' --root captures",
        "scout --json extract corpus",
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
    native = openswap.probe_binary("postlight-parser", probe_args=("--version",))
    extras = {
        "readable": openswap.probe_binary("readable", probe_args=("--version",)),
        "trafilatura": openswap.probe_binary("trafilatura", probe_args=("--version",)),
    }
    return openswap.capability_report(
        "extract",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_EXTRACT_DB") or extract.DB_REL)


def _open_ledger(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return extract.open_store(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no corpus ledger at {path} — ingest something first",
            command=command,
            example="scout --json extract batch article.html",
        )
    return extract.open_store(path), path


def is_url(source: str) -> bool:
    """http(s) only: file:// and friends would smuggle a read past the gate."""
    return urlsplit(source).scheme in ("http", "https")


def _gate_url(url: str, command: str) -> None:
    """Manifest allowlist (loopback) OR the persisted user allowlist.

    Same doctrine as links #4: the manifest names the hosts this adapter trusts
    by default, and anything else must be in the user's own policy file. A
    manifest is never widened to match the URL being read.
    """
    allowed, _reason = check_permission(_manifest(), "network", url)
    if allowed:
        return
    enforce_user_url_or_raise(url, context=command)


def _fetch_url(url: str, *, timeout: float, max_bytes: int) -> dict:
    """One GET -> {html, url, error}. Redirects followed (an article moves).

    Reads at most max_bytes so a runaway response cannot become a memory event
    mid-batch, and decodes through the core's HTML5 charset precedence
    (BOM > Content-Type > <meta charset> > utf-8) instead of assuming utf-8.
    """
    req = urllib.request.Request(  # noqa: S310 - scheme checked by is_url + gate
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
    )
    try:
        with urllib.request.urlopen(  # noqa: S310
            req, timeout=timeout, context=ssl.create_default_context()
        ) as resp:
            raw = resp.read(max_bytes)
            charset = None
            try:
                charset = resp.headers.get_content_charset()
            except Exception:
                charset = None
            final = resp.geturl() or url
        return {"html": extract.decode_html(raw, charset), "url": final, "error": None}
    except Exception as e:
        # DNS vs TLS vs timeout vs 404 stays distinguishable in the batch report
        return {"html": "", "url": url, "error": f"{type(e).__name__}: {e}"}


def _read_stdin() -> dict:
    try:
        raw = sys.stdin.buffer.read()
    except (AttributeError, ValueError):  # a text-only stdin (some test hosts)
        raw = (sys.stdin.read() or "").encode("utf-8", "replace")
    if not raw.strip():
        return {"html": "", "url": None, "error": "stdin was empty"}
    return {"html": extract.decode_html(raw), "url": None, "error": None}


def _read_file(source: str) -> dict:
    path = Path(source)
    if not path.is_file():
        return {"html": "", "url": None, "error": f"no such file: {path}"}
    try:
        return {
            "html": extract.decode_html(path.read_bytes()),
            "url": path.resolve().as_uri(),
            "error": None,
        }
    except OSError as e:
        return {"html": "", "url": None, "error": f"{type(e).__name__}: {e}"}


def load_source(
    source: str, *, timeout: float = 15.0, max_bytes: int = extract.MAX_FETCH_BYTES
) -> dict:
    """The one I/O boundary: source id -> {html, url, error}. Never raises.

    Tests inject their own callable of this shape into extract.run_batch, which
    is why no test needs a socket.
    """
    if source == extract.STDIN_SOURCE:
        return _read_stdin()
    if is_url(source):
        return _fetch_url(source, timeout=timeout, max_bytes=max_bytes)
    return _read_file(source)


def prefetch(sources: list[str], loader, *, jobs: int = 1) -> dict[str, dict]:
    """source -> document, fetching URLs concurrently when asked.

    Concurrency lives HERE and not in the extraction loop on purpose: the batch
    still consumes sources in input order (deterministic, diffable reports)
    while the network waits overlap, which is the whole throughput story. Policy
    gating happens before this call — never inside a worker thread, where a
    typer.Exit would be swallowed by the future.
    """
    urls = [s for s in sources if is_url(s)]
    if jobs > 1 and len(urls) > 1:
        with ThreadPoolExecutor(max_workers=min(jobs, len(urls))) as pool:
            fetched = dict(zip(urls, pool.map(loader, urls), strict=True))
    else:
        fetched = {s: loader(s) for s in urls}
    for src in sources:
        if src not in fetched:
            fetched[src] = loader(src)
    return fetched


def _fail_on_or_die(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=f"scout --json extract {command.split()[-1]} --fail-on warning",
        )


def _gate_exit(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json extract hello"]))
def hello():
    """Smoke check — is the extract surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "extract"},
            command="extract hello",
            example="scout --json extract read article.html",
            discover="scout extract detect",
        ),
        command="extract hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json extract detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="extract detect",
            example="scout --json extract read article.html",
            discover="scout extract read --help",
        ),
        command="extract detect",
    )


@app.command(
    "read",
    epilog=examples_epilog(
        [
            "scout --json extract read article.html",
            "scout extract read article.html --text",
            "scout extract read https://example.com/post --text > post.txt",
            "cat page.html | scout --json extract read -",
            "scout --json extract read article.html --record --fail-on warning",
        ]
    ),
)
def read(
    source: str = typer.Argument(..., help="file path, http(s) URL, or - for stdin"),
    text_out: bool = typer.Option(
        False,
        "--text",
        help="write ONLY the article text to stdout (pipe-friendly); "
        "ignored under --json, which always emits the envelope",
    ),
    timeout: float = typer.Option(15.0, "--timeout", help="URL fetch timeout, seconds"),
    max_bytes: int = typer.Option(
        extract.MAX_FETCH_BYTES, "--max-bytes", help="cap on bytes read from a URL"
    ),
    min_chars: int = typer.Option(
        extract.MIN_PARAGRAPH_CHARS,
        "--min-chars",
        help="shortest text run scored as a paragraph (Readability's floor)",
    ),
    thin_words: int = typer.Option(
        extract.THIN_WORDS, "--thin-words", help="below this a result is thin-content"
    ),
    record: bool = typer.Option(
        False, "--record/--no-record", help="persist into the corpus ledger"
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"corpus ledger path (default {extract.DB_REL} or $SCOUT_EXTRACT_DB)",
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if extraction quality maps at/above this severity "
        "(error|warning|suggestion) — the ingestion gate hook",
    ),
):
    """One page -> title, byline, date, text, word_count. Real I/O lives here."""
    _fail_on_or_die(fail_on, "extract read")
    if is_url(source):
        sanitize_no_proxy_env()
        _gate_url(source, "extract read")
    doc = load_source(source, timeout=timeout, max_bytes=max_bytes)
    if doc["error"]:
        fail_agent(
            f"cannot read {source}: {doc['error']}",
            command="extract read",
            example="scout --json extract read article.html",
        )
    res = extract.extract(
        doc["html"], url=doc["url"], source=source, min_paragraph_chars=min_chars
    )
    if record:
        conn, path = _open_ledger(db)
        res["id"] = extract.record_document(conn, res)
        res["db"] = str(path)
    diags = extract.to_diagnostics([res], thin_words=thin_words)
    if text_out and not is_json():
        # the pipe-friendly ingestion mode: article text, nothing else
        typer.echo(res["text"])
        _gate_exit(diags, fail_on)
        return
    emit(
        ok(
            {**res, "diagnostics": diags, "summary": openswap.summarize(diags)},
            command="extract read",
            example="scout --json extract batch --glob '**/*.html'",
            discover="scout extract corpus",
        ),
        command="extract read",
    )
    _gate_exit(diags, fail_on)


@app.command(
    "batch",
    epilog=examples_epilog(
        [
            "scout --json extract batch a.html b.html",
            "scout --json extract batch --glob '**/*.html' --root captures",
            "scout --json extract batch --list urls.txt --jobs 8",
            "scout --json extract batch --list urls.txt --fail-on error",
        ]
    ),
)
def batch(
    sources: list[str] = typer.Argument(
        None, help="file paths and/or http(s) URLs (or use --list / --glob)"
    ),
    list_file: str | None = typer.Option(
        None, "--list", help="newline-delimited sources file (# comments allowed)"
    ),
    glob: str | None = typer.Option(
        None, "--glob", help="glob under --root, e.g. '**/*.html' (sorted, stable)"
    ),
    root: str = typer.Option(".", "--root", help="directory --glob is relative to"),
    jobs: int = typer.Option(
        4, "--jobs", help="concurrent URL fetches; files are read serially"
    ),
    timeout: float = typer.Option(15.0, "--timeout", help="per-URL fetch timeout"),
    max_bytes: int = typer.Option(
        extract.MAX_FETCH_BYTES, "--max-bytes", help="cap on bytes read per URL"
    ),
    min_chars: int = typer.Option(
        extract.MIN_PARAGRAPH_CHARS, "--min-chars", help="paragraph scoring floor"
    ),
    thin_words: int = typer.Option(
        extract.THIN_WORDS, "--thin-words", help="thin-content threshold, words"
    ),
    db: str | None = typer.Option(None, "--db", help="corpus ledger path"),
    record: bool = typer.Option(
        True,
        "--record/--no-record",
        help="persist into the corpus ledger (off = extract-and-report only)",
    ),
    cache: bool = typer.Option(
        True,
        "--cache/--no-cache",
        help="reuse a stored row when the page bytes are unchanged "
        "(the batch throughput win) — --no-cache forces a re-parse",
    ),
    full_text: bool = typer.Option(
        False, "--full-text", help="include every article body in the JSON envelope"
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 on any diagnostic at/above this severity"
    ),
):
    """Ingest many pages: cache-deduped, input-ordered, one report. The daily path."""
    _fail_on_or_die(fail_on, "extract batch")
    want = list(sources or [])
    if list_file:
        path = Path(list_file)
        if not path.is_file():
            fail_agent(
                f"no source list at {path}",
                command="extract batch",
                example="scout --json extract batch --list urls.txt",
            )
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                want.append(line)
    if glob:
        want.extend(sorted(str(p) for p in Path(root).glob(glob) if p.is_file()))
    # de-dupe while keeping input order: the report must stay diffable
    seen: set[str] = set()
    ordered = [s for s in want if not (s in seen or seen.add(s))]
    if not ordered:
        fail_agent(
            "no sources — pass paths/URLs, --list FILE or --glob PATTERN",
            command="extract batch",
            example="scout --json extract batch --glob '**/*.html' --root captures",
            discover="scout extract read --help",
        )
    if any(is_url(s) for s in ordered):
        sanitize_no_proxy_env()
        for src in ordered:  # gate BEFORE any worker thread exists
            if is_url(src):
                _gate_url(src, "extract batch")

    if record:
        conn, path = _open_ledger(db)
    else:
        conn, path = extract.open_store(":memory:"), None  # dry-run, same pipeline

    def loader(src: str) -> dict:
        return load_source(src, timeout=timeout, max_bytes=max_bytes)

    fetched = prefetch(ordered, loader, jobs=jobs)
    res = extract.run_batch(
        conn,
        ordered,
        lambda src: fetched.get(src, {"error": "not fetched"}),
        record=record,
        use_cache=cache,
        min_paragraph_chars=min_chars,
    )
    diags = extract.to_diagnostics(res["results"], thin_words=thin_words)
    rows = [
        {k: v for k, v in r.items() if full_text or k != "text"} for r in res["results"]
    ]
    emit(
        ok(
            {
                "db": str(path) if path else None,
                "recorded": record,
                "sources": len(ordered),
                "extracted": res["extracted"],
                "cached": res["cached"],
                "failed": res["failed"],
                "words": res["words"],
                "results": rows,
                "failures": res["failures"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="extract batch",
            example="scout --json extract corpus",
            discover="scout extract corpus",
        ),
        command="extract batch",
    )
    _gate_exit(diags, fail_on)


@app.command(
    "corpus",
    epilog=examples_epilog(
        [
            "scout --json extract corpus",
            "scout --json extract corpus --limit 50",
            "scout --json extract corpus --id 3 --text",
        ]
    ),
)
def corpus(
    db: str | None = typer.Option(None, "--db", help="corpus ledger path"),
    limit: int = typer.Option(20, "--limit", help="rows to list (newest first)"),
    source: str | None = typer.Option(
        None, "--source", help="only rows ingested from this exact source id"
    ),
    doc_id: int | None = typer.Option(
        None, "--id", help="one document instead of the listing"
    ),
    text_out: bool = typer.Option(
        False, "--text", help="with --id: write ONLY the stored text to stdout"
    ),
):
    """Corpus rollup + recent rows from the ledger — no fetches, no network."""
    conn, path = _open_existing(db, "extract corpus")
    if doc_id is not None:
        doc = extract.document_text(conn, doc_id)
        if doc is None:
            fail_agent(
                f"no document with id {doc_id} in {path}",
                command="extract corpus",
                example="scout --json extract corpus --limit 50",
            )
        if text_out and not is_json():
            typer.echo(doc["text"])
            return
        emit(
            ok(
                {"db": str(path), **doc},
                command="extract corpus",
                example="scout --json extract corpus",
                discover="scout extract corpus",
            ),
            command="extract corpus",
        )
        return
    emit(
        ok(
            {
                "db": str(path),
                "stats": extract.corpus_stats(conn),
                "documents": extract.recent_documents(conn, limit=limit, source=source),
            },
            command="extract corpus",
            example="scout --json extract corpus --id 1 --text",
            discover="scout extract batch --help",
        ),
        command="extract corpus",
    )


def register(root):
    root.add_typer(app, name="extract")
