# Solo personal project, no connection to employer, built with public/free-tier only
"""SEO — polite crawl frontier + on-page audit core (openswap #3: Screaming
Frog + Semrush + Yoast, the merged category).

Everything deterministic lives here: URL normalization, the html.parser fact
extractor, the on-page audit rules (title/description length windows,
canonicals, single-h1, noindex, OG/Twitter completeness, alt coverage, JSON-LD
parseability), hashlib duplicate-title detection, the resumable sqlite3 crawl
frontier, and the Screaming Frog-shaped CSV export. Real I/O stays out: the
`seo` plugin CLI supplies the urllib fetcher and injects it into crawl() as a
callable (bigbang/core/uptime.py + plugins/uptime/cli.py is the pattern), so
the whole pipeline is unit-testable fully offline.

Same-host is judged against the START URL's hostname (exact match) — a
cross-host redirect or an off-host link never widens the crawl; that plus
robots honoring IS the politeness contract, not a flag.

Audit thresholds are data (policy-as-config): DEFAULT_CONFIG holds the
built-in windows and load_config(path) overlays a JSON file on top, so a
per-site style needs no code edit.

Extension points:
- Broken-link checker (openswap build #4): facts["links"] per page plus the
  frontier table IS the site link graph; a pass that verifies external links
  plugs in as another audit over site_rows().
- Sitemap emitter (table #10): rows where to_rows() says "Indexable" are the
  sitemap URL set — read the same store, emit XML.
- A11y lint (#25): parse_page already carries img/alt and heading facts; add
  checks over the stored facts without re-crawling.
- Secure-headers audit (#22): pages.headers stores the full response header
  map per URL — audit CSP/HSTS from the store, zero refetches.
- Family gate: audit_crawl() -> openswap.summarize() and the CLI's --fail-on
  is the same pre-publish gate contract as prose lint and uptime check.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import sqlite3
import time
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from bigbang.core import openswap

if TYPE_CHECKING:
    from collections.abc import Callable

USER_AGENT = "scout-seo"
DB_REL = Path(".scout") / "seo.db"
SCHEMA_VERSION = "1"
# One source of truth for lintable extensions — extension-list drift between
# core and CLI is a known bug class in this repo, so the CLI imports this.
HTML_EXTS = (".html", ".htm")

# The 8-site public fleet (same origins as uptime.DEFAULT_TARGETS minus the
# API/local endpoints — those are probe targets, not crawlable sites). Every
# host here must also appear in the plugin manifest's network domain allowlist
# (default-deny) before a crawl is allowed.
DEFAULT_SITES: dict[str, str] = {
    "hub": "https://dumbmodel.com",
    "hoops": "https://hoops.jcamd.com",
    "grid": "https://gridiron.dumbmodel.com",
    "pitch": "https://pitch.jcamd.com",
    "equi": "https://equities.jcamd.com",
    "arcad": "https://arcade.dumbmodel.com",
    "arxiv": "https://arxiviq.com",
    "bhenre": "https://www.bhenre.com",
}

DEFAULT_CONFIG: dict[str, Any] = {
    # character windows, the Screaming Frog/Yoast consensus defaults
    "title": {"min": 30, "max": 60},
    "description": {"min": 70, "max": 160},
    "og_required": ["og:title", "og:description", "og:image"],
    "twitter_required": ["twitter:card"],
}


def load_config(path: str | None = None) -> dict[str, Any]:
    """DEFAULT_CONFIG overlaid with an optional JSON file.

    Merge semantics mirror uptime.load_targets: dicts merge key-by-key,
    scalars/lists replace. Unknown keys and malformed windows raise ValueError
    for the CLI to convert into a fail_agent envelope.
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config file must be a JSON object")
        for key, val in raw.items():
            if key not in cfg:
                raise ValueError(f"unknown config key {key!r} (known: {sorted(cfg)})")
            if isinstance(cfg[key], dict):
                if not isinstance(val, dict):
                    raise ValueError(f"config {key!r}: must be an object")
                cfg[key].update(val)
            else:
                cfg[key] = val
    for key in ("title", "description"):
        win = cfg[key]
        lo, hi = win.get("min"), win.get("max")
        if not (isinstance(lo, int) and isinstance(hi, int) and 0 <= lo <= hi):
            raise ValueError(f"config {key!r}: needs int 0 <= min <= max, got {win!r}")
    for key in ("og_required", "twitter_required"):
        if not (isinstance(cfg[key], list) and all(isinstance(x, str) for x in cfg[key])):
            raise ValueError(f"config {key!r}: must be a list of property names")
    return cfg


# ---- URL helpers ------------------------------------------------------------


def _ensure_root_path(url: str) -> str:
    # bare origin and origin+"/" are the same resource — normalize so the
    # frontier seed and a discovered "/" link dedupe instead of double-fetching
    s = urlsplit(url)
    if s.scheme in ("http", "https") and not s.path:
        return urlunsplit((s.scheme, s.netloc, "/", s.query, ""))
    return url


def site_key(url: str) -> str:
    """Canonical store key for a start URL (defragged, root path normalized)."""
    return _ensure_root_path(urldefrag(str(url).strip())[0])


def resolve_link(href: str, base: str) -> str | None:
    """Absolute defragged http(s) URL, or None for mailto:/js:/fragment links."""
    h = (href or "").strip()
    if not h or h.startswith("#"):
        return None
    try:
        absu = urldefrag(urljoin(base, h))[0]
    except ValueError:
        return None
    if urlsplit(absu).scheme not in ("http", "https"):
        return None
    return _ensure_root_path(absu)


def robots_parser(start_url: str, robots_text: str) -> urllib.robotparser.RobotFileParser:
    """Build a RobotFileParser from already-fetched robots.txt text (core stays
    pure — the CLI does the one fetch and passes the body in)."""
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(urljoin(site_key(start_url), "/robots.txt"))
    rp.parse((robots_text or "").splitlines())
    return rp


# ---- page fact extraction ---------------------------------------------------


class _PageParser(HTMLParser):
    """Tolerant single-pass fact extractor (html.parser never chokes on soup)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.base_href: str | None = None
        self.title_line = 0
        self.description: str | None = None
        self.description_line = 0
        self.robots_meta: str | None = None
        self.canonical: str | None = None
        self.canonical_line = 0
        self.og: dict[str, str] = {}
        self.twitter: dict[str, str] = {}
        self.h1s: list[dict[str, Any]] = []
        self.hrefs: list[str] = []
        self.images_total = 0
        self.images_missing_alt: list[dict[str, Any]] = []
        self.json_ld_blocks: list[dict[str, Any]] = []
        self.word_count = 0
        self._title_parts: list[str] = []
        self._in_title = False
        self._in_h1 = False
        self._h1_parts: list[str] = []
        self._h1_pos = (0, 0)
        self._in_script = False
        self._in_style = False
        self._jsonld_parts: list[str] | None = None
        self._jsonld_line = 0
        self._svg_depth = 0

    def title_text(self) -> str | None:
        """First <title> text — finalized here so an unterminated tag in
        truncated/malformed HTML still yields what was captured."""
        t = " ".join("".join(self._title_parts).split())
        return t or None

    def _meta(self, a: dict[str, Any], line: int) -> None:
        name = (a.get("name") or "").strip().lower()
        prop = (a.get("property") or "").strip().lower()
        content = (a.get("content") or "").strip()
        if name == "description" and self.description is None:
            self.description = content
            self.description_line = line
        elif name == "robots" and self.robots_meta is None:
            self.robots_meta = content
        if prop.startswith("og:"):
            self.og.setdefault(prop, content)
        key = name or prop  # twitter:* cards appear under either attribute
        if key.startswith("twitter:"):
            self.twitter.setdefault(key, content)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        line, off = self.getpos()
        a = dict(attrs)
        if tag == "svg":
            self._svg_depth += 1
        elif tag == "base" and self.base_href is None and a.get("href"):
            self.base_href = a["href"].strip()
        elif tag == "title" and self._svg_depth == 0 and not self._title_parts:
            self._in_title = True
            self.title_line = line
        elif tag == "meta":
            self._meta(a, line)
        elif tag == "link":
            rels = (a.get("rel") or "").lower().split()
            if "canonical" in rels and self.canonical is None and a.get("href"):
                self.canonical = a["href"].strip()
                self.canonical_line = line
        elif tag == "a":
            if a.get("href"):
                self.hrefs.append(a["href"])
        elif tag == "img":
            self.images_total += 1
            # alt="" is a deliberate decorative signal — only a MISSING
            # attribute is flagged (Screaming Frog's "Missing Alt Attribute")
            if "alt" not in a:
                self.images_missing_alt.append(
                    {"src": a.get("src") or "", "line": line, "col": off + 1}
                )
        elif tag == "h1":
            self._in_h1 = True
            self._h1_parts = []
            self._h1_pos = (line, off + 1)
        elif tag == "script":
            self._in_script = True
            if (a.get("type") or "").strip().lower() == "application/ld+json":
                self._jsonld_parts = []
                self._jsonld_line = line
        elif tag == "style":
            self._in_style = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg" and self._svg_depth:
            self._svg_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "h1" and self._in_h1:
            self._in_h1 = False
            line, col = self._h1_pos
            text = " ".join("".join(self._h1_parts).split())
            self.h1s.append({"text": text, "line": line, "col": col})
        elif tag == "script":
            self._in_script = False
            if self._jsonld_parts is not None:
                self.json_ld_blocks.append(
                    {"line": self._jsonld_line, "text": "".join(self._jsonld_parts)}
                )
                self._jsonld_parts = None
        elif tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._in_script:
            if self._jsonld_parts is not None:
                self._jsonld_parts.append(data)
            return
        if self._in_style:
            return
        if self._in_h1:
            self._h1_parts.append(data)
        self.word_count += len(data.split())


def parse_page(html_text: str, url: str) -> dict[str, Any]:
    """Extract the audit surface from one HTML page (never raises).

    Links resolve against <base href> when present, else the page URL, and
    split internal/external by exact hostname match against the page URL.
    Line/col positions come from the parser so diagnostics point at markup.
    """
    p = _PageParser()
    try:
        p.feed(html_text or "")
        p.close()
    except Exception:
        pass  # tolerant by contract: a parser hiccup must not kill a crawl pass
    base = p.base_href or url
    host = (urlsplit(url).hostname or "").lower()
    internal: list[str] = []
    external: list[str] = []
    seen: set[str] = set()
    for href in p.hrefs:
        link = resolve_link(href, base)
        if link is None or link in seen:
            continue
        seen.add(link)
        if (urlsplit(link).hostname or "").lower() == host:
            internal.append(link)
        else:
            external.append(link)
    json_ld = []
    for block in p.json_ld_blocks:
        try:
            json.loads(block["text"])
            json_ld.append({"line": block["line"], "ok": True, "error": None})
        except ValueError as e:
            json_ld.append({"line": block["line"], "ok": False, "error": str(e)[:120]})
    return {
        "url": url,
        "title": p.title_text(),
        "title_line": p.title_line,
        "description": p.description,
        "description_line": p.description_line,
        "robots": p.robots_meta,
        "noindex": "noindex" in (p.robots_meta or "").lower(),
        "canonical": p.canonical,
        "canonical_line": p.canonical_line,
        "og": p.og,
        "twitter": p.twitter,
        "h1": p.h1s,
        "links": {"internal": internal, "external": external},
        "images": {"total": p.images_total, "missing_alt": p.images_missing_alt},
        "json_ld": json_ld,
        "word_count": p.word_count,
    }


# ---- the audit pass ---------------------------------------------------------


def audit_page(
    url: str,
    *,
    status: int | None,
    facts: dict[str, Any] | None,
    redirects: list[dict[str, Any]] | None = None,
    error: str | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One page -> family diagnostics. Reachability first; on-page checks only
    for answered non-error pages with parsed facts (an error body's markup is
    not the deployed content and must not generate on-page noise)."""
    cfg = config or DEFAULT_CONFIG
    diags: list[dict[str, Any]] = []

    def add(rule, message, *, severity="warning", line=0, col=0, suggestion=None):
        diags.append(
            openswap.diagnostic(
                path=url, line=line, col=col, rule=rule, severity=severity,
                message=message, suggestion=suggestion,
            )
        )

    hops = redirects or []
    if hops:
        chain = " -> ".join(str(h.get("to", "?")) for h in hops)
        if len(hops) >= 2:
            add("seo:redirect-chain", f"{len(hops)} redirect hops: {chain}")
        else:
            add("seo:redirect", f"redirects to {chain}", severity="suggestion")
    if status is None:
        add("seo:unreachable", f"fetch failed — {error or 'no answer'}",
            severity="error")
        return diags
    if status >= 400:
        add("seo:http-error", f"http {status}", severity="error")
        return diags
    if facts is None:
        return diags

    title = (facts.get("title") or "").strip()
    t_cfg = cfg["title"]
    if not title:
        add("seo:title-missing", "no <title>", severity="error")
    elif not (t_cfg["min"] <= len(title) <= t_cfg["max"]):
        add(
            "seo:title-length",
            f"title length {len(title)} outside {t_cfg['min']}-{t_cfg['max']}",
            line=facts.get("title_line") or 0,
        )
    desc = (facts.get("description") or "").strip()
    d_cfg = cfg["description"]
    if not desc:
        add("seo:description-missing", "no meta description")
    elif not (d_cfg["min"] <= len(desc) <= d_cfg["max"]):
        add(
            "seo:description-length",
            f"description length {len(desc)} outside {d_cfg['min']}-{d_cfg['max']}",
            severity="suggestion",
            line=facts.get("description_line") or 0,
        )
    canonical = (facts.get("canonical") or "").strip()
    if not canonical:
        add("seo:canonical-missing", "no rel=canonical", severity="suggestion")
    else:
        c_host = (urlsplit(urljoin(url, canonical)).hostname or "").lower()
        if c_host != (urlsplit(url).hostname or "").lower():
            add(
                "seo:canonical-offsite",
                f"canonical points off-site: {canonical}",
                line=facts.get("canonical_line") or 0,
            )
    if facts.get("noindex"):
        add("seo:noindex", f"meta robots {facts.get('robots')!r} blocks indexing")
    h1s = facts.get("h1") or []
    if not h1s:
        add("seo:h1-missing", "no <h1>")
    elif len(h1s) > 1:
        add(
            "seo:h1-multiple",
            f"{len(h1s)} <h1> elements (want exactly 1)",
            line=h1s[1].get("line") or 0,
        )
    og = facts.get("og") or {}
    missing_og = [k for k in cfg["og_required"] if not (og.get(k) or "").strip()]
    if missing_og:
        add("seo:og-incomplete", "missing " + ", ".join(missing_og),
            severity="suggestion")
    tw = facts.get("twitter") or {}
    missing_tw = [k for k in cfg["twitter_required"] if not (tw.get(k) or "").strip()]
    if missing_tw:
        add("seo:twitter-incomplete", "missing " + ", ".join(missing_tw),
            severity="suggestion")
    images = facts.get("images") or {}
    missing_alt = images.get("missing_alt") or []
    if missing_alt:
        first = missing_alt[0]
        add(
            "seo:img-alt",
            f"{len(missing_alt)} of {images.get('total', 0)} images missing an"
            " alt attribute",
            line=first.get("line") or 0,
            col=first.get("col") or 0,
            suggestion=f"first: {first.get('src') or '<no src>'}",
        )
    for block in facts.get("json_ld") or []:
        if not block.get("ok"):
            add(
                "seo:jsonld-invalid",
                f"JSON-LD block does not parse: {block.get('error')}",
                severity="error",
                line=block.get("line") or 0,
            )
    return diags


def title_fingerprint(title: str) -> str:
    """Stable hash of a whitespace/case-normalized title (dup detection)."""
    norm = " ".join((title or "").lower().split())
    # usedforsecurity=False, not a `# noqa`: this is duplicate DETECTION (12 hex chars
    # of a normalized title), never a security boundary, and saying so in the API is
    # self-documenting where a suppression comment would only silence the linter.
    return hashlib.sha1(norm.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def duplicate_titles(pages: list[tuple[str, str | None]]) -> list[dict[str, Any]]:
    """Site-level pass: (url, title) pairs -> one warning per page whose
    normalized title is shared. Empty/missing titles are audit_page's job."""
    groups: dict[str, list[str]] = {}
    first_title: dict[str, str] = {}
    for url, title in pages:
        if not title or not title.strip():
            continue
        fp = title_fingerprint(title)
        groups.setdefault(fp, []).append(url)
        first_title.setdefault(fp, title.strip())
    diags: list[dict[str, Any]] = []
    for fp, urls in groups.items():
        if len(urls) < 2:
            continue
        for u in urls:
            diags.append(
                openswap.diagnostic(
                    path=u,
                    line=0,
                    col=0,
                    rule="seo:title-duplicate",
                    severity="warning",
                    message=(
                        f"title {first_title[fp][:60]!r} shared by {len(urls)}"
                        f" pages (fingerprint {fp})"
                    ),
                )
            )
    return diags


# ---- crawl store: resumable sqlite frontier ---------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS frontier(
    site TEXT NOT NULL,
    url TEXT NOT NULL,
    depth INTEGER NOT NULL,
    found_on TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    reason TEXT,
    PRIMARY KEY(site, url)
);
CREATE INDEX IF NOT EXISTS idx_frontier_site_state ON frontier(site, state);
CREATE TABLE IF NOT EXISTS pages(
    site TEXT NOT NULL,
    url TEXT NOT NULL,
    ts REAL NOT NULL,
    depth INTEGER NOT NULL,
    status INTEGER,
    error TEXT,
    final_url TEXT,
    redirects TEXT NOT NULL DEFAULT '[]',
    content_type TEXT,
    headers TEXT NOT NULL DEFAULT '{}',
    facts TEXT,
    PRIMARY KEY(site, url)
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the crawl store.

    `frontier` is the resumable work queue (pending survives interruption and
    a later pass picks it up); `pages` is the one-table audit surface —
    status, redirect chain, response headers, and parsed facts per URL.
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


def frontier_counts(conn: sqlite3.Connection, site: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT state, COUNT(*) AS n FROM frontier WHERE site = ? GROUP BY state",
        (site,),
    )
    return {r["state"]: int(r["n"]) for r in rows}


def crawl(
    conn: sqlite3.Connection,
    start_url: str,
    fetch: Callable[[str], dict[str, Any]],
    *,
    max_pages: int = 25,
    max_depth: int = 3,
    robots: urllib.robotparser.RobotFileParser | None = None,
    ts: float | None = None,
) -> dict[str, Any]:
    """One bounded crawl pass; re-running with the same store resumes.

    `fetch(url)` must return {"status": int|None, "final_url": str,
    "redirects": [{"code", "to"}], "content_type": str|None, "headers": dict,
    "body": str, "error": str|None} — the CLI injects the real urllib fetcher
    (which owns the politeness delay); tests inject fakes (offline invariant).
    Already-fetched URLs are never refetched; robots disallows mark frontier
    rows 'skipped' without spending fetch budget.
    """
    site = site_key(start_url)
    host = (urlsplit(site).hostname or "").lower()
    now = time.time() if ts is None else ts
    conn.execute(
        "INSERT OR IGNORE INTO frontier(site, url, depth, found_on, state)"
        " VALUES(?, ?, 0, NULL, 'pending')",
        (site, site),
    )
    conn.commit()
    fetched = skipped = errors = 0
    while fetched < max_pages:
        row = conn.execute(
            "SELECT url, depth FROM frontier WHERE site = ? AND state = 'pending'"
            " ORDER BY depth, url LIMIT 1",
            (site,),
        ).fetchone()
        if row is None:
            break
        url, depth = row["url"], int(row["depth"])
        if robots is not None and not robots.can_fetch(USER_AGENT, url):
            conn.execute(
                "UPDATE frontier SET state = 'skipped', reason = 'robots'"
                " WHERE site = ? AND url = ?",
                (site, url),
            )
            conn.commit()
            skipped += 1
            continue
        r = fetch(url)
        fetched += 1
        status = r.get("status")
        ctype = (r.get("content_type") or "").lower()
        body = r.get("body") or ""
        facts = None
        if status is not None and status < 400 and "html" in ctype and body:
            facts = parse_page(body, r.get("final_url") or url)
        conn.execute(
            "INSERT OR REPLACE INTO pages(site, url, ts, depth, status, error,"
            " final_url, redirects, content_type, headers, facts)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                site,
                url,
                now,
                depth,
                status,
                r.get("error"),
                r.get("final_url") or url,
                json.dumps(r.get("redirects") or []),
                r.get("content_type"),
                json.dumps(r.get("headers") or {}),
                None if facts is None else json.dumps(facts),
            ),
        )
        if status is None:
            errors += 1
        conn.execute(
            "UPDATE frontier SET state = ?, reason = ? WHERE site = ? AND url = ?",
            ("error" if status is None else "done", r.get("error"), site, url),
        )
        if facts is not None and depth < max_depth:
            links = facts["links"]["internal"] + facts["links"]["external"]
            for link in links:
                # same-host is judged against the START host, not final_url's —
                # a cross-host redirect must not widen the crawl
                if (urlsplit(link).hostname or "").lower() != host:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO frontier(site, url, depth, found_on)"
                    " VALUES(?, ?, ?, ?)",
                    (site, link, depth + 1, url),
                )
        conn.commit()
    return {
        "site": site,
        "host": host,
        "fetched": fetched,
        "errors": errors,
        "skipped_robots": skipped,
        "frontier": frontier_counts(conn, site),
        "pages": int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM pages WHERE site = ?", (site,)
            ).fetchone()["n"]
        ),
    }


# ---- reads: the audit / export contract -------------------------------------


def site_rows(conn: sqlite3.Connection, site: str) -> list[dict[str, Any]]:
    """All crawled pages for one site, JSON columns decoded, URL-ordered."""
    out = []
    for r in conn.execute("SELECT * FROM pages WHERE site = ? ORDER BY url", (site,)):
        d = dict(r)
        d["redirects"] = json.loads(d["redirects"] or "[]")
        d["headers"] = json.loads(d["headers"] or "{}")
        d["facts"] = json.loads(d["facts"]) if d["facts"] else None
        out.append(d)
    return out


def audit_crawl(
    conn: sqlite3.Connection, site: str, *, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Per-page audits + the site-level duplicate-title pass, sorted."""
    cfg = config or DEFAULT_CONFIG
    rows = site_rows(conn, site)
    diags: list[dict[str, Any]] = []
    for r in rows:
        diags.extend(
            audit_page(
                r["url"],
                status=r["status"],
                facts=r["facts"],
                redirects=r["redirects"],
                error=r["error"],
                config=cfg,
            )
        )
    diags.extend(
        duplicate_titles([(r["url"], (r["facts"] or {}).get("title")) for r in rows])
    )
    return openswap.sort_diagnostics(diags)


CSV_COLUMNS = [
    "Address",
    "Status Code",
    "Indexability",
    "Title 1",
    "Title 1 Length",
    "Meta Description 1",
    "Meta Description 1 Length",
    "H1-1",
    "H1 Count",
    "Canonical Link Element 1",
    "Redirect Hops",
    "Word Count",
    "Images",
    "Images Missing Alt",
    "OG Missing",
    "Twitter Missing",
    "JSON-LD Blocks",
    "JSON-LD Invalid",
    "Issues",
]


def to_rows(
    conn: sqlite3.Connection, site: str, *, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Screaming Frog-shaped per-URL rows (the CSV contract, file-free for
    tests). Indexability follows SF semantics: an errored, redirecting, or
    noindex address is Non-Indexable."""
    cfg = config or DEFAULT_CONFIG
    issues: dict[str, list[str]] = {}
    for d in audit_crawl(conn, site, config=cfg):
        issues.setdefault(d["path"], []).append(d["rule"])
    rows = []
    for r in site_rows(conn, site):
        f = r["facts"] or {}
        title = (f.get("title") or "").strip()
        desc = (f.get("description") or "").strip()
        h1s = f.get("h1") or []
        og = f.get("og") or {}
        tw = f.get("twitter") or {}
        jl = f.get("json_ld") or []
        images = f.get("images") or {}
        non_index = (
            r["status"] is None
            or r["status"] >= 400
            or bool(r["redirects"])
            or bool(f.get("noindex"))
        )
        rows.append(
            {
                "Address": r["url"],
                "Status Code": "" if r["status"] is None else r["status"],
                "Indexability": "Non-Indexable" if non_index else "Indexable",
                "Title 1": title,
                "Title 1 Length": len(title),
                "Meta Description 1": desc,
                "Meta Description 1 Length": len(desc),
                "H1-1": h1s[0]["text"] if h1s else "",
                "H1 Count": len(h1s),
                "Canonical Link Element 1": f.get("canonical") or "",
                "Redirect Hops": len(r["redirects"]),
                "Word Count": f.get("word_count") or 0,
                "Images": images.get("total", 0),
                "Images Missing Alt": len(images.get("missing_alt") or []),
                "OG Missing": ", ".join(
                    k for k in cfg["og_required"] if not (og.get(k) or "").strip()
                ),
                "Twitter Missing": ", ".join(
                    k for k in cfg["twitter_required"] if not (tw.get(k) or "").strip()
                ),
                "JSON-LD Blocks": len(jl),
                "JSON-LD Invalid": sum(1 for b in jl if not b.get("ok")),
                "Issues": "; ".join(issues.get(r["url"], [])),
            }
        )
    return rows


def export_csv(
    conn: sqlite3.Connection,
    site: str,
    path: str | Path,
    *,
    config: dict[str, Any] | None = None,
) -> int:
    """Write the per-URL table as CSV; returns the row count."""
    rows = to_rows(conn, site, config=config)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)
