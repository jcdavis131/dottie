# Solo personal project, no connection to employer, built with public/free-tier only
"""Extract — Readability-style article extraction core (openswap #11: Diffbot /
Mercury Parser).

The paid enemies here are both somebody else's parser: Diffbot bills per API
call to read a page for you, and Mercury Parser's hosted endpoint was retired
out from under everyone (its open successor is a node CLI that fetches outside
any policy gate). This adapter inverts that — the page is parsed on THIS box by
`html.parser`, and every judgment lives here so the whole pipeline is
unit-testable fully offline. The plugin CLI owns the one real I/O (urllib GET /
file read / stdin) and hands this module a `str` of HTML; nothing in this module
opens a socket or a file except the sqlite corpus ledger it is handed a path to.

The algorithm (Readability's, re-derived in stdlib):
- ONE html.parser pass builds a tolerant element tree. Never-content subtrees
  (script/style/svg/...) and page chrome (nav/footer/header/aside/form/...) are
  dropped at the parse boundary and counted in `removed`, so boilerplate can
  never leak into the article no matter how it scores.
- `_prune_unlikely` drops containers whose class/id reads as chrome
  (sidebar/comment/share/promo...) unless a content-ish token rescues them —
  Readability's unlikelyCandidates / okMaybeItsACandidate pair.
- Paragraph-ish nodes (>= MIN_PARAGRAPH_CHARS of text) score 1 + commas +
  length/100 (capped), and hand that score to their parent (full), grandparent
  (half) and great-grandparent (third), on top of a per-tag base score and a
  +/-25 class/id weight.
- Every candidate is then multiplied by `1 - link_density`, which is what
  actually kills link farms, tag clouds and "related posts" rails: a block that
  is mostly anchor text scores ~0 even when it is long.
- The winner plus its qualifying siblings become the article; the renderer walks
  that subtree in document order, keeps `<pre>` verbatim, collapses whitespace
  everywhere else, and joins blocks with a blank line.

Metadata is collected in the SAME pass and deliberately independent of content
selection, so a headline or byline sitting inside a dropped `<header>` is still
found: JSON-LD (Article/NewsArticle/BlogPosting...), og:/twitter:/dc: meta,
`rel=author`, class/id byline elements, `<time datetime>`, `<h1>`, `<html lang>`.
`clean_title`, `clean_byline` and `normalize_date` are pure and separately
testable; date parsing is locale-independent by construction (own month table +
email.utils.parsedate_tz — never strptime %B, whose meaning depends on LC_TIME).

Throughput over latency (this sits on the daily research-ingestion path):
- one parse pass, descendant text memoized per node (no O(n^2) re-walks)
- the corpus ledger is keyed by sha256 of the raw HTML, so `run_batch` returns a
  cached row for bytes it has already parsed and never re-parses them
- the CLI can prefetch URLs concurrently and still feed `run_batch` in input
  order, because ordering lives here and not in the fetcher

Extension points:
- Thresholds as config: extract(min_paragraph_chars=), to_diagnostics(
  thin_words=, max_link_density=) — feed them from a JSON overlay, no code edit.
- New metadata sources: add a key to _TITLE_META / _BYLINE_META / _DATE_META;
  the priority chain and `*_source` provenance fields follow automatically.
- Downstream consumers: the ledger (documents table) is the read contract —
  `recent_documents`, `corpus_stats`, `cached_document`.
- Native tier: there is none to prefer. Diffbot is SaaS and the surviving
  Mercury fork (postlight-parser) is a node CLI that fetches on its own, so the
  plugin surfaces it in `detect` but never executes it.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import re
import sqlite3
import time
from datetime import date
from email.utils import parsedate_tz
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bigbang.core import openswap

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

SCHEMA_VERSION = "1"
DB_REL = Path(".scout") / "extract.db"

# a page bigger than this is a download, not an article (the CLI caps its read
# here too — a runaway response must not become a memory event mid-batch)
MAX_FETCH_BYTES = 8 * 1024 * 1024

# Readability's paragraph floor: shorter runs are furniture, not prose.
MIN_PARAGRAPH_CHARS = 25
# diagnostic budgets (words / anchor-text ratio); overridable per call
THIN_WORDS = 120
MAX_LINK_DENSITY = 0.5

STDIN_SOURCE = "-"

# ---- tag classes ------------------------------------------------------------

# never content, and their text is not even stored (skipping it is the cheap
# win on script-heavy pages)
RAW_TAGS = frozenset(
    {"script", "style", "noscript", "template", "svg", "math", "canvas"}
)
# page chrome: dropped from the content tree, but their text IS kept in the
# node so metadata capture (a byline inside <header>) still works
CHROME_TAGS = frozenset(
    {
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "menu",
        "dialog",
        "fieldset",
        "select",
        "textarea",
        "button",
        "iframe",
        "object",
        "embed",
        "video",
        "audio",
        "map",
    }
)
DROP_TAGS = RAW_TAGS | CHROME_TAGS

VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
# the only void elements that mean anything to a text renderer; the rest
# (meta/link/input/...) are never linked into the content tree, so a `<div>`
# holding one still counts as a paragraph container
KEEP_VOID_TAGS = frozenset({"br", "img", "wbr", "hr"})

# tags HTML lets you leave open: a new one of these implicitly closes the last
_IMPLICIT_CLOSE = {
    "li": frozenset({"li"}),
    "dt": frozenset({"dt", "dd"}),
    "dd": frozenset({"dt", "dd"}),
    "td": frozenset({"td", "th"}),
    "th": frozenset({"td", "th"}),
    "tr": frozenset({"tr", "td", "th"}),
    "option": frozenset({"option"}),
}

INLINE_TAGS = frozenset(
    {
        "a",
        "abbr",
        "b",
        "bdi",
        "bdo",
        "big",
        "br",
        "cite",
        "code",
        "data",
        "del",
        "dfn",
        "em",
        "font",
        "i",
        "img",
        "ins",
        "kbd",
        "label",
        "mark",
        "nobr",
        "q",
        "rp",
        "rt",
        "ruby",
        "s",
        "samp",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "time",
        "tt",
        "u",
        "var",
        "wbr",
    }
)

# nodes scored as "a paragraph of prose"
PARA_TAGS = frozenset({"p", "pre", "td", "blockquote", "figcaption", "dd", "li"})
# containers that count as a paragraph when they hold only inline children
PARA_CONTAINERS = frozenset({"div", "section", "article", "main"})

# Readability's per-tag base score for a candidate container: semantic
# containers start ahead, list/heading wrappers start behind
_BASE_SCORE = {
    "article": 8.0,
    "main": 8.0,
    "section": 5.0,
    "div": 5.0,
    "pre": 3.0,
    "td": 3.0,
    "blockquote": 3.0,
    "address": -3.0,
    "ol": -3.0,
    "ul": -3.0,
    "dl": -3.0,
    "dd": -3.0,
    "dt": -3.0,
    "li": -3.0,
    "form": -3.0,
    "h1": -5.0,
    "h2": -5.0,
    "h3": -5.0,
    "h4": -5.0,
    "h5": -5.0,
    "h6": -5.0,
    "th": -5.0,
}

_POSITIVE_RE = re.compile(
    r"article|body|content|entry|hentry|h-entry|main|page|pagination|post|story"
    r"|text|blog|column",
    re.IGNORECASE,
)
_NEGATIVE_RE = re.compile(
    r"hidden|banner|combx|comment|com-|contact|foot|footer|footnote|gdpr|masthead"
    r"|media|meta|modal|outbrain|promo|related|scroll|share|shoutbox|sidebar"
    r"|skyscraper|sponsor|shopping|tags|tool|widget|newsletter|subscribe|cookie",
    re.IGNORECASE,
)
# Readability's unlikelyCandidates / okMaybeItsACandidate pair
_UNLIKELY_RE = re.compile(
    r"banner|breadcrumb|combx|comment|community|cover-wrap|disqus|extra|footer"
    r"|gdpr|header|legends|masthead|menu|modal|nav|pager|pagination|popup|promo"
    r"|related|remark|replies|rss|shoutbox|sidebar|skyscraper|social|sponsor"
    r"|supplemental|newsletter|subscribe|cookie|ad-break|agegate|share",
    re.IGNORECASE,
)
_MAYBE_RE = re.compile(r"and|article|body|column|content|main|shadow", re.IGNORECASE)
# elements that are the article by fiat and are never pruned by class/id
_NEVER_PRUNE = frozenset({"body", "article", "main", "[document]"})

# ---- metadata keys ----------------------------------------------------------

# priority order, most trustworthy first — extend these, not the pickers
_TITLE_META = ("og:title", "twitter:title", "dc.title", "citation_title", "title")
_BYLINE_META = (
    "author",
    "article:author",
    "og:article:author",
    "byl",
    "dc.creator",
    "citation_author",
    "parsely-author",
    "twitter:creator",
)
_DATE_META = (
    "article:published_time",
    "article:published",
    "og:article:published_time",
    "datepublished",
    "date",
    "pubdate",
    "publishdate",
    "publish-date",
    "publication_date",
    "dc.date",
    "dc.date.issued",
    "citation_publication_date",
    "citation_date",
    "parsely-pub-date",
    "sailthru.date",
    "article.published",
    "timestamp",
)
_LD_ARTICLE_TYPES = frozenset(
    {
        "article",
        "newsarticle",
        "blogposting",
        "report",
        "scholarlyarticle",
        "techarticle",
        "liveblogposting",
        "webpage",
    }
)

_BYLINE_ATTR_RE = re.compile(
    r"byline|by-line|byl\b|author|writtenby|written-by|dc-creator|contributor",
    re.IGNORECASE,
)
_BY_PREFIX_RE = re.compile(
    r"^\s*(?:by|von|par|posted\s+by|written\s+by|words\s+by|story\s+by|author)\b"
    r"[:\s]*",
    re.IGNORECASE,
)
_TITLE_SEPS = (" | ", " – ", " — ", " :: ", " » ", " › ", " • ", " - ", " / ")

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_ISO_DATE_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_TEXT_DATE_RE = re.compile(
    r"^(?:(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})|([A-Za-z]{3,9})\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?),?\s+(\d{4})",
)
_COMPACT_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\S+")
_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]*?charset\s*=\s*["']?\s*([A-Za-z0-9_.:+-]+)""", re.IGNORECASE
)


def _ws(text: str | None) -> str:
    """Collapse all whitespace runs to one space and strip. The single
    normalizer — every comparison and every emitted string goes through it."""
    return _WS_RE.sub(" ", text or "").strip()


def word_count(text: str | None) -> int:
    """Whitespace-separated tokens — the honest, language-agnostic count."""
    return len(_WORD_RE.findall(text or ""))


def content_hash(html: str | None) -> str:
    """sha256 of the raw document — the corpus cache key (identical bytes are
    never parsed twice, which is where batch throughput comes from)."""
    return hashlib.sha256((html or "").encode("utf-8", "replace")).hexdigest()


# ---- charset sniffing (the CLI hands us bytes; HTML5 precedence order) -------


def sniff_charset(raw: bytes, header_charset: str | None = None) -> str:
    """BOM > HTTP header > `<meta charset>` > utf-8, same order a browser uses.

    An unknown/garbage encoding name never wins: it is validated through
    codecs.lookup so a hostile page cannot make the decode raise.
    """
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    for cand in (header_charset, _meta_charset(raw)):
        if not cand:
            continue
        try:
            codecs.lookup(cand)
        except (LookupError, TypeError, ValueError):
            continue
        return cand
    return "utf-8"


def _meta_charset(raw: bytes) -> str | None:
    m = _META_CHARSET_RE.search(raw[:4096])
    if not m:
        return None
    try:
        return m.group(1).decode("ascii", "ignore") or None
    except Exception:
        return None


def decode_html(raw: bytes, header_charset: str | None = None) -> str:
    """Bytes -> str, never raising: undecodable bytes become U+FFFD."""
    enc = sniff_charset(raw, header_charset)
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


# ---- the tolerant element tree ----------------------------------------------


class _Node:
    """One element. `items` keeps text and child elements interleaved in
    document order, which is what lets the renderer emit loose text sitting
    between two `<p>`s without reordering the article."""

    __slots__ = ("_tc", "attrs", "final", "items", "line", "parent", "score", "tag")

    def __init__(
        self, tag: str, attrs: dict[str, str], parent: _Node | None, line: int = 0
    ) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.line = line
        self.items: list[tuple[str, Any]] = []
        self.score: float | None = None
        self.final: float | None = None
        self._tc: tuple[str, str] | None = None  # (text, link_text) memo

    # -- derived text (memoized: batch mode walks these repeatedly) ----------
    def _compute(self) -> tuple[str, str]:
        text: list[str] = []
        links: list[str] = []
        for kind, val in self.items:
            if kind == "text":
                text.append(val)
            else:
                t, lt = val.parts()
                text.append(t)
                links.append(t if val.tag == "a" else lt)
        return "".join(text), "".join(links)

    def parts(self) -> tuple[str, str]:
        if self._tc is None:
            self._tc = self._compute()
        return self._tc

    @property
    def text(self) -> str:
        return self.parts()[0]

    @property
    def link_text(self) -> str:
        return self.parts()[1]

    def describe(self) -> str:
        """tag#id.class — the human/agent-readable identity of the winner."""
        out = self.tag
        node_id = _ws(self.attrs.get("id"))
        if node_id:
            out += "#" + node_id.replace(" ", "-")
        cls = _ws(self.attrs.get("class"))
        if cls:
            out += "." + ".".join(cls.split())
        return out

    def children(self) -> list[_Node]:
        return [v for kind, v in self.items if kind == "node"]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<_Node {self.describe()} score={self.score}>"


def link_density(node: _Node) -> float:
    """Anchor chars / total chars in [0, 1]. The single most useful signal in
    the whole scorer: it is what separates prose from a list of links."""
    text = _ws(node.text)
    if not text:
        return 0.0
    return min(1.0, len(_ws(node.link_text)) / len(text))


class _Document(HTMLParser):
    """Single-pass tree builder + metadata collector (html.parser never chokes
    on soup, so `feed` is wrapped by the caller and partial trees are fine)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("[document]", {}, None)
        self.stack: list[_Node] = [self.root]
        self.removed: dict[str, int] = {}
        self.meta: dict[str, str] = {}
        self.lang: str | None = None
        self.json_ld: list[Any] = []
        self.h1s: list[str] = []
        self.times: list[dict[str, str]] = []
        self.bylines: list[str] = []
        self.rel_authors: list[str] = []
        self.title_tag: str | None = None
        self._title_parts: list[str] = []
        self._in_title = False
        self._raw_depth = 0
        self._ld_parts: list[str] | None = None
        # capture frames: (node, kind) finalized when the node is popped
        self._captures: list[tuple[_Node, str]] = []

    # -- capture bookkeeping -------------------------------------------------
    def _maybe_capture(self, node: _Node, tag: str, a: dict[str, str]) -> None:
        rel = (a.get("rel") or "").lower().split()
        item = (a.get("itemprop") or "").lower()
        blob = f"{a.get('class') or ''} {a.get('id') or ''}"
        if tag == "h1":
            self._captures.append((node, "h1"))
        elif tag == "time":
            self._captures.append((node, "time"))
        elif tag == "a" and "author" in rel:
            self._captures.append((node, "rel-author"))
        elif item in ("author", "creator") or (
            tag not in ("a",) and _BYLINE_ATTR_RE.search(blob)
        ):
            self._captures.append((node, "byline"))

    def _finalize(self, node: _Node) -> None:
        while self._captures and self._captures[-1][0] is node:
            _, kind = self._captures.pop()
            text = _ws(node.text)
            if kind == "h1":
                if text:
                    self.h1s.append(text)
            elif kind == "time":
                self.times.append(
                    {
                        "datetime": _ws(node.attrs.get("datetime")),
                        "text": text,
                        "itemprop": (node.attrs.get("itemprop") or "").lower(),
                        "pubdate": "pubdate" if "pubdate" in node.attrs else "",
                    }
                )
            elif kind in ("byline", "rel-author") and text:
                self.bylines.append(text)
                if kind == "rel-author":
                    self.rel_authors.append(text)

    # -- HTMLParser hooks ----------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        line = self.getpos()[0]

        if tag == "html" and a.get("lang") and not self.lang:
            self.lang = _ws(a["lang"])
        elif tag == "meta":
            self._meta(a)
        elif tag == "link":
            if "author" in (a.get("rel") or "").lower().split() and a.get("title"):
                self.bylines.append(_ws(a["title"]))
        elif tag == "title" and not self._title_parts and self._raw_depth == 0:
            self._in_title = True  # an <svg><title> is a tooltip, not the page
        elif tag == "script" and (a.get("type") or "").lower().strip() == (
            "application/ld+json"
        ):
            self._ld_parts = []

        if tag in VOID_TAGS:
            # void elements carry attributes we may want (img/meta) but never
            # children — record and move on, no stack churn
            if tag in KEEP_VOID_TAGS and tag not in DROP_TAGS:
                node = _Node(tag, a, self.stack[-1], line)
                self.stack[-1].items.append(("node", node))
            return

        self._implicit_close(tag)
        parent = self.stack[-1]
        node = _Node(tag, a, parent, line)
        if tag in DROP_TAGS:
            self.removed[tag] = self.removed.get(tag, 0) + 1
        else:
            parent.items.append(("node", node))
        if tag in RAW_TAGS:
            self._raw_depth += 1
        self.stack.append(node)
        self._maybe_capture(node, tag, a)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            self.handle_starttag(tag, attrs)
            return
        # self-closed non-void (<div/>, <time ... />): open and immediately
        # close so the capture frame still fires
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            self.title_tag = _ws("".join(self._title_parts)) or None
        if tag == "script" and self._ld_parts is not None:
            self._flush_ld()
        if tag in VOID_TAGS:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                # implicit-close everything left open above the match
                for node in reversed(self.stack[i:]):
                    if node.tag in RAW_TAGS and self._raw_depth:
                        self._raw_depth -= 1
                    self._finalize(node)
                del self.stack[i:]
                return
        # stray end tag with no open match: ignore (tolerant by contract)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._ld_parts is not None:
            self._ld_parts.append(data)
            return
        if self._raw_depth:
            return  # css/js text is never content and is not worth storing
        self.stack[-1].items.append(("text", data))

    def close(self) -> None:
        """Finish the feed, then finalize every element left open (a truncated
        page must still yield its captured h1/byline/time)."""
        super().close()
        if self._ld_parts is not None:
            self._flush_ld()
        for node in reversed(self.stack[1:]):
            self._finalize(node)
        del self.stack[1:]

    # -- helpers -------------------------------------------------------------
    def _implicit_close(self, tag: str) -> None:
        """Close tags HTML lets you omit. `<p>a<p>b` must be two paragraphs,
        not a nested one, or the same text gets scored twice."""
        top = self.stack[-1].tag
        if top == "p" and tag not in INLINE_TAGS:
            self.handle_endtag("p")
            return
        closes = _IMPLICIT_CLOSE.get(tag)
        if closes and top in closes:
            self.handle_endtag(top)

    def _meta(self, a: dict[str, str]) -> None:
        key = (a.get("property") or a.get("name") or a.get("itemprop") or "").strip()
        content = _ws(a.get("content"))
        if not key or not content:
            return
        self.meta.setdefault(key.lower(), content)

    def _flush_ld(self) -> None:
        blob = "".join(self._ld_parts or [])
        self._ld_parts = None
        blob = blob.strip()
        if not blob:
            return
        try:
            self.json_ld.append(json.loads(blob))
        except (ValueError, TypeError):
            return  # a broken ld+json block is not an extraction failure


def parse_document(html: str) -> _Document:
    """Feed `html` through the tolerant parser. Never raises: a truncated or
    hostile document yields whatever tree was built before the trouble."""
    doc = _Document()
    try:
        doc.feed(html or "")
    except Exception:
        pass  # tolerant by contract, same doctrine as the seo/links parsers
    try:
        doc.close()
    except Exception:
        pass
    return doc


# ---- scoring ----------------------------------------------------------------


def _walk(node: _Node) -> Iterator[_Node]:
    for child in node.children():
        yield child
        yield from _walk(child)


def _class_weight(node: _Node) -> float:
    weight = 0.0
    for attr in ("class", "id"):
        val = node.attrs.get(attr) or ""
        if not val:
            continue
        if _POSITIVE_RE.search(val):
            weight += 25.0
        if _NEGATIVE_RE.search(val):
            weight -= 25.0
    return weight


def base_score(tag: str) -> float:
    """Readability's per-tag prior (semantic containers start ahead)."""
    return _BASE_SCORE.get(tag, 0.0)


def is_paragraph(node: _Node) -> bool:
    """A prose-bearing leaf: a real paragraph tag, or a container holding only
    inline children (the `<div>text</div>` shape half the web still ships)."""
    if node.tag in PARA_TAGS:
        return True
    if node.tag in PARA_CONTAINERS:
        return not any(
            kind == "node" and val.tag not in INLINE_TAGS for kind, val in node.items
        )
    return False


def prune_unlikely(root: _Node) -> int:
    """Drop chrome-by-class/id containers. Returns how many were dropped.

    Readability's rule: the class/id says sidebar/comment/share/promo AND no
    content-ish token rescues it. Structural elements (body/article/main) and
    anything holding a real `<article>` are never pruned — a wrapper named
    "page-header" must not be allowed to take the article with it.
    """
    dropped = 0
    protected: set[int] = set()
    for node in _walk(root):
        if node.tag in ("article", "main"):
            anc: _Node | None = node
            while anc is not None:  # never prune a wrapper around the article
                protected.add(id(anc))
                anc = anc.parent
    for node in list(_walk(root)):
        if node.tag in _NEVER_PRUNE or node.parent is None:
            continue
        if id(node) in protected:
            continue
        blob = f"{node.attrs.get('class') or ''} {node.attrs.get('id') or ''}"
        if not blob.strip():
            continue
        if not _UNLIKELY_RE.search(blob) or _MAYBE_RE.search(blob):
            continue
        parent = node.parent
        for i, (kind, val) in enumerate(parent.items):
            if kind == "node" and val is node:
                del parent.items[i]
                parent._tc = None
                dropped += 1
                break
    if dropped:
        for node in [root, *_walk(root)]:
            node._tc = None  # memos above a pruned node are now stale
    return dropped


def score_document(
    root: _Node, *, min_paragraph_chars: int = MIN_PARAGRAPH_CHARS
) -> list[_Node]:
    """Score every candidate container in place; return them in document order.

    Each qualifying paragraph hands its score to parent (full), grandparent
    (half) and great-grandparent (third) — nesting depth should not decide the
    winner. `final` folds in the link-density penalty.
    """
    candidates: list[_Node] = []
    for para in _walk(root):
        if not is_paragraph(para):
            continue
        inner = _ws(para.text)
        if len(inner) < min_paragraph_chars:
            continue
        gain = 1.0 + inner.count(",") + inner.count("，") + min(len(inner) // 100, 3)
        divisor = (1.0, 2.0, 3.0)
        anc = para.parent
        level = 0
        while anc is not None and level < 3:
            if anc.tag != "[document]":
                if anc.score is None:
                    anc.score = base_score(anc.tag) + _class_weight(anc)
                    candidates.append(anc)
                anc.score += gain / divisor[level]
            anc = anc.parent
            level += 1
    for cand in candidates:
        cand.final = (cand.score or 0.0) * (1.0 - link_density(cand))
    return candidates


def select_content(candidates: list[_Node]) -> tuple[_Node | None, list[_Node]]:
    """Winner + the siblings that clearly belong to the same article.

    Sibling inclusion is what recovers a lead paragraph or a pull quote that
    lives outside the top-scoring div: a sibling joins on score (>= 20% of the
    winner, floor 10) or on being a substantial, low-link `<p>`.
    """
    best: _Node | None = None
    for cand in candidates:
        if best is None or (cand.final or 0.0) > (best.final or 0.0):
            best = cand  # strict >: first max wins, so ties stay deterministic
    if best is None:
        return None, []
    parent = best.parent
    if parent is None or parent.tag == "[document]":
        return best, [best]
    threshold = max(10.0, (best.final or 0.0) * 0.2)
    content: list[_Node] = []
    for kind, sib in parent.items:
        if kind != "node":
            continue
        if sib is best:
            content.append(sib)
            continue
        if (sib.final or 0.0) >= threshold:
            content.append(sib)
            continue
        if sib.tag == "p":
            text = _ws(sib.text)
            if len(text) >= 80 and link_density(sib) < 0.25:
                content.append(sib)
    return best, content


# ---- rendering --------------------------------------------------------------


def _flush(buf: list[str], out: list[str]) -> None:
    text = _ws("".join(buf))
    buf.clear()
    if text:
        out.append(text)


def _render_node(node: _Node, out: list[str]) -> None:
    if node.tag == "pre":
        block = node.text.strip("\n")
        if block.strip():
            out.append(block)  # verbatim: code blocks are content, not prose
        return
    buf: list[str] = []
    for kind, val in node.items:
        if kind == "text":
            buf.append(val)
        elif val.tag == "br":
            buf.append(" ")
        elif val.tag in INLINE_TAGS:
            buf.append(val.text)
        else:
            _flush(buf, out)
            _render_node(val, out)
    _flush(buf, out)


def render_text(nodes: Iterable[_Node]) -> str:
    """Content nodes -> plain text: one blank line between blocks, `<pre>`
    verbatim, whitespace collapsed everywhere else, no HTML left behind."""
    out: list[str] = []
    for node in nodes:
        _render_node(node, out)
    return "\n\n".join(out)


# ---- metadata: JSON-LD ------------------------------------------------------


def _ld_nodes(blob: Any) -> Iterator[dict[str, Any]]:
    if isinstance(blob, list):
        for item in blob:
            yield from _ld_nodes(item)
        return
    if not isinstance(blob, dict):
        return
    yield blob
    for key in ("@graph", "mainEntity", "mainEntityOfPage"):
        if key in blob:
            yield from _ld_nodes(blob[key])


def _ld_types(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type") or node.get("type") or ""
    vals = raw if isinstance(raw, list) else [raw]
    return {str(v).strip().lower() for v in vals if v}


def _ld_name(value: Any) -> str | None:
    """author/creator can be a str, a dict with a name, or a list of either."""
    if isinstance(value, str):
        return _ws(value) or None
    if isinstance(value, dict):
        return _ws(value.get("name")) or None
    if isinstance(value, list):
        names = [n for n in (_ld_name(v) for v in value) if n]
        return ", ".join(names) or None
    return None


def json_ld_facts(blobs: list[Any]) -> dict[str, str]:
    """Pull headline/author/datePublished out of ld+json Article nodes.

    Non-article nodes are used only as a fallback, so a site-wide
    Organization/WebSite block can never supply the "author" of a story.
    """
    facts: dict[str, str] = {}
    fallback: dict[str, str] = {}
    for blob in blobs:
        for node in _ld_nodes(blob):
            target = facts if _ld_types(node) & _LD_ARTICLE_TYPES else fallback
            headline = _ws(node.get("headline") or node.get("name"))
            if headline and "headline" not in target:
                target["headline"] = headline
            author = _ld_name(node.get("author") or node.get("creator"))
            if author and "author" not in target:
                target["author"] = author
            published = _ws(
                node.get("datePublished")
                or node.get("dateCreated")
                or node.get("dateModified")
            )
            if published and "published" not in target:
                target["published"] = published
    for key, val in fallback.items():
        facts.setdefault(key, val)
    return facts


# ---- metadata: title / byline / date ---------------------------------------


def _strip_site(title: str, site_name: str | None) -> str:
    if not site_name:
        return title
    site = _ws(site_name)
    if not site:
        return title
    low = title.lower()
    for sep in _TITLE_SEPS:
        tail = (sep + site).lower()
        if low.endswith(tail) and len(title) > len(tail):
            return title[: -len(tail)].strip()
    return title


def clean_title(
    raw: str | None, *, site_name: str | None = None, h1: str | None = None
) -> str | None:
    """`<title>` -> headline: drop the site suffix, split on the separator, and
    let a multi-word `<h1>` that reproduces part of the title win (it is the
    headline without the chrome the `<title>` tag carries)."""
    title = _strip_site(_ws(raw), site_name)
    if not title:
        return _ws(h1) or None
    best = title
    for sep in _TITLE_SEPS:
        if sep in title:
            head, _, tail = title.rpartition(sep)
            head, tail = head.strip(), tail.strip()
            if len(head.split()) >= 3:
                best = head
            elif len(tail.split()) >= 3:
                best = tail
            break
    heading = _ws(h1)
    if heading and len(heading.split()) >= 2 and heading.lower() in title.lower():
        # the h1 wins only when it is at least as specific as the split result,
        # or when the split failed and chrome is still attached
        if len(heading) >= len(best) or any(sep in best for sep in _TITLE_SEPS):
            best = heading
    return best or None


def clean_byline(raw: str | None) -> str | None:
    """Strip the "By "/"Posted by" prefix and trailing separators; reject
    anything that is plainly not a name (a URL, a date, a paragraph)."""
    text = _ws(raw)
    if not text:
        return None
    text = _ws(_BY_PREFIX_RE.sub("", text)).strip(" ,|·—–-/")
    text = _ws(text)
    if not text or len(text) > 120:
        return None
    low = text.lower()
    if "http://" in low or "https://" in low:
        return None
    if normalize_date(text):
        return None  # a dateline is not a byline
    return text


def _ymd(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_date(raw: str | None) -> str | None:
    """Any publication timestamp -> "YYYY-MM-DD", or None.

    Day granularity on purpose: a corpus filters and sorts by day, and the full
    original string is kept alongside as `date_raw`. Locale-independent by
    construction — own month table plus email.utils.parsedate_tz, never
    strptime("%B"), whose meaning depends on the machine's LC_TIME.
    """
    text = _ws(raw)
    if not text or len(text) > 64:
        return None
    m = _ISO_DATE_RE.match(text)
    if m:
        return _ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _COMPACT_DATE_RE.match(text)
    if m:
        return _ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _TEXT_DATE_RE.match(text)
    if m:
        day = m.group(1) or m.group(4)
        month = (m.group(2) or m.group(3) or "").lower()
        if month in _MONTHS:
            return _ymd(int(m.group(5)), _MONTHS[month], int(day))
    parsed = parsedate_tz(text)  # RFC 2822: "Tue, 05 Mar 2026 09:00:00 GMT"
    if parsed:
        return _ymd(parsed[0], parsed[1], parsed[2])
    m = re.match(r"^(\d{10})(?:\d{3})?$", text)  # unix seconds / millis
    if m:
        try:
            return date.fromtimestamp(int(m.group(1))).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    return None


def _pick_title(doc: _Document, ld: dict[str, str]) -> tuple[str | None, str]:
    site = doc.meta.get("og:site_name")
    h1 = doc.h1s[0] if len(doc.h1s) == 1 else None
    headline = ld.get("headline")
    if headline and 4 <= len(headline) <= 250:
        return _strip_site(headline, site), "json-ld:headline"
    for key in _TITLE_META:
        val = doc.meta.get(key)
        if val:
            return _strip_site(val, site), f"meta:{key}"
    cleaned = clean_title(doc.title_tag, site_name=site, h1=h1)
    if cleaned:
        return cleaned, "title-tag"
    if doc.h1s:
        return doc.h1s[0], "h1"
    return None, "none"


def _pick_byline(doc: _Document, ld: dict[str, str]) -> tuple[str | None, str]:
    author = clean_byline(ld.get("author"))
    if author:
        return author, "json-ld:author"
    for key in _BYLINE_META:
        val = clean_byline(doc.meta.get(key))
        if val:
            return val, f"meta:{key}"
    for val in doc.rel_authors:
        cleaned = clean_byline(val)
        if cleaned:
            return cleaned, "rel=author"
    for val in doc.bylines:
        cleaned = clean_byline(val)
        if cleaned:
            return cleaned, "byline-class"
    return None, "none"


def _pick_date(
    doc: _Document, ld: dict[str, str]
) -> tuple[str | None, str, str | None]:
    published = ld.get("published")
    if published and normalize_date(published):
        return normalize_date(published), "json-ld:datePublished", published
    for key in _DATE_META:
        val = doc.meta.get(key)
        if val and normalize_date(val):
            return normalize_date(val), f"meta:{key}", val
    # <time>: a pubdate/itemprop-marked element outranks a bare one
    ranked = sorted(
        doc.times,
        key=lambda t: 0 if (t["pubdate"] or "publish" in t["itemprop"]) else 1,
    )
    for t in ranked:
        for raw in (t["datetime"], t["text"]):
            if raw and normalize_date(raw):
                return normalize_date(raw), "time", raw
    return None, "none", None


# ---- the public extraction entry point --------------------------------------


def extract(
    html: str,
    *,
    url: str | None = None,
    source: str | None = None,
    min_paragraph_chars: int = MIN_PARAGRAPH_CHARS,
) -> dict[str, Any]:
    """One HTML document -> the article record. Pure: no I/O, never raises.

    Returns title/byline/date/text/word_count (the contract the CLI prints)
    plus the provenance a research corpus needs to be audited later: which rule
    produced each field, which block won and with what score/link-density, and
    what was thrown away.
    """
    doc = parse_document(html)
    pruned = prune_unlikely(doc.root)
    candidates = score_document(doc.root, min_paragraph_chars=min_paragraph_chars)
    best, content = select_content(candidates)
    if not content:
        # no scoring candidate survived (a stub page, or all chrome): fall back
        # to the whole cleaned tree rather than emitting nothing
        content = [doc.root]
    text = render_text(content)
    ld = json_ld_facts(doc.json_ld)
    title, title_source = _pick_title(doc, ld)
    byline, byline_source = _pick_byline(doc, ld)
    date_iso, date_source, date_raw = _pick_date(doc, ld)
    removed = dict(sorted(doc.removed.items()))
    if pruned:
        removed["unlikely-class"] = pruned
    return {
        "source": source or url or STDIN_SOURCE,
        "url": url,
        "title": title,
        "title_source": title_source,
        "byline": byline,
        "byline_source": byline_source,
        "date": date_iso,
        "date_source": date_source,
        "date_raw": date_raw,
        "text": text,
        "word_count": word_count(text),
        "chars": len(text),
        "excerpt": text[:280].strip(),
        "language": doc.lang or doc.meta.get("og:locale") or None,
        "site_name": doc.meta.get("og:site_name"),
        "content_hash": content_hash(html),
        "candidate": best.describe() if best is not None else None,
        "candidate_score": round(best.final, 2) if best is not None else None,
        "link_density": round(
            link_density(content[0]) if len(content) == 1 else _blocks_density(content),
            3,
        ),
        "blocks": len(content),
        "removed": removed,
    }


def _blocks_density(nodes: list[_Node]) -> float:
    text = "".join(_ws(n.text) for n in nodes)
    links = "".join(_ws(n.link_text) for n in nodes)
    return min(1.0, len(links) / len(text)) if text else 0.0


# ---- family diagnostics -----------------------------------------------------


def to_diagnostics(
    results: list[dict[str, Any]],
    *,
    thin_words: int = THIN_WORDS,
    max_link_density: float = MAX_LINK_DENSITY,
) -> list[dict[str, Any]]:
    """Map extraction quality onto the openswap diagnostic schema, so
    `--fail-on` gates a bad ingest exactly like a prose lint or a cert error.

    An empty extraction is an ERROR (the pipeline would ingest nothing); thin or
    link-heavy content is a WARNING (probably a landing page or a link rail); a
    missing title/date is a SUGGESTION (usable, just less citable).
    """
    diags: list[dict[str, Any]] = []
    for res in results:
        path = res.get("url") or res.get("source") or STDIN_SOURCE
        words = int(res.get("word_count") or 0)
        if words == 0:
            diags.append(
                openswap.diagnostic(
                    path=path,
                    line=1,
                    rule="extract:no-content",
                    severity="error",
                    message="no article text extracted",
                    suggestion="check the page is HTML (not a JS shell or a PDF)",
                    source="extract",
                )
            )
        elif words < thin_words:
            diags.append(
                openswap.diagnostic(
                    path=path,
                    line=1,
                    rule="extract:thin-content",
                    severity="warning",
                    message=f"only {words} words extracted (< {thin_words})",
                    suggestion="likely an index/landing page, not an article",
                    source="extract",
                )
            )
        density = float(res.get("link_density") or 0.0)
        if words and density > max_link_density:
            diags.append(
                openswap.diagnostic(
                    path=path,
                    line=1,
                    rule="extract:link-heavy",
                    severity="warning",
                    message=f"link density {density:.2f} > {max_link_density:.2f}",
                    suggestion="the winning block may be a link rail, not prose",
                    source="extract",
                )
            )
        if not res.get("title"):
            diags.append(
                openswap.diagnostic(
                    path=path,
                    line=1,
                    rule="extract:no-title",
                    severity="suggestion",
                    message="no title found",
                    suggestion="page ships no og:title/<title>/<h1>",
                    source="extract",
                )
            )
        if not res.get("date"):
            diags.append(
                openswap.diagnostic(
                    path=path,
                    line=1,
                    rule="extract:no-date",
                    severity="suggestion",
                    message="no publication date found",
                    suggestion="undated source — cite with the access date",
                    source="extract",
                )
            )
    return openswap.sort_diagnostics(diags)


# ---- corpus ledger ----------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    url TEXT,
    ts REAL NOT NULL,
    title TEXT,
    byline TEXT,
    date TEXT,
    language TEXT,
    word_count INTEGER NOT NULL DEFAULT 0,
    chars INTEGER NOT NULL DEFAULT 0,
    link_density REAL,
    candidate TEXT,
    text TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source, id);
CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(date, id);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_DOC_COLUMNS = (
    "id",
    "content_hash",
    "source",
    "url",
    "ts",
    "title",
    "byline",
    "date",
    "language",
    "word_count",
    "chars",
    "link_density",
    "candidate",
)


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the corpus ledger.

    Its own file, NOT the shared uptime ledger: ingestion writes are bursty and
    text-heavy, and must never contend with monitoring probes for the same
    sqlite write lock (the glitch #8 doctrine).
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


def record_document(
    conn: sqlite3.Connection, result: dict[str, Any], *, ts: float | None = None
) -> int:
    """Upsert one extraction, keyed by content hash. Re-ingesting the same bytes
    refreshes ts/source instead of growing a duplicate row."""
    now = time.time() if ts is None else float(ts)
    conn.execute(
        "INSERT INTO documents(content_hash, source, url, ts, title, byline, date,"
        " language, word_count, chars, link_density, candidate, text)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(content_hash) DO UPDATE SET ts=excluded.ts,"
        " source=excluded.source, url=excluded.url",
        (
            result.get("content_hash") or content_hash(result.get("text")),
            result.get("source") or STDIN_SOURCE,
            result.get("url"),
            now,
            result.get("title"),
            result.get("byline"),
            result.get("date"),
            result.get("language"),
            int(result.get("word_count") or 0),
            int(result.get("chars") or 0),
            result.get("link_density"),
            result.get("candidate"),
            result.get("text") or "",
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM documents WHERE content_hash = ?",
        (result.get("content_hash") or content_hash(result.get("text")),),
    ).fetchone()
    return int(row["id"])


def cached_document(conn: sqlite3.Connection, hash_hex: str) -> dict[str, Any] | None:
    """A previously parsed document, shaped like an `extract()` result."""
    row = conn.execute(
        "SELECT * FROM documents WHERE content_hash = ?", (hash_hex,)
    ).fetchone()
    if row is None:
        return None
    out = {k: row[k] for k in _DOC_COLUMNS}
    out["text"] = row["text"]
    out["excerpt"] = (row["text"] or "")[:280].strip()
    return out


def recent_documents(
    conn: sqlite3.Connection, *, limit: int = 20, source: str | None = None
) -> list[dict[str, Any]]:
    """Newest-first corpus rows WITHOUT the text bodies (a listing, not a dump).

    The body is dropped in Python rather than by naming columns in the SQL, so
    the query stays a constant string with bound parameters only.
    """
    if source:
        rows = conn.execute(
            "SELECT * FROM documents WHERE source = ? ORDER BY id DESC LIMIT ?",
            (source, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [{k: r[k] for k in _DOC_COLUMNS} for r in rows]


def document_text(conn: sqlite3.Connection, doc_id: int) -> dict[str, Any] | None:
    """One stored document including its text (the re-read path)."""
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (int(doc_id),)
    ).fetchone()
    if row is None:
        return None
    out = {k: row[k] for k in _DOC_COLUMNS}
    out["text"] = row["text"]
    return out


def corpus_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Ingestion rollup — the number a daily research loop actually watches."""
    row = conn.execute(
        "SELECT COUNT(*) AS documents, COALESCE(SUM(word_count), 0) AS words,"
        " COALESCE(SUM(chars), 0) AS chars, COUNT(DISTINCT source) AS sources,"
        " SUM(CASE WHEN title IS NOT NULL AND title <> '' THEN 1 ELSE 0 END) AS titled,"
        " SUM(CASE WHEN date IS NOT NULL AND date <> '' THEN 1 ELSE 0 END) AS dated,"
        " MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM documents"
    ).fetchone()
    out = dict(row)
    docs = int(out["documents"] or 0)
    out["titled"] = int(out["titled"] or 0)
    out["dated"] = int(out["dated"] or 0)
    out["avg_words"] = round((out["words"] or 0) / docs, 1) if docs else 0.0
    return out


# ---- batch ------------------------------------------------------------------


def run_batch(
    conn: sqlite3.Connection,
    sources: Iterable[str],
    fetch: Callable[[str], dict[str, Any]],
    *,
    record: bool = True,
    use_cache: bool = True,
    ts: float | None = None,
    min_paragraph_chars: int = MIN_PARAGRAPH_CHARS,
) -> dict[str, Any]:
    """Extract many sources in INPUT ORDER, skipping bytes already in the ledger.

    `fetch(source) -> {"html": str, "url": str | None, "error": str | None}` is
    the injected I/O boundary: the CLI reads files / GETs URLs (concurrently if
    it likes) and this loop stays pure and ordered, which is why the whole batch
    path is testable offline. A fetch failure is recorded and the batch
    continues — one dead URL must not abort a night's ingestion.
    """
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    cached = 0
    for src in sources:
        try:
            doc = fetch(src) or {}
        except Exception as e:  # a fetcher bug is a row, not a crashed batch
            failures.append({"source": src, "error": f"{type(e).__name__}: {e}"})
            continue
        if doc.get("error"):
            failures.append({"source": src, "error": str(doc["error"])})
            continue
        html = doc.get("html") or ""
        hash_hex = content_hash(html)
        hit = cached_document(conn, hash_hex) if use_cache else None
        if hit is not None:
            hit["cached"] = True
            # `source` is where these bytes were FIRST seen; `requested` is what
            # this run asked for, so the report still maps row-for-row to input
            hit["requested"] = src
            results.append(hit)
            cached += 1
            continue
        res = extract(
            html,
            url=doc.get("url"),
            source=src,
            min_paragraph_chars=min_paragraph_chars,
        )
        res["cached"] = False
        res["requested"] = src
        if record:
            res["id"] = record_document(conn, res, ts=ts)
        results.append(res)
    return {
        "results": results,
        "failures": failures,
        "cached": cached,
        "extracted": len(results) - cached,
        "failed": len(failures),
        "words": sum(int(r.get("word_count") or 0) for r in results),
    }
