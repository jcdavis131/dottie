# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout later` — Pocket / Raindrop replacement, on this box (openswap #34).

A read-later inbox whose identity is a CANONICAL url: save the same article from
a newsletter, a tweet and a bookmark export and it is ONE sqlite row with the
union of its tags. `fetch` is the only command that opens a socket, and the GET
is injected into bigbang/core/later.run_fetch as a callable, so every judgment —
canonicalisation, dedupe, the lifecycle, the diagnostics — is unit-testable
offline with no fixture server.

The chain, not a silo: `pull` reads the #12 `feeds` store (Feedly) and turns
ranked entries into offers, `fetch` hands each page to #11 `extract` (Diffbot)
and stores the corpus doc_id. Nothing here parses a feed or an article; the
queue's own job is identity, triage and provenance. See the core module
docstring for why this is not an extension of feeds' entries table (feeds
dedupes per SUBSCRIPTION on purpose; an inbox must dedupe globally on the url).

Policy: `add`, `import`, `canon`, `list`, `mark` and `board` make ZERO network
calls — they cannot, there is no code path. `fetch` is default-deny twice over:
this plugin's manifest allowlists LOOPBACK ONLY (a read-later queue holds
arbitrary user-chosen urls, so a manifest naming them would be a rubber stamp),
and every other host must be in the PERSISTED USER allowlist
(`scout reach allow <host>`). A url in neither list is recorded state "denied"
with no socket opened, so one off-allowlist link cannot kill the pass.

There is no native tier and `native_used` is False on every tier: wallabag is a
PHP web app, and shiori / buku / archivebox each own their own store and fetch
outside this policy gate, so they are PROBED for awareness and never executed.
"""

from __future__ import annotations

import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import typer

from bigbang.core import extract, feeds, later, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import (
    check_permission,
    check_user_url,
    enforce_or_raise,
    load_manifest,
)

FALLBACK_SCOPE = (
    "pure-stdlib read-later queue is the complete product for this adapter: "
    "RFC 3986 url canonicalisation with tracking-parameter stripping, sha256 "
    "identity, order-independent sqlite dedupe with an alias trail, tags, an "
    "unread/reading/archived/dropped lifecycle, Pocket/Raindrop HTML+CSV "
    "import, a bridge from the #12 feeds reader, and a gated fetch pass that "
    "hands bodies to the #11 extract corpus; tier 'fallback' is the expected "
    "steady state — Pocket and Raindrop are SaaS, and every self-hosted clone "
    "keeps its own store and fetches outside this policy gate. What it does "
    "NOT do is mirror assets or render an offline copy"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; shiori, buku or "
    "archivebox on PATH are surfaced for manual use only, never executed"
)
NEVER_EXECUTED = (
    "shiori/buku/archivebox are probed for awareness and NEVER executed: each "
    "owns its own database and fetches on its own, which would move the queue "
    "outside the per-url policy gate and make the verdict depend on PATH"
)
USER_AGENT = "scout-later"

app = make_plugin_app(
    "later",
    "Read-later queue (Pocket/Raindrop-class), fully local: canonical-url "
    "dedupe in sqlite, tags, lifecycle, and a gated fetch into the corpus",
    examples=[
        "scout --json later add https://example.com/post --tag ai",
        "scout --json later canon 'https://Example.com/p?utm_source=nl#x'",
        "scout --json later import ril_export.html",
        "scout --json later list --state unread",
        "scout --json later fetch --limit 5 --fail-on error",
        "scout --json later board",
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
    native = openswap.probe_binary("shiori", probe_args=("--version",))
    extras = {
        "buku": openswap.probe_binary("buku", probe_args=("--version",)),
        "archivebox": openswap.probe_binary("archivebox", probe_args=("version",)),
    }
    report = openswap.capability_report(
        "later",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    report["native_used"] = False
    report["native_never_executed"] = NEVER_EXECUTED
    report["scope_limits"] = later.SCOPE_LIMITS
    return report


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_LATER_DB") or later.DB_REL)


def _open_store(db: str | None):
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return later.open_store(path), path


def _open_existing(db: str | None, command: str):
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no queue at {path} — save something first",
            command=command,
            example="scout --json later add https://example.com/post",
        )
    return later.open_store(path), path


def _policy_or_fail(policy_file: str | None, command: str) -> dict:
    try:
        return later.load_policy(policy_file)
    except Exception as e:
        fail_agent(
            f"bad canonicalisation policy: {type(e).__name__}: {e}",
            command=command,
            example="scout --json later policy --policy later-policy.json",
            discover="scout --json later policy",
        )
        raise  # unreachable: fail_agent exits


def _rules_or_fail(rules_file: str | None, command: str) -> dict:
    try:
        return later.load_rules(rules_file)
    except Exception as e:
        fail_agent(
            f"bad rules overlay: {type(e).__name__}: {e}",
            command=command,
            example="scout --json later board --rules later-rules.json",
            discover="scout --json later policy",
        )
        raise  # unreachable: fail_agent exits


def _fail_on_or_die(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=f"scout --json later {command.split()[-1]} --fail-on error",
        )


def _gate_exit(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


def _gate(url: str) -> tuple[bool, str]:
    """Manifest allowlist (loopback) OR the persisted user allowlist. Default-deny.

    Two lists on purpose (the links #4 doctrine): the manifest names what this
    adapter trusts without being asked, the user's policy file names what they
    added by hand, and the manifest is NEVER widened to match the url that was
    saved last. A denial is a recorded row, not an exception.
    """
    allowed, why = check_permission(_manifest(), "network", url)
    if allowed:
        return True, "manifest allowlist (loopback)"
    allowed_user, why_user = check_user_url(url)
    if allowed_user:
        return True, "user allowlist"
    return False, f"{why}; {why_user}"


def _fetch_page(url: str, *, timeout: float, max_bytes: int) -> dict:
    """The ONE real I/O call in this plugin: one GET -> {status, html, url, error}.

    Never raises: DNS vs TLS vs timeout vs 404 must stay distinguishable per row
    so a pass over 40 links reports 40 outcomes instead of dying on the first.
    Bytes are read up to max_bytes and decoded through extract's HTML5 charset
    precedence rather than assuming utf-8.
    """
    req = urllib.request.Request(  # noqa: S310 - http(s) only, policy-gated above
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}, method="GET"
    )
    try:
        with urllib.request.urlopen(  # noqa: S310
            req, timeout=timeout, context=ssl.create_default_context()
        ) as r:
            raw = r.read(max_bytes)
            try:
                charset = r.headers.get_content_charset()
            except Exception:
                charset = None
            return {
                "status": int(r.status),
                "html": extract.decode_html(raw, charset),
                "url": r.geturl() or url,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        return {"status": int(e.code), "html": "", "url": url, "error": f"http {e.code}"}
    except Exception as e:
        return {"status": None, "html": "", "url": url, "error": f"{type(e).__name__}: {e}"}


def _make_ingest(corpus, *, ts: float | None):
    """The #11 hand-off: one page -> {doc_id, words, title} in the corpus ledger.

    Injected into later.run_fetch so the queue never imports an extractor of its
    own, and so tests can hand in a fake and stay offline.
    """

    def ingest(html: str, url: str, item: dict) -> dict:
        try:
            res = extract.extract(html, url=url, source=f"later:{item['id']}")
            doc_id = None if corpus is None else extract.record_document(corpus, res, ts=ts)
            return {"doc_id": doc_id, "words": res.get("word_count"), "title": res.get("title")}
        except Exception as e:  # a bad page is one row, not a dead pass
            return {"error": f"{type(e).__name__}: {e}"}

    return ingest


@app.command("hello", epilog=examples_epilog(["scout --json later hello"]))
def hello():
    """Smoke check — is the later surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "later"},
            command="later hello",
            example="scout --json later add https://example.com/post",
            discover="scout later detect",
        ),
        command="later hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json later detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    data = _capability()
    net = (_manifest().get("capabilities") or {}).get("network") or {}
    data["egress"] = {
        "network_enabled": bool(net.get("enabled")),
        "manifest_domains": list(net.get("domains") or []),
        "user_allowlist_required": "every non-loopback url, checked per item at fetch time",
        "commands_with_zero_egress": ["add", "import", "pull", "canon", "list", "mark", "board"],
    }
    emit(
        ok(
            data,
            command="later detect",
            example="scout --json later fetch --limit 3",
            discover="scout --json later policy",
        ),
        command="later detect",
    )


@app.command(
    "policy",
    epilog=examples_epilog(
        ["scout --json later policy", "scout --json later policy --policy later-policy.json"]
    ),
)
def policy_cmd(
    policy_file: str | None = typer.Option(
        None, "--policy", help="JSON overlay of canonicalisation rules (policy-as-config)"
    ),
    rules_file: str | None = typer.Option(None, "--rules", help="JSON overlay of diagnostic rules"),
):
    """Publish the effective canonicalisation policy and diagnostic rule table."""
    pol = _policy_or_fail(policy_file, "later policy")
    rules = _rules_or_fail(rules_file, "later policy")
    emit(
        ok(
            {
                "policy": pol,
                "policy_overlay": policy_file,
                "defaults": later.DEFAULT_POLICY,
                "tracking_params": sorted(later.TRACKING_PARAMS),
                "tracking_prefixes": list(later.TRACKING_PREFIXES),
                "rules": rules,
                "rules_overlay": rules_file,
                "severities": list(openswap.SEVERITIES),
                "states": list(later.STATES),
                "scope_limits": later.SCOPE_LIMITS,
            },
            command="later policy",
            example="scout --json later canon https://example.com/p?utm_source=x",
            discover="scout --json later board",
        ),
        command="later policy",
    )


@app.command(
    "canon",
    epilog=examples_epilog(
        [
            "scout --json later canon 'https://Example.com/p?utm_source=nl#x'",
            "scout --json later canon https://a.example/x https://A.example/x/",
        ]
    ),
)
def canon(
    urls: list[str] = typer.Argument(..., help="urls to canonicalise (no database, no network)"),
    policy_file: str | None = typer.Option(None, "--policy", help="JSON canonicalisation overlay"),
):
    """Show the canonical form, key and applied rules for urls. Pure function."""
    pol = _policy_or_fail(policy_file, "later canon")
    readings = [later.canonicalise(u, policy=pol) for u in urls]
    groups: dict[str, list[str]] = {}
    for reading in readings:
        if reading["key"] is not None:
            groups.setdefault(reading["key"], []).append(reading["input"])
    emit(
        ok(
            {
                "readings": readings,
                "distinct": len(groups),
                "collapsed": [
                    {"key": k, "url": next(r["url"] for r in readings if r["key"] == k), "inputs": v}
                    for k, v in sorted(groups.items())
                    if len(v) > 1
                ],
                "invalid": [r["input"] for r in readings if r["error"] is not None],
            },
            command="later canon",
            example="scout --json later add https://example.com/post --tag ai",
            discover="scout --json later policy",
        ),
        command="later canon",
    )


def _report_add(result: dict, path: Path, command: str, example: str) -> None:
    emit(
        ok(
            {
                "db": str(path),
                "counts": result["counts"],
                "added": result["added"],
                "duplicate": result["duplicate"],
                "invalid": result["invalid"],
                "note": (
                    "counts.collapsed is offers that folded onto another offer in"
                    " the SAME batch; counts.duplicate is offers whose canonical"
                    " url was already queued"
                ),
            },
            command=command,
            example=example,
            discover="scout --json later list",
        ),
        command=command,
    )


@app.command(
    "add",
    epilog=examples_epilog(
        [
            "scout --json later add https://example.com/post",
            "scout --json later add https://example.com/post --tag ai --tag paper",
            "scout --json later add https://a.example/x https://b.example/y --note 'from standup'",
        ]
    ),
)
def add(
    urls: list[str] = typer.Argument(..., help="urls to queue (canonicalised, then deduped)"),
    tag: list[str] = typer.Option([], "--tag", help="tag (repeatable); tags of a duplicate merge"),
    title: str | None = typer.Option(None, "--title", help="title, when the page has none yet"),
    note: str | None = typer.Option(None, "--note", help="why you saved it"),
    db: str | None = typer.Option(None, "--db", help=f"queue path (default {later.DB_REL})"),
    policy_file: str | None = typer.Option(None, "--policy", help="JSON canonicalisation overlay"),
):
    """Queue urls. No network on this path — canonicalise, dedupe, store."""
    pol = _policy_or_fail(policy_file, "later add")
    conn, path = _open_store(db)
    offers = [
        later.offer(u, title=title, note=note, tags=tag, source="manual") for u in urls
    ]
    _report_add(
        later.add_offers(conn, offers, policy=pol),
        path,
        "later add",
        "scout --json later list --state unread",
    )


@app.command(
    "import",
    epilog=examples_epilog(
        [
            "scout --json later import ril_export.html",
            "scout --json later import raindrop.csv --no-folder-tags",
        ]
    ),
)
def import_cmd(
    source: str = typer.Argument(..., help="Pocket/Raindrop/browser export (.html or .csv)"),
    folder_tags: bool = typer.Option(
        True, "--folder-tags/--no-folder-tags", help="turn export folders/collections into tags"
    ),
    db: str | None = typer.Option(None, "--db", help=f"queue path (default {later.DB_REL})"),
    policy_file: str | None = typer.Option(None, "--policy", help="JSON canonicalisation overlay"),
):
    """Import a bookmark export. Reads one local file; opens no socket."""
    pol = _policy_or_fail(policy_file, "later import")
    path = Path(source)
    if not path.is_file():
        fail_agent(
            f"no such export file: {source}",
            command="later import",
            example="scout --json later import ril_export.html",
        )
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        offers = (
            later.parse_csv(text, folders_as_tags=folder_tags)
            if path.suffix.lower() == ".csv"
            else later.parse_bookmarks(text, folders_as_tags=folder_tags)
        )
    except (OSError, ValueError) as e:
        fail_agent(
            f"could not read {source}: {type(e).__name__}: {e}",
            command="later import",
            example="scout --json later import raindrop.csv",
        )
        raise  # unreachable: fail_agent exits
    conn, db_path = _open_store(db)
    _report_add(
        later.add_offers(conn, offers, policy=pol),
        db_path,
        "later import",
        "scout --json later list --limit 10",
    )


@app.command(
    "pull",
    epilog=examples_epilog(
        ["scout --json later pull", "scout --json later pull --min-score 2 --limit 20 --mark"]
    ),
)
def pull(
    min_score: float = typer.Option(0.0, "--min-score", help="only entries scoring at least this"),
    limit: int = typer.Option(25, "--limit", help="most ranked entries to take"),
    new_only: bool = typer.Option(True, "--new/--all", help="only entries not yet digested"),
    mark_digested: bool = typer.Option(
        False, "--mark/--no-mark", help="stamp the pulled feed entries as digested"
    ),
    feeds_db: str | None = typer.Option(None, "--feeds-db", help=f"reader path ({feeds.DB_REL})"),
    db: str | None = typer.Option(None, "--db", help=f"queue path (default {later.DB_REL})"),
    policy_file: str | None = typer.Option(None, "--policy", help="JSON canonicalisation overlay"),
):
    """Pull ranked #12 feeds entries into the queue. Reads two local dbs, no network."""
    pol = _policy_or_fail(policy_file, "later pull")
    reader_path = Path(feeds_db or os.environ.get("SCOUT_FEEDS_DB") or feeds.DB_REL)
    if not reader_path.exists():
        fail_agent(
            f"no feeds reader store at {reader_path} — run `scout feeds fetch` first",
            command="later pull",
            example="scout --json later pull --feeds-db .scout/feeds.db",
        )
    reader = feeds.open_store(reader_path)
    dg = feeds.digest(reader, min_score=min_score, limit=limit, new_only=new_only)
    conn, db_path = _open_store(db)
    result = later.add_offers(conn, later.offers_from_entries(dg["items"]), policy=pol)
    if mark_digested:
        feeds.mark_digested(reader, [i["id"] for i in dg["items"]])
    result["counts"]["entries_offered"] = dg["count"]
    _report_add(result, db_path, "later pull", "scout --json later fetch --limit 5")


@app.command(
    "list",
    epilog=examples_epilog(
        [
            "scout --json later list",
            "scout --json later list --state unread --tag ai",
            "scout --json later list --unfetched --limit 5",
        ]
    ),
)
def list_cmd(
    state: str | None = typer.Option(None, "--state", help=f"filter: {'|'.join(later.STATES)}"),
    tag: str | None = typer.Option(None, "--tag", help="filter by one tag"),
    unfetched: bool = typer.Option(False, "--unfetched", help="only items never fetched"),
    limit: int = typer.Option(later.DEFAULT_LIST_LIMIT, "--limit", help="cap rows"),
    db: str | None = typer.Option(None, "--db", help=f"queue path (default {later.DB_REL})"),
):
    """List queued items, oldest save first. Reads the queue; no network."""
    conn, path = _open_existing(db, "later list")
    try:
        items = later.list_items(conn, state=state, tag=tag, unfetched=unfetched, limit=limit)
    except ValueError as e:
        fail_agent(
            str(e), command="later list", example="scout --json later list --state unread"
        )
        raise  # unreachable: fail_agent exits
    emit(
        ok(
            {
                "db": str(path),
                "filters": {"state": state, "tag": tag, "unfetched": unfetched, "limit": limit},
                "count": len(items),
                "items": items,
                "fingerprint": later.queue_fingerprint(conn),
            },
            command="later list",
            example="scout --json later mark 1 --state archived",
            discover="scout --json later board",
        ),
        command="later list",
    )


@app.command(
    "mark",
    epilog=examples_epilog(
        [
            "scout --json later mark 3 --state archived",
            "scout --json later mark 'https://example.com/p?utm_source=x' --state read",
        ]
    ),
)
def mark_cmd(
    idents: list[str] = typer.Argument(..., help="item ids, or urls in ANY spelling"),
    state: str = typer.Option(..., "--state", help=f"new state: {'|'.join(later.STATES)}"),
    db: str | None = typer.Option(None, "--db", help=f"queue path (default {later.DB_REL})"),
    policy_file: str | None = typer.Option(None, "--policy", help="JSON canonicalisation overlay"),
):
    """Move items through the lifecycle. A url is matched by its canonical key."""
    pol = _policy_or_fail(policy_file, "later mark")
    conn, path = _open_existing(db, "later mark")
    moved, failed = [], []
    for ident in idents:
        try:
            moved.append(later.mark(conn, ident, state, policy=pol))
        except ValueError as e:
            failed.append({"ident": ident, "error": str(e)})
    if failed and not moved:
        fail_agent(
            "; ".join(f["error"] for f in failed),
            command="later mark",
            example="scout --json later mark 1 --state archived",
            discover="scout --json later list",
        )
    emit(
        ok(
            {"db": str(path), "moved": moved, "failed": failed, "state": state},
            command="later mark",
            example="scout --json later list --state archived",
            discover="scout --json later board",
        ),
        command="later mark",
    )
    if failed:
        raise typer.Exit(code=1)


@app.command(
    "fetch",
    epilog=examples_epilog(
        [
            "scout --json later fetch --limit 5",
            "scout --json later fetch --retry --fail-on error",
            "scout --json later fetch --limit 1 --no-ingest",
        ]
    ),
)
def fetch_cmd(
    limit: int = typer.Option(later.DEFAULT_FETCH_LIMIT, "--limit", help="most items to try"),
    retry: bool = typer.Option(False, "--retry", help="also retry items whose last fetch failed"),
    ingest: bool = typer.Option(
        True, "--ingest/--no-ingest", help="hand each body to the #11 extract corpus"
    ),
    timeout: float = typer.Option(15.0, "--timeout", help="per-request timeout in seconds"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 on findings at/above this severity (the cron hook)"
    ),
    db: str | None = typer.Option(None, "--db", help=f"queue path (default {later.DB_REL})"),
    corpus_db: str | None = typer.Option(None, "--corpus-db", help=f"#11 ledger ({extract.DB_REL})"),
    rules_file: str | None = typer.Option(None, "--rules", help="JSON overlay of diagnostic rules"),
):
    """Fetch the head of the queue into the corpus. The ONE networked command."""
    _fail_on_or_die(fail_on, "later fetch")
    rules = _rules_or_fail(rules_file, "later fetch")
    conn, path = _open_existing(db, "later fetch")
    corpus = None
    corpus_path: Path | None = None
    if ingest:
        corpus_path = Path(corpus_db or os.environ.get("SCOUT_EXTRACT_DB") or extract.DB_REL)
        enforce_or_raise(_manifest(), "fs_write_arg", str(corpus_path))
        corpus = extract.open_store(corpus_path)
    run = later.run_fetch(
        conn,
        lambda url: _fetch_page(url, timeout=timeout, max_bytes=extract.MAX_FETCH_BYTES),
        limit=limit,
        gate=_gate,
        ingest=_make_ingest(corpus, ts=None) if ingest else None,
        retry=retry,
    )
    diags = later.fetch_diagnostics(run["results"], rules=rules)
    emit(
        ok(
            {
                "db": str(path),
                "tier": _capability()["tier"],
                "native_used": False,
                "ingested_into": None if corpus is None else str(corpus_path),
                "attempted": run["attempted"],
                "counts": run["counts"],
                "words": run["words"],
                "results": run["results"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="later fetch",
            example="scout --json later board --fail-on warning",
            discover="scout --json later list --state unread",
        ),
        command="later fetch",
    )
    _gate_exit(diags, fail_on)


@app.command(
    "board",
    epilog=examples_epilog(
        ["scout --json later board", "scout --json later board --stale-days 7 --fail-on warning"]
    ),
)
def board_cmd(
    stale_days: float = typer.Option(
        later.STALE_DAYS, "--stale-days", help="unread for this long is a finding"
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 on findings at/above this severity"
    ),
    db: str | None = typer.Option(None, "--db", help=f"queue path (default {later.DB_REL})"),
    rules_file: str | None = typer.Option(None, "--rules", help="JSON overlay of diagnostic rules"),
):
    """Queue rollup: states, staleness, duplicate bodies, dedupe savings."""
    _fail_on_or_die(fail_on, "later board")
    rules = _rules_or_fail(rules_file, "later board")
    conn, path = _open_existing(db, "later board")
    snapshot = later.board(conn, stale_days=stale_days)
    diags = later.queue_diagnostics(conn, stale_days=stale_days, rules=rules)
    emit(
        ok(
            {
                "db": str(path),
                "board": snapshot,
                "fingerprint": later.queue_fingerprint(conn),
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="later board",
            example="scout --json later fetch --limit 5",
            discover="scout --json later list --state unread",
        ),
        command="later board",
    )
    _gate_exit(diags, fail_on)


def register(root):
    root.add_typer(app, name="later")
