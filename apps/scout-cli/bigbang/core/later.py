# Solo personal project, no connection to employer, built with public/free-tier only
"""Later — read-later queue with canonical-URL dedupe (openswap #34: Pocket / Raindrop).

The paid thing being deleted is a hosted URL inbox: you save a link from
anywhere, their servers dedupe it, fetch the page and keep the reader copy. This
adapter keeps the inbox on THIS box — a sqlite queue whose identity is a
CANONICAL url, an importer for the Pocket/Raindrop export formats, and a fetch
pass that hands each page to the #11 `extract` ingestion pipeline. Everything
deterministic lives here; the plugin CLI owns the ONE real I/O (the urllib GET)
and injects it, so the whole queue is unit-testable with strings and no socket.

WHY A NEW ADAPTER AND NOT AN EXTENSION OF `feeds` (#12), whose docstring
nominates "#34 Pocket/Raindrop" as an extension point of its store: the two
differ on IDENTITY, which is the whole product here.
- feeds dedupes per SUBSCRIPTION — UNIQUE(feed, key) over guid/link/title+date —
  and says so: a cross-listed arXiv paper is deliberately two rows. A read-later
  inbox needs the opposite: ONE row for a URL no matter how many times, from how
  many sources, in how many spellings it was saved. That identity cannot be
  added to feeds' entries table without breaking the guarantee feeds documents.
- feeds fetches the FEED and never the item; this fetches the ITEM and has a
  per-item fetch state machine, an attempt counter and a content hash.
- feeds entries are publisher-supplied and immutable; queue items have a
  user-owned lifecycle (unread -> reading -> archived / dropped) and user tags.
The bridge is real rather than rhetorical: `offers_from_entries` consumes exactly
the rows `feeds.digest()` emits, so `feeds -> later -> extract` is one chain and
the reader is not reimplemented here. Nothing in this module parses a feed.

Reuse instead of retyping (extension-list drift is a known bug class in this
repo): absolutization / defragging / http(s)-only / bare-origin path comes from
`seo.resolve_link` (#3), the body hash is `extract.content_hash` (#11) so a
queue row and its corpus document share ONE identity, and export timestamps go
through `feeds.parse_entry_time` (#12) so date parsing stays locale-independent.

DEDUPE IS PROVABLY ORDER-INDEPENDENT, and that is a design constraint, not a
hope. `merge_offers` folds a bag of offers into one row per canonical key using
only COMMUTATIVE, ASSOCIATIVE reductions — min() for the added timestamp, set
union for tags and sources, and max-by-(length, text) for title/note — so the
result is a function of the SET of offers and never of their arrival order. The
same reductions are used again when a batch meets rows already in the store,
which makes add(a) then add(b) equal add(a+b). `queue_fingerprint` hashes exactly
the order-independent projection (never the AUTOINCREMENT id, which *is* insertion
order) so the property is falsifiable in one assertion.

Honesty rules that shape the code:
- A canonicalisation has EITHER a `url`+`key` OR an `error`, never both, never
  neither. A scheme-less "example.com/x" is an ERROR naming the fact, because
  inventing https:// would be a guess that silently changes which resource got
  queued.
- Every rule that CHANGED the url is listed in `applied`, and every dropped
  query parameter is named in `dropped_params`. A canonicaliser that will not
  show its work cannot be audited when two links wrongly collapse into one.
- A fetch result's `state` is the reading: `error` is non-None only for
  error/denied, `content_hash` is non-None only when a body actually arrived,
  and `words` stays None when no ingest callable ran rather than defaulting to
  0 — a zero word count is a measurement, and none was taken.
- An empty queue reports `oldest_unread: None` with a note saying why, never an
  age of 0 days.

SCOPE_LIMITS names what this deliberately does not do (no rendered archive, no
highlights, no full-text search of its own — #20 `search` and #11 `extract` own
those), and ships in the payload of `board` and `detect`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import string
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from bigbang.core import extract, feeds, openswap, seo

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

DB_REL = Path(".scout") / "later.db"
SCHEMA_VERSION = "1"

# item lifecycle (user-owned; a fetch never changes it)
STATE_UNREAD = "unread"
STATE_READING = "reading"
STATE_ARCHIVED = "archived"
STATE_DROPPED = "dropped"
STATES = (STATE_UNREAD, STATE_READING, STATE_ARCHIVED, STATE_DROPPED)
# states a fetch pass will consider (an archived item is done, a dropped one is
# a decision — refetching either would undo the user's own triage)
FETCHABLE_STATES = (STATE_UNREAD, STATE_READING)

# per-item fetch outcomes
FETCH_OK = "ok"
FETCH_EMPTY = "empty"
FETCH_ERROR = "error"
FETCH_DENIED = "denied"
FETCH_STATES = (FETCH_OK, FETCH_EMPTY, FETCH_ERROR, FETCH_DENIED)

DEFAULT_SOURCE = "manual"
DEFAULT_FETCH_LIMIT = 10
DEFAULT_LIST_LIMIT = 50
STALE_DAYS = 30.0
DAY = 86400.0

SCOPE_LIMITS = (
    "a URL inbox with canonical-url dedupe, tags, a lifecycle and a gated fetch"
    " that feeds the #11 extract corpus — NOT an offline archive (no assets are"
    " mirrored and no rendered copy is kept beyond the extracted text), NOT a"
    " highlighter, and NOT a search engine: #20 search and #11 extract own"
    " retrieval, so a queue row stores the doc_id rather than a second copy"
)

# ---- canonicalisation -------------------------------------------------------

# Exact parameter names known to carry campaign/click identity rather than
# content. Dropping them is what makes the same article saved from a newsletter
# and from a tweet ONE queue row.
TRACKING_PARAMS = frozenset(
    {
        "fbclid", "gclid", "gclsrc", "dclid", "wbraid", "gbraid", "msclkid",
        "twclid", "igshid", "ttclid", "yclid", "s_cid", "mc_cid", "mc_eid",
        "oly_anon_id", "oly_enc_id", "vero_conv", "vero_id", "ck_subscriber_id",
        "_hsenc", "_hsmi", "hsctatracking", "mkt_tok", "trk", "trkcampaign",
        "ref_src", "ref_url", "spm", "scm", "share_id", "sharetype",
        "campaign_id", "cmpid", "ncid", "sr_share", "wt_mc", "at_medium",
        "at_campaign", "guccounter", "guce_referrer", "guce_referrer_sig",
    }
)
# Prefix families: utm_* (Google/Urchin), pk_*/mtm_* (Matomo), _ga* / ga_*,
# hsa_* (HubSpot ads), at_custom* (Guardian), __cf_* (Cloudflare beacons).
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "ga_", "_ga", "hsa_", "at_custom", "__cf_")

DEFAULT_POLICY: dict[str, Any] = {
    # always-safe RFC 3986 normalizations
    "lowercase_host": True,
    "strip_default_port": True,
    "resolve_dot_segments": True,
    "normalize_percent_encoding": True,
    "drop_userinfo": True,
    # opinionated, but this is a read-later inbox and they are what make it work
    "drop_fragment": True,
    "drop_tracking_params": True,
    "sort_query": True,
    # OFF by default: both can change which resource is addressed on a badly
    # configured host, so they are a choice the user makes, not one made for them
    "strip_www": False,
    "strip_trailing_slash": False,
    # extra site-specific junk params, e.g. ["ref", "source"]
    "extra_tracking_params": [],
}
_POLICY_FLAGS = tuple(k for k, v in DEFAULT_POLICY.items() if isinstance(v, bool))

_PCT_RE = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
_DEFAULT_PORTS = {"http": "80", "https": "443"}
_WS_RE = re.compile(r"\s+")


def _clean(text: Any) -> str:
    """Collapse whitespace runs and strip — the one text normalizer."""
    return _WS_RE.sub(" ", str(text)).strip() if text is not None else ""


def validate_policy(raw: Any) -> dict[str, Any]:
    """DEFAULT_POLICY overlaid with `raw`, or ValueError naming the problem.

    An unknown key is a hard error: silently ignoring a typo would ship a
    canonicaliser that quietly is not the one the operator configured, and every
    URL in the store would then carry the wrong identity.
    """
    merged: dict[str, Any] = dict(DEFAULT_POLICY)
    merged["extra_tracking_params"] = list(DEFAULT_POLICY["extra_tracking_params"])
    if raw is None:
        return merged
    if not isinstance(raw, dict):
        raise ValueError("policy must be a JSON object of {rule: bool}")
    for key, value in raw.items():
        if key not in merged:
            raise ValueError(f"unknown policy key {key!r} (known: {sorted(merged)})")
        if key == "extra_tracking_params":
            if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                raise ValueError("extra_tracking_params must be a list of parameter names")
            merged[key] = sorted({v.strip().lower() for v in value if v.strip()})
            continue
        if not isinstance(value, bool):
            raise ValueError(f"policy {key!r}: must be true or false, got {value!r}")
        merged[key] = value
    return merged


def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    """DEFAULT_POLICY with an optional JSON overlay (policy-as-config)."""
    if path is None:
        return validate_policy(None)
    return validate_policy(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def is_tracking_param(name: str, extra: Iterable[str] = ()) -> bool:
    """Is this query parameter campaign/click identity rather than content?"""
    n = (name or "").strip().lower()
    if not n:
        return False
    if n in TRACKING_PARAMS or n in {e.strip().lower() for e in extra}:
        return True
    return n.startswith(TRACKING_PREFIXES)


def normalize_percent(text: str) -> str:
    """Decode %XX of unreserved characters, uppercase the rest (RFC 3986 6.2.2).

    Only unreserved bytes are decoded, so a %26 stays escaped and can never
    smuggle a new query parameter into the canonical form.
    """

    def repl(m: re.Match[str]) -> str:
        ch = chr(int(m.group(1), 16))
        return ch if ch in _UNRESERVED else "%" + m.group(1).upper()

    return _PCT_RE.sub(repl, text)


def resolve_dot_segments(path: str) -> str:
    """RFC 3986 5.2.4 — remove . and .. without ever escaping above the root."""
    segments = path.split("/")
    out: list[str] = []
    last = len(segments) - 1
    for i, seg in enumerate(segments):
        if seg == ".":
            if i == last:
                out.append("")
            continue
        if seg == "..":
            if len(out) > 1:
                out.pop()
            if i == last:
                out.append("")
            continue
        out.append(seg)
    return "/".join(out)


def split_authority(netloc: str) -> tuple[str, str, str]:
    """(userinfo, host, port) — IPv6 literals keep their brackets.

    Hand-rolled instead of SplitResult.hostname/.port because those raise on a
    malformed authority; here a malformed authority must become a recorded
    ERROR on one row, not an exception that aborts a whole import.
    """
    userinfo, sep, hostport = netloc.rpartition("@")
    if not sep:
        userinfo, hostport = "", netloc
    if hostport.startswith("["):
        end = hostport.find("]")
        if end == -1:
            return userinfo, hostport, ""
        rest = hostport[end + 1 :]
        return userinfo, hostport[: end + 1], rest[1:] if rest.startswith(":") else ""
    host, sep2, port = hostport.rpartition(":")
    if not sep2:
        return userinfo, hostport, ""
    if not port.isdigit():  # ":" that is not a port — malformed, keep it whole
        return userinfo, hostport, ""
    return userinfo, host, port


def url_key(canonical: str) -> str:
    """sha256 of the canonical url — the fixed-width dedupe identity.

    A hash rather than the url itself so the UNIQUE index stays index-friendly
    at any url length (the glitch #8 fingerprint doctrine), and so the key never
    changes shape when a url does.
    """
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _authority(scheme: str, netloc: str, pol: dict[str, Any], applied: list[str]) -> tuple[str, str | None]:
    """(canonical authority, error) for one URL under `pol`."""
    userinfo, host, port = split_authority(netloc)
    if userinfo and pol["drop_userinfo"]:
        # credentials in a saved link are a leak waiting to be shared; dropping
        # them also means two users' copies of the same page dedupe to one row
        applied.append("drop-userinfo")
        userinfo = ""
    if not host:
        return "", "no host in the URL"
    if host.startswith("[") and not host.endswith("]"):
        return "", f"malformed IPv6 authority {host!r}"
    if pol["lowercase_host"] and host != host.lower():
        applied.append("lowercase-host")
        host = host.lower()
    if host.endswith(".") and len(host) > 1:
        # "example.com." and "example.com" are the same name in DNS
        applied.append("strip-root-dot")
        host = host.rstrip(".")
    if pol["strip_www"] and host.startswith("www."):
        applied.append("strip-www")
        host = host[4:]
    if port and pol["strip_default_port"] and port == _DEFAULT_PORTS.get(scheme):
        applied.append("strip-default-port")
        port = ""
    if not host or host == "[]":
        return "", "no host in the URL"
    authority = f"{userinfo}@{host}" if userinfo else host
    return (f"{authority}:{port}" if port else authority), None


def _query(query: str, pol: dict[str, Any], applied: list[str], dropped: list[str]) -> str:
    """Canonical query string: tracking params dropped, survivors sorted."""
    # empty tokens ("a&&b", a trailing "&") carry nothing and are dropped
    tokens = [t for t in query.split("&") if t]
    kept: list[tuple[str, str]] = []
    for token in tokens:
        name = token.split("=", 1)[0]
        if pol["drop_tracking_params"] and is_tracking_param(name, pol["extra_tracking_params"]):
            dropped.append(name)
            continue
        text = normalize_percent(token) if pol["normalize_percent_encoding"] else token
        kept.append((name.lower(), text))
    if dropped:
        applied.append("drop-tracking-params")
    if pol["sort_query"]:
        ordered = [t for _, t in sorted(kept)]
        if ordered != [t for _, t in kept]:
            applied.append("sort-query")
    else:
        ordered = [t for _, t in kept]
    return "&".join(ordered)


def canonicalise(raw: Any, *, base: str = "", policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """One URL -> its canonical form, or an error saying why it has none.

    EITHER `url` + `key` OR `error` — never both, never neither. `applied` names
    every rule that changed the input and `dropped_params` every parameter
    removed, so a collapse of two links into one row is auditable afterwards.
    Idempotent: canonicalising a canonical url returns it unchanged.
    """
    pol = validate_policy(policy) if policy is not None else validate_policy(None)
    text = str(raw).strip() if raw is not None else ""
    out: dict[str, Any] = {
        "input": raw if isinstance(raw, str) else text,
        "url": None,
        "key": None,
        "error": None,
        "applied": [],
        "dropped_params": [],
        "fragment": None,
    }
    if not text:
        out["error"] = "empty url"
        return out
    if _WS_RE.search(text):
        out["error"] = "url contains unencoded whitespace (percent-encode it as %20)"
        return out
    try:
        parts = urlsplit(text)
        absolute = seo.resolve_link(text, base)
    except ValueError as e:
        out["error"] = f"unparseable url: {e}"
        return out
    if absolute is None:
        out["error"] = (
            "not an absolute http(s) url — mailto:/javascript:/relative and"
            " fragment-only links are not read-later items, and a missing scheme"
            " is not guessed"
        )
        return out
    fragment = parts.fragment or None
    applied: list[str] = list(out["applied"])
    dropped: list[str] = out["dropped_params"]
    s = urlsplit(absolute)
    scheme = s.scheme.lower()
    authority, error = _authority(scheme, s.netloc, pol, applied)
    if error is not None:
        out["error"] = error
        return out
    path = s.path or "/"
    if pol["resolve_dot_segments"]:
        resolved = resolve_dot_segments(path)
        if resolved != path:
            applied.append("resolve-dot-segments")
            path = resolved
    if pol["normalize_percent_encoding"]:
        normalized = normalize_percent(path)
        if normalized != path:
            applied.append("normalize-percent-encoding")
            path = normalized
    if pol["strip_trailing_slash"] and path.endswith("/") and path != "/":
        applied.append("strip-trailing-slash")
        path = path.rstrip("/")
    query = _query(s.query, pol, applied, dropped)
    keep_fragment = "" if pol["drop_fragment"] else (fragment or "")
    if fragment and pol["drop_fragment"]:
        applied.append("drop-fragment")
    url = urlunsplit((scheme, authority, path or "/", query, keep_fragment))
    out["url"] = url
    out["key"] = url_key(url)
    out["fragment"] = fragment
    out["applied"] = applied
    out["dropped_params"] = sorted(set(dropped))
    return out


# ---- offers and their order-independent merge --------------------------------


def normalize_tags(value: Any) -> list[str]:
    """Any tag spelling -> a sorted, lowercased, deduplicated list.

    Sorted because the stored list is part of the dedupe fingerprint: two
    identical tag sets must serialize identically regardless of typing order.
    """
    if value is None:
        return []
    raw = value.split(",") if isinstance(value, str) else list(value)
    tags = {_clean(t).lower() for t in raw}
    return sorted(t for t in tags if t)


def offer(
    url: Any,
    *,
    title: Any = None,
    note: Any = None,
    tags: Any = (),
    source: str = DEFAULT_SOURCE,
    added_ts: float | None = None,
) -> dict[str, Any]:
    """One save request, before canonicalisation. `added_ts=None` = unknown."""
    return {
        "url": url,
        "title": _clean(title) or None,
        "note": _clean(note) or None,
        "tags": normalize_tags(tags),
        "source": _clean(source) or DEFAULT_SOURCE,
        "added_ts": None if added_ts is None else float(added_ts),
    }


def _as_offer(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return offer(value)
    if isinstance(value, dict):
        return offer(
            value.get("url"),
            title=value.get("title"),
            note=value.get("note"),
            tags=value.get("tags") or (),
            source=value.get("source") or DEFAULT_SOURCE,
            added_ts=value.get("added_ts"),
        )
    raise TypeError(f"an offer must be a url string or a dict, got {type(value).__name__}")


def merge_text(a: Any, b: Any) -> str | None:
    """The longer of two texts, equal lengths broken by taking the lexicographic
    LAST; None when both are empty.

    Commutative and associative — that is the requirement, not a nicety: the
    merged row must not depend on which order the same set of offers arrived in.
    Longest wins because "Title - Site Name" carries more than "Site Name", and
    concatenating would make the result order-dependent. The tie-break is
    arbitrary on purpose: what matters is that it is a TOTAL order, so max() is
    well defined however the offers are shuffled.
    """
    candidates = [t for t in (_clean(a), _clean(b)) if t]
    if not candidates:
        return None
    return max(candidates, key=lambda t: (len(t), t))


def merge_sources(a: Any, b: Any) -> str:
    """Union of comma-separated provenance labels, sorted (a set, so commutative)."""
    parts = {
        _clean(p)
        for value in (a, b)
        for p in (str(value).split(",") if value else [])
    }
    return ",".join(sorted(p for p in parts if p)) or DEFAULT_SOURCE


def merge_ts(a: float | None, b: float | None) -> float | None:
    """The EARLIEST known save time (min is commutative and associative)."""
    values = [float(v) for v in (a, b) if v is not None]
    return min(values) if values else None


def merge_offers(
    offers: Iterable[Any], *, policy: dict[str, Any] | None = None, ts: float | None = None
) -> dict[str, Any]:
    """Fold a bag of offers into one row per canonical key. ORDER-INDEPENDENT.

    A pure function of (the SET of offers, ts, policy): every field is combined
    with a commutative+associative reduction, so permuting the input cannot
    change `items`. `ts` fills in an unknown save time and the row records
    WHICH it was in `added_ts_source` — a substituted clock reading must never
    be indistinguishable from one the export actually carried.
    """
    pol = validate_policy(policy) if policy is not None else validate_policy(None)
    now = time.time() if ts is None else float(ts)
    items: dict[str, dict[str, Any]] = {}
    invalid: list[dict[str, Any]] = []
    offered = 0
    for raw in offers:
        offered += 1
        o = _as_offer(raw)
        can = canonicalise(o["url"], policy=pol)
        if can["error"] is not None:
            invalid.append(
                {
                    "input": can["input"],
                    "error": can["error"],
                    "title": o["title"],
                    "source": o["source"],
                }
            )
            continue
        alias = _clean(o["url"])
        stamped = now if o["added_ts"] is None else o["added_ts"]
        stamp_source = "run-clock" if o["added_ts"] is None else "offer"
        row = items.get(can["key"])
        if row is None:
            items[can["key"]] = {
                "key": can["key"],
                "url": can["url"],
                "title": o["title"],
                "note": o["note"],
                "tags": list(o["tags"]),
                "source": o["source"],
                "added_ts": stamped,
                "added_ts_source": stamp_source,
                "aliases": {alias: {"times": 1, "first_seen_ts": stamped}},
            }
            continue
        row["title"] = merge_text(row["title"], o["title"])
        row["note"] = merge_text(row["note"], o["note"])
        row["tags"] = sorted(set(row["tags"]) | set(o["tags"]))
        row["source"] = merge_sources(row["source"], o["source"])
        row["added_ts"] = merge_ts(row["added_ts"], stamped)
        if stamp_source == "offer":
            row["added_ts_source"] = "offer"
        seen = row["aliases"].get(alias)
        if seen is None:
            row["aliases"][alias] = {"times": 1, "first_seen_ts": stamped}
        else:
            seen["times"] += 1
            seen["first_seen_ts"] = merge_ts(seen["first_seen_ts"], stamped)
    return {
        "offered": offered,
        "items": items,
        "keys": sorted(items),
        "invalid": invalid,
        "collapsed": offered - len(items) - len(invalid),
    }


# ---- store ------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    title TEXT,
    note TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL DEFAULT 'unread',
    source TEXT NOT NULL DEFAULT 'manual',
    added_ts REAL NOT NULL,
    added_ts_source TEXT NOT NULL DEFAULT 'run-clock',
    state_ts REAL,
    fetch_state TEXT,
    fetch_ts REAL,
    fetch_status INTEGER,
    fetch_error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    doc_id INTEGER,
    words INTEGER
);
CREATE INDEX IF NOT EXISTS idx_items_queue ON items(state, added_ts, key);
CREATE INDEX IF NOT EXISTS idx_items_content ON items(content_hash);
CREATE TABLE IF NOT EXISTS aliases(
    key TEXT NOT NULL,
    raw TEXT NOT NULL,
    first_seen_ts REAL NOT NULL,
    times INTEGER NOT NULL DEFAULT 1,
    UNIQUE(key, raw)
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_ITEM_COLUMNS = (
    "id", "key", "url", "title", "note", "state", "source", "added_ts",
    "added_ts_source", "state_ts", "fetch_state", "fetch_ts", "fetch_status",
    "fetch_error", "attempts", "content_hash", "doc_id", "words",
)


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the queue — its OWN sqlite file.

    Never the #2 uptime ledger and never the #11 corpus: a fetch pass writes
    text-heavy rows in bursts and must not contend for a write lock with
    monitoring probes (the glitch #8 doctrine). The corpus link is a doc_id,
    which is why the two databases stay separate files.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = {k: row[k] for k in _ITEM_COLUMNS}
    try:
        out["tags"] = json.loads(row["tags"]) or []
    except (TypeError, ValueError):
        out["tags"] = []
    return out


def get_by_key(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM items WHERE key = ?", (key,)).fetchone())


def get_by_id(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM items WHERE id = ?", (int(item_id),)).fetchone())


def resolve_ident(
    conn: sqlite3.Connection, ident: Any, *, policy: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, str]:
    """(item, how) for an id or a url in ANY spelling. how names the lookup used.

    A url is canonicalised first, so `later mark https://x/?utm_source=n read`
    finds the row saved as https://x/ — the same identity function the queue was
    built with, not a second one that could disagree.
    """
    text = _clean(ident)
    if isinstance(ident, int) or text.isdigit():
        return get_by_id(conn, int(text or ident)), "id"
    can = canonicalise(text, policy=policy)
    if can["error"] is not None:
        return None, f"not an id and not a url: {can['error']}"
    hit = get_by_key(conn, can["key"])
    return hit, "canonical-url"


def add_offers(
    conn: sqlite3.Connection,
    offers: Iterable[Any],
    *,
    ts: float | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge offers into the queue. The resulting store is order-independent.

    The same reductions used inside a batch are used again against rows already
    present, so add(a) then add(b) leaves exactly what add(a + b) would. `state`
    is deliberately NOT touched: re-saving a dropped url must not resurrect it
    behind the user's back — `mark` is the only way a lifecycle moves.
    """
    now = time.time() if ts is None else float(ts)
    merged = merge_offers(offers, policy=policy, ts=now)
    added: list[dict[str, Any]] = []
    duplicate: list[dict[str, Any]] = []
    for key in merged["keys"]:  # sorted: the REPORT is deterministic too
        row = merged["items"][key]
        existing = get_by_key(conn, key)
        if existing is None:
            cur = conn.execute(
                "INSERT INTO items(key, url, title, note, tags, state, source,"
                " added_ts, added_ts_source) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    key, row["url"], row["title"], row["note"],
                    json.dumps(row["tags"]), STATE_UNREAD, row["source"],
                    row["added_ts"], row["added_ts_source"],
                ),
            )
            added.append(
                {
                    "id": int(cur.lastrowid),
                    "key": key,
                    "url": row["url"],
                    "title": row["title"],
                    "tags": row["tags"],
                    "state": STATE_UNREAD,
                }
            )
        else:
            tags = sorted(set(existing["tags"]) | set(row["tags"]))
            conn.execute(
                "UPDATE items SET title = ?, note = ?, tags = ?, source = ?,"
                " added_ts = ?, added_ts_source = ? WHERE key = ?",
                (
                    merge_text(existing["title"], row["title"]),
                    merge_text(existing["note"], row["note"]),
                    json.dumps(tags),
                    merge_sources(existing["source"], row["source"]),
                    merge_ts(existing["added_ts"], row["added_ts"]),
                    "offer" if "offer" in (existing["added_ts_source"], row["added_ts_source"]) else "run-clock",
                    key,
                ),
            )
            duplicate.append(
                {
                    "id": existing["id"],
                    "key": key,
                    "url": row["url"],
                    "state": existing["state"],
                    "tags": tags,
                    "reason": "canonical url already queued",
                }
            )
        for alias, meta in sorted(row["aliases"].items()):
            conn.execute(
                "INSERT INTO aliases(key, raw, first_seen_ts, times) VALUES(?,?,?,?)"
                " ON CONFLICT(key, raw) DO UPDATE SET times = times + excluded.times,"
                " first_seen_ts = MIN(aliases.first_seen_ts, excluded.first_seen_ts)",
                (key, alias, meta["first_seen_ts"], meta["times"]),
            )
    conn.commit()
    return {
        "offered": merged["offered"],
        "added": added,
        "duplicate": duplicate,
        "invalid": merged["invalid"],
        "collapsed": merged["collapsed"],
        "counts": {
            "offered": merged["offered"],
            "added": len(added),
            "duplicate": len(duplicate),
            "invalid": len(merged["invalid"]),
            "collapsed": merged["collapsed"],
        },
    }


def queue_fingerprint(conn: sqlite3.Connection) -> dict[str, Any]:
    """sha256 over the order-independent projection of the queue.

    Deliberately EXCLUDES the AUTOINCREMENT id (which *is* insertion order) and
    every fetch column (a wall-clock outcome). What remains is what dedupe
    promises to make a function of the offer SET, so "insertion order does not
    matter" becomes one comparable number instead of a claim.
    """
    items = conn.execute(
        "SELECT key, url, title, note, tags, state, source, added_ts,"
        " added_ts_source FROM items ORDER BY key"
    ).fetchall()
    aliases = conn.execute(
        "SELECT key, raw, times, first_seen_ts FROM aliases ORDER BY key, raw"
    ).fetchall()
    payload = {
        "items": [[r[k] for k in r.keys()] for r in items],
        "aliases": [[r[k] for k in r.keys()] for r in aliases],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "items": len(items),
        "aliases": len(aliases),
        "digest": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
    }


def mark(
    conn: sqlite3.Connection,
    ident: Any,
    state: str,
    *,
    ts: float | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Move one item's lifecycle state. Raises ValueError when it cannot."""
    if state not in STATES:
        raise ValueError(f"state must be one of {'|'.join(STATES)}, got {state!r}")
    item, how = resolve_ident(conn, ident, policy=policy)
    if item is None:
        raise ValueError(f"no queued item for {ident!r} ({how})")
    now = time.time() if ts is None else float(ts)
    conn.execute(
        "UPDATE items SET state = ?, state_ts = ? WHERE id = ?", (state, now, item["id"])
    )
    conn.commit()
    return {
        "id": item["id"],
        "url": item["url"],
        "matched_by": how,
        "previous_state": item["state"],
        "state": state,
        "changed": item["state"] != state,
    }


def list_items(
    conn: sqlite3.Connection,
    *,
    state: str | None = None,
    tag: str | None = None,
    unfetched: bool = False,
    limit: int = DEFAULT_LIST_LIMIT,
) -> list[dict[str, Any]]:
    """The queue board: oldest-first, tie-broken on key so ties never wobble."""
    if state is not None and state not in STATES:
        raise ValueError(f"state must be one of {'|'.join(STATES)}, got {state!r}")
    where = ["1 = 1"]
    params: list[Any] = []
    if state is not None:
        where.append("state = ?")
        params.append(state)
    if unfetched:
        where.append("fetch_state IS NULL")
    rows = conn.execute(
        # S608: `where` holds fixed literals only — every value travels as a ?
        "SELECT i.*, (SELECT COUNT(*) FROM aliases a WHERE a.key = i.key) AS aliases"  # noqa: S608
        " FROM items i WHERE " + " AND ".join(where) + " ORDER BY i.added_ts, i.key",
        tuple(params),
    ).fetchall()
    out = []
    wanted = _clean(tag).lower() if tag else None
    for r in rows:
        item = _row(r)
        if item is None:  # unreachable: rows come from a SELECT
            continue
        if wanted and wanted not in item["tags"]:
            continue
        item["aliases"] = int(r["aliases"])
        out.append(item)
        if limit and limit > 0 and len(out) >= limit:
            break
    return out


def pending(
    conn: sqlite3.Connection, *, limit: int = DEFAULT_FETCH_LIMIT, retry: bool = False
) -> list[dict[str, Any]]:
    """Items a fetch pass should try, oldest-save first (deterministic order)."""
    clause = "(fetch_state IS NULL OR fetch_state <> 'ok')" if retry else "fetch_state IS NULL"
    placeholders = ",".join("?" for _ in FETCHABLE_STATES)
    rows = conn.execute(
        # S608: both fragments are fixed literals built here, values are bound
        f"SELECT * FROM items WHERE state IN ({placeholders}) AND {clause}"  # noqa: S608
        " ORDER BY added_ts, key LIMIT ?",
        (*FETCHABLE_STATES, int(limit) if limit and limit > 0 else -1),
    ).fetchall()
    return [item for item in (_row(r) for r in rows) if item is not None]


def content_duplicates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Distinct urls whose FETCHED BODIES were byte-identical, grouped.

    Computed at read time by grouping rather than stamped on the second row at
    fetch time, so the answer does not depend on which url was fetched first.
    """
    rows = conn.execute(
        "SELECT id, url, content_hash FROM items WHERE content_hash IS NOT NULL"
        " ORDER BY content_hash, id"
    ).fetchall()
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["content_hash"], []).append({"id": int(r["id"]), "url": r["url"]})
    return [
        {"content_hash": h, "items": members}
        for h, members in sorted(groups.items())
        if len(members) > 1
    ]


def _content_duplicate_of(conn: sqlite3.Connection, hash_hex: str, item_id: int) -> int | None:
    row = conn.execute(
        "SELECT MIN(id) AS first_id FROM items WHERE content_hash = ? AND id <> ?",
        (hash_hex, int(item_id)),
    ).fetchone()
    return None if row is None or row["first_id"] is None else int(row["first_id"])


# ---- the fetch pass (the ONE real I/O is injected) --------------------------


def _record_fetch(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    ts: float,
    state: str,
    status: int | None = None,
    error: str | None = None,
    content_hash: str | None = None,
    doc_id: int | None = None,
    words: int | None = None,
    title: str | None = None,
) -> None:
    """Persist one attempt. attempts always grows — a denial IS an attempt."""
    conn.execute(
        "UPDATE items SET fetch_state = ?, fetch_ts = ?, fetch_status = ?,"
        " fetch_error = ?, attempts = attempts + 1,"
        " content_hash = COALESCE(?, content_hash), doc_id = COALESCE(?, doc_id),"
        " words = COALESCE(?, words),"
        " title = CASE WHEN title IS NULL OR title = '' THEN COALESCE(?, title) ELSE title END"
        " WHERE id = ?",
        (state, ts, status, error, content_hash, doc_id, words, title, int(item_id)),
    )
    conn.commit()


def _fetch_one(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    response: dict[str, Any],
    *,
    ingest: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None,
) -> dict[str, Any]:
    """One response -> the result row. Pure apart from the duplicate lookup."""
    res: dict[str, Any] = {
        "id": item["id"], "url": item["url"], "state": FETCH_ERROR,
        "status": response.get("status"), "content_hash": None, "doc_id": None,
        "words": None, "duplicate_of": None, "error": None, "note": None, "title": None,
    }
    status = response.get("status")
    if response.get("error"):
        res["error"] = str(response["error"])
        return res
    if status is not None and not 200 <= int(status) < 300:
        res["error"] = f"http {int(status)}"
        return res
    html = response.get("html") or ""
    res["content_hash"] = extract.content_hash(html)
    res["duplicate_of"] = _content_duplicate_of(conn, res["content_hash"], item["id"])
    if not html.strip():
        res["state"] = FETCH_EMPTY
        res["note"] = "the response carried no body, so nothing was ingested"
        return res
    if ingest is None:
        res["state"] = FETCH_OK
        res["note"] = "no ingest callable was supplied: the body was hashed, not parsed"
        return res
    try:
        ing = ingest(html, response.get("url") or item["url"], item) or {}
    except Exception as e:  # an ingest bug is one row, not a dead pass
        res["error"] = f"ingest raised {type(e).__name__}: {e}"
        return res
    if ing.get("error"):
        res["error"] = f"ingest failed: {ing['error']}"
        return res
    res["words"] = int(ing.get("words") or 0)
    res["doc_id"] = ing.get("doc_id")
    res["title"] = _clean(ing.get("title")) or None
    res["state"] = FETCH_EMPTY if res["words"] == 0 else FETCH_OK
    if res["state"] == FETCH_EMPTY:
        res["note"] = "the page was parsed but no article text was found in it"
    return res


def run_fetch(
    conn: sqlite3.Connection,
    fetch: Callable[[str], dict[str, Any]],
    *,
    limit: int = DEFAULT_FETCH_LIMIT,
    ts: float | None = None,
    gate: Callable[[str], tuple[bool, str]] | None = None,
    ingest: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
    retry: bool = False,
) -> dict[str, Any]:
    """Fetch the head of the queue and hand each body to `ingest`.

    `fetch(url) -> {"status": int|None, "html": str, "url": str|None,
    "error": str|None}` is the injected I/O boundary — the CLI supplies the
    urllib GET, tests supply canned dicts, and that is why nothing here opens a
    socket. `gate(url) -> (allowed, reason)` is the CLI's policy check: a denied
    url is recorded state "denied" and `fetch` is NEVER called for it, so one
    off-allowlist link cannot kill the pass (the links #4 doctrine).
    """
    now = time.time() if ts is None else float(ts)
    results: list[dict[str, Any]] = []
    for item in pending(conn, limit=limit, retry=retry):
        if gate is not None:
            allowed, reason = gate(item["url"])
            if not allowed:
                res = {
                    "id": item["id"], "url": item["url"], "state": FETCH_DENIED,
                    "status": None, "content_hash": None, "doc_id": None,
                    "words": None, "duplicate_of": None, "note": None, "title": None,
                    "error": f"policy-denied: {reason}",
                }
                _record_fetch(conn, item["id"], ts=now, state=FETCH_DENIED, error=res["error"])
                results.append(res)
                continue
        try:
            response = fetch(item["url"]) or {}
        except Exception as e:  # a fetcher bug is one row, not a dead pass
            response = {"error": f"{type(e).__name__}: {e}", "status": None}
        res = _fetch_one(conn, item, response, ingest=ingest)
        _record_fetch(
            conn,
            item["id"],
            ts=now,
            state=res["state"],
            status=res["status"],
            error=res["error"],
            content_hash=res["content_hash"],
            doc_id=res["doc_id"],
            words=res["words"],
            title=res["title"],
        )
        results.append(res)
    counts = dict.fromkeys(FETCH_STATES, 0)
    for res in results:
        counts[res["state"]] = counts.get(res["state"], 0) + 1
    return {
        "ts": now,
        "attempted": len(results),
        "counts": counts,
        "words": sum(int(r["words"]) for r in results if r["words"] is not None),
        "results": results,
    }


# ---- the board and the family gate ------------------------------------------


def board(
    conn: sqlite3.Connection, *, now: float | None = None, stale_days: float = STALE_DAYS
) -> dict[str, Any]:
    """Queue rollup. A measurement that cannot be taken is None WITH a reason."""
    clock = time.time() if now is None else float(now)
    by_state = dict.fromkeys(STATES, 0)
    by_fetch = dict.fromkeys(FETCH_STATES, 0)
    unfetched = 0
    tags: dict[str, int] = {}
    total = 0
    oldest: dict[str, Any] | None = None
    stale: list[dict[str, Any]] = []
    for r in conn.execute("SELECT * FROM items ORDER BY added_ts, key").fetchall():
        item = _row(r)
        if item is None:  # unreachable: rows come from a SELECT
            continue
        total += 1
        by_state[item["state"]] = by_state.get(item["state"], 0) + 1
        if item["fetch_state"] is None:
            unfetched += 1
        else:
            by_fetch[item["fetch_state"]] = by_fetch.get(item["fetch_state"], 0) + 1
        for t in item["tags"]:
            tags[t] = tags.get(t, 0) + 1
        if item["state"] != STATE_UNREAD:
            continue
        age_days = (clock - item["added_ts"]) / DAY
        if oldest is None:
            oldest = {
                "id": item["id"], "url": item["url"], "added_ts": item["added_ts"],
                "age_days": round(age_days, 2),
            }
        if age_days >= stale_days:
            stale.append({"id": item["id"], "url": item["url"], "age_days": round(age_days, 2)})
    notes: list[str] = []
    if oldest is None:
        notes.append(
            f"no {STATE_UNREAD} items, so there is no queue age to report"
            " (0 days would be a fabricated reading)"
        )
    duplicates = content_duplicates(conn)
    aliases = int(conn.execute("SELECT COUNT(*) AS n FROM aliases").fetchone()["n"])
    return {
        "now": clock,
        "total": total,
        "by_state": by_state,
        "by_fetch_state": by_fetch,
        "unfetched": unfetched,
        "oldest_unread": oldest,
        "stale_days": float(stale_days),
        "stale": stale,
        "tags": dict(sorted(tags.items())),
        "aliases": aliases,
        "alias_savings": max(0, aliases - total),
        "content_duplicate_groups": len(duplicates),
        "content_duplicates": duplicates,
        "notes": notes,
        "scope_limits": SCOPE_LIMITS,
    }


RULES: dict[str, dict[str, Any]] = {
    # a url that could not be canonicalised was NOT queued — silence here would
    # be an import that lost links without saying so
    "later:invalid-url": {"enabled": True, "severity": "error"},
    "later:fetch-error": {"enabled": True, "severity": "error"},
    "later:policy-denied": {"enabled": True, "severity": "warning"},
    "later:empty-article": {"enabled": True, "severity": "warning"},
    "later:duplicate-content": {"enabled": True, "severity": "info"},
    "later:stale": {"enabled": True, "severity": "suggestion"},
}


def load_rules(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """RULES with an optional JSON overlay. Unknown id / bad severity = error."""
    merged = {rid: dict(cfg) for rid, cfg in RULES.items()}
    if path is None:
        return merged
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("rules overlay must be a JSON object of rule -> settings")
    for rid, cfg in raw.items():
        if rid not in merged:
            raise ValueError(f"unknown rule id {rid!r} (see: scout later rules)")
        if not isinstance(cfg, dict):
            raise ValueError(f"rule {rid!r}: settings must be a JSON object")
        sev = cfg.get("severity")
        if sev is not None and sev not in openswap.SEVERITIES:
            raise ValueError(
                f"rule {rid!r}: severity must be one of {'|'.join(openswap.SEVERITIES)}"
            )
        merged[rid].update(cfg)
    return merged


def _diag(
    rules: dict[str, dict[str, Any]], rule: str, path: str, message: str, suggestion: str | None = None
) -> dict[str, Any] | None:
    cfg = rules.get(rule) or {}
    if not cfg.get("enabled", True):
        return None
    return openswap.diagnostic(
        path=path,
        line=0,
        col=0,
        rule=rule,
        severity=cfg.get("severity", "warning"),
        message=message,
        suggestion=suggestion,
        source="later",
    )


def fetch_diagnostics(
    results: Iterable[dict[str, Any]],
    invalid: Iterable[dict[str, Any]] = (),
    *,
    rules: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One pass's failures on the family diagnostic schema (the cron/CI hook)."""
    rs = rules or load_rules()
    diags: list[dict[str, Any]] = []
    for bad in invalid:
        diags.append(
            _diag(
                rs,
                "later:invalid-url",
                str(bad.get("input") or "<empty>"),
                f"not queued: {bad.get('error')}",
                "fix the url in the source export, or save it with a scheme",
            )
        )
    for res in results:
        if res["state"] == FETCH_ERROR:
            diags.append(_diag(rs, "later:fetch-error", res["url"], f"fetch failed: {res['error']}"))
        elif res["state"] == FETCH_DENIED:
            diags.append(
                _diag(
                    rs,
                    "later:policy-denied",
                    res["url"],
                    f"never fetched: {res['error']}",
                    "scout reach allow <host> to widen the user allowlist",
                )
            )
        elif res["state"] == FETCH_EMPTY:
            diags.append(_diag(rs, "later:empty-article", res["url"], f"nothing ingested: {res['note']}"))
    return openswap.sort_diagnostics([d for d in diags if d is not None])


def queue_diagnostics(
    conn: sqlite3.Connection,
    *,
    now: float | None = None,
    stale_days: float = STALE_DAYS,
    rules: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Standing queue health: staleness and byte-identical duplicates."""
    rs = rules or load_rules()
    snapshot = board(conn, now=now, stale_days=stale_days)
    diags = [
        _diag(
            rs,
            "later:stale",
            item["url"],
            f"unread for {item['age_days']:g} days (>= {stale_days:g})",
            "read it, archive it, or drop it — a queue nobody triages is a bookmark folder",
        )
        for item in snapshot["stale"]
    ]
    for group in snapshot["content_duplicates"]:
        ids = ", ".join(str(m["id"]) for m in group["items"])
        diags.append(
            _diag(
                rs,
                "later:duplicate-content",
                group["items"][0]["url"],
                f"{len(group['items'])} queued urls returned byte-identical bodies (items {ids})",
                "different urls, same page — archive the copies",
            )
        )
    return openswap.sort_diagnostics([d for d in diags if d is not None])


# ---- importers (Pocket / Raindrop exports, and the #12 feeds bridge) --------


def parse_add_date(value: Any) -> float | None:
    """A bookmark-export ADD_DATE -> epoch seconds, or None when it is unclear.

    Seconds below 1e11 and milliseconds below 1e14 are accepted. A WebKit/1601
    epoch (Chrome's internal JSON) lands above that and is REFUSED rather than
    guessed: a wrong date silently reorders the whole queue, and `add_offers`
    records `added_ts_source` so a fallback to the run clock stays visible.
    """
    text = _clean(value)
    if not text.isdigit():
        return None
    number = int(text)
    if number <= 0:
        return None
    if number < 100_000_000_000:
        return float(number)
    if number < 100_000_000_000_000:
        return number / 1000.0
    return None


class _BookmarkParser(HTMLParser):
    """Netscape bookmark-file reader (Pocket ril_export.html, Raindrop, browsers).

    Tolerant by necessity: real export files leave <DT> and <DD> unclosed, so a
    pending note is flushed whenever the next structural tag opens rather than
    waiting for an end tag that never comes. <H3> folder names are tracked per
    <DL> depth because Raindrop writes collections that way.
    """

    def __init__(self, *, folders_as_tags: bool = True) -> None:
        super().__init__(convert_charrefs=True)
        self.offers: list[dict[str, Any]] = []
        self.folders_as_tags = folders_as_tags
        self._stack: list[str | None] = []
        self._last_h3: str | None = None
        self._h3: list[str] | None = None
        self._anchor: dict[str, Any] | None = None
        self._note: list[str] | None = None
        self._note_target: dict[str, Any] | None = None

    @property
    def folder(self) -> str | None:
        for name in reversed(self._stack):
            if name:
                return name
        return None

    def flush_note(self) -> None:
        if self._note is not None and self._note_target is not None:
            text = _clean("".join(self._note))
            if text:
                self._note_target["note"] = text
        self._note = None

    def finish(self) -> None:
        """Close whatever the file left open — exports routinely leave an anchor
        or a <DD> dangling at EOF, and a dropped link is a lost link."""
        if self._anchor is not None:
            self._close_anchor()
        self.flush_note()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {(k or "").lower(): (v or "") for k, v in attrs}
        if tag in ("dl", "dt", "h3", "a"):
            self.flush_note()
            if self._anchor is not None:  # an <A> the export never closed
                self._close_anchor()
        if tag == "dl":
            self._stack.append(self._last_h3)
            self._last_h3 = None
        elif tag == "h3":
            self._h3 = []
        elif tag == "a":
            self._anchor = {"attrs": a, "parts": []}
        elif tag == "dd":
            self._note = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "dl":
            self.flush_note()
            if self._stack:
                self._stack.pop()
        elif tag == "h3":
            self._last_h3 = _clean("".join(self._h3 or [])) or None
            self._h3 = None
        elif tag == "a" and self._anchor is not None:
            self._close_anchor()

    def _close_anchor(self) -> None:
        anchor = self._anchor or {}
        self._anchor = None
        a = anchor.get("attrs") or {}
        tags = normalize_tags(a.get("tags"))
        if self.folders_as_tags and self.folder:
            tags = sorted(set(tags) | {self.folder.lower()})
        built = offer(
            a.get("href"),
            title=_clean("".join(anchor.get("parts") or [])),
            tags=tags,
            source="bookmarks",
            added_ts=parse_add_date(a.get("add_date")),
        )
        self.offers.append(built)
        self._note_target = built

    def handle_data(self, data: str) -> None:
        if self._h3 is not None:
            self._h3.append(data)
        if self._anchor is not None:
            self._anchor["parts"].append(data)
        if self._note is not None:
            self._note.append(data)


def parse_bookmarks(html: str, *, folders_as_tags: bool = True) -> list[dict[str, Any]]:
    """Every <A HREF> of a bookmark export, with its TAGS, folder, note and date.

    Anchors with no href are still returned (url None) so `merge_offers` records
    them as invalid: an import that silently drops rows is how a migration
    quietly loses links.
    """
    parser = _BookmarkParser(folders_as_tags=folders_as_tags)
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # tolerant by contract: soup must not kill an import
        pass
    parser.finish()
    return parser.offers


_CSV_URL = ("url", "link", "href", "uri")
_CSV_TITLE = ("title", "name")
_CSV_TAGS = ("tags", "tag", "labels")
_CSV_NOTE = ("note", "notes", "excerpt", "comment", "description")
_CSV_DATE = ("created", "added", "date", "timestamp", "add_date", "time_added")
_CSV_FOLDER = ("folder", "collection", "folders")


def _pick(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if row.get(name):
            return row[name]
    return ""


def parse_csv(text: str, *, folders_as_tags: bool = True) -> list[dict[str, Any]]:
    """Raindrop-style CSV export -> offers. ValueError if there is no url column.

    Dates go through feeds.parse_entry_time (#12) first — locale-independent by
    construction — then the epoch reader, so both "2026-07-01T10:00:00Z" and
    "1780000000" work and anything else leaves the date unknown rather than wrong.
    """
    reader = csv.DictReader(io.StringIO(text or ""))
    headers = [(_clean(h) or "").lower() for h in (reader.fieldnames or [])]
    if not any(h in _CSV_URL for h in headers):
        raise ValueError(
            f"no url column in the CSV (looked for {', '.join(_CSV_URL)}; found: "
            f"{', '.join(headers) or 'no header row'})"
        )
    offers: list[dict[str, Any]] = []
    for raw in reader:
        row = {(_clean(k) or "").lower(): _clean(v) for k, v in raw.items() if k}
        tags = normalize_tags(_pick(row, _CSV_TAGS))
        folder = _pick(row, _CSV_FOLDER)
        if folders_as_tags and folder:
            tags = sorted(set(tags) | {folder.lower()})
        stamp = _pick(row, _CSV_DATE)
        offers.append(
            offer(
                _pick(row, _CSV_URL),
                title=_pick(row, _CSV_TITLE),
                note=_pick(row, _CSV_NOTE),
                tags=tags,
                source="csv",
                added_ts=feeds.parse_entry_time(stamp) or parse_add_date(stamp),
            )
        )
    return offers


def offers_from_entries(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows exactly as `feeds.digest()["items"]` emits them -> queue offers.

    The #12 -> #34 -> #11 chain: the reader ranks, the queue dedupes across
    feeds (which feeds itself deliberately does not — see the module docstring),
    and the fetch pass hands the page to the #11 corpus. Matched keywords become
    tags so the interest that surfaced a link survives into the inbox.
    """
    out: list[dict[str, Any]] = []
    for entry in entries:
        feed = _clean(entry.get("feed"))
        tags = normalize_tags(list(entry.get("matched") or []) + list(entry.get("tags") or []))
        published = entry.get("published_ts")
        first_seen = entry.get("first_seen_ts")
        out.append(
            offer(
                entry.get("link"),
                title=entry.get("title"),
                note=entry.get("summary"),
                tags=tags,
                source=f"feeds:{feed}" if feed else "feeds",
                added_ts=published if published is not None else first_seen,
            )
        )
    return out
