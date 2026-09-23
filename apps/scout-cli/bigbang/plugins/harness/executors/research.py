"""The deep_research tier: real sources, cited answers.

Sources, in order:

* arXiv (``export.arxiv.org/api/query``). Always sends a User-Agent (the API
  answers 406 without one on some networks) and form-encodes the query with
  ``+`` for spaces (``%20`` also drew 406 here). Calls are spaced by
  ``DOTTIE_ARXIV_MIN_INTERVAL`` seconds (default 3, arXiv's published courtesy).
* Semantic Scholar (``api.semanticscholar.org``), only with
  ``SEMANTIC_SCHOLAR_API_KEY`` (the keyless API answers 429 under load; set
  ``DOTTIE_S2_ANON=1`` to try it anyway). A 429 is recorded, never retried.
* jarvisd memory recall (``GET $JARVIS_URL/api/recall``), only when ``JARVIS_URL`` is set.

The answer cites its sources as ``[n]``. With an LLM backend reachable
(:mod:`.llm_exec`) the answer is synthesised from the retrieved sources;
without one it is extractive (the goal's quoted title or arXiv id selects the
source, and a question word picks the field: id, first author, year,
category, title). Network failure of every source raises ExecutorUnavailable.
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from bigbang.plugins.harness.executors import llm_exec
from bigbang.plugins.harness.executors.base import ExecResult, ExecutorUnavailable

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
USER_AGENT = "dottie-router-probe/0.1 (+https://github.com/jcdavis131/dottie)"
_ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_ID_RE = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
_QUOTED = re.compile(r"[\"“']([^\"”']{8,})[\"”']")
_STOP = frozenset("a an the of in on for to and or is are was were what which who whose find paper titled "
                  "arxiv id identifier year first author category please give me that this with by from".split())
_LOCK = threading.Lock()
_LAST_CALL = [0.0]


def _get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})  # noqa: S310
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  (https only, fixed hosts)
        return resp.read()


def _arxiv_wait() -> None:
    try:
        gap = float(os.environ.get("DOTTIE_ARXIV_MIN_INTERVAL", "3"))
    except ValueError:
        gap = 3.0
    with _LOCK:
        wait = _LAST_CALL[0] + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.monotonic()


def parse_arxiv_feed(xml_bytes: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)  # noqa: S314
    out = []
    for e in root.findall("a:entry", _ATOM):
        raw_id = (e.findtext("a:id", "", _ATOM) or "").rsplit("/abs/", 1)[-1]
        m = _ID_RE.search(raw_id)
        if not m:
            continue
        cat = e.find("arxiv:primary_category", _ATOM)
        out.append({
            "id": m.group(1),
            "url": f"https://arxiv.org/abs/{m.group(1)}",
            "title": " ".join((e.findtext("a:title", "", _ATOM) or "").split()),
            "authors": [(a.findtext("a:name", "", _ATOM) or "").strip() for a in e.findall("a:author", _ATOM)],
            "year": (e.findtext("a:published", "", _ATOM) or "")[:4],
            "primary_category": cat.get("term") if cat is not None else None,
            "summary": " ".join((e.findtext("a:summary", "", _ATOM) or "").split())[:400],
            "origin": "arxiv",
        })
    return out


def arxiv_query(*, search: str | None = None, ids: list[str] | None = None, max_results: int = 5) -> list[dict[str, Any]]:
    """The arXiv API. ``ids`` are fetched one per request with no other parameter (the only
    shape this sandbox's egress was served; multi-id and ``max_results`` drew 406), then the
    ``/abs`` page (robots-allowed, 15 s crawl delay) when the API refuses."""
    if ids:
        out: list[dict[str, Any]] = []
        for i in ids:
            _arxiv_wait()
            try:
                out += parse_arxiv_feed(_get(f"{ARXIV_API}?{urllib.parse.urlencode({'id_list': i})}"))
            except urllib.error.HTTPError as exc:
                if exc.code not in (403, 406, 429):
                    raise
                out += arxiv_abs(i)
        return out
    _arxiv_wait()
    return parse_arxiv_feed(_get(f"{ARXIV_API}?{urllib.parse.urlencode({'search_query': search, 'max_results': max_results})}"))


_META = re.compile(r'<meta name="citation_(title|author|date|arxiv_id)" content="([^"]*)"')
_SUBJECT = re.compile(r'primary-subject">[^<(]*\(([a-z-]+(?:\.[A-Za-z-]+)?)\)')


def arxiv_abs(arxiv_id: str) -> list[dict[str, Any]]:
    """One paper's metadata from its ``/abs`` page citation meta tags (robots: Allow /abs, crawl-delay 15)."""
    with _LOCK:
        wait = _LAST_CALL[0] + 15.0 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.monotonic()
    page = _get(f"https://arxiv.org/abs/{arxiv_id}").decode("utf-8", "replace")
    meta: dict[str, list[str]] = {}
    for k, v in _META.findall(page):
        meta.setdefault(k, []).append(html.unescape(v))
    if "title" not in meta:
        return []
    subj = _SUBJECT.search(page)
    authors = [" ".join(reversed([p.strip() for p in a.split(",", 1)])) for a in meta.get("author", [])]
    return [{"id": arxiv_id, "url": f"https://arxiv.org/abs/{arxiv_id}", "title": meta["title"][0],
             "authors": authors, "year": (meta.get("date") or [""])[0][:4],
             "primary_category": subj.group(1) if subj else None, "summary": "", "origin": "arxiv"}]


def s2_search(query: str) -> tuple[list[dict[str, Any]], str | None]:
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    if not key and os.environ.get("DOTTIE_S2_ANON", "") != "1":
        return [], "semantic scholar skipped (no SEMANTIC_SCHOLAR_API_KEY)"
    url = f"{S2_API}?{urllib.parse.urlencode({'query': query[:200], 'limit': 3, 'fields': 'title,year,authors,externalIds,url'})}"
    try:
        body = json.loads(_get(url, headers={"x-api-key": key} if key else None))
    except urllib.error.HTTPError as exc:
        return [], f"semantic scholar HTTP {exc.code}" + (" (rate limited; not retried)" if exc.code == 429 else "")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return [], f"semantic scholar unreachable: {type(exc).__name__}"
    out = []
    for p in body.get("data") or []:
        arx = (p.get("externalIds") or {}).get("ArXiv")
        out.append({"id": arx or p.get("paperId"), "url": p.get("url"), "title": p.get("title"),
                    "authors": [a.get("name") for a in p.get("authors") or []], "year": str(p.get("year") or ""),
                    "primary_category": None, "summary": "", "origin": "semantic_scholar"})
    return out, None


def jarvis_recall(query: str) -> tuple[list[dict[str, Any]], str | None]:
    base = os.environ.get("JARVIS_URL", "").strip().rstrip("/")
    if not base:
        return [], None
    headers = {}
    if os.environ.get("JARVIS_BEARER"):
        headers["Authorization"] = f"Bearer {os.environ['JARVIS_BEARER']}"
    try:
        body = json.loads(_get(f"{base}/api/recall?{urllib.parse.urlencode({'q': query[:200], 'limit': 3})}",
                               headers=headers, timeout=5.0))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return [], f"jarvisd recall failed: {type(exc).__name__}"
    items = body if isinstance(body, list) else body.get("memories") or body.get("results") or body.get("items") or []
    return [{"id": f"memory:{it.get('id')}", "url": None, "title": str(it.get("text") or it.get("content") or "")[:160],
             "authors": [], "year": "", "primary_category": None, "summary": "", "origin": "jarvisd"}
            for it in items if isinstance(it, dict)], None


def _keywords(goal: str) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", goal.lower()) if t not in _STOP and len(t) > 2]
    return " AND ".join(f"all:{t}" for t in toks[:6])


def retrieve(goal: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Sources for ``goal`` and notes on what was skipped. ExecutorUnavailable when arXiv is unreachable."""
    ids = [m.group(1) for m in _ID_RE.finditer(goal)]
    quoted = _QUOTED.search(goal)
    try:
        if ids:
            sources = arxiv_query(ids=ids[:5], max_results=len(ids[:5]))
        elif quoted:
            sources = arxiv_query(search=f'ti:"{quoted.group(1)}"', max_results=5)
        else:
            q = _keywords(goal)
            sources = arxiv_query(search=q, max_results=5) if q else []
    except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError) as exc:
        raise ExecutorUnavailable(f"arXiv unreachable: {type(exc).__name__}: {exc}") from exc
    notes = []
    extra, note = s2_search(quoted.group(1) if quoted else goal)
    notes += [note] if note else []
    extra2, note2 = jarvis_recall(goal)
    notes += [note2] if note2 else []
    seen = {s["id"] for s in sources}
    sources += [s for s in extra + extra2 if s.get("id") and s["id"] not in seen]
    if quoted:  # the source whose title IS the quoted title goes first
        want = re.sub(r"\W+", " ", quoted.group(1).lower()).strip()
        sources.sort(key=lambda s: re.sub(r"\W+", " ", str(s.get("title") or "").lower()).strip() != want)
    return sources, notes


def extractive_answer(goal: str, top: dict[str, Any]) -> str:
    g = goal.lower()
    if "first author" in g:
        value = (top.get("authors") or ["?"])[0]
    elif "year" in g:
        value = top.get("year") or "?"
    elif "category" in g:
        value = top.get("primary_category") or "?"
    elif "arxiv id" in g or "identifier" in g or "arxiv number" in g:
        value = top.get("id")
    elif "title" in g:
        value = top.get("title")
    else:
        value = f"{top.get('title')}: {str(top.get('summary') or '')[:200]}"
    return f"{value} [1]"


def _listing(sources: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{i}] {s.get('id')} - {s.get('title')} ({', '.join((s.get('authors') or [])[:3])}, "
                     f"{s.get('year')}) {s.get('url') or ''}" for i, s in enumerate(sources, 1))


def run(goal: str, *, k: int = 3) -> ExecResult:
    t0 = time.perf_counter()
    sources, notes = retrieve(goal)
    sources = sources[: max(k, 1)]
    listing = _listing(sources)
    if not sources:
        return ExecResult(tier="deep_research", backend="arxiv", answer="no sources found", text="",
                          latency_ms=round((time.perf_counter() - t0) * 1000, 3), meta={"notes": notes})
    backend = "+".join(sorted({s["origin"] for s in sources}))
    try:
        res = llm_exec.complete(
            f"Task: {goal}\n\nSources:\n{listing}\n\nAnswer using only these sources and cite them as [n].",
            tier="deep_research")
    except ExecutorUnavailable as exc:
        notes.append(f"extractive answer ({exc})")
        answer = extractive_answer(goal, sources[0])
        return ExecResult(tier="deep_research", backend=backend, answer=answer,
                          text=f"{answer}\n\n{listing}", sources=sources, latency_ms=round((time.perf_counter() - t0) * 1000, 3),
                          meta={"notes": notes, "synthesis": "extractive"})
    res.backend = f"{backend}+{res.backend}"
    res.sources, res.text = sources, res.text + "\n\n" + listing
    res.latency_ms = round((time.perf_counter() - t0) * 1000, 3)
    res.meta = {**res.meta, "notes": notes, "synthesis": "llm"}
    return res
