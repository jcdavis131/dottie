# Solo personal project, no connection to employer, built with public/free-tier only
"""MegaWika adapter — claim passages joined with their independently-authored sources.

The multi-source history doctrine's strongest per-event cross-validation: each MegaWika
entry pairs a Wikipedia passage with the full text of the sources it CITES (distinct
authors, distinct sites). The adapter emits one document per entry:

    <passage>
    SOURCES (independently authored):
    [1] <url>
    <source excerpt>
    ...

Entries with fewer than ``MIN_SOURCES`` cited sources are dropped — a single-source
"cross-validation" would be the exact bias the doctrine forbids. Schema verified ON-BOX
2026-07-19 by streaming real rows through the collector image (script dataset; the HF
viewer cannot serve it): top-level ``article_title/article_text/entries``, where
``entries`` arrives either as a list of dicts or as HF's columnar struct-of-lists —
both handled; anything else returns None honestly.
"""

from __future__ import annotations

MIN_SOURCES = 2
MAX_SOURCES_PER_ENTRY = 3
SOURCE_EXCERPT_CHARS = 1500
MAX_ENTRIES_PER_ARTICLE = 4


def _entries_as_dicts(entries) -> list[dict]:
    """Normalize both observed layouts to a list of per-entry dicts."""
    if isinstance(entries, list):
        return [e for e in entries if isinstance(e, dict)]
    if isinstance(entries, dict):
        lists = {k: v for k, v in entries.items() if isinstance(v, list)}
        if not lists:
            return []
        n = min(len(v) for v in lists.values())
        return [{k: v[i] for k, v in lists.items()} for i in range(n)]
    return []


def _passage_text(entry: dict) -> str:
    p = entry.get("passage")
    if isinstance(p, dict):
        t = p.get("text")
        if isinstance(t, list):
            return "\n".join(str(x) for x in t if x)
        return str(t or "")
    return str(p or "")


def adapt_record(rec: dict) -> dict | None:
    entries = _entries_as_dicts(rec.get("entries"))
    title = str(rec.get("article_title") or "").strip()
    docs: list[str] = []
    for entry in entries[:MAX_ENTRIES_PER_ARTICLE]:
        passage = _passage_text(entry).strip()
        urls = entry.get("source_url") or []
        texts = entry.get("source_text") or []
        if not isinstance(urls, list) or not isinstance(texts, list):
            continue
        sources = [(str(u), str(t).strip()) for u, t in zip(urls, texts) if str(t).strip()]
        if not passage or len(sources) < MIN_SOURCES:
            continue                      # single-source claims are the bias we exclude
        blocks = [passage, "", "SOURCES (independently authored):"]
        for i, (u, t) in enumerate(sources[:MAX_SOURCES_PER_ENTRY], 1):
            blocks.append(f"[{i}] {u}")
            blocks.append(t[:SOURCE_EXCERPT_CHARS])
        docs.append("\n".join(blocks))
    if not docs:
        return None
    header = f"# {title}\n\n" if title else ""
    return {"text": header + "\n\n---\n\n".join(docs)}
