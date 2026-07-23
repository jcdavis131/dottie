# Solo personal project, no connection to employer, built with public/free-tier only
"""Links — broken-link verification riding the crawler core (openswap #4:
Ahrefs broken-link / Dr. Link Check).

Everything deterministic lives here: the internal-link survey over the seo
crawl store (a link is verified against the CRAWL RESULTS — zero refetches),
the dict-adjacency internal link graph with orphan-page and link-to-redirect
reports, the external verifier (HEAD-then-GET fallback, retry/backoff,
per-domain rate limiting, wall-clock budget — clock and sleep are injected so
politeness is unit-testable), the local docs checker (href/src extraction via
html.parser plus a markdown pass, anchor fragments validated against parsed
element ids and GitHub-style heading slugs), and the sqlite3 status store
whose runs are diffable (new-broken / fixed / still-broken). Real I/O stays
out: the `links` plugin CLI supplies the urllib HEAD/GET prober and injects it
into verify_external() as a callable (the seo/uptime pattern), so the whole
pipeline is unit-testable fully offline.

The external allowlist is config (policy-as-config): hosts in
`external_allow` are trusted without a fetch. Which external hosts may be
fetched AT ALL is not decided here — the CLI gates every candidate URL
through the manifest domain allowlist and the persisted user allowlist
(default-deny) before the prober ever sees it.

Extension points:
- Scheduled runs: `scout links check <site> --external --fail-on error` is the
  weekly-cron / per-deploy gate; `scout links diff <site> --fail-on-new` turns
  run-over-run regressions into a CI signal.
- Graph exports: link_survey()["graph"] is plain dict adjacency — `scout links
  graph --dot` feeds Graphviz, and the same dict can feed the SEO auditor's
  reports without re-crawling.
- Site-mode anchor validation: seo.parse_page defrags links and stores no
  element ids, so fragment checks currently cover local docs only; storing
  fragments + ids in the seo facts would extend them to crawled sites.
- allowlist widening: external_allow in a JSON --config file needs no code
  edit to trust a new host.
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

from bigbang.core import openswap, seo

if TYPE_CHECKING:
    from collections.abc import Callable

USER_AGENT = "scout-links"
DB_REL = Path(".scout") / "links.db"
SCHEMA_VERSION = "1"
# One source of truth for checkable docs — extension-list drift between core
# and CLI is a known bug class in this repo, so the CLI imports this. HTML
# extensions come from the seo core (the crawler substrate this adapter rides).
DOC_EXTS = (*seo.HTML_EXTS, ".md")

# States a diff counts as broken (transport failure is broken until proven up).
BROKEN_STATES = ("broken", "unreachable")

DEFAULT_CONFIG: dict[str, Any] = {
    # hosts (exact or dot-suffix) trusted without fetching — reported as
    # 'allowlisted', never probed
    "external_allow": [],
    "per_domain_delay_s": 1.0,
    "retry_attempts": 2,
    "retry_backoff_s": 0.25,
    # wall-clock cap for one external pass; leftovers report 'unverified'
    "budget_s": 60.0,
}


def load_config(path: str | None = None) -> dict[str, Any]:
    """DEFAULT_CONFIG overlaid with an optional JSON file (seo.load_config
    semantics: scalars/lists replace, unknown keys raise for fail_agent)."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config file must be a JSON object")
        for key, val in raw.items():
            if key not in cfg:
                raise ValueError(f"unknown config key {key!r} (known: {sorted(cfg)})")
            cfg[key] = val
    allow = cfg["external_allow"]
    if not (isinstance(allow, list) and all(isinstance(x, str) for x in allow)):
        raise ValueError("config 'external_allow': must be a list of hosts")
    for key in ("per_domain_delay_s", "retry_backoff_s", "budget_s"):
        v = cfg[key]
        if not (isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0):
            raise ValueError(f"config {key!r}: needs a number >= 0, got {v!r}")
    n = cfg["retry_attempts"]
    if not (isinstance(n, int) and not isinstance(n, bool) and n >= 0):
        raise ValueError(f"config 'retry_attempts': needs an int >= 0, got {n!r}")
    return cfg


def host_allowed(host: str, allow: list[str]) -> bool:
    """Exact-host or dot-suffix match, same semantics as the policy engine."""
    h = (host or "").lower()
    for entry in allow:
        want = (entry or "").strip().lower()
        if want and (h == want or h.endswith("." + want)):
            return True
    return False


# ---- internal survey: the crawl store IS the verifier -----------------------


def link_survey(
    rows: list[dict[str, Any]], *, frontier: dict[str, str] | None = None
) -> dict[str, Any]:
    """Verify every internal link against the crawl results and build the
    graph — zero fetches by construction.

    `rows` is seo.site_rows() output; `frontier` optionally maps url -> state
    so an uncrawled target can say WHY (pending budget vs robots-skipped).
    Internal states: ok | broken (target answered >= 400) | unreachable
    (target's fetch failed at crawl time) | redirect (target 3xx-hopped — link
    the final URL instead) | uncrawled (not in the store; unverifiable until
    the crawl budget covers it). Orphans are crawled HTML pages at depth > 0
    with zero inbound internal links — rare in a single BFS pass (discovery
    implies an inbound edge) but real once a store accretes passes or links
    rot out from under a page.
    """
    by_url = {r["url"]: r for r in rows}
    graph: dict[str, list[str]] = {}
    internal: dict[str, dict[str, Any]] = {}
    external: dict[str, dict[str, Any]] = {}
    inbound: dict[str, int] = {}
    for r in rows:
        facts = r.get("facts")
        if not facts:
            continue
        page = r["url"]
        links = facts.get("links") or {}
        targets = sorted(set(links.get("internal") or []))
        graph[page] = targets
        for t in targets:
            if t != page:
                inbound[t] = inbound.get(t, 0) + 1
            internal.setdefault(t, {"refs": []})["refs"].append(page)
        for x in links.get("external") or []:
            external.setdefault(x, {"refs": []})["refs"].append(page)
    for target, rec in internal.items():
        rec["refs"] = sorted(rec["refs"])
        rec["status"] = None
        row = by_url.get(target)
        if row is None:
            rec["state"] = "uncrawled"
            rec["detail"] = (frontier or {}).get(target) or "not in frontier"
        elif row["status"] is None:
            rec["state"] = "unreachable"
            rec["detail"] = row.get("error") or "fetch failed at crawl time"
        elif row["status"] >= 400:
            rec["state"] = "broken"
            rec["status"] = row["status"]
            rec["detail"] = f"http {row['status']}"
        elif row.get("redirects"):
            rec["state"] = "redirect"
            rec["status"] = row["status"]
            rec["detail"] = f"-> {row.get('final_url') or '?'}"
        else:
            rec["state"] = "ok"
            rec["status"] = row["status"]
            rec["detail"] = None
    for rec in external.values():
        rec["refs"] = sorted(rec["refs"])
    orphans = sorted(
        u
        for u, r in by_url.items()
        if r.get("facts") and int(r.get("depth") or 0) > 0 and inbound.get(u, 0) == 0
    )
    return {"graph": graph, "internal": internal, "external": external,
            "orphans": orphans}


# ---- external verification: HEAD-then-GET under politeness ------------------


def verify_external(
    urls: list[str],
    probe: Callable[[str, str], dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, dict[str, Any]]:
    """url -> {state, status, method, detail, attempts} without opening a
    socket here — `probe(url, method)` must return {"status": int|None,
    "error": str|None} and never raise (the CLI injects the urllib prober;
    tests inject fakes — the offline invariant).

    Per URL: HEAD first, GET whenever HEAD did not answer < 400 (servers that
    404/405 a HEAD but 200 a GET are common — GET is the authority). The
    HEAD+GET cycle retries with doubling backoff only on retryable outcomes
    (transport failure, 5xx, 429); a plain 4xx is an answer. Politeness:
    consecutive probes to one host wait per_domain_delay_s apart, and once
    budget_s of wall clock is spent, remaining urls report 'unverified'
    rather than blowing the invocation's time box.
    """
    cfg = config or DEFAULT_CONFIG
    delay = float(cfg["per_domain_delay_s"])
    attempts = int(cfg["retry_attempts"])
    backoff = float(cfg["retry_backoff_s"])
    budget = float(cfg["budget_s"])
    allow = cfg["external_allow"]
    last_by_host: dict[str, float] = {}
    start = clock()
    out: dict[str, dict[str, Any]] = {}

    def polite(url: str, host: str, method: str) -> dict[str, Any]:
        wait = last_by_host.get(host, float("-inf")) + delay - clock()
        if wait > 0:
            sleep(wait)
        last_by_host[host] = clock()
        return probe(url, method)

    for url in urls:
        host = (urlsplit(url).hostname or "").lower()
        if host_allowed(host, allow):
            out[url] = {"state": "allowlisted", "status": None, "method": None,
                        "detail": "config external_allow", "attempts": 0}
            continue
        if clock() - start > budget:
            out[url] = {"state": "unverified", "status": None, "method": None,
                        "detail": f"budget {budget:g}s exhausted", "attempts": 0}
            continue
        n = 0
        r: dict[str, Any] = {"status": None, "error": "no probe ran"}
        method = None
        for i in range(attempts + 1):
            r = polite(url, host, "HEAD")
            n += 1
            method = "HEAD"
            s = r.get("status")
            if s is None or s >= 400:
                r = polite(url, host, "GET")
                n += 1
                method = "GET"
                s = r.get("status")
            if s is not None and s < 500 and s != 429:
                break
            if i < attempts:
                sleep(backoff * (2**i))
        s = r.get("status")
        if s is None:
            state, detail = "unreachable", r.get("error") or "no answer"
        elif s >= 400:
            state, detail = "broken", f"http {s}"
        else:
            state, detail = "ok", None
        out[url] = {"state": state, "status": s, "method": method,
                    "detail": detail, "attempts": n}
    return out


# ---- diagnostics: survey + external results -> the family schema ------------

_INTERNAL_RULES = {
    "broken": ("links:internal-broken", "error"),
    "unreachable": ("links:internal-unreachable", "warning"),
    "redirect": ("links:internal-redirect", "suggestion"),
    "uncrawled": ("links:internal-uncrawled", "info"),
}
_EXTERNAL_RULES = {
    "broken": ("links:external-broken", "error"),
    "unreachable": ("links:external-unreachable", "warning"),
}


def to_diagnostics(
    survey: dict[str, Any],
    external_results: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Actionable findings only — ok/allowlisted/unverified stay counts, not
    noise. `path` is the first referring page (where the fix happens); the
    facts keep no per-link line numbers, so positions stay 0."""
    diags: list[dict[str, Any]] = []

    def refs_note(refs: list[str]) -> str:
        return f" ({len(refs)} referring page{'s' if len(refs) != 1 else ''})"

    for target, rec in survey["internal"].items():
        hit = _INTERNAL_RULES.get(rec["state"])
        if hit is None:
            continue
        rule, sev = hit
        suggestion = None
        if rec["state"] == "redirect":
            suggestion = "link the final URL directly"
        elif rec["state"] == "uncrawled":
            suggestion = "raise --max-pages/--max-depth and re-crawl"
        diags.append(
            openswap.diagnostic(
                path=rec["refs"][0], line=0, col=0, rule=rule, severity=sev,
                message=f"{target} {rec['detail']}{refs_note(rec['refs'])}",
                suggestion=suggestion,
            )
        )
    for url, res in (external_results or {}).items():
        hit = _EXTERNAL_RULES.get(res.get("state") or "")
        if hit is None:
            continue
        rule, sev = hit
        refs = (survey["external"].get(url) or {}).get("refs") or ["?"]
        diags.append(
            openswap.diagnostic(
                path=refs[0], line=0, col=0, rule=rule, severity=sev,
                message=f"{url} {res.get('detail')}{refs_note(refs)}",
                suggestion=f"verified via {res.get('method')}"
                f" after {res.get('attempts')} probe(s)",
            )
        )
    for url in survey["orphans"]:
        diags.append(
            openswap.diagnostic(
                path=url, line=0, col=0, rule="links:orphan-page",
                severity="suggestion",
                message="no inbound internal links in the crawl graph",
                suggestion="link it from a crawled page or retire it",
            )
        )
    return openswap.sort_diagnostics(diags)


def state_counts(
    survey: dict[str, Any], external_results: dict[str, dict[str, Any]] | None = None
) -> dict[str, dict[str, int]]:
    """The day-one glance: how many links are in each state, per kind."""
    internal: dict[str, int] = {}
    for rec in survey["internal"].values():
        internal[rec["state"]] = internal.get(rec["state"], 0) + 1
    external: dict[str, int] = {}
    for res in (external_results or {}).values():
        st = res.get("state") or "?"
        external[st] = external.get(st, 0) + 1
    return {"internal": dict(sorted(internal.items())),
            "external": dict(sorted(external.items()))}


# ---- local docs: href/src + anchors, fully offline --------------------------

# elements whose reference attribute a docs tree must keep resolvable
_REF_ATTRS = {"a": "href", "link": "href", "img": "src", "script": "src",
              "iframe": "src", "source": "src", "video": "src", "audio": "src"}
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_MD_REF_DEF = re.compile(r"^\s*\[[^\]]+\]:\s+(\S+)")
_HTML_ID = re.compile(r"""\s(?:id|name)=["']([^"']+)["']""")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


class _DocParser(HTMLParser):
    """Tolerant href/src + element-id collector (html.parser never chokes)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[dict[str, Any]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        line, off = self.getpos()
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"].strip())
        if tag == "a" and a.get("name"):  # legacy anchors still anchor
            self.ids.add(a["name"].strip())
        attr = _REF_ATTRS.get(tag)
        if attr and a.get(attr):
            self.refs.append(
                {"target": a[attr].strip(), "tag": tag, "line": line, "col": off + 1}
            )

    handle_startendtag = handle_starttag


def anchor_slug(heading: str) -> str:
    """GitHub-style heading anchor: lowercase, punctuation dropped, each
    space becomes one hyphen (so doubled spaces double the hyphen)."""
    s = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return s.replace(" ", "-")


def parse_doc(text: str, suffix: str) -> dict[str, Any]:
    """One local doc -> {refs: [{target, tag, line, col}], ids: set}.

    HTML goes through html.parser; markdown gets inline/image links,
    reference definitions, heading slugs (duplicates suffixed -1, -2 the
    GitHub way), and any literal id=/name= attributes in embedded HTML.
    """
    if suffix.lower() in seo.HTML_EXTS:
        p = _DocParser()
        try:
            p.feed(text or "")
            p.close()
        except Exception:
            pass  # tolerant by contract, same as the crawler's parser
        return {"refs": p.refs, "ids": p.ids}
    refs: list[dict[str, Any]] = []
    ids: set[str] = set()
    slug_seen: dict[str, int] = {}
    for lineno, ln in enumerate((text or "").splitlines(), 1):
        m = _MD_HEADING.match(ln)
        if m:
            slug = anchor_slug(m.group(2))
            n = slug_seen.get(slug, 0)
            slug_seen[slug] = n + 1
            ids.add(slug if n == 0 else f"{slug}-{n}")
        for lm in _MD_LINK.finditer(ln):
            refs.append({"target": lm.group(1), "tag": "md",
                         "line": lineno, "col": lm.start() + 1})
        rm = _MD_REF_DEF.match(ln)
        if rm:
            refs.append({"target": rm.group(1), "tag": "md-ref",
                         "line": lineno, "col": rm.start(1) + 1})
        for im in _HTML_ID.finditer(ln):
            ids.add(im.group(1).strip())
    return {"refs": refs, "ids": ids}


def check_files(
    files: list[Path], *, root: Path | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Offline docs-tree check -> (family diagnostics, stats).

    Relative targets resolve against the referring file, root-absolute ("/x")
    against --root (skipped and counted when no root is given). Fragments
    validate against the target doc's parsed ids — cross-file targets outside
    the passed set are parsed on demand so a link INTO an unchecked doc still
    verifies. External http(s) refs are counted, never fetched (this is the
    pre-publish gate: zero network by construction); other schemes are
    skipped. Duplicate-target refs in one file collapse to the first
    occurrence to keep reports readable.
    """
    docs: dict[Path, dict[str, Any]] = {}
    for f in files:
        p = Path(f).resolve()
        docs[p] = parse_doc(p.read_text(encoding="utf-8", errors="replace"),
                            p.suffix)

    def doc_for(p: Path) -> dict[str, Any] | None:
        if p not in docs and p.suffix.lower() in DOC_EXTS and p.is_file():
            docs[p] = parse_doc(p.read_text(encoding="utf-8", errors="replace"),
                                p.suffix)
        return docs.get(p)

    diags: list[dict[str, Any]] = []
    stats = {"files": len(files), "external_refs": 0, "skipped_schemes": 0,
             "root_relative_skipped": 0, "checked_refs": 0}
    for f in sorted({Path(x).resolve() for x in files}):
        info = docs[f]
        seen: set[str] = set()
        for ref in info["refs"]:
            t = ref["target"].strip()
            if not t or t in seen:
                continue
            seen.add(t)
            if _SCHEME.match(t):
                if t.lower().startswith(("http://", "https://")):
                    stats["external_refs"] += 1
                else:
                    stats["skipped_schemes"] += 1
                continue
            stats["checked_refs"] += 1
            if t.startswith("#"):
                frag = unquote(t[1:])
                if frag and frag not in info["ids"]:
                    diags.append(openswap.diagnostic(
                        path=str(f), line=ref["line"], col=ref["col"],
                        rule="links:fragment-missing", severity="warning",
                        message=f"#{frag} not found in {f.name}",
                        suggestion="add the anchor or fix the fragment",
                    ))
                continue
            path_part, _, frag = t.partition("#")
            path_part = unquote(path_part.split("?", 1)[0])
            if path_part.startswith("/"):
                if root is None:
                    stats["root_relative_skipped"] += 1
                    continue
                target = (root / path_part.lstrip("/")).resolve()
            else:
                target = (f.parent / path_part).resolve()
            if not target.exists():
                diags.append(openswap.diagnostic(
                    path=str(f), line=ref["line"], col=ref["col"],
                    rule="links:file-missing", severity="error",
                    message=f"{t} -> {target} does not exist",
                    suggestion="fix the path or restore the file",
                ))
                continue
            if frag:
                tdoc = doc_for(target)
                if tdoc is not None and unquote(frag) not in tdoc["ids"]:
                    diags.append(openswap.diagnostic(
                        path=str(f), line=ref["line"], col=ref["col"],
                        rule="links:fragment-missing", severity="warning",
                        message=f"{t}: #{unquote(frag)} not in {target.name}",
                        suggestion="add the anchor or fix the fragment",
                    ))
    return openswap.sort_diagnostics(diags), stats


# ---- status store: runs diffable across time --------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    ts REAL NOT NULL,
    external_checked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_site ON runs(site, id);
CREATE TABLE IF NOT EXISTS link_status(
    run_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    status INTEGER,
    detail TEXT,
    ref_count INTEGER NOT NULL DEFAULT 0,
    first_ref TEXT,
    PRIMARY KEY(run_id, url)
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the link-status store — one row per link per
    run, so two runs diff into new-broken / fixed / still-broken."""
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


def record_run(
    conn: sqlite3.Connection,
    site: str,
    survey: dict[str, Any],
    external_results: dict[str, dict[str, Any]] | None = None,
    *,
    ts: float | None = None,
) -> int:
    """Persist one verification pass; returns the run id."""
    ext = external_results or {}
    cur = conn.execute(
        "INSERT INTO runs(site, ts, external_checked) VALUES(?, ?, ?)",
        (site, time.time() if ts is None else ts,
         int(any(r.get("method") for r in ext.values()))),
    )
    run_id = int(cur.lastrowid)
    for url, rec in survey["internal"].items():
        conn.execute(
            "INSERT OR REPLACE INTO link_status(run_id, url, kind, state,"
            " status, detail, ref_count, first_ref) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, url, "internal", rec["state"], rec["status"],
             rec["detail"], len(rec["refs"]), rec["refs"][0]),
        )
    for url, rec in survey["external"].items():
        res = ext.get(url) or {"state": "unverified", "status": None,
                               "detail": "external verification off"}
        conn.execute(
            "INSERT OR REPLACE INTO link_status(run_id, url, kind, state,"
            " status, detail, ref_count, first_ref) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, url, "external", res.get("state"), res.get("status"),
             res.get("detail"), len(rec["refs"]), rec["refs"][0]),
        )
    conn.commit()
    return run_id


def runs_for(conn: sqlite3.Connection, site: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, ts, external_checked FROM runs WHERE site = ? ORDER BY id",
            (site,),
        )
    ]


def diff_runs(
    conn: sqlite3.Connection,
    site: str,
    *,
    run_a: int | None = None,
    run_b: int | None = None,
) -> dict[str, Any]:
    """Compare two runs (default: the latest two). Broken means a state in
    BROKEN_STATES; links absent from a run land in added/removed so a diff
    never silently conflates 'gone' with 'fixed'."""
    runs = runs_for(conn, site)
    ids = [r["id"] for r in runs]
    if run_a is None or run_b is None:
        if len(ids) < 2:
            raise ValueError(f"need two runs for {site!r}, have {len(ids)}")
        run_a, run_b = ids[-2], ids[-1]
    for rid in (run_a, run_b):
        if rid not in ids:
            raise ValueError(f"run {rid} not found for {site!r} (have {ids})")

    def states(rid: int) -> dict[str, str]:
        return {
            r["url"]: r["state"]
            for r in conn.execute(
                "SELECT url, state FROM link_status WHERE run_id = ?", (rid,)
            )
        }

    a, b = states(run_a), states(run_b)
    broken_a = {u for u, s in a.items() if s in BROKEN_STATES}
    broken_b = {u for u, s in b.items() if s in BROKEN_STATES}
    return {
        "site": site,
        "run_a": run_a,
        "run_b": run_b,
        "new_broken": sorted(broken_b - broken_a - (set(b) - set(a))),
        "appeared_broken": sorted((set(b) - set(a)) & broken_b),
        "fixed": sorted((broken_a & set(b)) - broken_b),
        "still_broken": sorted(broken_a & broken_b),
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
    }
