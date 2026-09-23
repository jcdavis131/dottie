"""Stage 1: harvest real arXiv papers for the topics arxiviq tracks.

Each topic is asked twice through the arXiv API: the most relevant papers and
the most recent ones, so the pack mixes the canon with this month's work. No
fallback, no templated papers: a topic that does not answer is recorded as
failed in the snapshot's stats and simply contributes nothing.

Output: sources/papers.jsonl.gz (committed snapshot) + sources/harvest_stats.json.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

from .common import SOURCES, polite_get, write_jsonl

API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARX = "{http://arxiv.org/schemas/atom}"

# (tag, human label, arXiv search_query). The first eight are the topics the
# original arxiviq tracked; the last two widen toward decision models.
TOPICS: list[tuple[str, str, str]] = [
    ("world_models", "World models", 'abs:"world model" AND (cat:cs.LG OR cat:cs.AI OR cat:cs.CV)'),
    ("jepa", "Joint-embedding predictive architectures", 'abs:"joint embedding predictive" OR abs:"joint-embedding predictive" OR ti:JEPA'),
    ("imagebind", "Multimodal joint embeddings (ImageBind)", 'abs:ImageBind OR (abs:"joint embedding" AND abs:multimodal AND cat:cs.CV)'),
    ("v_jepa", "Video prediction in latent space (V-JEPA)", 'abs:"V-JEPA" OR (abs:video AND abs:"latent prediction" AND cat:cs.CV)'),
    ("pred_coding", "Predictive coding", 'abs:"predictive coding" AND (cat:cs.LG OR cat:cs.NE OR cat:q-bio.NC)'),
    ("hamiltonian", "Hamiltonian and Lagrangian networks", 'abs:"Hamiltonian neural network" OR abs:"Lagrangian neural network" OR abs:"Hamiltonian neural networks"'),
    ("train_dynamics", "Training dynamics", 'abs:"training dynamics" AND (cat:cs.LG OR cat:stat.ML)'),
    ("foundation_wm", "Foundation world models for robotics", 'abs:"world model" AND (cat:cs.RO OR abs:robot)'),
    ("decision_models", "Calibrated decision models", '(abs:"decision transformer" OR abs:"calibrated" AND abs:"decision") AND (cat:cs.LG OR cat:cs.AI)'),
    ("ssl_repr", "Self-supervised representation learning", 'abs:"self-supervised" AND abs:"representation learning" AND cat:cs.LG'),
]
TOPIC_LABELS = {t: label for t, label, _ in TOPICS}

_WS = re.compile(r"\s+")


def _text(el: ET.Element | None) -> str:
    return _WS.sub(" ", el.text or "").strip() if el is not None else ""


def parse_atom(xml_bytes: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)  # noqa: S314 - arXiv's own Atom feed
    out: list[dict[str, Any]] = []
    for e in root.findall(f"{ATOM}entry"):
        raw_id = _text(e.find(f"{ATOM}id"))
        m = re.search(r"arxiv\.org/abs/([^\s]+?)(v\d+)?$", raw_id)
        if not m:
            continue
        authors = []
        for a in e.findall(f"{ATOM}author"):
            name = _text(a.find(f"{ATOM}name"))
            if not name:
                continue
            affs = [_text(x) for x in a.findall(f"{ARX}affiliation") if _text(x)]
            authors.append({"name": name, "arxiv_affiliations": affs})
        cats = [c.get("term") for c in e.findall(f"{ATOM}category") if c.get("term")]
        prim = e.find(f"{ARX}primary_category")
        out.append(
            {
                "arxiv_id": m.group(1),
                "version": (m.group(2) or "v1").lstrip("v"),
                "title": _text(e.find(f"{ATOM}title")),
                "abstract": _text(e.find(f"{ATOM}summary")),
                "authors": authors,
                "published": _text(e.find(f"{ATOM}published")),
                "updated": _text(e.find(f"{ATOM}updated")),
                "primary_category": prim.get("term") if prim is not None else (cats[0] if cats else ""),
                "categories": cats,
                "comment": _text(e.find(f"{ARX}comment")),
                "journal_ref": _text(e.find(f"{ARX}journal_ref")),
                "doi": _text(e.find(f"{ARX}doi")),
            }
        )
    return out


def fetch(query: str, *, sort: str, n: int) -> list[dict[str, Any]]:
    # Parentheses stay literal: percent-encoded ones draw a 406 from the API.
    q = urllib.parse.urlencode({"search_query": query, "start": 0, "max_results": n, "sortBy": sort, "sortOrder": "descending"}, safe="():")
    # arXiv asks for no more than one request every three seconds.
    return parse_atom(polite_get(f"{API}?{q}", host_gap_s=3.2, timeout=90))


def harvest(per_topic_relevant: int, per_topic_recent: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    papers: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"topics": {}, "failed": []}
    for tag, _label, query in TOPICS:
        for sort, n in (("relevance", per_topic_relevant), ("submittedDate", per_topic_recent)):
            if n <= 0:
                continue
            try:
                got = fetch(query, sort=sort, n=n)
            except Exception as err:  # recorded, never papered over
                stats["failed"].append({"topic": tag, "sort": sort, "error": str(err)[:200]})
                continue
            stats["topics"].setdefault(tag, {})[sort] = len(got)
            for p in got:
                if not p["abstract"] or not p["title"]:
                    continue
                cur = papers.get(p["arxiv_id"])
                if cur is None:
                    p["topics"] = [tag]
                    p["found_by"] = [f"{tag}:{sort}"]
                    papers[p["arxiv_id"]] = p
                else:
                    if tag not in cur["topics"]:
                        cur["topics"].append(tag)
                    cur["found_by"].append(f"{tag}:{sort}")
    rows = sorted(papers.values(), key=lambda p: p["arxiv_id"])
    stats.update(
        {
            "papers": len(rows),
            "multi_topic": sum(1 for p in rows if len(p["topics"]) > 1),
            "harvested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "api": API,
            "synthetic": 0,
        }
    )
    return rows, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--relevant", type=int, default=90, help="most relevant papers per topic")
    ap.add_argument("--recent", type=int, default=60, help="most recent papers per topic")
    args = ap.parse_args(argv)
    rows, stats = harvest(args.relevant, args.recent)
    write_jsonl(SOURCES / "papers.jsonl.gz", rows)
    (SOURCES / "harvest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("papers", "multi_topic", "failed")}, indent=2))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
