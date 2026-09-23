"""Stage 2: enrich harvested papers with who wrote them and where.

Three keyless sources, each optional and each recorded:
  Semantic Scholar  citation counts, venue, author ids and h-index (batch API)
  arXiv HTML        per-author affiliation lines from the paper's own header,
                    kept only where the LaTeXML author block names each author
                    separately and the name matches the arXiv author list
  ROR               affiliation string -> research organisation (id, type,
                    country), accepted only when ROR itself marks the match
                    as chosen; otherwise the raw string stays with no ROR id
  OpenAlex          authorships with institutions already linked to ROR (id,
                    type, country); the fullest source. Its keyless budget is
                    shared per IP, so `--openalex` runs as a separate pass,
                    with OPENALEX_API_KEY when set, and fills only authors the
                    other sources left without an affiliation.

Output: sources/enrich.jsonl.gz, sources/ror.jsonl.gz (committed snapshots),
resumable: papers already enriched are skipped on a re-run.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import unicodedata
import urllib.parse
from typing import Any

from .common import SOURCES, polite_get, read_jsonl, write_jsonl

S2_BATCH = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "title,year,venue,publicationVenue,citationCount,influentialCitationCount,referenceCount,externalIds,fieldsOfStudy,authors.authorId,authors.name,authors.hIndex,authors.affiliations"
ROR_URL = "https://api.ror.org/v2/organizations"

_CREATOR = re.compile(r'<span class="ltx_creator ltx_role_author">(.*?)</span>\s*(?=<span class="ltx_author_before">|</div>|<span class="ltx_creator)', re.S)
_PERSON = re.compile(r'<span class="ltx_personname">(.*?)</span>', re.S)
_AFF = re.compile(r'<span class="ltx_contact ltx_role_affiliation"><span class="ltx_contact_name">Affiliation: </span>(.*?)</span>', re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return _WS.sub(" ", re.sub(r"[^a-z ]", " ", s.lower())).strip()


def clean(s: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", s))).strip(" ,;")


def parse_html_affiliations(page: str, author_names: list[str]) -> dict[str, list[str]]:
    """name (as arXiv lists it) -> affiliation lines, for authors named one per block."""
    head = page[: page.find('class="ltx_abstract') if 'class="ltx_abstract' in page else 200_000]
    wanted = {norm_name(n): n for n in author_names}
    out: dict[str, list[str]] = {}
    for block in _CREATOR.findall(head):
        pm = _PERSON.search(block)
        if not pm:
            continue
        who = norm_name(clean(re.sub(r"<sup.*?</sup>", " ", pm.group(1), flags=re.S)))
        name = wanted.get(who)
        if not name:
            continue
        affs = [a for a in (clean(x) for x in _AFF.findall(block)) if 2 < len(a) < 200]
        if affs:
            out[name] = affs
    return out


def s2_batch(ids: list[str]) -> list[dict[str, Any] | None]:
    body = json.dumps({"ids": [f"ARXIV:{i}" for i in ids]}).encode()
    raw = polite_get(f"{S2_BATCH}?fields={S2_FIELDS}", host_gap_s=3.5, data=body, headers={"content-type": "application/json"}, timeout=120, tries=6)
    return json.loads(raw)


def ror_match(affiliation: str) -> dict[str, Any] | None:
    q = urllib.parse.urlencode({"affiliation": affiliation})
    d = json.loads(polite_get(f"{ROR_URL}?{q}", host_gap_s=0.25, timeout=30))
    for it in d.get("items", []):
        if not it.get("chosen"):
            continue
        org = it["organization"]
        names = [n["value"] for n in org.get("names", []) if "ror_display" in n.get("types", [])]
        loc = (org.get("locations") or [{}])[0].get("geonames_details", {})
        return {
            "ror": org.get("id"),
            "name": names[0] if names else None,
            "types": org.get("types", []),
            "country": loc.get("country_code"),
            "country_name": loc.get("country_name"),
            "score": it.get("score"),
        }
    return None


OPENALEX = "https://api.openalex.org/works"


def openalex_batch(ids: list[str]) -> dict[str, dict[str, Any]]:
    """arXiv id -> OpenAlex work (authorships only), looked up by the arXiv DOI."""
    flt = "doi:" + "|".join(f"10.48550/arxiv.{i}" for i in ids)
    q = {"filter": flt, "per-page": "50", "select": "doi,authorships"}
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        q["api_key"] = key
    d = json.loads(polite_get(f"{OPENALEX}?{urllib.parse.urlencode(q)}", host_gap_s=0.2, timeout=60))
    out = {}
    for w in d.get("results", []):
        doi = (w.get("doi") or "").lower()
        m = re.search(r"10\.48550/arxiv\.(.+)$", doi)
        if m:
            out[m.group(1)] = w
    return out


def enrich_openalex() -> dict[str, Any]:
    """Fill authors still without an affiliation from OpenAlex; record its institutions as ROR matches."""
    done = {r["arxiv_id"]: r for r in read_jsonl(SOURCES / "enrich.jsonl.gz")}
    cache = {r["affiliation"]: r for r in read_jsonl(SOURCES / "ror.jsonl.gz")}
    ids = sorted(done)
    stats = {"asked": len(ids), "works": 0, "authors_filled": 0}
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        try:
            works = openalex_batch(chunk)
        except Exception as err:
            stats["error"] = str(err)[:200]
            break
        stats["works"] += len(works)
        for aid, w in works.items():
            rec = done.get(aid)
            if not rec:
                continue
            by_name = {norm_name((a.get("author") or {}).get("display_name") or ""): a for a in w.get("authorships", [])}
            for a in rec["authors"]:
                if a["affiliations"]:
                    continue
                oa = by_name.get(norm_name(a["name"]))
                insts = [x for x in (oa or {}).get("institutions", []) if x.get("display_name")]
                if not insts:
                    continue
                a["affiliations"] = [x["display_name"] for x in insts]
                a["affiliation_source"] = "openalex"
                stats["authors_filled"] += 1
                for x in insts:
                    if x["display_name"] in cache and cache[x["display_name"]].get("match"):
                        continue
                    cache[x["display_name"]] = {
                        "affiliation": x["display_name"],
                        "match": None
                        if not x.get("ror")
                        else {"ror": x["ror"], "name": x["display_name"], "types": [x["type"]] if x.get("type") else [], "country": x.get("country_code"), "country_name": None, "score": None, "via": "openalex"},
                    }
    write_jsonl(SOURCES / "enrich.jsonl.gz", sorted(done.values(), key=lambda r: r["arxiv_id"]))
    write_jsonl(SOURCES / "ror.jsonl.gz", sorted(cache.values(), key=lambda r: r["affiliation"]))
    return stats


def enrich(limit: int | None, skip_html: bool) -> dict[str, Any]:
    papers = read_jsonl(SOURCES / "papers.jsonl.gz")
    if limit:
        papers = papers[:limit]
    done = {r["arxiv_id"]: r for r in read_jsonl(SOURCES / "enrich.jsonl.gz")}
    todo = [p for p in papers if p["arxiv_id"] not in done]
    stats: dict[str, Any] = {"papers": len(papers), "new": len(todo), "s2_found": 0, "html_structured": 0, "html_failed": 0}

    # Semantic Scholar, 100 per call.
    s2: dict[str, dict[str, Any]] = {}
    for i in range(0, len(todo), 100):
        chunk = [p["arxiv_id"] for p in todo[i : i + 100]]
        try:
            for aid, rec in zip(chunk, s2_batch(chunk), strict=False):
                if rec:
                    s2[aid] = rec
        except Exception as err:
            stats.setdefault("s2_errors", []).append(str(err)[:160])
    stats["s2_found"] = len(s2)

    for n, p in enumerate(todo, 1):
        aid = p["arxiv_id"]
        rec = s2.get(aid)
        names = [a["name"] for a in p["authors"]]
        html_affs: dict[str, list[str]] = {}
        html_status = "skipped"
        if not skip_html:
            try:
                page = polite_get(f"https://arxiv.org/html/{aid}", host_gap_s=2.0, timeout=60, tries=2).decode("utf-8", "ignore")
                html_affs = parse_html_affiliations(page, names)
                html_status = "structured" if html_affs else "unstructured"
            except Exception as err:
                html_status = f"unavailable:{str(err)[:60]}"
        stats["html_structured"] += html_status == "structured"
        stats["html_failed"] += html_status.startswith("unavailable")
        s2_authors = {norm_name(a.get("name") or ""): a for a in (rec or {}).get("authors") or []}
        authors = []
        for a in p["authors"]:
            s2a = s2_authors.get(norm_name(a["name"]), {})
            affs = html_affs.get(a["name"]) or a.get("arxiv_affiliations") or []
            src = "arxiv-html" if a["name"] in html_affs else ("arxiv-api" if a.get("arxiv_affiliations") else None)
            if not affs and s2a.get("affiliations"):
                affs, src = s2a["affiliations"], "semantic-scholar"
            authors.append({"name": a["name"], "affiliations": affs, "affiliation_source": src, "s2_author_id": s2a.get("authorId"), "h_index": s2a.get("hIndex")})
        venue = (rec or {}).get("publicationVenue") or {}
        done[aid] = {
            "arxiv_id": aid,
            "authors": authors,
            "html_affiliations": html_status,
            "s2": None
            if not rec
            else {
                "paper_id": rec.get("paperId"),
                "citation_count": rec.get("citationCount"),
                "influential_citation_count": rec.get("influentialCitationCount"),
                "reference_count": rec.get("referenceCount"),
                "venue": rec.get("venue") or None,
                "venue_type": venue.get("type"),
                "venue_name": venue.get("name"),
                "doi": (rec.get("externalIds") or {}).get("DOI"),
                "dblp": (rec.get("externalIds") or {}).get("DBLP"),
                "fields_of_study": rec.get("fieldsOfStudy") or [],
            },
            "enriched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if n % 50 == 0:
            write_jsonl(SOURCES / "enrich.jsonl.gz", sorted(done.values(), key=lambda r: r["arxiv_id"]))
            print(f"[enrich] {n}/{len(todo)} html_structured={stats['html_structured']}", flush=True)
    write_jsonl(SOURCES / "enrich.jsonl.gz", sorted(done.values(), key=lambda r: r["arxiv_id"]))

    # ROR over every distinct affiliation string, cached across runs.
    cache = {r["affiliation"]: r for r in read_jsonl(SOURCES / "ror.jsonl.gz")}
    strings = sorted({aff for r in done.values() for a in r["authors"] for aff in a["affiliations"]} - set(cache))
    for i, aff in enumerate(strings, 1):
        try:
            cache[aff] = {"affiliation": aff, "match": ror_match(aff)}
        except Exception as err:
            cache[aff] = {"affiliation": aff, "match": None, "error": str(err)[:120]}
        if i % 100 == 0:
            write_jsonl(SOURCES / "ror.jsonl.gz", sorted(cache.values(), key=lambda r: r["affiliation"]))
            print(f"[ror] {i}/{len(strings)}", flush=True)
    write_jsonl(SOURCES / "ror.jsonl.gz", sorted(cache.values(), key=lambda r: r["affiliation"]))
    stats["affiliation_strings"] = len(cache)
    stats["ror_matched"] = sum(1 for r in cache.values() if r.get("match"))
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--skip-html", action="store_true")
    ap.add_argument("--openalex", action="store_true", help="only the OpenAlex pass over papers already enriched")
    args = ap.parse_args(argv)
    if args.openalex:
        stats = enrich_openalex()
        (SOURCES / "openalex_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(stats, indent=2))
        return 0 if "error" not in stats else 1
    stats = enrich(args.limit, args.skip_html)
    (SOURCES / "enrich_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
