# Solo personal project, no connection to employer, built with public/free-tier only
"""Searchindex — build-time site-search index (openswap #23: Algolia DocSearch).

Algolia's product is not "a search engine" — it is a HOSTED index plus a
JavaScript widget: you push your pages to their cluster, hold an API key, and
their CDN answers your visitors' keystrokes. This adapter deletes the cluster
and the key and keeps the widget: `scout searchindex build` reads the pages you
own, tokenizes them, and emits a STATIC ARTIFACT — sharded JSON posting lists
plus one dependency-free JS client — that you deploy next to the site. The
visitor's browser fetches the manifest and exactly the shards their query
routes to; nothing is sent anywhere, so "no query ever left the visitor" is
architectural, not a privacy policy.

Why this is NOT search #20 (which also names Algolia): #20 is a sqlite3 FTS5
database that only this box can query (Python + sqlite + the .db file). It
cannot ship. This one produces deployable bytes that a browser executes with no
server, no Python and no sqlite at runtime — the on-site search box. The two
share a corpus layer on purpose (`search.iter_files`, `search.read_document`)
rather than each growing its own walker.

The pipeline, all deterministic and all here:
- fold/tokenize/stem — NFKD fold, combining marks dropped, `[a-z0-9]+` runs,
  stopwords, and a guarded light stemmer (plurals + -ing/-ed with a 3-char
  minimum stem, so "user" never collapses into "use").
- extract_document — per-page fields. HTML title/description/h1/noindex come
  from seo #3's parse_page (reused, not re-implemented); body text comes from a
  boilerplate-aware html.parser pass; markdown gets front-matter and syntax
  stripped. A `noindex` page is EXCLUDED and says so.
- build_index — weighted per-field term scores (title 8, heading 4,
  description 3, path 2, body 1 by default; integers so a posting is byte-exact
  in JSON), first-character routing so a prefix query needs ONE shard, and a
  balanced route plan whose table ships in the manifest (the client never
  guesses where a term lives).
- render_files — every artifact byte, ready for the caller to write: sorted-key
  compact ASCII JSON with a trailing newline, sha256 per file, and a content
  fingerprint that EXCLUDES generated_utc, so "did the content change" and
  "when was it built" stay separable.
- rank — the BM25-ish ranking the JS client implements, in Python, so the
  ranking is testable without a browser. The client is a CONSTANT that reads
  every parameter (weights, k1/b, stopwords, routes, limits) from the manifest,
  so no number is duplicated; only the fold/stem/rank LOGIC is mirrored, and a
  node-present test runs the real JS against the real artifact to prove the two
  agree hit for hit.
- verify — re-hash what is on disk against the manifest, so a half-deployed or
  stale shard is a caught error rather than a silently empty search box.

Honesty rules this core keeps:
- The index alphabet is ASCII `[a-z0-9]` after folding. Latin diacritics fold
  in ("café" -> cafe); CJK/Cyrillic/Greek do NOT, so their characters are
  COUNTED per page and reported (`unsupported_chars` + a diagnostic), never
  silently dropped to make a build look clean.
- A page with no indexable term is reported (`empty-page`), and a build with no
  terms at all is an ERROR — an index that matches nothing is the silent no-op
  the family bans.
- `url` is only absolute when the caller supplies --base-url; otherwise it is
  the site-root-relative path, labelled `url_kind: "relative"`. No domain is
  ever invented.
- Every number in a report is measured. A skipped page carries its reason.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bigbang.core import ollama, openswap, prose, seo, sitemap

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

FORMAT = "scout-searchindex"
FORMAT_VERSION = "1"

INDEX_NAME = "searchindex.json"
CLIENT_NAME = "searchindex.js"
SHARD_PREFIX = "searchindex-"
SHARD_SUFFIX = ".json"

# Pages, not source: the extension set is DERIVED from the sibling adapters
# (prose #1 owns the prose list, seo #3 the HTML one) because a hand-copied
# extension list is exactly how links #4's DOC_EXTS drifted from seo.HTML_EXTS.
PAGE_EXTS: tuple[str, ...] = tuple(sorted({*prose.PROSE_EXTS, *seo.HTML_EXTS}))

# Query-time stopwords must match build-time stopwords or the client searches a
# vocabulary the index does not have, so there is ONE list. It is derived from
# ollama's English function-word list (same language, same purpose) plus the
# words a site's own chrome contributes on every page. The manifest carries the
# list's sha256, so an upstream edit shows up as a changed artifact instead of a
# silent re-ranking.
STOPWORDS: frozenset[str] = frozenset(
    {
        *ollama._STOPWORDS,  # one list for the whole tree, deliberately not retyped
        "home",
        "page",
        "site",
        "www",
        "http",
        "https",
        "html",
        "index",
        "skip",
        "content",
        "menu",
        "toggle",
    }
)

MIN_TERM_LEN = 2
# A 32+ character run is a base64 blob, a minified line or a hash — not a word
# anyone searches for, and one of them can outweigh a whole page.
MAX_TERM_LEN = 32
# The stemmer never leaves a stem shorter than this, which is what keeps
# use/used/using apart from "us" (a false merge is worse than a missed one).
MIN_STEM = 3

FIELDS: tuple[str, ...] = ("title", "heading", "description", "path", "body")
# Integers on purpose: a posting score is then an int, so the JSON is byte-exact
# and no float formatting difference can shift a shard's sha256.
DEFAULT_WEIGHTS: dict[str, int] = {
    "title": 8,
    "heading": 4,
    "description": 3,
    "path": 2,
    "body": 1,
}

DEFAULT_SHARDS = 8
EXCERPT_CHARS = 200
# Prefix expansion is capped so one-letter keystroke cannot pull a whole shard
# into the score accumulator.
PREFIX_LIMIT = 24
DEFAULT_LIMIT = 10

# BM25 knobs, shared with the generated client by injection (never retyped).
K1 = 1.2
B = 0.75

# Byte budgets: what a visitor DOWNLOADS is the cost this adapter is replacing,
# so exceeding them is reported rather than discovered in the field.
MANIFEST_BYTE_BUDGET = 512 * 1024
SHARD_BYTE_BUDGET = 256 * 1024

# Subtrees whose text is markup, not content. `title` is in the list because the
# title is already a FIELD (weight 8): leaving it in the body would score it
# twice and open every excerpt with a copy of the page's own title (measured on
# the demo corpus — "Pricing Pricing plans Widget pricing is...").
SKIP_TAGS: tuple[str, ...] = ("script", "style", "template", "noscript", "svg", "title")
# Site chrome repeats on every page; indexing it makes every page match every
# nav word. Dropped by default, restorable with keep_boilerplate=True.
BOILERPLATE_TAGS: tuple[str, ...] = ("nav", "footer")
# The per-page escape hatch: <div data-searchindex="skip"> ... </div>
SKIP_ATTR = "data-searchindex"
SKIP_ATTR_VALUE = "skip"

KIND_HTML = "html"
KIND_MARKDOWN = "markdown"
KIND_TEXT = "text"

_MARKS_STRIPPED = "combining marks dropped"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ASCII_TOKEN = re.compile(r"^[a-z0-9]+$")
_FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---[ \t]*\r?\n", re.DOTALL)
_MD_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_MD_FENCE_RE = re.compile(r"^[ \t]{0,3}(?:```|~~~).*?$", re.MULTILINE)
_MD_NOISE_RE = re.compile(r"[*_`>\[\]()!|]+")
_WS_RE = re.compile(r"\s+")

# Plural "-es" only drops after these endings (boxes, dishes, churches).
_ES_ENDINGS: tuple[str, ...] = ("s", "x", "z", "ch", "sh")
# Consonants collapsed after -ing/-ed (shipping -> shipp -> ship). 's' is
# excluded on purpose: "passing" -> "pass" must stay "pass".
_DOUBLED = "bdfglmnprt"
_VOWELS = "aeiouy"


# ---- tokenization -----------------------------------------------------------


def fold(text: Any) -> str:
    """NFKD-fold to lowercase with combining marks removed.

    This is the whole reason "café" and "cafe" are one term. Marks are stripped
    BEFORE tokenizing because a leftover U+0308 would split "coöperate" into
    "coo" + "perate". The generated JS client does the same two steps
    (`normalize("NFKD")` + `\\p{M}` removal), so both sides agree on Latin text
    by construction rather than by hope.
    """
    if text is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()


def tokenize(text: Any) -> list[str]:
    """Folded text -> `[a-z0-9]+` runs, in order. No stopwords, no stemming."""
    return _TOKEN_RE.findall(fold(text))


def unsupported_chars(text: Any) -> int:
    """Count alphanumeric characters that this index's alphabet cannot hold.

    CJK, Cyrillic, Greek, Hebrew, Devanagari: folding does not make them ASCII,
    so no token can contain them. Rule 5 of this family says a thing that cannot
    be measured is reported with a reason — so those characters are COUNTED and
    surfaced as a diagnostic instead of vanishing into a clean-looking build.
    """
    return sum(1 for ch in fold(text) if ch.isalnum() and not _ASCII_TOKEN.match(ch))


def _depluralize(w: str) -> str:
    """ONE plural reduction step, or `w` unchanged when no rule applies."""
    if w.endswith("sses"):
        return w[:-2]  # classes -> class
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"  # queries -> query
    if w.endswith("es") and len(w) > 4 and w[:-2].endswith(_ES_ENDINGS):
        return w[:-2]  # boxes -> box, dishes -> dish
    if w.endswith(("ss", "us", "is")):
        return w  # gloss, status, basis
    if w.endswith("s"):
        return w[:-1]  # pages -> page
    return w


def stem(word: str) -> str:
    """Guarded light stemmer: plurals, then -ing/-ed. Idempotent by design.

    Deliberately NOT Porter: -er/-ly/-ment merge unrelated words ("user"/"use",
    "family"/"fami") and a site search that answers the wrong page is worse than
    one that misses a conjugation. Every rule refuses to leave a stem shorter
    than MIN_STEM or one with no vowel, which is why "using" stays "using"
    (stripping would yield "us").

    The plural step runs to a FIXED POINT, which is what makes stem(stem(w)) ==
    stem(w) true rather than nearly true: "analyses" reduces to "analys", whose
    own trailing "s" a second call would have stripped — so the loop strips it
    now and both calls agree on "analy". Each pass shortens the word, so the loop
    always terminates.
    """
    w = str(word)
    while len(w) > MIN_STEM:
        reduced = _depluralize(w)
        if reduced == w:
            break
        w = reduced
    if len(w) > MIN_STEM:
        if w.endswith("ing") and _stemmable(w[:-3]):
            w = _collapse(w[:-3])
        elif w.endswith("ed") and _stemmable(w[:-2]):
            w = _collapse(w[:-2])
    return w


def _stemmable(candidate: str) -> bool:
    return len(candidate) >= MIN_STEM and any(v in candidate for v in _VOWELS)


def _collapse(candidate: str) -> str:
    if (
        len(candidate) > MIN_STEM
        and candidate[-1] == candidate[-2]
        and candidate[-1] in _DOUBLED
    ):
        return candidate[:-1]
    return candidate


def terms(
    text: Any,
    *,
    stemming: bool = True,
    stopwords: frozenset[str] | None = None,
    min_len: int = MIN_TERM_LEN,
    max_len: int = MAX_TERM_LEN,
) -> tuple[list[str], dict[str, int]]:
    """Text -> (index terms in order, counts of what was dropped and why).

    The second element is why this returns a tuple: "3,412 tokens became 1,890
    terms" is only auditable if the 1,522 losses are attributed (stopword /
    too-short / too-long). Stopwords are filtered on the RAW token, before
    stemming, so the list stays a list of words rather than of stems.
    """
    stops = STOPWORDS if stopwords is None else stopwords
    dropped = {"stopword": 0, "too_short": 0, "too_long": 0}
    out: list[str] = []
    for token in tokenize(text):
        if token in stops:
            dropped["stopword"] += 1
            continue
        if len(token) < min_len:
            dropped["too_short"] += 1
            continue
        if len(token) > max_len:
            dropped["too_long"] += 1
            continue
        out.append(stem(token) if stemming else token)
    return out, dropped


def query_terms(
    text: Any,
    *,
    stemming: bool = True,
    stopwords: frozenset[str] | None = None,
    min_len: int = MIN_TERM_LEN,
    max_len: int = MAX_TERM_LEN,
) -> list[str]:
    """A query string -> deduped index terms, first occurrence order kept."""
    found, _dropped = terms(
        text, stemming=stemming, stopwords=stopwords, min_len=min_len, max_len=max_len
    )
    seen: set[str] = set()
    out: list[str] = []
    for t in found:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ---- page extraction --------------------------------------------------------


class _BodyText(HTMLParser):
    """Collect visible text, skipping markup subtrees and (by default) chrome.

    seo #3's _PageParser already extracts the FACTS (title, description, h1,
    robots) and is reused for them; it deliberately discards body text, so this
    adds only the missing piece instead of forking it. Block-level tags emit a
    space so "</p><p>" cannot weld two words into one token.
    """

    def __init__(self, *, keep_boilerplate: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipped_subtrees = 0
        self._skip_depth = 0
        self._skip_tag: str | None = None
        self._drop = set(SKIP_TAGS) | (set() if keep_boilerplate else set(BOILERPLATE_TAGS))

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._skip_tag is not None:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        marked = dict(attrs).get(SKIP_ATTR)
        if tag in self._drop or (marked or "").strip().lower() == SKIP_ATTR_VALUE:
            self._skip_tag = tag
            self._skip_depth = 1
            self.skipped_subtrees += 1
            return
        self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_tag is not None:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth <= 0:
                    self._skip_tag = None
            return
        self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_tag is None:
            self.parts.append(data)

    def text(self) -> str:
        return _WS_RE.sub(" ", "".join(self.parts)).strip()


def html_body_text(html_text: str, *, keep_boilerplate: bool = False) -> tuple[str, int]:
    """HTML -> (visible text, skipped subtree count). Never raises."""
    parser = _BodyText(keep_boilerplate=keep_boilerplate)
    try:
        parser.feed(html_text or "")
        parser.close()
    except Exception:  # tolerant by contract, exactly like seo.parse_page
        pass
    return parser.text(), parser.skipped_subtrees


def page_kind(rel: str) -> str:
    """Extension -> how to read the page. Unknown text is read as plain text."""
    suffix = Path(rel).suffix.lower()
    if suffix in seo.HTML_EXTS:
        return KIND_HTML
    if suffix in (".md", ".markdown"):
        return KIND_MARKDOWN
    return KIND_TEXT


def markdown_fields(text: str) -> tuple[str | None, list[str], str]:
    """Markdown -> (title, headings, body text).

    Front matter is dropped (YAML keys are not prose), fences and inline syntax
    are stripped, and the FIRST h1 is the title only if the document has one —
    a missing title stays None so the caller reports it instead of the index
    inventing a label from the filename.
    """
    body = _FRONTMATTER_RE.sub("", text or "")
    headings = [
        _WS_RE.sub(" ", m.group(2)).strip() for m in _MD_HEADING_RE.finditer(body)
    ]
    title = None
    for m in _MD_HEADING_RE.finditer(body):
        if len(m.group(1)) == 1:
            title = _WS_RE.sub(" ", m.group(2)).strip() or None
            break
    plain = _MD_FENCE_RE.sub(" ", body)
    plain = _MD_HEADING_RE.sub(lambda m: m.group(2), plain)
    plain = _MD_NOISE_RE.sub(" ", plain)
    return title, headings, _WS_RE.sub(" ", plain).strip()


def excerpt(text: str, *, chars: int = EXCERPT_CHARS) -> str:
    """A results-list preview: collapsed whitespace, cut on a word boundary."""
    flat = _WS_RE.sub(" ", str(text or "")).strip()
    if len(flat) <= chars:
        return flat
    cut = flat[:chars]
    head, sep, _tail = cut.rpartition(" ")
    return (head if sep and len(head) >= chars // 2 else cut).rstrip() + "…"


def extract_document(
    text: str,
    *,
    rel: str,
    url: str,
    keep_boilerplate: bool = False,
    excerpt_chars: int = EXCERPT_CHARS,
) -> dict[str, Any]:
    """One page's raw text -> the field dict build_index consumes.

    HTML facts come from seo.parse_page (one implementation of "what is this
    page's title/description/h1/robots" in the tree). `noindex` is carried, not
    acted on, so the caller can report the exclusion; a page the site tells
    robots to ignore must not surface in the site's own search box either.
    """
    kind = page_kind(rel)
    doc: dict[str, Any] = {
        "path": rel,
        "url": url,
        "kind": kind,
        "title": None,
        "description": None,
        "headings": [],
        "body": "",
        "noindex": False,
        "chars": len(text or ""),
        "skipped_subtrees": 0,
    }
    if kind == KIND_HTML:
        facts = seo.parse_page(text or "", url)
        body, skipped = html_body_text(text or "", keep_boilerplate=keep_boilerplate)
        doc.update(
            title=facts["title"],
            description=facts["description"] or None,
            headings=[h["text"] for h in facts["h1"] if h.get("text")],
            body=body,
            noindex=bool(facts["noindex"]),
            skipped_subtrees=skipped,
        )
    elif kind == KIND_MARKDOWN:
        title, headings, body = markdown_fields(text or "")
        doc.update(title=title, headings=headings, body=body)
    else:
        doc["body"] = _WS_RE.sub(" ", text or "").strip()
    doc["excerpt"] = excerpt(doc["body"] or doc["title"] or "", chars=excerpt_chars)
    return doc


def ext_globs(exts: Iterable[str] | None) -> list[str]:
    """['md', '.MD', '*.md'] -> ['*.md'] — an extension filter with NO wildcard.

    Windows-safety, measured on this box: click emulates cmd.exe by expanding an
    argv token that glob-matches files in the CWD BEFORE the parser sees it, so
    `--glob "*.html"` run from a directory containing index.html silently arrives
    as `--glob index.html` (quoting does not help — the shell is not the one
    expanding). `--ext html` carries no wildcard, so nothing can rewrite it.
    Lives in the core, not the CLI, so a test can pin the behaviour directly.
    """
    out: list[str] = []
    for raw in exts or ():
        if raw is None:
            continue  # str(None) would silently become the "*.none" filter
        ext = str(raw).strip().lstrip("*").lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        pattern = f"*{ext}"
        if pattern not in out:
            out.append(pattern)
    return out


def default_include() -> list[str]:
    """Include globs when the caller names none: the page-extension set."""
    return [f"*{ext}" for ext in PAGE_EXTS]


def url_for_rel(
    rel: str,
    *,
    base_url: str | None = None,
    strip_index: bool = True,
    clean_urls: bool = False,
) -> tuple[str, str]:
    """(url, url_kind) for a site-root-relative page path.

    With a base URL this is sitemap #10's url_for — the same index.html/clean-URL
    rules the sitemap and canonicals already use, so search results and the
    sitemap cannot disagree about a page's address. WITHOUT one, the result is
    the root-relative path labelled "relative": inventing a scheme and host
    would be fabricating the one field a visitor clicks.
    """
    if base_url:
        return (
            sitemap.url_for(
                rel,
                sitemap.normalize_base(base_url),
                strip_index=strip_index,
                clean_urls=clean_urls,
            ),
            "absolute",
        )
    relative = sitemap.url_for(
        rel, "/", strip_index=strip_index, clean_urls=clean_urls
    )
    return relative, "relative"


# ---- index construction -----------------------------------------------------


def shard_name(index: int) -> str:
    """Deterministic shard filename. Zero-padded so a listing sorts correctly."""
    return f"{SHARD_PREFIX}{int(index):03d}{SHARD_SUFFIX}"


def is_artifact_name(name: str) -> bool:
    """Does this filename belong to this adapter's artifact namespace?

    Used to spot ORPHANS: a shard left behind by a build that produced fewer
    shards is still served by the host and still fetched by a stale client, so
    `verify` reports it rather than letting a deploy rot quietly.
    """
    n = str(name)
    return n in (INDEX_NAME, CLIENT_NAME) or (
        n.startswith(SHARD_PREFIX) and n.endswith(SHARD_SUFFIX)
    )


def validate_weights(weights: dict[str, Any] | None) -> dict[str, int]:
    """Field weights -> validated ints. Raises rather than indexing nothing.

    All-zero weights would produce an empty index with a cheerful ok:true, which
    is the silent no-op the family bans — so it is a ValueError, as is an
    unknown field name (a mistyped --weight must not be ignored).
    """
    merged = dict(DEFAULT_WEIGHTS)
    for key, value in (weights or {}).items():
        if key not in DEFAULT_WEIGHTS:
            raise ValueError(f"unknown field {key!r} — weights are for {list(FIELDS)}")
        try:
            ivalue = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"weight for {key!r} must be an integer, got {value!r}"
            ) from exc
        if ivalue < 0:
            raise ValueError(f"weight for {key!r} must be >= 0, got {ivalue}")
        merged[key] = ivalue
    if not any(merged.values()):
        raise ValueError("at least one field weight must be > 0 or nothing is indexed")
    return merged


def plan_routes(bucket_counts: dict[str, int], shards: int) -> dict[str, int]:
    """First-character buckets -> shard index, balanced by posting count.

    Routing on the first character (not a hash) is what makes as-you-type prefix
    search correct with ONE fetch: every term starting with "t" is in the same
    shard, so expanding "tok" never needs the other shards. Hash routing would
    balance better and break prefix search — and `hash()` in particular is
    salted per process, so it could never appear in a reproducible artifact.

    The plan ships in the manifest, so the client reads the table instead of
    re-deriving it; rebalancing after a content change is therefore invisible to
    it. Buckets are walked in sorted order and a shard closes when adding the
    next bucket would land FURTHER from the target share than stopping does —
    best-fit rather than "close on overflow", which for {a:10, b:10, c:1, d:1}
    over two shards is the difference between 20/2 and 10/12. Each advance
    happens while placing a bucket, so no shard is ever left empty and the shard
    count never exceeds the bucket count.
    """
    if int(shards) < 1:
        raise ValueError(f"shards must be >= 1, got {shards!r}")
    buckets = sorted(bucket_counts.items())
    total = sum(count for _char, count in buckets)
    if not buckets or total <= 0:
        return {}
    limit = min(int(shards), len(buckets))
    share = total / limit
    routes: dict[str, int] = {}
    current, running = 0, 0
    for char, count in buckets:
        if (
            current < limit - 1
            and running > 0
            and abs(running + count - share) > abs(running - share)
        ):
            current += 1
            running = 0
        routes[char] = current
        running += count
    return routes


def _field_texts(doc: dict[str, Any]) -> dict[str, str]:
    """The five weighted fields of one page, as text."""
    return {
        "title": str(doc.get("title") or ""),
        "heading": " ".join(str(h) for h in (doc.get("headings") or [])),
        "description": str(doc.get("description") or ""),
        # the path is curated vocabulary ("docs/pricing.html" -> pricing), the
        # same reason search #20 weights its path column above its body column
        "path": str(doc.get("path") or "").replace("/", " ").replace("-", " "),
        "body": str(doc.get("body") or ""),
    }


def score_document(
    doc: dict[str, Any],
    *,
    weights: dict[str, int],
    stemming: bool = True,
    stopwords: frozenset[str] | None = None,
    min_len: int = MIN_TERM_LEN,
    max_len: int = MAX_TERM_LEN,
) -> dict[str, Any]:
    """One page -> {term: weighted int score}, its length, and its losses.

    The score is sum(field_weight * occurrences) as an INTEGER: floats would put
    formatting differences into the shard bytes and therefore into its sha256.
    `length` is the unweighted term count — BM25's document length, so a long
    page does not out-rank a focused one just by repeating a word.
    """
    scores: dict[str, int] = {}
    length = 0
    dropped = {"stopword": 0, "too_short": 0, "too_long": 0}
    per_field: dict[str, int] = {}
    fields = _field_texts(doc)
    for field, text in fields.items():
        weight = int(weights.get(field, 0))
        found, lost = terms(
            text,
            stemming=stemming,
            stopwords=stopwords,
            min_len=min_len,
            max_len=max_len,
        )
        for key in dropped:
            dropped[key] += lost[key]
        per_field[field] = len(found)
        length += len(found)
        if weight <= 0:
            continue
        for term in found:
            scores[term] = scores.get(term, 0) + weight
    return {
        "scores": scores,
        "length": length,
        "dropped": dropped,
        "field_terms": per_field,
        "unsupported": unsupported_chars(" ".join(fields.values())),
    }


def stopword_provenance(stopwords: frozenset[str] | None = None) -> dict[str, Any]:
    """{count, sha256, words} for the stopword list actually used.

    The words ship because the CLIENT must drop exactly what the build dropped —
    a query-time list that has drifted searches a vocabulary the index does not
    have. The hash is the audit: the list is DERIVED from ollama's, so an edit
    there would otherwise silently re-rank every site; carrying its fingerprint
    turns that into a visible artifact change.
    """
    words = sorted(STOPWORDS if stopwords is None else stopwords)
    digest = hashlib.sha256("\n".join(words).encode("utf-8")).hexdigest()
    return {"count": len(words), "sha256": digest, "words": words}


def build_index(
    documents: Iterable[dict[str, Any]],
    *,
    shards: int = DEFAULT_SHARDS,
    weights: dict[str, Any] | None = None,
    stemming: bool = True,
    stopwords: frozenset[str] | None = None,
    min_len: int = MIN_TERM_LEN,
    max_len: int = MAX_TERM_LEN,
    include_noindex: bool = False,
    site: str | None = None,
    url_kind: str = "relative",
) -> dict[str, Any]:
    """Extracted pages -> the routed, sharded index (bytes come from render_files).

    Deterministic in document order: ids are assigned in the order given (the
    CLI hands them over sorted by path), postings are sorted by (-score, id) so
    the strongest page for a term comes first, and every dict written out is
    key-sorted at dump time. A noindex page is EXCLUDED by default and appears in
    the report's `skipped` list with that reason — a page the site tells crawlers
    to ignore must not surface in the site's own search box either.
    """
    wts = validate_weights(weights)
    docs: list[dict[str, Any]] = []
    postings: dict[str, dict[int, int]] = {}
    skipped: list[dict[str, str]] = []
    empty: list[str] = []
    untitled: list[str] = []
    unsupported: list[dict[str, Any]] = []
    dropped_terms = {"stopword": 0, "too_short": 0, "too_long": 0}
    seen_urls: dict[str, list[str]] = {}
    pages_seen = 0

    for doc in documents:
        pages_seen += 1
        rel = str(doc.get("path") or "")
        if doc.get("noindex") and not include_noindex:
            skipped.append({"path": rel, "reason": "noindex"})
            continue
        scored = score_document(
            doc,
            weights=wts,
            stemming=stemming,
            stopwords=stopwords,
            min_len=min_len,
            max_len=max_len,
        )
        for key in dropped_terms:
            dropped_terms[key] += scored["dropped"][key]
        doc_id = len(docs)
        for term, score in scored["scores"].items():
            postings.setdefault(term, {})[doc_id] = score
        if not scored["scores"]:
            empty.append(rel)
        if not doc.get("title"):
            untitled.append(rel)
        if scored["unsupported"]:
            unsupported.append({"path": rel, "chars": int(scored["unsupported"])})
        seen_urls.setdefault(str(doc.get("url") or ""), []).append(rel)
        docs.append(
            {
                "id": doc_id,
                "path": rel,
                "url": str(doc.get("url") or ""),
                "title": doc.get("title") or None,
                "excerpt": str(doc.get("excerpt") or ""),
                "terms": int(scored["length"]),
                "kind": str(doc.get("kind") or KIND_TEXT),
            }
        )

    bucket_counts: dict[str, int] = {}
    for term, plist in postings.items():
        bucket_counts[term[0]] = bucket_counts.get(term[0], 0) + len(plist)
    routes = plan_routes(bucket_counts, shards)
    shard_count = (max(routes.values()) + 1) if routes else 0
    shard_terms: list[dict[str, list[list[int]]]] = [{} for _i in range(shard_count)]
    for term in sorted(postings):
        plist = postings[term]
        shard_terms[routes[term[0]]][term] = [
            [doc_id, plist[doc_id]]
            for doc_id in sorted(plist, key=lambda d: (-plist[d], d))
        ]

    lengths = [int(d["terms"]) for d in docs]
    manifest: dict[str, Any] = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "site": site or None,
        "url_kind": str(url_kind),
        "client": CLIENT_NAME,
        "doc_count": len(docs),
        "term_count": len(postings),
        "posting_count": sum(len(p) for p in postings.values()),
        "avg_terms": round(sum(lengths) / len(lengths), 6) if lengths else 0.0,
        "weights": dict(sorted(wts.items())),
        "stemming": bool(stemming),
        "stopwords": stopword_provenance(stopwords),
        "min_len": int(min_len),
        "max_len": int(max_len),
        "k1": K1,
        "b": B,
        "prefix_limit": PREFIX_LIMIT,
        "routes": routes,
        "shards": [
            {"name": shard_name(i), "terms": len(shard_terms[i])}
            for i in range(shard_count)
        ],
        "docs": docs,
    }
    report = {
        "pages_seen": pages_seen,
        "documents": len(docs),
        "terms": len(postings),
        "postings": manifest["posting_count"],
        "shard_count": shard_count,
        "skipped": skipped,
        "empty_pages": sorted(empty),
        "untitled_pages": sorted(untitled),
        "unsupported_pages": sorted(unsupported, key=lambda u: u["path"]),
        "duplicate_urls": [
            {"url": url, "paths": sorted(paths)}
            for url, paths in sorted(seen_urls.items())
            if len(paths) > 1
        ],
        "dropped_terms": dropped_terms,
    }
    return {"manifest": manifest, "shards": shard_terms, "report": report}


def shard_loader(index: dict[str, Any]) -> Callable[[str], dict[str, Any]]:
    """In-memory loader for rank(): shard filename -> its term table.

    Same shape as the browser's `load` callback and the CLI's file reader, so
    ranking has exactly one implementation and the tests exercise the real one.
    """
    names = {s["name"]: i for i, s in enumerate(index["manifest"]["shards"])}
    shards = index["shards"]

    def load(name: str) -> dict[str, Any]:
        return shards[names[name]] if name in names else {}

    return load


# ---- artifact bytes ---------------------------------------------------------


def dump_bytes(obj: Any) -> bytes:
    """The one canonical artifact encoding: sorted keys, no spaces, ASCII, \\n.

    write_bytes + an explicit trailing "\\n" instead of write_text: on Windows
    write_text turns every newline into CRLF, so the file would not match its own
    recorded sha256 and every rebuild would diff against itself. ensure_ascii
    keeps the bytes independent of whatever charset the static host guesses.
    """
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return (text + "\n").encode("ascii")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest_bytes(data: bytes | None) -> dict[str, Any]:
    """Artifact manifest bytes -> dict. Anything else raises with the reason.

    A directory that holds some other tool's index.json must not be read as if
    it were ours, so the `format` marker is checked before the caller can trust a
    single field.
    """
    if not data:
        raise ValueError(f"{INDEX_NAME} is empty — nothing to read")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{INDEX_NAME} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{INDEX_NAME} is not a JSON object")
    if parsed.get("format") != FORMAT:
        raise ValueError(
            f"{INDEX_NAME} is not a {FORMAT} manifest "
            f"(format={parsed.get('format')!r}) — refusing to read it as one"
        )
    return parsed


def load_shard_bytes(data: bytes | None) -> dict[str, Any]:
    """Shard bytes -> its term table. Corrupt bytes raise; absent bytes are {}.

    Absent is a legitimate state the caller must handle (verify reports it as
    missing); corrupt is not, and quietly treating it as "no terms" would turn a
    truncated upload into a search box that answers nothing.
    """
    if data is None:
        return {}
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"shard is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("shard is not a JSON object of term -> postings")
    return parsed


def fingerprint(manifest: dict[str, Any]) -> str:
    """Content hash of the manifest EXCLUDING when it was generated.

    So "the index changed" and "the index was rebuilt" are different questions:
    two builds of the same corpus an hour apart share a fingerprint and differ
    only in generated_utc.
    """
    stripped = {
        k: v for k, v in manifest.items() if k not in ("generated_utc", "fingerprint")
    }
    return sha256_bytes(dump_bytes(stripped))


def format_utc(ts: float) -> str:
    """UTC stamp, locale-independent (time.gmtime, never strftime %b/localtime)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))


def render_files(index: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """The sharded index -> every artifact byte, plus the finalized manifest.

    This function does no I/O: it returns {name: bytes} and the caller writes it
    (the plugin's ONE real side effect). Sizes and sha256s are recorded per file
    because what a visitor DOWNLOADS is the cost Algolia's CDN was hiding — and
    because `verify` needs something to check the deployed bytes against.
    """
    stamp = time.time() if now is None else float(now)
    manifest = dict(index["manifest"])
    files: dict[str, bytes] = {}
    shards_meta: list[dict[str, Any]] = []
    for i, table in enumerate(index["shards"]):
        name = shard_name(i)
        data = dump_bytes(table)
        files[name] = data
        shards_meta.append(
            {
                "name": name,
                "terms": len(table),
                "postings": sum(len(p) for p in table.values()),
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )
    client = client_js()
    files[CLIENT_NAME] = client
    manifest["shards"] = shards_meta
    manifest["client_bytes"] = len(client)
    manifest["client_sha256"] = sha256_bytes(client)
    manifest["default_limit"] = DEFAULT_LIMIT
    manifest["fingerprint"] = fingerprint(manifest)
    manifest["generated_utc"] = format_utc(stamp)
    files[INDEX_NAME] = dump_bytes(manifest)
    sizes = {
        "manifest": len(files[INDEX_NAME]),
        "client": len(client),
        "shards": sum(len(files[m["name"]]) for m in shards_meta),
        "total": sum(len(v) for v in files.values()),
        # what one query costs a visitor: the manifest plus the shards it routes
        # to (one per query term), never the whole index
        "first_query": len(files[INDEX_NAME])
        + (max((m["bytes"] for m in shards_meta), default=0)),
    }
    return {"manifest": manifest, "files": files, "sizes": sizes}


# ---- ranking (mirrored by the generated client) ------------------------------


def _idf(doc_count: int, df: int) -> float:
    """BM25 inverse document frequency. A term in every page ranks nothing."""
    return math.log(1 + (doc_count - df + 0.5) / (df + 0.5))


def expand_term(
    table: dict[str, Any], term: str, *, prefix: bool, limit: int = PREFIX_LIMIT
) -> dict[str, Any]:
    """One query term -> the postings lists it should score against.

    Exact match always counts. Prefix expansion (Algolia's as-you-type
    behaviour, applied by rank() to the LAST term only) is deterministic: the
    widest terms first, ties alphabetical, capped at `limit`. Because routing is
    by first character, every candidate lives in the shard already loaded — the
    expansion costs no extra fetch.
    """
    out: dict[str, Any] = {}
    if term in table:
        out[term] = table[term]
    if not prefix:
        return out
    candidates = sorted(
        (k for k in table if k != term and k.startswith(term)),
        key=lambda k: (-len(table[k]), k),
    )[: max(0, int(limit))]
    for k in candidates:
        out[k] = table[k]
    return out


def rank(
    manifest: dict[str, Any],
    load_shard: Callable[[str], dict[str, Any]],
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    prefix: bool = True,
    match_all: bool = True,
) -> dict[str, Any]:
    """Rank the index against a query — the algorithm the JS client implements.

    Kept in Python so the ranking is testable without a browser, and because the
    CLI's `query` command must be able to prove the deployed artifact answers
    correctly. BM25 with per-term contributions: a term's score for a page is the
    BEST of its expansions (never the sum, or a keystroke that expands into
    twelve variants would beat an exact match). match_all=True is Algolia-like
    AND semantics; the unmatched terms are always reported, so "why did this
    return nothing" has an answer instead of an empty list.

    Every returned score is rounded to 6 decimals — the same rounding the client
    applies, so the two agree on ORDER even where libm differs in the last bits.
    """
    docs = manifest.get("docs") or []
    doc_count = int(manifest.get("doc_count") or 0)
    avg = float(manifest.get("avg_terms") or 0.0) or 1.0
    k1 = float(manifest.get("k1", K1))
    b = float(manifest.get("b", B))
    stops = frozenset((manifest.get("stopwords") or {}).get("words") or [])
    qterms = query_terms(
        query,
        stemming=bool(manifest.get("stemming", True)),
        stopwords=stops,
        min_len=int(manifest.get("min_len", MIN_TERM_LEN)),
        max_len=int(manifest.get("max_len", MAX_TERM_LEN)),
    )
    out: dict[str, Any] = {
        "query": str(query),
        "terms": qterms,
        "unmatched": [],
        "match_all": bool(match_all),
        "prefix": bool(prefix),
        "limit": int(limit),
        "total": 0,
        "returned": 0,
        "hits": [],
        "shards_read": [],
        "reason": None,
    }
    if not qterms or not doc_count:
        out["reason"] = (
            "index holds no documents"
            if not doc_count
            else "no indexable term in the query (all stopwords, too short, or "
            "outside the a-z0-9 alphabet)"
        )
        return out
    tables: dict[str, dict[str, Any]] = {}
    per_term: list[dict[int, float]] = []
    for position, term in enumerate(qterms):
        idx = (manifest.get("routes") or {}).get(term[:1])
        name = None
        if idx is not None:
            shards = manifest.get("shards") or []
            if 0 <= int(idx) < len(shards):
                name = shards[int(idx)]["name"]
        table: dict[str, Any] = {}
        if name is not None:
            if name not in tables:
                tables[name] = load_shard(name) or {}
            table = tables[name]
        expansions = expand_term(
            table,
            term,
            prefix=bool(prefix) and position == len(qterms) - 1,
            limit=int(manifest.get("prefix_limit", PREFIX_LIMIT)),
        )
        if not expansions:
            out["unmatched"].append(term)
        best: dict[int, float] = {}
        for postings in expansions.values():
            weight = _idf(doc_count, len(postings))
            for doc_id, tf in postings:
                length = int(docs[doc_id]["terms"]) if 0 <= doc_id < len(docs) else 0
                contribution = (
                    weight * tf * (k1 + 1) / (tf + k1 * (1 - b + b * (length / avg)))
                )
                if contribution > best.get(doc_id, float("-inf")):
                    best[doc_id] = contribution
        per_term.append(best)
    out["shards_read"] = sorted(tables)
    ids: set[int] | None = None
    for best in per_term:
        keys = set(best)
        if ids is None:
            ids = keys
        elif match_all:
            ids &= keys
        else:
            ids |= keys
    candidates = ids or set()
    totals = {
        doc_id: round(sum(best.get(doc_id, 0.0) for best in per_term), 6)
        for doc_id in candidates
    }
    ordered = sorted(totals, key=lambda d: (-totals[d], d))
    out["total"] = len(ordered)
    for position, doc_id in enumerate(ordered[: max(0, int(limit))]):
        hit = dict(docs[doc_id])
        hit["score"] = totals[doc_id]
        hit["rank"] = position + 1
        out["hits"].append(hit)
    out["returned"] = len(out["hits"])
    return out


# ---- deployed-artifact verification -----------------------------------------


def verify(
    manifest: dict[str, Any],
    files: dict[str, bytes],
    *,
    listing: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Check bytes on disk against the manifest that claims to describe them.

    A search box that silently returns nothing because one shard failed to
    upload is the exact failure this catches: every shard and the client are
    re-hashed, the manifest's own fingerprint is recomputed from its content, and
    a file that is ABSENT is reported as missing — never assumed to match.
    `listing` (all artifact-named files in the directory) additionally surfaces
    ORPHANS: a shard from an older, wider build that a stale client still fetches.
    """
    report: dict[str, Any] = {
        "format": manifest.get("format"),
        "format_version": manifest.get("format_version"),
        "checked": 0,
        "missing": [],
        "mismatched": [],
        "orphans": [],
        "oversized": [],
        "doc_count": int(manifest.get("doc_count") or 0),
        "term_count": int(manifest.get("term_count") or 0),
        "fingerprint": {
            "stored": manifest.get("fingerprint"),
            "recomputed": fingerprint(manifest),
        },
        "ok": False,
    }
    if manifest.get("format") != FORMAT:
        report["error"] = (
            f"not a {FORMAT} manifest (format={manifest.get('format')!r}) — "
            "nothing was verified"
        )
        return report
    expected = [
        {"name": s["name"], "sha256": s.get("sha256"), "bytes": s.get("bytes")}
        for s in (manifest.get("shards") or [])
    ]
    expected.append(
        {
            "name": str(manifest.get("client") or CLIENT_NAME),
            "sha256": manifest.get("client_sha256"),
            "bytes": manifest.get("client_bytes"),
        }
    )
    for item in expected:
        data = files.get(item["name"])
        if data is None:
            report["missing"].append(item["name"])
            continue
        report["checked"] += 1
        actual = sha256_bytes(data)
        if item["sha256"] and actual != item["sha256"]:
            report["mismatched"].append(
                {
                    "name": item["name"],
                    "expected_sha256": item["sha256"],
                    "actual_sha256": actual,
                    "expected_bytes": item["bytes"],
                    "actual_bytes": len(data),
                }
            )
    for shard in manifest.get("shards") or []:
        if int(shard.get("bytes") or 0) > SHARD_BYTE_BUDGET:
            report["oversized"].append(
                {
                    "name": shard["name"],
                    "bytes": int(shard["bytes"]),
                    "budget": SHARD_BYTE_BUDGET,
                }
            )
    manifest_bytes = len(dump_bytes(manifest))
    if manifest_bytes > MANIFEST_BYTE_BUDGET:
        report["oversized"].append(
            {
                "name": INDEX_NAME,
                "bytes": manifest_bytes,
                "budget": MANIFEST_BYTE_BUDGET,
            }
        )
    known = {INDEX_NAME, *(s["name"] for s in manifest.get("shards") or [])}
    known.add(str(manifest.get("client") or CLIENT_NAME))
    report["orphans"] = sorted(
        name
        for name in (listing or ())
        if is_artifact_name(name) and name not in known
    )
    report["fingerprint"]["match"] = (
        report["fingerprint"]["stored"] == report["fingerprint"]["recomputed"]
    )
    report["ok"] = (
        not report["missing"]
        and not report["mismatched"]
        and bool(report["fingerprint"]["match"])
    )
    return report


# ---- family schema ----------------------------------------------------------

_INDEX_PATH = "(index)"

# Why a page is missing from the index decides how loud it should be. A root
# that does not exist is an ERROR (a build over nothing must not exit 0 quietly);
# a page we could not read is a warning; a policy exclusion is info.
SKIP_SEVERITY: dict[str, str] = {
    "missing-root": "error",
    "unreadable": "warning",
    "duplicate-path": "warning",
    "too-large": "info",
    "binary": "info",
    "noindex": "info",
}
_SKIP_HINTS: dict[str, str] = {
    "missing-root": "nothing under this root was indexed — check the path",
    "unreadable": "a locked or permission-denied file, not a policy choice",
    "duplicate-path": "two roots contribute the same site-relative path",
    "too-large": "raise --max-kb if this page really should be searchable",
    "noindex": "the page's robots meta excludes it from search",
}


def _diag(path: str, rule: str, severity: str, message: str, suggestion: str | None):
    return openswap.diagnostic(
        path=path,
        line=0,
        col=0,
        rule=rule,
        severity=severity,
        message=message,
        suggestion=suggestion,
        source="searchindex",
    )


def to_diagnostics(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a build or verify report onto the family diagnostic schema.

    Errors are the two states that make a search box lie: an index with no terms
    (every query returns nothing, with a cheerful ok:true) and deployed bytes
    that do not match the manifest (missing/mismatched shard, broken
    fingerprint). Everything else is graded by how much it degrades a result:
    a page that can never be found is a warning, a page with no label is a
    suggestion, an excluded noindex page is info.
    """
    diags: list[dict[str, Any]] = []
    if report.get("documents") == 0 and "pages_seen" in report:
        diags.append(
            _diag(
                _INDEX_PATH,
                "searchindex:empty-index",
                "error",
                f"no page was indexed ({report.get('pages_seen', 0)} seen) — "
                "every query would return nothing",
                "check the roots, --ext filters and noindex tags",
            )
        )
    elif report.get("terms") == 0 and "pages_seen" in report:
        diags.append(
            _diag(
                _INDEX_PATH,
                "searchindex:empty-index",
                "error",
                f"{report.get('documents')} page(s) indexed but zero terms — "
                "every query would return nothing",
                "check --weight values and the stopword/length filters",
            )
        )
    for path in report.get("empty_pages") or []:
        diags.append(
            _diag(
                str(path),
                "searchindex:empty-page",
                "warning",
                "no indexable term on this page — it can never be a search result",
                "check for text hidden behind script/nav tags or data-searchindex=skip",
            )
        )
    for path in report.get("untitled_pages") or []:
        diags.append(
            _diag(
                str(path),
                "searchindex:no-title",
                "suggestion",
                "no <title> or h1 — the result row has no label but the URL",
                "add a <title> (seo #3 audits this too)",
            )
        )
    for entry in report.get("unsupported_pages") or []:
        diags.append(
            _diag(
                str(entry.get("path", "?")),
                "searchindex:non-ascii-dropped",
                "warning",
                f"{entry.get('chars')} character(s) are outside this index's "
                "a-z0-9 alphabet (CJK/Cyrillic/Greek fold to nothing) and are "
                "not searchable",
                "these characters are counted, not indexed — do not rely on them",
            )
        )
    for entry in report.get("duplicate_urls") or []:
        for path in entry.get("paths", [])[1:]:
            diags.append(
                _diag(
                    str(path),
                    "searchindex:duplicate-url",
                    "warning",
                    f"maps to {entry.get('url')!r}, already claimed by "
                    f"{entry.get('paths', ['?'])[0]}",
                    "two results will link to the same page",
                )
            )
    for entry in report.get("skipped") or []:
        reason = str(entry.get("reason", "unknown"))
        diags.append(
            _diag(
                str(entry.get("path", "?")),
                f"searchindex:skipped:{reason}",
                SKIP_SEVERITY.get(reason, "warning"),
                f"not indexed ({reason}) — no query can match it",
                _SKIP_HINTS.get(reason),
            )
        )
    return openswap.sort_diagnostics(diags + _verify_diagnostics(report))


def _verify_diagnostics(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The verify half of to_diagnostics (kept separate so each stays readable)."""
    diags: list[dict[str, Any]] = []
    for name in report.get("missing") or []:
        diags.append(
            _diag(
                str(name),
                "searchindex:missing-file",
                "error",
                "manifest names this file but it is not on disk — search would "
                "fail for every term routed to it",
                "rebuild and redeploy the whole artifact directory",
            )
        )
    for entry in report.get("mismatched") or []:
        diags.append(
            _diag(
                str(entry.get("name", "?")),
                "searchindex:sha256-mismatch",
                "error",
                f"content does not match the manifest "
                f"({entry.get('actual_bytes')} bytes, sha256 "
                f"{str(entry.get('actual_sha256'))[:12]}... != "
                f"{str(entry.get('expected_sha256'))[:12]}...)",
                "a partial upload or an edited file — redeploy from one build",
            )
        )
    fp = report.get("fingerprint") or {}
    if fp.get("stored") is not None and fp.get("match") is False:
        diags.append(
            _diag(
                INDEX_NAME,
                "searchindex:fingerprint-mismatch",
                "error",
                "the manifest's fingerprint does not match its own content — it "
                "was edited after the build",
                "rebuild rather than hand-editing the manifest",
            )
        )
    for name in report.get("orphans") or []:
        diags.append(
            _diag(
                str(name),
                "searchindex:orphan-file",
                "info",
                "artifact-named file no build produced — a stale client may "
                "still fetch it",
                "delete it with your deploy tool once no cached client needs it",
            )
        )
    for entry in report.get("oversized") or []:
        diags.append(
            _diag(
                str(entry.get("name", "?")),
                "searchindex:oversized",
                "suggestion",
                f"{entry.get('bytes')} bytes exceeds the "
                f"{entry.get('budget')}-byte budget a visitor downloads",
                "raise --shards to split the postings, or trim the corpus",
            )
        )
    return diags


# ---- the shipped client -----------------------------------------------------

# Every tunable this client uses (weights, k1/b, stopword list, stemming on/off,
# term-length bounds, routes, shard names, default limit) is READ FROM THE
# MANIFEST at runtime, so there are no constants to keep in sync with Python and
# the file below is byte-identical across builds. What IS mirrored is the logic:
# fold/tokenize/stem and the BM25 accumulation. tests/test_searchindex.py runs
# this exact file under node against a real artifact and asserts hit-for-hit
# agreement with rank() (skipped, and said so, where node is absent).
_CLIENT_JS = r"""/* scout searchindex client (openswap #23 - the Algolia widget, unhosted).
 * Generated by `scout searchindex build`. No dependencies, no build step, no
 * API key, no analytics: it fetches the manifest and the one shard a query
 * routes to, both served from your own origin, and ranks in the visitor's tab.
 * Results are written with textContent, never innerHTML, so page text can never
 * become markup.
 *
 * Browser:  ScoutSearchIndex.attach({base: "/search", input: "#q", results: "#hits"})
 * Manual:   ScoutSearchIndex.open("/search").then(c => c.search("query"))
 * Node/CJS: require("./searchindex.js").create(manifest, name => JSON.parse(...))
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else {
    root.ScoutSearchIndex = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var INDEX_NAME = "searchindex.json";
  var MARKS = /\p{M}/gu;
  var TOKENS = /[a-z0-9]+/g;
  var ES_ENDINGS = ["s", "x", "z", "ch", "sh"];
  var DOUBLED = "bdfglmnprt";
  var VOWELS = "aeiouy";
  var MIN_STEM = 3;

  function fold(value) {
    if (value === null || value === undefined) return "";
    return String(value).normalize("NFKD").replace(MARKS, "").toLowerCase();
  }

  function tokenize(value) {
    return fold(value).match(TOKENS) || [];
  }

  function endsWithAny(word, list) {
    for (var i = 0; i < list.length; i++) {
      if (word.endsWith(list[i])) return true;
    }
    return false;
  }

  function stemmable(word) {
    if (word.length < MIN_STEM) return false;
    for (var i = 0; i < word.length; i++) {
      if (VOWELS.indexOf(word.charAt(i)) >= 0) return true;
    }
    return false;
  }

  function collapse(word) {
    var last = word.charAt(word.length - 1);
    if (word.length > MIN_STEM && last === word.charAt(word.length - 2) &&
        DOUBLED.indexOf(last) >= 0) {
      return word.slice(0, -1);
    }
    return word;
  }

  function depluralize(w) {
    if (w.endsWith("sses")) return w.slice(0, -2);
    if (w.endsWith("ies") && w.length > 4) return w.slice(0, -3) + "y";
    if (w.endsWith("es") && w.length > 4 &&
        endsWithAny(w.slice(0, -2), ES_ENDINGS)) {
      return w.slice(0, -2);
    }
    if (w.endsWith("ss") || w.endsWith("us") || w.endsWith("is")) return w;
    if (w.endsWith("s")) return w.slice(0, -1);
    return w;
  }

  function stem(word) {
    var w = String(word), reduced;
    while (w.length > MIN_STEM) {
      reduced = depluralize(w);
      if (reduced === w) break;
      w = reduced;
    }
    if (w.length > MIN_STEM) {
      if (w.endsWith("ing") && stemmable(w.slice(0, -3))) {
        w = collapse(w.slice(0, -3));
      } else if (w.endsWith("ed") && stemmable(w.slice(0, -2))) {
        w = collapse(w.slice(0, -2));
      }
    }
    return w;
  }

  function idf(docCount, df) {
    return Math.log(1 + (docCount - df + 0.5) / (df + 0.5));
  }

  function round6(value) {
    return Math.round(value * 1e6) / 1e6;
  }

  function Client(manifest, load) {
    this.manifest = manifest || {};
    this.load = load;
    this.cache = {};
    var words = ((this.manifest.stopwords || {}).words) || [];
    this.stop = {};
    for (var i = 0; i < words.length; i++) this.stop[words[i]] = 1;
  }

  Client.prototype.terms = function (text) {
    var m = this.manifest;
    var minLen = m.min_len === undefined ? 1 : m.min_len;
    var maxLen = m.max_len === undefined ? 64 : m.max_len;
    var stemming = m.stemming !== false;
    var tokens = tokenize(text);
    var seen = {}, out = [];
    for (var i = 0; i < tokens.length; i++) {
      var token = tokens[i];
      if (this.stop[token]) continue;
      if (token.length < minLen || token.length > maxLen) continue;
      var term = stemming ? stem(token) : token;
      if (!seen[term]) {
        seen[term] = 1;
        out.push(term);
      }
    }
    return out;
  };

  Client.prototype.shardFor = function (term) {
    var index = (this.manifest.routes || {})[term.charAt(0)];
    if (index === undefined || index === null) return null;
    var shard = (this.manifest.shards || [])[index];
    return shard ? shard.name : null;
  };

  Client.prototype.table = function (name) {
    if (name === null) return Promise.resolve({});
    if (!this.cache[name]) {
      this.cache[name] = Promise.resolve(this.load(name)).then(function (data) {
        return data || {};
      });
    }
    return this.cache[name];
  };

  Client.prototype.expand = function (table, term, prefix) {
    var out = {}, keys = [], k;
    if (table[term]) out[term] = table[term];
    if (!prefix) return out;
    for (k in table) {
      if (Object.prototype.hasOwnProperty.call(table, k) &&
          k !== term && k.indexOf(term) === 0) {
        keys.push(k);
      }
    }
    keys.sort(function (a, b) {
      var d = table[b].length - table[a].length;
      if (d !== 0) return d;
      return a < b ? -1 : (a > b ? 1 : 0);
    });
    var cap = this.manifest.prefix_limit === undefined ? 24 : this.manifest.prefix_limit;
    keys = keys.slice(0, cap);
    for (var i = 0; i < keys.length; i++) out[keys[i]] = table[keys[i]];
    return out;
  };

  Client.prototype.search = function (query, options) {
    var self = this, opts = options || {}, m = this.manifest;
    var limit = opts.limit === undefined
      ? (m.default_limit === undefined ? 10 : m.default_limit) : opts.limit;
    var prefix = opts.prefix === undefined ? true : !!opts.prefix;
    var matchAll = opts.matchAll === undefined ? true : !!opts.matchAll;
    var qterms = this.terms(query);
    var docCount = m.doc_count || 0;
    var result = {
      query: query === null || query === undefined ? "" : String(query),
      terms: qterms, unmatched: [], match_all: matchAll, prefix: prefix,
      limit: limit, total: 0, returned: 0, hits: [], shards_read: [], reason: null
    };
    if (!qterms.length || !docCount) {
      result.reason = docCount
        ? "no indexable term in the query"
        : "index holds no documents";
      return Promise.resolve(result);
    }
    var names = qterms.map(function (t) { return self.shardFor(t); });
    return Promise.all(names.map(function (n) { return self.table(n); }))
      .then(function (tables) {
        var avg = m.avg_terms || 1, k1 = m.k1, b = m.b, docs = m.docs || [];
        var perTerm = [], read = {};
        for (var i = 0; i < qterms.length; i++) {
          if (names[i] !== null) read[names[i]] = 1;
          var table = tables[i] || {};
          var expansions = self.expand(table, qterms[i],
                                       prefix && i === qterms.length - 1);
          var used = Object.keys(expansions);
          if (!used.length) result.unmatched.push(qterms[i]);
          var best = {};
          for (var u = 0; u < used.length; u++) {
            var postings = expansions[used[u]];
            var weight = idf(docCount, postings.length);
            for (var p = 0; p < postings.length; p++) {
              var docId = postings[p][0], tf = postings[p][1];
              var doc = docs[docId] || {};
              var length = doc.terms || 0;
              var contribution = weight * tf * (k1 + 1) /
                (tf + k1 * (1 - b + b * (length / avg)));
              if (best[docId] === undefined || contribution > best[docId]) {
                best[docId] = contribution;
              }
            }
          }
          perTerm.push(best);
        }
        result.shards_read = Object.keys(read).sort();
        var ids = null, i2, key;
        for (i2 = 0; i2 < perTerm.length; i2++) {
          var keys = Object.keys(perTerm[i2]);
          if (ids === null) {
            ids = {};
            for (key = 0; key < keys.length; key++) ids[keys[key]] = 1;
          } else if (matchAll) {
            var kept = {};
            for (key = 0; key < keys.length; key++) {
              if (ids[keys[key]]) kept[keys[key]] = 1;
            }
            ids = kept;
          } else {
            for (key = 0; key < keys.length; key++) ids[keys[key]] = 1;
          }
        }
        var totals = {}, all = Object.keys(ids || {});
        for (i2 = 0; i2 < all.length; i2++) {
          var sum = 0;
          for (var t2 = 0; t2 < perTerm.length; t2++) {
            sum += perTerm[t2][all[i2]] || 0;
          }
          totals[all[i2]] = round6(sum);
        }
        var ordered = all.map(Number).sort(function (a, b2) {
          var d = totals[b2] - totals[a];
          return d !== 0 ? d : a - b2;
        });
        result.total = ordered.length;
        for (i2 = 0; i2 < ordered.length && i2 < limit; i2++) {
          var id = ordered[i2], hit = {}, field;
          var source = docs[id] || {};
          for (field in source) {
            if (Object.prototype.hasOwnProperty.call(source, field)) {
              hit[field] = source[field];
            }
          }
          hit.score = totals[id];
          hit.rank = i2 + 1;
          result.hits.push(hit);
        }
        result.returned = result.hits.length;
        return result;
      });
  };

  function create(manifest, load) {
    return new Client(manifest, load);
  }

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function (response) {
      if (!response.ok) {
        throw new Error("searchindex: HTTP " + response.status + " for " + url);
      }
      return response.json();
    });
  }

  function open(base, getJson) {
    var get = getJson || fetchJson;
    var dir = String(base === undefined || base === null ? "." : base)
      .replace(/\/+$/, "");
    return Promise.resolve(get(dir + "/" + INDEX_NAME)).then(function (manifest) {
      var version = manifest.fingerprint
        ? "?v=" + String(manifest.fingerprint).slice(0, 12) : "";
      return create(manifest, function (name) {
        return get(dir + "/" + name + version);
      });
    });
  }

  function render(container, result, options) {
    var empty = options.empty || "No results.";
    container.textContent = "";
    if (!result.hits.length) {
      var none = document.createElement("p");
      none.className = "searchindex-empty";
      none.textContent = result.reason || empty;
      container.appendChild(none);
      return;
    }
    var list = document.createElement("ol");
    list.className = "searchindex-hits";
    for (var i = 0; i < result.hits.length; i++) {
      var hit = result.hits[i];
      var item = document.createElement("li");
      var link = document.createElement("a");
      link.href = hit.url;
      link.textContent = hit.title || hit.url;
      item.appendChild(link);
      if (hit.excerpt) {
        var blurb = document.createElement("p");
        blurb.className = "searchindex-excerpt";
        blurb.textContent = hit.excerpt;
        item.appendChild(blurb);
      }
      list.appendChild(item);
    }
    container.appendChild(list);
  }

  function attach(options) {
    var opts = options || {};
    var input = typeof opts.input === "string"
      ? document.querySelector(opts.input) : opts.input;
    var container = typeof opts.results === "string"
      ? document.querySelector(opts.results) : opts.results;
    if (!input || !container) {
      throw new Error("searchindex: attach needs an input and a results element");
    }
    var pending = open(opts.base, opts.fetchJson);
    var timer = null;
    function run() {
      var text = input.value;
      pending.then(function (client) {
        return client.search(text, opts);
      }).then(function (result) {
        render(container, result, opts);
        if (typeof opts.onResults === "function") opts.onResults(result);
      }).catch(function (error) {
        container.textContent = String(error && error.message ? error.message : error);
      });
    }
    input.addEventListener("input", function () {
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(run, opts.delay === undefined ? 120 : opts.delay);
    });
    return pending;
  }

  return {
    fold: fold, tokenize: tokenize, stem: stem, idf: idf,
    create: create, open: open, attach: attach, render: render,
    INDEX_NAME: INDEX_NAME
  };
});
"""


def client_js() -> bytes:
    """The dependency-free JS client, byte-exact and ASCII.

    A constant, not a template: the client reads its parameters from the
    manifest, so nothing needs interpolating and the same bytes ship on every
    build (its sha256 is a stable fact the manifest records).
    """
    return _CLIENT_JS.encode("ascii")
