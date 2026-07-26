# Solo personal project, no connection to employer, built with public/free-tier only
"""Feeds — RSS/Atom reader core (openswap #12: Feedly Pro).

miniflux pattern in pure stdlib: this module owns everything deterministic —
the xml.etree parser for RSS 2.0 / RSS 1.0 (RDF) / Atom behind one small
namespace shim (`local()` is the whole shim), locale-independent timestamp
parsing, the sha256 dedupe identity (entry id, else link, else title+date),
optional keyword scoring, the sqlite3 store (feeds / entries — its OWN file,
.scout/feeds.db, so a daily poll never contends with the #2 uptime ledger's
write lock), and the digest emitter in both shapes (structured dict + rendered
text). Real I/O stays out: the `feeds` plugin CLI supplies the urllib
conditional GET and injects it into run_fetch() as a callable
(bigbang/core/uptime.py + plugins/uptime/cli.py is the pattern), so the whole
pipeline is unit-testable fully offline.

Conditional GET is the reason this adapter is cheap enough to run hourly:
conditional_headers() replays the ETag / Last-Modified stored on the feed row,
a feed that has not changed answers 304 with no body, and run_fetch records the
304 WITHOUT re-parsing or re-ingesting anything. A 200 that arrives with no
ETag clears the stored one (replace_validators) — keeping a stale validator
would make a changed feed answer 304 forever, the one failure mode that would
silently stop the research ingestion.

Policy lives in the CLI, not here: run_fetch takes an optional `gate(url)`
callable and, when it denies, records state "denied" and NEVER calls fetch —
one off-allowlist feed must not kill the whole poll (the links #4 doctrine of
default-deny recorded as a report row rather than raised).

Dedupe is per SUBSCRIPTION (UNIQUE(feed, key)), which is what a reader wants:
unsubscribing drops that feed's rows and nothing else. The visible consequence
is that a cross-listed item — an arXiv paper announced in both cs.LG and cs.CL,
observed live on the first real poll — appears once per feed in a digest. A
digest-level collapse on `link` is the natural next step and belongs in digest(),
not in the store.

Extension points:
- Keyword profiles: load_keywords() overlays a JSON {keyword: weight} file onto
  DEFAULT_KEYWORDS (pure config, uptime.load_targets merge semantics), so
  steering the research loop's interests never touches code.
- Read-later / inbox adapters (#34 Pocket/Raindrop): add_feed + ingest are the
  write contract; any producer of normalized entries can push into the same
  store and inherit dedupe, scoring, and the digest.
- Digest publishing (#27 Zapier-class glue): digest() is the machine shape and
  render_digest() the paste/email artifact; both are pure functions of the
  store plus an explicit `now`, so a scheduled job stays deterministic.
- Family gate: to_diagnostics() maps fetch failures onto the openswap
  diagnostic schema (error=error, policy-denied=warning), so
  openswap.summarize() treats a dead feed exactly like a prose lint finding and
  `fetch --fail-on` becomes the cron/CI hook.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

from bigbang.core import openswap

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

DB_REL = Path(".scout") / "feeds.db"
SCHEMA_VERSION = "1"

# fetch outcomes (the report contract; also the diagnostics mapping keys)
STATE_OK = "ok"
STATE_NOT_MODIFIED = "not-modified"
STATE_ERROR = "error"
STATE_DENIED = "denied"
STATES = (STATE_OK, STATE_NOT_MODIFIED, STATE_ERROR, STATE_DENIED)

FORMAT_RSS = "rss"
FORMAT_RSS1 = "rss1"
FORMAT_ATOM = "atom"

SUMMARY_CAP = 1000
TITLE_CAP = 400
TITLE_WEIGHT = 2.0
DEFAULT_LIMIT = 20
DEFAULT_DIGEST_HOURS = 168.0  # one week of research ingestion

_FEED_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# Namespace shim — the only namespaces a real-world feed needs. Elements are
# matched by LOCAL name (see local()), so these constants exist for
# documentation and for the two places a namespace is genuinely disambiguating.
ATOM_NS = "http://www.w3.org/2005/Atom"
RSS1_NS = "http://purl.org/rss/1.0/"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"

# Seed research sources (daily ingestion: arxiv + ML blogs). Every host here
# must also appear in the plugin manifest's network domain allowlist
# (default-deny) or `fetch` records it denied and never opens a socket. This is
# a SEED list, not a verified-live list: a moved endpoint shows up as an honest
# error row on the feed, never as silence.
DEFAULT_FEEDS: dict[str, dict[str, Any]] = {
    "arxiv-cs-lg": {
        "url": "https://rss.arxiv.org/rss/cs.LG",
        "note": "arXiv cs.LG — machine learning",
    },
    "arxiv-cs-cl": {
        "url": "https://rss.arxiv.org/rss/cs.CL",
        "note": "arXiv cs.CL — computation and language",
    },
    "hf-blog": {
        "url": "https://huggingface.co/blog/feed.xml",
        "note": "Hugging Face blog",
    },
    "simonwillison": {
        "url": "https://simonwillison.net/atom/everything/",
        "note": "Simon Willison — LLM tooling commentary (Atom)",
    },
}

# The research loop's actual interests as weights (pure config — override with
# a JSON overlay, don't edit code). Phrases are allowed: whitespace in a
# keyword matches any run of whitespace in the text.
DEFAULT_KEYWORDS: dict[str, float] = {
    "curriculum learning": 3.0,
    "muon": 3.0,
    "optimizer": 2.0,
    "learning rate schedule": 2.0,
    "distillation": 2.0,
    "quantization": 2.0,
    "mixture of experts": 2.0,
    "small language model": 2.0,
    "tokenizer": 1.5,
    "benchmark contamination": 2.5,
    "evaluation harness": 2.0,
    "checkpoint": 1.0,
    "perplexity": 1.5,
}


class FeedError(ValueError):
    """Malformed or unrecognized feed document (the CLI turns this into fail_agent)."""


# ---- the namespace shim -----------------------------------------------------


def local(tag: Any) -> str:
    """'{http://www.w3.org/2005/Atom}entry' -> 'entry'. The whole shim.

    Every lookup in this module goes through local(), which is why one parser
    handles RSS 2.0 (no namespace), RSS 1.0 (RDF + purl namespaces), Atom, and
    the dc:/content: extensions without a namespace map per format. Lowercased
    so RSS's `pubDate` and Atom's `updated` are looked up the same way.
    """
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _children(el: ET.Element, *names: str) -> list[ET.Element]:
    """Direct children whose local name is in `names`, document order."""
    wanted = set(names)
    return [k for k in el if local(k.tag) in wanted]


def _first(el: ET.Element | None, *names: str) -> ET.Element | None:
    """First direct child matching `names` in PREFERENCE order, not doc order."""
    if el is None:
        return None
    for name in names:
        for kid in el:
            if local(kid.tag) == name:
                return kid
    return None


def _text(el: ET.Element | None, *names: str) -> str:
    """Concatenated text of the first matching child (mixed content included).

    itertext() rather than .text: Atom content type="xhtml" nests real markup,
    and a title containing an entity-escaped tag would otherwise truncate.
    """
    kid = _first(el, *names)
    if kid is None:
        return ""
    return "".join(kid.itertext())


class _TextExtract(HTMLParser):
    """Tags out, character refs decoded (html.parser never chokes on soup)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(value: str | None, *, cap: int = SUMMARY_CAP) -> str:
    """Feed descriptions are HTML; scoring and digests want text.

    Whitespace is collapsed so a summary is one line, and the result is capped
    (with an ellipsis when truncated) — the store holds a digest-sized excerpt,
    not whole articles. Never raises: a parser failure falls back to a tag strip.
    """
    if not value:
        return ""
    parser = _TextExtract()
    try:
        parser.feed(value)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    if cap > 0 and len(text) > cap:
        text = text[:cap].rstrip() + "…"
    return text


# ---- timestamps -------------------------------------------------------------

_ISO_HINT = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _epoch(dt: datetime) -> float:
    # a feed timestamp with no offset is UTC by fiat; guessing local time would
    # make the same document parse differently on two machines
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def parse_entry_time(value: Any) -> float | None:
    """RSS RFC-822 pubDate or Atom ISO-8601 timestamp -> epoch seconds.

    Locale-independent by construction: email.utils for RFC-822 and
    fromisoformat for ISO-8601, never strptime's locale-sensitive %b (the
    certmon #9 lesson). A trailing 'Z' is normalized here rather than leaning on
    3.11's fromisoformat, so the parse does not shift with the interpreter.
    Unparseable junk returns None — a feed with a bad date is still usable.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if _ISO_HINT.match(s):
        iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
        try:
            return _epoch(datetime.fromisoformat(iso))
        except Exception:
            return None
    try:
        dt = parsedate_to_datetime(s)
    except Exception:
        return None
    return None if dt is None else _epoch(dt)


def fmt_ts(ts: Any) -> str:
    """Epoch -> 'YYYY-MM-DD HH:MM UTC' (gmtime: same string on every box)."""
    if ts is None:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return ""


# ---- the parser -------------------------------------------------------------

_DOCTYPE_RE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


def _entry_link(el: ET.Element, fmt: str) -> str:
    """Atom prefers rel="alternate" (the human page), RSS has one <link>."""
    if fmt == FORMAT_ATOM:
        links = _children(el, "link")
        for want_rel in ("alternate", None):
            for ln in links:
                rel = (ln.get("rel") or "").strip().lower()
                href = (ln.get("href") or "").strip()
                if not href:
                    continue
                if want_rel is None or rel in ("", want_rel):
                    return href
        return ""
    return _text(el, "link").strip()


def _entry_of(el: ET.Element, fmt: str) -> dict[str, Any]:
    """One <item>/<entry> -> the normalized entry shape (all formats, one dict)."""
    guid = _text(el, "id", "guid").strip() or None
    link = _entry_link(el, fmt) or None
    if not link and guid and guid.startswith(("http://", "https://")):
        # RSS guid isPermaLink="true": the id IS the page
        link = guid
    author_el = _first(el, "author", "creator", "managingeditor")
    author = None
    if author_el is not None:
        author = (
            strip_html(_text(author_el, "name"), cap=120)
            or strip_html("".join(author_el.itertext()), cap=120)
            or None
        )
    tags = []
    for cat in _children(el, "category", "subject"):
        # Atom puts the label in @term, RSS in the element text
        value = (cat.get("term") or "").strip() or strip_html(
            "".join(cat.itertext()), cap=80
        )
        if value and value not in tags:
            tags.append(value)
    return {
        "guid": guid,
        "link": link,
        "title": strip_html(_text(el, "title"), cap=TITLE_CAP) or None,
        "summary": strip_html(
            _text(el, "summary", "description", "content", "encoded", "subtitle")
        ),
        "author": author,
        "tags": tags,
        "published_ts": parse_entry_time(
            _text(el, "published", "pubdate", "date", "updated", "modified")
        ),
    }


def parse_feed(document: str | bytes) -> dict[str, Any]:
    """RSS 2.0 / RSS 1.0 (RDF) / Atom -> {format, title, link, entries}.

    Bytes are preferred (an XML encoding declaration is honored); a str is
    encoded utf-8 for convenience in tests and fixtures. A DOCTYPE is REFUSED
    before parsing: stdlib ElementTree never fetches external DTDs, but an
    internal <!ENTITY> chain is still an expansion bomb, and no real feed
    carries a DOCTYPE — so refusing one closes the whole xml.etree attack
    surface without taking a defusedxml dependency (this family is stdlib-only).
    Raises FeedError on anything that is not a recognizable feed.
    """
    raw = (
        document.encode("utf-8", "replace")
        if isinstance(document, str)
        else bytes(document)
    )
    if not raw.strip():
        raise FeedError("empty document")
    if _DOCTYPE_RE.search(raw[:4096]):
        raise FeedError("refusing a DOCTYPE declaration (entity-expansion risk)")
    try:
        # S314: the DOCTYPE refusal above removes the entity-expansion vector,
        # which is the only xml.etree exposure defusedxml would add here.
        root = ET.fromstring(raw)  # noqa: S314
    except ET.ParseError as e:
        raise FeedError(f"not well-formed XML: {e}") from e
    rname = local(root.tag)
    if rname == "feed":
        fmt, entry_names, container = FORMAT_ATOM, ("entry",), root
    elif rname in ("rss", "rdf"):
        fmt = FORMAT_RSS if rname == "rss" else FORMAT_RSS1
        entry_names = ("item",)
        channel = _first(root, "channel")
        container = channel if channel is not None else root
    else:
        raise FeedError(f"unrecognized feed root <{root.tag}>")
    items: list[ET.Element] = []
    seen: set[int] = set()
    # RSS 1.0 hangs <item> off rdf:RDF as a SIBLING of <channel>; RSS 2.0 nests
    # them inside it. Scanning both (identity-deduped) covers every shape.
    for parent in (container, root):
        for el in _children(parent, *entry_names):
            if id(el) not in seen:
                seen.add(id(el))
                items.append(el)
    return {
        "format": fmt,
        "title": strip_html(_text(container, "title"), cap=TITLE_CAP) or None,
        "link": _entry_link(container, fmt) or None,
        "entries": [_entry_of(el, fmt) for el in items],
    }


# ---- dedupe identity --------------------------------------------------------


def entry_key(entry: dict[str, Any]) -> str:
    """Stable dedupe identity: entry id, else link, else title+timestamp.

    sha256 hexdigest (the glitch #8 fingerprint doctrine) so the key is
    fixed-width and index-friendly no matter how long a guid is. An entry with
    no id, no link and no title collapses onto one key by design — there is
    nothing left to tell two such entries apart, and inventing a per-fetch id
    would re-import them forever.
    """
    ident = (entry.get("guid") or "").strip() or (entry.get("link") or "").strip()
    if not ident:
        ident = f"{(entry.get('title') or '').strip()}\n{entry.get('published_ts')}"
    return hashlib.sha256(ident.encode("utf-8")).hexdigest()


# ---- keyword scoring (optional) ---------------------------------------------


def load_keywords(path: str | None = None) -> dict[str, float]:
    """DEFAULT_KEYWORDS overlaid with an optional JSON {keyword: weight} file.

    Merge semantics mirror uptime.load_targets: a weight replaces, and `false`
    or 0 drops the keyword entirely. Raises ValueError / OSError / json errors
    for the CLI to convert into a fail_agent envelope.
    """
    keywords: dict[str, float] = copy.deepcopy(DEFAULT_KEYWORDS)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("keywords file must be a JSON object of {keyword: weight}")
        for kw, weight in raw.items():
            if not (isinstance(kw, str) and kw.strip()):
                raise ValueError(f"keyword {kw!r}: must be a non-empty string")
            if weight is False or weight == 0:
                keywords.pop(kw, None)
                continue
            # bool is an int subclass: `"muon": true` must not pass as weight 1
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise ValueError(f"keyword {kw!r}: weight must be a number")
            if weight < 0:
                raise ValueError(f"keyword {kw!r}: weight must be >= 0")
            keywords[kw] = float(weight)
    return keywords


@lru_cache(maxsize=512)
def _pattern(keyword: str) -> re.Pattern[str]:
    # (?<!\w)/(?!\w) instead of \b so punctuated keywords ("gpt-4", "c++")
    # still anchor on word edges; whitespace in a phrase matches any run of
    # whitespace, because feed text wraps wherever the publisher felt like it
    body = r"\s+".join(re.escape(part) for part in keyword.split())
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def score_entry(
    entry: dict[str, Any],
    keywords: dict[str, float] | None,
    *,
    title_weight: float = TITLE_WEIGHT,
) -> dict[str, Any]:
    """{"score", "matched"} — a title hit outweighs a body hit; no keywords = 0.

    Each keyword scores AT MOST once, at its best field, so a keyword-stuffed
    summary can never outrank a genuine title match. Scoring is entirely
    optional: with an empty keyword set every entry scores 0 and the digest
    falls back to pure recency ordering.
    """
    if not keywords:
        return {"score": 0.0, "matched": []}
    title = entry.get("title") or ""
    body_parts = [entry.get("summary") or "", " ".join(entry.get("tags") or [])]
    body = " ".join(p for p in body_parts if p)
    score = 0.0
    matched: list[str] = []
    for keyword, weight in keywords.items():
        pattern = _pattern(keyword)
        in_title = bool(pattern.search(title))
        in_body = bool(pattern.search(body))
        if not (in_title or in_body):
            continue
        score += float(weight) * (title_weight if in_title else 1.0)
        matched.append(keyword)
    return {"score": round(score, 3), "matched": sorted(matched)}


# ---- store ------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds(
    name TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    note TEXT,
    added_ts REAL NOT NULL,
    etag TEXT,
    last_modified TEXT,
    last_fetch_ts REAL,
    last_status INTEGER,
    last_error TEXT,
    fetches INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS entries(
    id INTEGER PRIMARY KEY,
    feed TEXT NOT NULL,
    key TEXT NOT NULL,
    guid TEXT,
    link TEXT,
    title TEXT,
    summary TEXT,
    author TEXT,
    tags TEXT,
    published_ts REAL,
    first_seen_ts REAL NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    matched TEXT,
    digested_ts REAL,
    UNIQUE(feed, key)
);
CREATE INDEX IF NOT EXISTS idx_entries_feed_seen ON entries(feed, first_seen_ts);
CREATE INDEX IF NOT EXISTS idx_entries_rank ON entries(score, published_ts);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the reader store — its OWN sqlite file.

    Never the #2 uptime ledger: an hourly poll of 40 feeds holds the write lock
    in bursts, and monitoring must never wait behind reading (the runtrack #10
    and glitch #8 doctrine). `feeds` rows carry the conditional-GET validators;
    `entries` is the deduped item table (UNIQUE(feed, key) IS the dedupe).
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


def valid_feed_name(name: Any) -> bool:
    """Registry hygiene: lowercase [a-z0-9][a-z0-9._-]{0,63} (heartbeat #6 rule)."""
    return isinstance(name, str) and bool(_FEED_NAME_RE.match(name))


def add_feed(
    conn: sqlite3.Connection,
    name: str,
    url: str,
    *,
    note: str | None = None,
    ts: float | None = None,
) -> dict[str, Any]:
    """Register (or re-point) one feed. Idempotent; no network.

    Re-adding the same name+url is a no-op success. Re-adding with a DIFFERENT
    url re-points the row and CLEARS the stored ETag/Last-Modified: those
    validators belong to the old resource, and replaying them at a new URL
    would invite a bogus 304 (silent ingestion death).
    """
    if not valid_feed_name(name):
        raise ValueError(f"feed name {name!r}: must match {_FEED_NAME_RE.pattern}")
    if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
        raise ValueError(f"feed {name!r}: needs an http(s) url, got {url!r}")
    ts = time.time() if ts is None else float(ts)
    row = conn.execute("SELECT * FROM feeds WHERE name = ?", (name,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO feeds(name, url, note, added_ts) VALUES(?, ?, ?, ?)",
            (name, url, note, ts),
        )
        conn.commit()
        return {"feed": name, "url": url, "created": True, "repointed": False}
    if row["url"] != url:
        conn.execute(
            "UPDATE feeds SET url = ?, etag = NULL, last_modified = NULL,"
            " note = COALESCE(?, note) WHERE name = ?",
            (url, note, name),
        )
        conn.commit()
        return {
            "feed": name,
            "url": url,
            "created": False,
            "repointed": True,
            "previous_url": row["url"],
        }
    if note is not None:
        conn.execute("UPDATE feeds SET note = ? WHERE name = ?", (note, name))
        conn.commit()
    return {"feed": name, "url": url, "created": False, "repointed": False}


def seed_feeds(
    conn: sqlite3.Connection,
    feeds: dict[str, dict[str, Any]] | None = None,
    *,
    ts: float | None = None,
) -> list[dict[str, Any]]:
    """Bulk-register DEFAULT_FEEDS (or a given map). Idempotent, no network."""
    src = DEFAULT_FEEDS if feeds is None else feeds
    return [
        add_feed(conn, name, cfg["url"], note=cfg.get("note"), ts=ts)
        for name, cfg in src.items()
    ]


def get_feed(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM feeds WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def list_feeds(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Registry board: every feed with its validators and entry counts.

    `conditional` reports whether the NEXT poll can be a cheap one — that is the
    single number that tells you the ETag/Last-Modified machinery is working.
    """
    rows = conn.execute(
        "SELECT f.*,"
        " (SELECT COUNT(*) FROM entries e WHERE e.feed = f.name) AS entries,"
        " (SELECT COUNT(*) FROM entries e WHERE e.feed = f.name"
        "   AND e.digested_ts IS NULL) AS undigested"
        " FROM feeds f ORDER BY f.name"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["conditional"] = bool(d.get("etag") or d.get("last_modified"))
        out.append(d)
    return out


def conditional_headers(feed_row: dict[str, Any] | None) -> dict[str, str]:
    """Stored validators as request headers — the whole point of adapter #12.

    If-None-Match beats If-Modified-Since when both exist (an ETag is exact,
    a date is second-resolution), but sending both is what real readers do and
    costs nothing.
    """
    headers: dict[str, str] = {}
    if not feed_row:
        return headers
    etag = feed_row.get("etag")
    last_modified = feed_row.get("last_modified")
    if etag:
        headers["If-None-Match"] = str(etag)
    if last_modified:
        headers["If-Modified-Since"] = str(last_modified)
    return headers


def record_fetch(
    conn: sqlite3.Connection,
    name: str,
    *,
    ts: float,
    status: int | None,
    etag: str | None = None,
    last_modified: str | None = None,
    error: str | None = None,
    title: str | None = None,
    replace_validators: bool = False,
) -> None:
    """Persist one poll's outcome on the feed row.

    replace_validators=True (a fresh 200 body) SETS both validators to exactly
    what the response carried — including NULL. A 200 without an ETag must clear
    the old one; keeping it would make the next poll send a validator the server
    still matches, and the feed would answer 304 forever while actually changing.
    A 304 or an error keeps what we have (COALESCE), because nothing new was
    learned about the resource.
    """
    if replace_validators:
        conn.execute(
            "UPDATE feeds SET etag = ?, last_modified = ? WHERE name = ?",
            (etag, last_modified, name),
        )
    else:
        conn.execute(
            "UPDATE feeds SET etag = COALESCE(?, etag),"
            " last_modified = COALESCE(?, last_modified) WHERE name = ?",
            (etag, last_modified, name),
        )
    conn.execute(
        "UPDATE feeds SET last_fetch_ts = ?, last_status = ?, last_error = ?,"
        " title = COALESCE(?, title), fetches = fetches + 1 WHERE name = ?",
        (ts, status, error, title, name),
    )
    conn.commit()


def ingest(
    conn: sqlite3.Connection,
    feed: str,
    entries: Iterable[dict[str, Any]],
    *,
    ts: float,
    keywords: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Dedupe + score + store one parsed document's entries.

    UNIQUE(feed, key) plus INSERT OR IGNORE IS the dedupe: an unchanged item
    re-offered on every poll inserts zero rows, and rowcount tells us which
    entries are genuinely new (the digest's whole basis). Duplicates are NOT
    re-scored — a stored score is the one the digest already ranked.
    """
    new: list[dict[str, Any]] = []
    duplicate = 0
    for entry in entries:
        key = entry_key(entry)
        scored = score_entry(entry, keywords)
        cur = conn.execute(
            "INSERT OR IGNORE INTO entries(feed, key, guid, link, title, summary,"
            " author, tags, published_ts, first_seen_ts, score, matched)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                feed,
                key,
                entry.get("guid"),
                entry.get("link"),
                entry.get("title"),
                entry.get("summary"),
                entry.get("author"),
                json.dumps(entry.get("tags") or []),
                entry.get("published_ts"),
                ts,
                scored["score"],
                json.dumps(scored["matched"]),
            ),
        )
        if cur.rowcount == 1:
            new.append(
                {
                    "id": int(cur.lastrowid),
                    "key": key,
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "published_ts": entry.get("published_ts"),
                    "score": scored["score"],
                    "matched": scored["matched"],
                }
            )
        else:
            duplicate += 1
    conn.commit()
    return {
        "feed": feed,
        "offered": len(new) + duplicate,
        "new": len(new),
        "duplicate": duplicate,
        "entries": new,
    }


# ---- the poll ---------------------------------------------------------------


def run_fetch(
    conn: sqlite3.Connection,
    fetch: Callable[[str, dict[str, str]], dict[str, Any]],
    *,
    names: list[str] | None = None,
    ts: float | None = None,
    keywords: dict[str, float] | None = None,
    gate: Callable[[str], tuple[bool, str]] | None = None,
) -> dict[str, Any]:
    """One poll over the registry: conditional GET, parse, dedupe, score, record.

    `fetch(url, headers)` must return {"status": int|None, "body": bytes|str,
    "etag": str|None, "last_modified": str|None, "error": str|None} — the CLI
    injects the real urllib conditional GET; tests inject fakes (the offline
    invariant). `gate(url) -> (allowed, reason)` is the CLI's policy check: a
    denied feed is recorded state "denied" and `fetch` is NEVER called for it,
    so one off-allowlist feed cannot kill the whole poll.
    """
    ts = time.time() if ts is None else float(ts)
    rows = list_feeds(conn)
    if names:
        known = {r["name"] for r in rows}
        missing = [n for n in names if n not in known]
        if missing:
            raise ValueError(f"unknown feed(s): {', '.join(sorted(missing))}")
        wanted = set(names)
        rows = [r for r in rows if r["name"] in wanted]
    results: list[dict[str, Any]] = []
    for row in rows:
        name, url = row["name"], row["url"]
        res: dict[str, Any] = {
            "feed": name,
            "url": url,
            "state": STATE_ERROR,
            "status": None,
            "conditional": False,
            "new": 0,
            "duplicate": 0,
            "entries": [],
            "error": None,
        }
        if gate is not None:
            allowed, reason = gate(url)
            if not allowed:
                res["state"] = STATE_DENIED
                res["error"] = f"policy-denied: {reason}"
                record_fetch(conn, name, ts=ts, status=None, error=res["error"])
                results.append(res)
                continue
        headers = conditional_headers(row)
        res["conditional"] = bool(headers)
        r = fetch(url, headers)
        status = r.get("status")
        res["status"] = status
        if r.get("error") or status is None:
            res["error"] = r.get("error") or "no answer"
            record_fetch(conn, name, ts=ts, status=status, error=res["error"])
        elif int(status) == 304:
            # the cheap path: no body, nothing re-parsed, validators preserved
            res["state"] = STATE_NOT_MODIFIED
            record_fetch(
                conn,
                name,
                ts=ts,
                status=int(status),
                etag=r.get("etag"),
                last_modified=r.get("last_modified"),
                error=None,
            )
        elif 200 <= int(status) < 300:
            try:
                parsed = parse_feed(r.get("body") or b"")
            except FeedError as e:
                res["error"] = f"unparseable: {e}"
                record_fetch(conn, name, ts=ts, status=int(status), error=res["error"])
            else:
                ing = ingest(conn, name, parsed["entries"], ts=ts, keywords=keywords)
                res.update(
                    state=STATE_OK,
                    format=parsed["format"],
                    offered=ing["offered"],
                    new=ing["new"],
                    duplicate=ing["duplicate"],
                    entries=ing["entries"],
                )
                record_fetch(
                    conn,
                    name,
                    ts=ts,
                    status=int(status),
                    etag=r.get("etag"),
                    last_modified=r.get("last_modified"),
                    error=None,
                    title=parsed["title"],
                    replace_validators=True,
                )
        else:
            res["error"] = f"http {int(status)}"
            record_fetch(conn, name, ts=ts, status=int(status), error=res["error"])
        results.append(res)
    by_state: dict[str, int] = {}
    for r in results:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    return {
        "ts": ts,
        "results": results,
        "by_state": by_state,
        "new_entries": sum(r["new"] for r in results),
    }


_SEVERITY_OF = {STATE_ERROR: "error", STATE_DENIED: "warning"}


def to_diagnostics(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map failed polls onto the family diagnostic schema.

    error=error (a feed we cannot read is silent research ingestion — the
    failure mode this adapter exists to prevent), policy-denied=warning (a
    configuration fact, not a broken feed). ok / not-modified emit nothing.
    line/col carry no meaning for a URL and stay 0.
    """
    diags = []
    for r in results:
        severity = _SEVERITY_OF.get(r.get("state"))
        if severity is None:
            continue
        diags.append(
            openswap.diagnostic(
                path=r.get("url") or r["feed"],
                line=0,
                col=0,
                rule=f"feeds:{r['state']}",
                severity=severity,
                message=f"{r['feed']} {r['state']} — {r.get('error') or 'no detail'}",
            )
        )
    return openswap.sort_diagnostics(diags)


# ---- the digest -------------------------------------------------------------


def digest(
    conn: sqlite3.Connection,
    *,
    feed: str | None = None,
    since: float | None = None,
    min_score: float = 0.0,
    limit: int = DEFAULT_LIMIT,
    new_only: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    """Ranked entries + the counts a digest header needs. Read-only, no network.

    Ranking is score DESC then recency DESC: keyword-scored items lead, and
    everything ties back to time so a zero-keyword setup degrades to a plain
    reverse-chronological reader. Entries with no publication date rank by when
    we first saw them (COALESCE) instead of sinking below dateless noise.
    """
    now = time.time() if now is None else float(now)
    where = ["1 = 1"]
    params: list[Any] = []
    if feed:
        where.append("feed = ?")
        params.append(feed)
    if since is not None:
        where.append("COALESCE(published_ts, first_seen_ts) >= ?")
        params.append(float(since))
    if min_score and min_score > 0:
        where.append("score >= ?")
        params.append(float(min_score))
    if new_only:
        where.append("digested_ts IS NULL")
    rows = conn.execute(
        # S608: `where` holds only fixed literals built above — every caller
        # value travels as a ? parameter, none is interpolated
        "SELECT * FROM entries WHERE "  # noqa: S608
        + " AND ".join(where)
        + " ORDER BY score DESC, COALESCE(published_ts, first_seen_ts) DESC, id DESC"
        " LIMIT ?",
        (*params, int(limit) if limit and limit > 0 else -1),
    ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        for field in ("matched", "tags"):
            try:
                d[field] = json.loads(d[field]) if d[field] else []
            except (TypeError, ValueError):
                d[field] = []
        items.append(d)
    return {
        "generated_ts": now,
        "since": since,
        "min_score": float(min_score),
        "limit": int(limit),
        "new_only": bool(new_only),
        "feed": feed,
        "count": len(items),
        "feeds": sorted({i["feed"] for i in items}),
        "items": items,
    }


def mark_digested(
    conn: sqlite3.Connection, ids: Iterable[int], *, ts: float | None = None
) -> int:
    """Stamp digested_ts so `digest --new` never repeats an item. Returns rows hit."""
    id_list = [int(i) for i in ids]
    if not id_list:
        return 0
    ts = time.time() if ts is None else float(ts)
    placeholders = ",".join("?" for _ in id_list)
    cur = conn.execute(
        f"UPDATE entries SET digested_ts = ? WHERE id IN ({placeholders})",  # noqa: S608
        (ts, *id_list),
    )
    conn.commit()
    return int(cur.rowcount)


def render_digest(dg: dict[str, Any]) -> str:
    """The text emitter: a paste/email-ready digest (JSON is the machine side).

    A pure function of the digest dict — every timestamp comes from the dict and
    renders in UTC, so the same digest renders byte-identically on any box.
    """
    header = (
        f"feeds digest — {dg['count']} item(s)"
        f" from {len(dg['feeds'])} feed(s)  [{fmt_ts(dg.get('generated_ts'))}]"
    )
    lines = [header, "=" * len(header)]
    filters = []
    if dg.get("since") is not None:
        filters.append(f"since {fmt_ts(dg['since'])}")
    if dg.get("min_score"):
        filters.append(f"score >= {dg['min_score']}")
    if dg.get("new_only"):
        filters.append("undigested only")
    if dg.get("feed"):
        filters.append(f"feed {dg['feed']}")
    if filters:
        lines.append("filters: " + ", ".join(filters))
    lines.append("")
    if not dg["items"]:
        lines.append("(no entries matched — poll first, or widen the filters)")
    for i, it in enumerate(dg["items"], 1):
        lines.append(
            f"{i:>2}. [{float(it.get('score') or 0.0):.1f}] "
            f"{it.get('title') or '(untitled)'}"
        )
        meta = " · ".join(
            part
            for part in (
                it.get("feed"),
                fmt_ts(it.get("published_ts")),
                ", ".join(it.get("matched") or []),
            )
            if part
        )
        if meta:
            lines.append(f"    {meta}")
        if it.get("link"):
            lines.append(f"    {it['link']}")
        if it.get("summary"):
            lines.append(f"    {strip_html(it['summary'], cap=220)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
