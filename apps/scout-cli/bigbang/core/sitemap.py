# Solo personal project, no connection to employer, built with public/free-tier only
"""Sitemap — deterministic sitemap.xml / sitemapindex core (openswap rank 10:
XML-Sitemaps.com Pro).

XML-Sitemaps.com Pro is a paid *crawler* that fetches a live site from someone
else's datacenter to learn what the site contains. On a static fleet that is
strictly worse information than the build output itself: the `public/` tree IS
the URL set, and its mtimes ARE the lastmods. So this adapter deletes the
crawl and the SaaS both — a sorted os.walk plus xml.etree is the whole product,
and the deploy pipeline can regenerate a sitemap offline in milliseconds.

Three URL sources, one pipeline:
- a directory walk (`walk_entries`) — the built site, mtimes for lastmod;
- an explicit URL list (`parse_url_list`) — hand-curated or generated;
- the #3 seo crawl store's rows (`entries_from_crawl_rows`) — the documented
  extension point in bigbang/core/seo.py ("rows where to_rows() says
  Indexable ARE the sitemap URL set"), so a dynamic site reuses the crawl
  instead of a second fetcher.

DETERMINISM IS THE FEATURE, not a nicety. Output is a pure function of
(URL set, lastmods, options): entries are deduped and sorted by loc, XML is
indented with two spaces, files are written as UTF-8 with LF newlines and NO
generation timestamp anywhere. That makes `sitemap.xml` diffable in git and
makes `diff_files` a real deploy gate — drift means content changed, never
that the generator ran again. (It also means every writer path here emits
bytes, never text: Path.write_text would translate LF to CRLF on Windows and
the same content would diff against itself across machines.)

Protocol limits are enforced, not assumed: 50,000 URLs per file (over that,
`render_files` emits a sitemapindex plus `-1..-N` shards) and 50MB uncompressed
per file / 2,048 chars per loc, which surface as normalized openswap
diagnostics rather than silent truncation.

No sqlite ledger and no network: this adapter's persistent state is the emitted
XML in the site's own repo (git IS the history — a ledger would be a second,
weaker copy of what the diff already tells you), and `entries_from_crawl_rows`
reads the seo store the #3 adapter already owns. The plugin manifest therefore
disables the network axis entirely.

This module is PURE logic plus stats() of files under an explicit root: no
network, and the only writes are the ones the CLI asks for by path.
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from bigbang.core import openswap, seo

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'

# sitemaps.org protocol hard limits
MAX_URLS_PER_FILE = 50_000
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_LOC_LENGTH = 2048

CHANGEFREQS = ("always", "hourly", "daily", "weekly", "monthly", "yearly", "never")
LASTMOD_PRECISIONS = ("date", "second")

# W3C datetime, the subset the protocol accepts: a date, optionally with a time
# and a Z/±hh:mm offset. Checked rather than assumed because a lastmod is the
# one field a hand-written URL list gets wrong, and search engines drop the
# whole <url> element when it fails to parse.
_LASTMOD_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"([Tt]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([Zz]|[+-]\d{2}:\d{2})?)?$"
)
_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)

# One source of truth for the page-extension set: the HTML list comes from
# bigbang/core/seo.py, because extension-list drift between two adapters that
# describe "the same pages" is a known bug class in this repo. Anything else
# (.pdf, .txt) is opt-in per invocation via `exts`.
DEFAULT_EXTS = seo.HTML_EXTS
DEFAULT_INDEX_FILES = ("index.html", "index.htm")

# Always applied, on top of the caller's --exclude globs: dot-paths (.git,
# .vercel, .well-known scratch) and vendored trees are never indexable URLs,
# and shipping them would be a privacy leak, not a feature.
DEFAULT_EXCLUDES = (".*", "node_modules")


# ---- URL construction -------------------------------------------------------


def normalize_base(base_url: str) -> str:
    """Canonical base: `scheme://host[:port]/prefix/` with a trailing slash.

    Query and fragment are dropped (a base URL with either is a mistake, and
    silently keeping them would corrupt every loc). Raises ValueError so the
    CLI can convert it into one fail_agent envelope.
    """
    if not isinstance(base_url, str) or "://" not in base_url:
        raise ValueError(
            f"base URL must be absolute (https://host/...), got {base_url!r}"
        )
    u = urlsplit(base_url.strip())
    if u.scheme not in ("http", "https"):
        raise ValueError(f"base URL scheme must be http or https, got {u.scheme!r}")
    if not u.hostname:
        raise ValueError(f"base URL has no host: {base_url!r}")
    path = u.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((u.scheme, u.netloc, path, "", ""))


def _quote_path(rel: str) -> str:
    """Percent-encode a relative POSIX path for use in a loc.

    `safe` keeps the sub-delims that are legal in a path segment so ordinary
    URLs survive round-tripping; spaces and non-ASCII get encoded (a raw space
    in a loc is invalid XML sitemap content).
    """
    return quote(rel, safe="/~!$&'()*+,;=:@-._")


def url_for(
    rel: str,
    base: str,
    *,
    strip_index: bool = True,
    clean_urls: bool = False,
    index_files: tuple[str, ...] = DEFAULT_INDEX_FILES,
) -> str:
    """Map a site-root-relative path to its canonical loc.

    - `index.html` -> the base itself; `blog/index.html` -> `<base>blog/`
      (strip_index; the directory URL is what a static host serves and what
      canonicals point at).
    - clean_urls drops the extension (`about.html` -> `<base>about`), which is
      how Vercel/Netlify serve the same file. Off by default: the safe default
      is the path that literally exists.
    """
    rel = rel.replace("\\", "/").lstrip("/")
    parts = rel.split("/")
    name = parts[-1]
    if strip_index and name in index_files:
        rel = "/".join(parts[:-1])
        if rel:
            rel += "/"
    elif clean_urls:
        stem, dot, _ext = name.rpartition(".")
        if dot and stem:
            parts[-1] = stem
            rel = "/".join(parts)
    return base + _quote_path(rel)


def format_lastmod(ts: float, precision: str = "date") -> str:
    """W3C-datetime lastmod in UTC. `date` = YYYY-MM-DD, `second` = full stamp.

    UTC always (time.gmtime, never localtime): a sitemap regenerated on a box
    in another timezone must produce the same bytes for the same file mtimes.
    Date precision is the default because it is the granularity search engines
    act on and it keeps the git diff quiet on rebuilds within a day.
    """
    if precision not in LASTMOD_PRECISIONS:
        raise ValueError(
            f"lastmod precision must be one of {'|'.join(LASTMOD_PRECISIONS)}, "
            f"got {precision!r}"
        )
    tm = time.gmtime(ts)
    if precision == "date":
        return time.strftime("%Y-%m-%d", tm)
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", tm)


def format_priority(value: float | str) -> str:
    """Normalize a priority to the protocol's 0.0-1.0 decimal string."""
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"priority must be a number 0.0-1.0, got {value!r}") from exc
    if not (0.0 <= v <= 1.0):
        raise ValueError(f"priority must be between 0.0 and 1.0, got {value!r}")
    s = f"{v:.2f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def check_lastmod(value: str) -> str:
    """Return a W3C-datetime lastmod, or raise ValueError describing the shape."""
    v = str(value).strip()
    if not _LASTMOD_RE.match(v):
        raise ValueError(
            "lastmod must be a W3C datetime (YYYY-MM-DD, optionally "
            f"THH:MM:SS±hh:mm), got {value!r}"
        )
    return v


def make_entry(
    loc: str,
    *,
    lastmod: str | None = None,
    changefreq: str | None = None,
    priority: float | str | None = None,
    source: str = "",
) -> dict[str, Any]:
    """One validated <url> record. Raises ValueError on protocol violations."""
    if not isinstance(loc, str) or not loc.strip():
        raise ValueError("loc must be a non-empty string")
    loc = loc.strip()
    if "://" not in loc:
        raise ValueError(f"loc must be an absolute URL, got {loc!r}")
    if lastmod is not None:
        lastmod = check_lastmod(lastmod)
    if changefreq is not None and changefreq not in CHANGEFREQS:
        raise ValueError(
            f"changefreq must be one of {'|'.join(CHANGEFREQS)}, got {changefreq!r}"
        )
    return {
        "loc": loc,
        "lastmod": lastmod,
        "changefreq": changefreq,
        "priority": None if priority is None else format_priority(priority),
        "source": source,
    }


# ---- exclusion --------------------------------------------------------------


def match_exclude(
    rel: str, patterns: tuple[str, ...] | list[str], *, is_dir: bool = False
) -> str | None:
    """Return the first --exclude glob that covers `rel`, else None.

    A pattern is tried against the site-relative POSIX path, the basename, and
    every ancestor directory prefix, so `drafts/*`, `*.draft.html` and a bare
    `drafts` all do the obvious thing. With is_dir, the path is also tried with
    a trailing slash, so the subtree form `drafts/*` prunes the `drafts`
    directory itself instead of only rejecting its files one by one.

    fnmatchcase, never fnmatch: on Windows fnmatch normcases the path
    (lowercase + backslashes), which would make the same --exclude behave
    differently here than on the Linux CI box — a silent portability bug.
    """
    rel = rel.replace("\\", "/").lstrip("/")
    name = rel.rsplit("/", 1)[-1]
    parts = rel.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts))]
    candidates = [rel, name, *prefixes] + ([rel + "/"] if is_dir else [])
    for raw in patterns:
        pat = str(raw).replace("\\", "/").strip()
        if not pat:
            continue
        if pat.endswith("/"):
            pat += "*"
        if any(fnmatch.fnmatchcase(c, pat) for c in candidates):
            return raw
    return None


# ---- source 1: the directory walk ------------------------------------------


def walk_entries(
    root: str | Path,
    base_url: str,
    *,
    exts: tuple[str, ...] = DEFAULT_EXTS,
    excludes: tuple[str, ...] | list[str] = (),
    lastmod: str | None = "date",
    changefreq: str | None = None,
    priority: float | str | None = None,
    strip_index: bool = True,
    clean_urls: bool = False,
) -> dict[str, Any]:
    """Walk a built site directory into sorted entries. mtimes are the lastmod.

    `lastmod=None` omits the element entirely (fully mtime-independent output,
    which is what a repo that rewrites every file on every build wants).
    Excluded directories are pruned during the walk, so a big node_modules
    costs one fnmatch instead of a recursive descent. dirnames/filenames are
    sorted in place: os.walk order is filesystem-dependent, and this generator
    promises byte-identical output on any box.
    """
    base = normalize_base(base_url)
    root_path = Path(root).expanduser()
    if not root_path.is_dir():
        raise ValueError(f"root is not a directory: {root_path}")
    root_path = root_path.resolve()
    pats = [*DEFAULT_EXCLUDES, *excludes]
    wanted = tuple(e.lower() if e.startswith(".") else "." + e.lower() for e in exts)
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        here = Path(dirpath)
        rel_dir = here.relative_to(root_path).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames.sort()
        keep: list[str] = []
        for d in dirnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            hit = match_exclude(rel, pats, is_dir=True)
            if hit is None:
                keep.append(d)
            else:
                skipped.append({"path": rel + "/", "reason": f"excluded:{hit}"})
        dirnames[:] = keep
        for fname in sorted(filenames):
            rel = f"{rel_dir}/{fname}" if rel_dir else fname
            if not fname.lower().endswith(wanted):
                skipped.append({"path": rel, "reason": "extension"})
                continue
            hit = match_exclude(rel, pats)
            if hit is not None:
                skipped.append({"path": rel, "reason": f"excluded:{hit}"})
                continue
            stamp = None
            if lastmod is not None:
                stamp = format_lastmod((here / fname).stat().st_mtime, lastmod)
            entries.append(
                make_entry(
                    url_for(
                        rel, base, strip_index=strip_index, clean_urls=clean_urls
                    ),
                    lastmod=stamp,
                    changefreq=changefreq,
                    priority=priority,
                    source=rel,
                )
            )
    return {
        # by loc, not by file path: `index.html` -> `/` and clean-URL rewrites
        # reorder pages relative to their filenames, and the emitted order must
        # be the loc order for the output to be diffable.
        "entries": sorted(entries, key=lambda e: (e["loc"], e["source"])),
        "skipped": sorted(skipped, key=lambda s: s["path"]),
        "root": str(root_path),
        "base": base,
    }


# ---- source 2: an explicit URL list ----------------------------------------


def parse_url_list(
    text: str,
    base_url: str | None = None,
    *,
    lastmod: str | None = None,
    changefreq: str | None = None,
    priority: float | str | None = None,
) -> dict[str, Any]:
    """Parse `loc [lastmod]` lines. `#` comments and blank lines are ignored.

    A line may be an absolute URL or a site-relative path (`/about`), which is
    resolved against base_url — so a build script can pipe its route table
    straight in. A bad line is reported in `skipped` with the 1-based line
    number rather than aborting the whole file: one typo should not cost a
    deploy its sitemap.
    """
    base = normalize_base(base_url) if base_url else None
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) > 2:
            skipped.append(
                {
                    "path": f"line {i}",
                    "reason": f"expected `loc [lastmod]`, got {len(fields)} fields",
                }
            )
            continue
        loc, stamp = fields[0], (fields[1] if len(fields) > 1 else lastmod)
        if "://" not in loc:
            if base is None:
                skipped.append(
                    {
                        "path": f"line {i}",
                        "reason": f"relative path {loc!r} needs a base URL",
                    }
                )
                continue
            loc = base + _quote_path(loc.lstrip("/"))
        try:
            entries.append(
                make_entry(
                    loc,
                    lastmod=stamp,
                    changefreq=changefreq,
                    priority=priority,
                    source=f"line {i}",
                )
            )
        except ValueError as exc:
            skipped.append({"path": f"line {i}", "reason": str(exc)})
    return {"entries": entries, "skipped": skipped, "base": base}


# ---- source 3: the #3 seo crawl store --------------------------------------


def entries_from_crawl_rows(
    rows: list[dict[str, Any]],
    *,
    lastmod: str | None = None,
    changefreq: str | None = None,
    priority: float | str | None = None,
) -> dict[str, Any]:
    """Screaming-Frog-shaped rows (seo.to_rows) -> entries for Indexable URLs.

    The indexability verdict is the seo adapter's, not a second opinion: an
    errored, redirecting or noindex address is Non-Indexable there and is
    skipped here with that reason. Submitting a noindex URL is the classic
    sitemap own-goal, so this filter is the point of reading the crawl at all.
    """
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for row in rows:
        loc = str(row.get("Address") or "").strip()
        if not loc:
            continue
        if row.get("Indexability") != "Indexable":
            status = row.get("Status Code")
            skipped.append(
                {"path": loc, "reason": f"non-indexable (status {status or 'none'})"}
            )
            continue
        entries.append(
            make_entry(
                loc,
                lastmod=lastmod,
                changefreq=changefreq,
                priority=priority,
                source="crawl",
            )
        )
    return {"entries": entries, "skipped": skipped}


# ---- dedupe + validate ------------------------------------------------------


def dedupe(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Sort by loc and collapse duplicates, keeping the newest lastmod.

    Two sources (or an index.html and a clean-URL twin) can name the same loc;
    a sitemap with a repeated loc is malformed, so the collapse is mandatory
    and the survivors carry the most recent lastmod of the group. The dropped
    ones are reported so the operator can fix the real cause.
    """
    best: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for e in entries:
        loc = e["loc"]
        prev = best.get(loc)
        if prev is None:
            best[loc] = e
            continue
        keep, drop = (
            (e, prev) if (e["lastmod"] or "") > (prev["lastmod"] or "") else (prev, e)
        )
        best[loc] = keep
        duplicates.append(
            {"loc": loc, "kept_source": keep["source"], "dropped_source": drop["source"]}
        )
    return {
        "entries": [best[k] for k in sorted(best)],
        "duplicates": sorted(duplicates, key=lambda d: (d["loc"], d["dropped_source"])),
    }


def validate(
    entries: list[dict[str, Any]],
    base: str,
    *,
    duplicates: list[dict[str, Any]] | None = None,
    max_urls: int = MAX_URLS_PER_FILE,
) -> list[dict[str, Any]]:
    """Family-normalized diagnostics over the URL set (openswap invariant [C]).

    `path` is the loc itself (the addressable thing, exactly as the seo adapter
    uses the URL as the diagnostic path); the base URL stands in when a finding
    is about the set as a whole.
    """
    diags: list[dict[str, Any]] = []
    if not entries:
        diags.append(
            openswap.diagnostic(
                path=base,
                line=1,
                rule="sitemap:no-urls",
                severity="error",
                message="no URLs to emit — an empty sitemap tells crawlers nothing",
                suggestion="check --root/--urls and the --exclude globs",
                source="sitemap",
            )
        )
    for e in entries:
        loc = e["loc"]
        if not loc.startswith(base):
            diags.append(
                openswap.diagnostic(
                    path=loc,
                    line=1,
                    rule="sitemap:off-base",
                    severity="error",
                    message=f"loc is outside the base URL {base} (cross-site "
                    "sitemap entries are rejected by search engines)",
                    suggestion=f"drop it or generate a separate sitemap for "
                    f"{urlsplit(loc).netloc}",
                    source="sitemap",
                )
            )
        if e.get("lastmod"):
            try:
                check_lastmod(e["lastmod"])
            except ValueError as exc:
                # unreachable for entries built by make_entry (it validates on
                # construction) — this catches sitemaps written by someone else,
                # which is exactly what `lint` is pointed at.
                diags.append(
                    openswap.diagnostic(
                        path=loc,
                        line=1,
                        rule="sitemap:bad-lastmod",
                        severity="warning",
                        message=str(exc),
                        suggestion="use YYYY-MM-DD (search engines drop the whole "
                        "<url> element on an unparseable lastmod)",
                        source="sitemap",
                    )
                )
        if len(loc) > MAX_LOC_LENGTH:
            diags.append(
                openswap.diagnostic(
                    path=loc,
                    line=1,
                    rule="sitemap:loc-too-long",
                    severity="warning",
                    message=f"loc is {len(loc)} chars, over the "
                    f"{MAX_LOC_LENGTH}-char protocol limit",
                    suggestion="shorten the path or exclude the URL",
                    source="sitemap",
                )
            )
    for d in duplicates or []:
        diags.append(
            openswap.diagnostic(
                path=d["loc"],
                line=1,
                rule="sitemap:duplicate-loc",
                severity="warning",
                message=f"duplicate loc collapsed (kept {d['kept_source'] or '?'}, "
                f"dropped {d['dropped_source'] or '?'})",
                suggestion="two sources name the same URL — pick one",
                source="sitemap",
            )
        )
    if len(entries) > max_urls:
        diags.append(
            openswap.diagnostic(
                path=base,
                line=1,
                rule="sitemap:sharded",
                severity="info",
                message=f"{len(entries)} URLs exceed {max_urls} per file — "
                "emitting a sitemapindex plus shards",
                source="sitemap",
            )
        )
    return openswap.sort_diagnostics(diags)


def validate_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Diagnostics about the rendered files themselves (the 50MB limit)."""
    diags = []
    for f in files:
        if f["bytes"] > MAX_FILE_BYTES:
            diags.append(
                openswap.diagnostic(
                    path=f["name"],
                    line=1,
                    rule="sitemap:file-too-large",
                    severity="warning",
                    message=f"{f['name']} is {f['bytes']} bytes, over the "
                    f"{MAX_FILE_BYTES}-byte uncompressed protocol limit",
                    suggestion="lower --max-urls so the shards get smaller",
                    source="sitemap",
                )
            )
    return openswap.sort_diagnostics(diags)


# ---- XML --------------------------------------------------------------------


def _child(parent: ET.Element, tag: str, text: str) -> None:
    ET.SubElement(parent, tag).text = text


def build_urlset(entries: list[dict[str, Any]]) -> ET.Element:
    """<urlset> for the given entries, in the order supplied.

    xmlns is set as a literal attribute rather than via
    ET.register_namespace(): registration is global module state (it would
    leak into every other ElementTree user in the process), while the literal
    attribute serializes to the same bytes and re-parses as a real namespace.
    """
    root = ET.Element("urlset", {"xmlns": SITEMAP_NS})
    for e in entries:
        node = ET.SubElement(root, "url")
        _child(node, "loc", e["loc"])
        for key in ("lastmod", "changefreq", "priority"):
            if e.get(key):
                _child(node, key, str(e[key]))
    return root


def build_index(shards: list[dict[str, Any]]) -> ET.Element:
    """<sitemapindex> pointing at each shard's loc (+ its newest lastmod)."""
    root = ET.Element("sitemapindex", {"xmlns": SITEMAP_NS})
    for s in shards:
        node = ET.SubElement(root, "sitemap")
        _child(node, "loc", s["loc"])
        if s.get("lastmod"):
            _child(node, "lastmod", str(s["lastmod"]))
    return root


def render(root: ET.Element) -> str:
    """Declaration + two-space-indented XML + trailing newline. No timestamp."""
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return f"{XML_DECL}\n{body}\n"


def shard_entries(
    entries: list[dict[str, Any]], max_urls: int = MAX_URLS_PER_FILE
) -> list[list[dict[str, Any]]]:
    """Split into <= max_urls chunks, order preserved."""
    if max_urls < 1:
        raise ValueError(f"max_urls must be >= 1, got {max_urls}")
    return [entries[i : i + max_urls] for i in range(0, len(entries), max_urls)]


def shard_name(out_name: str, index: int) -> str:
    """`sitemap.xml` + 1 -> `sitemap-1.xml` (siblings of the index)."""
    stem, dot, ext = out_name.rpartition(".")
    return f"{stem}-{index}.{ext}" if dot else f"{out_name}-{index}"


def render_files(
    entries: list[dict[str, Any]],
    out_name: str,
    base: str,
    *,
    max_urls: int = MAX_URLS_PER_FILE,
) -> list[dict[str, Any]]:
    """The complete file set as in-memory XML — nothing touches the disk here.

    <= max_urls URLs: one urlset at `out_name`. Over it: `out_name` becomes the
    sitemapindex (the canonical location a robots.txt/Search Console entry
    already points at, so sharding never breaks an existing submission) and the
    URLs live in `out_name`-1..N siblings. Building the bytes before writing is
    what lets `diff_files` gate a deploy without a scratch directory.
    """
    shards = shard_entries(entries, max_urls) or [[]]
    if len(shards) == 1:
        files = [{"name": out_name, "kind": "urlset", "urls": len(shards[0]),
                  "xml": render(build_urlset(shards[0]))}]
    else:
        files = []
        refs = []
        for i, chunk in enumerate(shards, start=1):
            name = shard_name(out_name, i)
            files.append({"name": name, "kind": "urlset", "urls": len(chunk),
                          "xml": render(build_urlset(chunk))})
            stamps = [e["lastmod"] for e in chunk if e.get("lastmod")]
            refs.append({"loc": base + name, "lastmod": max(stamps) if stamps else None})
        files.insert(
            0,
            {"name": out_name, "kind": "sitemapindex", "urls": 0,
             "xml": render(build_index(refs))},
        )
    for f in files:
        f["bytes"] = len(f["xml"].encode("utf-8"))
    return files


def parse_sitemap(text: str) -> dict[str, Any]:
    """Read a urlset or sitemapindex back into entries (used by `lint`).

    Namespaces are stripped rather than matched, so a sitemap written by any
    other generator (or a namespace-less one) still lints.

    A DOCTYPE is REFUSED before parsing (same doctrine as feeds.parse_feed):
    stdlib ElementTree never fetches external DTDs, but an internal <!ENTITY>
    chain is still an expansion bomb, and no real sitemap carries a DOCTYPE — so
    refusing one closes the xml.etree attack surface without taking a defusedxml
    dependency (this family is stdlib-only).
    """
    if _DOCTYPE_RE.search(text[:4096]):
        raise ValueError("refusing a DOCTYPE declaration (entity-expansion risk)")
    try:
        # S314: the DOCTYPE refusal above removes the entity-expansion vector,
        # which is the only xml.etree exposure defusedxml would add here.
        root = ET.fromstring(text)  # noqa: S314
    except ET.ParseError as exc:
        raise ValueError(f"not parseable XML: {exc}") from exc
    tag = root.tag.rsplit("}", 1)[-1]
    if tag not in ("urlset", "sitemapindex"):
        raise ValueError(f"root element is <{tag}>, expected <urlset> or <sitemapindex>")
    child_tag = "url" if tag == "urlset" else "sitemap"
    entries = []
    for node in root:
        if node.tag.rsplit("}", 1)[-1] != child_tag:
            continue
        got: dict[str, Any] = {"loc": "", "lastmod": None, "changefreq": None,
                               "priority": None, "source": child_tag}
        for field in node:
            key = field.tag.rsplit("}", 1)[-1]
            if key in got:
                got[key] = (field.text or "").strip()
        entries.append(got)
    return {"kind": tag, "entries": entries, "count": len(entries)}


# ---- write / diff -----------------------------------------------------------


def write_files(files: list[dict[str, Any]], out_dir: str | Path) -> list[str]:
    """Write each rendered file into out_dir as UTF-8 bytes with LF endings.

    write_bytes, not write_text: text mode would translate LF to CRLF on
    Windows, and this generator's whole contract is byte-identical output
    across machines.
    """
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for f in files:
        p = d / f["name"]
        p.write_bytes(f["xml"].encode("utf-8"))
        written.append(str(p))
    return written


def diff_files(
    files: list[dict[str, Any]], out_dir: str | Path, *, context: int = 3
) -> dict[str, Any]:
    """Compare the rendered set against what is on disk (the deploy gate).

    Drift means the site's content changed since the last commit of the
    sitemap — never that the generator ran twice, because the output carries no
    timestamp. Files present on disk that the plan no longer produces (a stale
    shard left over from a bigger URL set) are reported as `stale`, since they
    would keep being served.
    """
    d = Path(out_dir)
    missing, changed, unchanged, diff_lines = [], [], [], []
    planned = {f["name"] for f in files}
    for f in files:
        p = d / f["name"]
        if not p.exists():
            missing.append(f["name"])
            continue
        have = p.read_bytes().decode("utf-8", errors="replace")
        if have == f["xml"]:
            unchanged.append(f["name"])
            continue
        changed.append(f["name"])
        diff_lines.extend(
            difflib.unified_diff(
                have.splitlines(),
                f["xml"].splitlines(),
                fromfile=f"{f['name']} (on disk)",
                tofile=f"{f['name']} (generated)",
                lineterm="",
                n=context,
            )
        )
    stale = sorted(
        p.name
        for p in (d.glob(f"{Path(files[0]['name']).stem}-*.xml") if files else [])
        if p.name not in planned
    )
    return {
        "drift": bool(missing or changed or stale),
        "missing": missing,
        "changed": changed,
        "unchanged": unchanged,
        "stale": stale,
        "diff": diff_lines,
    }


def summarize_files(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact file-set report for the JSON envelope."""
    return {
        "files": [
            {"name": f["name"], "kind": f["kind"], "urls": f["urls"], "bytes": f["bytes"]}
            for f in files
        ],
        "file_count": len(files),
        "urls": sum(f["urls"] for f in files),
        "sharded": any(f["kind"] == "sitemapindex" for f in files),
        "bytes": sum(f["bytes"] for f in files),
    }
