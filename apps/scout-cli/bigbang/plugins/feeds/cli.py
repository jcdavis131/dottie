# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout feeds` — Feedly Pro replacement, fully local (openswap #12).

miniflux pattern with zero install: RSS/Atom in, ranked digest out, and the
only real I/O — one urllib conditional GET per feed — lives here in _fetch.
Everything deterministic lives in bigbang/core/feeds.py (the xml.etree parser
behind a one-function namespace shim, RFC-822/ISO-8601 timestamps, the sha256
dedupe identity, keyword scoring, the sqlite store in .scout/feeds.db, and the
digest emitter in both shapes). Because the ETag/Last-Modified validators are
stored on the feed row and replayed on the next poll, an unchanged feed costs
one empty 304 round-trip — which is what makes an hourly research poll free.

There is no native binary tier to prefer: miniflux and FreshRSS are servers,
and newsboat is a TUI, none of which is a superset of "score, dedupe, and emit
a JSON digest". newsboat/rsstail are probed and surfaced by `detect` for manual
use but never executed — a spawned reader fetches outside the per-URL policy
gate (the links #4 doctrine). So the stdlib core IS the product and `detect`
reports tier=fallback as the expected steady state (scope honesty, not
degradation).

Policy: a seed feed's URL is covered by this plugin's manifest domain allowlist
(default-deny — adding a default feed means adding its domain there too), while
a feed the user types is covered by the persisted user allowlist instead, never
by a manifest widened to match it. `fetch` checks BOTH per URL and records a
denied feed as state "denied" without opening a socket, so one off-allowlist
feed cannot kill the whole poll. `add`, `list` and `digest` make no network
calls at all.
"""

from __future__ import annotations

import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import typer

from bigbang.core import feeds, openswap
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
    "pure-stdlib reader is the complete product for this adapter: xml.etree "
    "RSS 2.0/RSS 1.0/Atom parsing behind one namespace shim, conditional GET "
    "from sqlite-stored ETag/Last-Modified validators, sha256 dedupe by entry "
    "id or link, optional keyword scoring, and a digest emitter in text and "
    "JSON; tier 'fallback' is the expected steady state — miniflux and FreshRSS "
    "are servers and newsboat is a TUI, and all of them are surfaced for manual "
    "use but never executed, because a spawned reader fetches outside the "
    "per-URL policy gate"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; newsboat/rsstail on "
    "PATH are surfaced for manual reading only, never executed by scout"
)

app = make_plugin_app(
    "feeds",
    "Read RSS/Atom (Feedly Pro-class), fully local: conditional GET + sqlite dedupe + scored digest",
    examples=[
        "scout --json feeds add --seed",
        "scout --json feeds add arxiviq --url https://arxiviq.com/feed.xml",
        "scout --json feeds list",
        "scout --json feeds fetch",
        "scout --json feeds digest --min-score 2 --new --mark",
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
    native = openswap.probe_binary("newsboat", probe_args=("--version",))
    extras = {"rsstail": openswap.probe_binary("rsstail", probe_args=("-V",))}
    return openswap.capability_report(
        "feeds",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_FEEDS_DB") or feeds.DB_REL)


def _open_store(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write", str(path))
    return feeds.open_store(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no feed store at {path} — register a feed first",
            command=command,
            example="scout --json feeds add --seed",
        )
    return feeds.open_store(path), path


def _gate(url: str) -> tuple[bool, str]:
    """Manifest allowlist OR the persisted user allowlist — default-deny.

    Two lists on purpose (the links #4 doctrine): the manifest names the seed
    research sources this plugin ships with, and the user's own policy file
    names everything they added by hand. A URL in neither is refused here and
    recorded as a report row, never fetched — one off-allowlist feed must not
    kill the whole poll.
    """
    allowed, why = check_permission(_manifest(), "network", url)
    if allowed:
        return True, "manifest allowlist"
    allowed_user, why_user = check_user_url(url)
    if allowed_user:
        return True, "user allowlist"
    return False, f"{why}; {why_user}"


def _keywords_or_fail(keywords_file: str | None, command: str) -> dict:
    try:
        return feeds.load_keywords(keywords_file)
    except Exception as e:
        fail_agent(
            f"bad keywords file: {e}",
            command=command,
            example="scout --json feeds fetch --keywords research-keywords.json",
        )


def _fetch(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 15.0,
    read_cap: int = 4_000_000,
) -> dict:
    """One conditional GET via urllib. {status, body, etag, last_modified, error}.

    304 arrives as an HTTPError and is an ANSWER, not an outage (the smoke #5
    lesson): the caller must see status 304 so the stored validators survive and
    nothing is re-parsed. The body comes back as undecoded BYTES so parse_feed
    can honor an XML encoding declaration, and it is read only up to read_cap —
    a feed is a page of headlines, not a download.
    """
    req_headers = {
        "User-Agent": "scout-feeds",
        "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    }
    req_headers.update(headers or {})
    # S310 (file:/custom schemes): closed upstream — add_feed admits http(s)
    # only and every URL is policy-gated before this fetch runs
    req = urllib.request.Request(url, headers=req_headers, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(  # noqa: S310
            req, timeout=timeout, context=ssl.create_default_context()
        ) as r:
            return {
                "status": int(r.status),
                "body": r.read(read_cap),
                "etag": r.headers.get("ETag"),
                "last_modified": r.headers.get("Last-Modified"),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        body = b""
        if e.code != 304:  # a 304 carries no body by definition
            try:
                body = e.read(read_cap)
            except Exception:
                body = b""
        hdrs = e.headers
        return {
            "status": int(e.code),
            "body": body,
            "etag": hdrs.get("ETag") if hdrs else None,
            "last_modified": hdrs.get("Last-Modified") if hdrs else None,
            "error": None,
        }
    except Exception as e:
        return {
            "status": None,
            "body": b"",
            "etag": None,
            "last_modified": None,
            "error": f"{type(e).__name__}: {e}",
        }


@app.command("hello", epilog=examples_epilog(["scout --json feeds hello"]))
def hello():
    """Smoke check — is the feeds surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "feeds"},
            command="feeds hello",
            example="scout --json feeds add --seed",
            discover="scout feeds detect",
        ),
        command="feeds hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json feeds detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="feeds detect",
            example="scout --json feeds add --seed",
            discover="scout feeds list",
        ),
        command="feeds detect",
    )


@app.command(
    "add",
    epilog=examples_epilog(
        [
            "scout --json feeds add --seed",
            "scout --json feeds add arxiv-cs-lg --url https://rss.arxiv.org/rss/cs.LG",
            'scout --json feeds add hf-blog --url https://huggingface.co/blog/feed.xml --note "HF blog"',
        ]
    ),
)
def add(
    name: str | None = typer.Argument(
        None, help="feed name ([a-z0-9][a-z0-9._-]*); omit with --seed"
    ),
    url: str | None = typer.Option(None, "--url", help="feed document URL (http/https)"),
    note: str | None = typer.Option(None, "--note", help="why this feed is worth reading"),
    seed: bool = typer.Option(
        False, "--seed", help="register the built-in research feeds (idempotent)"
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"feed store path (default {feeds.DB_REL} or $SCOUT_FEEDS_DB)",
    ),
):
    """Register a feed in the store. No network — `fetch` does the polling."""
    if seed == bool(name or url):
        fail_agent(
            "give a NAME and --url, or --seed (not both)",
            command="feeds add",
            example="scout --json feeds add --seed",
        )
    if not seed and not (name and url):
        fail_agent(
            "a named feed needs both a name and --url",
            command="feeds add",
            example="scout --json feeds add arxiv-cs-lg --url https://rss.arxiv.org/rss/cs.LG",
        )
    conn, path = _open_store(db)
    try:
        added = feeds.seed_feeds(conn) if seed else [feeds.add_feed(conn, name, url, note=note)]
    except ValueError as e:
        fail_agent(
            str(e),
            command="feeds add",
            example="scout --json feeds add arxiv-cs-lg --url https://rss.arxiv.org/rss/cs.LG",
        )
    # provenance up front: say NOW whether the poll will be allowed to fetch it,
    # instead of letting the user discover a policy denial at fetch time
    for row in added:
        allowed, reason = _gate(row["url"])
        row["fetchable"] = allowed
        row["policy"] = reason
    emit(
        ok(
            {
                "db": str(path),
                "added": added,
                "count": len(added),
                "registered": len(feeds.list_feeds(conn)),
            },
            command="feeds add",
            example="scout --json feeds fetch",
            discover="scout feeds list",
        ),
        command="feeds add",
    )


@app.command(
    "list",
    epilog=examples_epilog(
        ["scout --json feeds list", "scout --json feeds list --db .scout/feeds.db"]
    ),
)
def list_cmd(
    db: str | None = typer.Option(None, "--db", help="feed store path"),
):
    """Registry board: validators, counts, policy — read-only, no network."""
    conn, path = _open_existing(db, "feeds list")
    rows = feeds.list_feeds(conn)
    for row in rows:
        allowed, reason = _gate(row["url"])
        row["fetchable"] = allowed
        row["policy"] = reason
    emit(
        ok(
            {
                "db": str(path),
                "count": len(rows),
                "feeds": rows,
                "conditional_ready": sum(1 for r in rows if r["conditional"]),
                "undigested": sum(int(r["undigested"]) for r in rows),
            },
            command="feeds list",
            example="scout --json feeds fetch",
            discover="scout feeds digest",
        ),
        command="feeds list",
    )


@app.command(
    "fetch",
    epilog=examples_epilog(
        [
            "scout --json feeds fetch",
            "scout --json feeds fetch --feed arxiv-cs-lg --feed hf-blog",
            "scout --json feeds fetch --keywords research-keywords.json --fail-on error",
        ]
    ),
)
def fetch_cmd(
    feed: list[str] = typer.Option(
        None, "--feed", help="poll only these feeds (repeatable); default: all registered"
    ),
    db: str | None = typer.Option(None, "--db", help="feed store path"),
    timeout: float = typer.Option(
        15.0, "--timeout", help="per-feed socket timeout, seconds"
    ),
    keywords_file: str | None = typer.Option(
        None, "--keywords", help="JSON {keyword: weight} overlay (policy-as-config)"
    ),
    no_score: bool = typer.Option(
        False, "--no-score", help="store entries unscored (pure reverse-chronological)"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any feed maps at/above this severity (error|warning) "
        "— the cron/CI gate hook for silent research ingestion",
    ),
):
    """One conditional-GET poll over the registry: parse, dedupe, score, record."""
    sanitize_no_proxy_env()
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command="feeds fetch",
            example="scout --json feeds fetch --fail-on error",
        )
    keywords = {} if no_score else _keywords_or_fail(keywords_file, "feeds fetch")
    conn, path = _open_existing(db, "feeds fetch")
    if not feeds.list_feeds(conn):
        fail_agent(
            f"no feeds registered in {path}",
            command="feeds fetch",
            example="scout --json feeds add --seed",
        )

    def fetch(url: str, headers: dict) -> dict:
        return _fetch(url, headers, timeout=timeout)

    try:
        res = feeds.run_fetch(
            conn,
            fetch,
            names=list(feed) if feed else None,  # typer hands back None, not []
            keywords=keywords,
            gate=_gate,
        )
    except ValueError as e:
        fail_agent(
            str(e),
            command="feeds fetch",
            example="scout --json feeds fetch --feed arxiv-cs-lg",
            discover="scout feeds list",
        )
    diags = feeds.to_diagnostics(res["results"])
    emit(
        ok(
            {
                "db": str(path),
                "by_state": res["by_state"],
                "new_entries": res["new_entries"],
                "keywords": len(keywords),
                "results": res["results"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="feeds fetch",
            example="scout --json feeds digest --new --mark",
            discover="scout feeds digest",
        ),
        command="feeds fetch",
    )
    if fail_on is not None:
        gate_rank = openswap.severity_rank(fail_on)
        if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
            raise typer.Exit(code=1)


@app.command(
    "digest",
    epilog=examples_epilog(
        [
            "scout --json feeds digest",
            "scout --json feeds digest --min-score 2 --new --mark",
            "scout --json feeds digest --feed arxiv-cs-lg --hours 24 --limit 5",
            "scout feeds digest --format text --out .scout/digest.txt",
        ]
    ),
)
def digest_cmd(
    db: str | None = typer.Option(None, "--db", help="feed store path"),
    feed: str | None = typer.Option(None, "--feed", help="one feed instead of all"),
    hours: float = typer.Option(
        feeds.DEFAULT_DIGEST_HOURS, "--hours", help="lookback window; 0 = all time"
    ),
    limit: int = typer.Option(
        feeds.DEFAULT_LIMIT, "--limit", help="max items; 0 = unlimited"
    ),
    min_score: float = typer.Option(
        0.0, "--min-score", help="drop entries scoring below this floor"
    ),
    new_only: bool = typer.Option(
        False, "--new/--all", help="only entries never digested before"
    ),
    mark: bool = typer.Option(
        False, "--mark", help="stamp the emitted entries so --new skips them next time"
    ),
    fmt: str = typer.Option(
        "text",
        "--format",
        help="text|json — text adds a rendered digest to the envelope",
    ),
    out: str | None = typer.Option(
        None, "--out", help="also write the rendered text digest to this path"
    ),
):
    """Ranked digest from the store (text + JSON) — read-only, no network."""
    if fmt not in ("text", "json"):
        fail_agent(
            f"--format must be text or json, got {fmt!r}",
            command="feeds digest",
            example="scout --json feeds digest --format text",
        )
    if out and fmt != "text":
        fail_agent(
            "--out writes the rendered text digest — pass --format text",
            command="feeds digest",
            example="scout feeds digest --format text --out .scout/digest.txt",
        )
    conn, path = _open_existing(db, "feeds digest")
    since = None if hours <= 0 else time.time() - hours * 3600.0
    dg = feeds.digest(
        conn,
        feed=feed,
        since=since,
        min_score=min_score,
        limit=limit,
        new_only=new_only,
    )
    data = {
        "db": str(path),
        "window_hours": hours if hours > 0 else None,
        "count": dg["count"],
        "feeds": dg["feeds"],
        "min_score": dg["min_score"],
        "new_only": dg["new_only"],
        "items": dg["items"],
    }
    if fmt == "text":
        data["text"] = feeds.render_digest(dg)
    if out:
        enforce_or_raise(_manifest(), "fs_write", out)
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(data["text"], encoding="utf-8")
        data["out"] = str(out_path)
    if mark:
        data["marked"] = feeds.mark_digested(conn, [i["id"] for i in dg["items"]])
    emit(
        ok(
            data,
            command="feeds digest",
            example="scout --json feeds fetch",
            discover="scout feeds list",
        ),
        command="feeds digest",
    )


def register(root):
    root.add_typer(app, name="feeds")
