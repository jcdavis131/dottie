"""Stage 3: turn real arXiv papers into paper-skill packages with Paper2Agent.

This sits between `enrich` and `teacher prepare`:

    harvest -> enrich -> skillify -> teacher prepare -> teacher ingest -> curate

The teacher works from title + abstract only; skillify adds what the abstract
never contains: the full paper as verified, section-continuous text, embedded
figure crops, and machine-readable table CSVs, extracted from the PDF itself.
That enables the fulltext question families (see `teacher prepare --fulltext`).

How it runs (stdlib only here):
  PDF fetch  curl https://arxiv.org/pdf/<id>v<version> into data/skillify/pdf/
  prepare    paper_bundle.py prepare <pdf> --work <workdir> --name <id> --main <pdf>
  extract    paper_bundle.py extract --work <workdir>          (~100 s for 85 pages)
  review-aid paper_bundle.py review-aid --work <workdir>       (contact sheets + queue)
  build      paper_bundle.py build --work <workdir> --output sources/paper_skills/<id> --draft
  verify     paper_bundle.py verify --work <workdir>           (integrity, not strict)

paper_bundle.py is an APPROVED EXTERNAL TOOL run via subprocess, never imported
or vendored. It lives outside this repo; see locate_paper_bundle() for where it
is found (PAPER_BUNDLE env var, then ~/workspace/skills/paper2agent/...).

Governance, as for every factory stage:
  - Extraction from real PDFs only. Nothing here writes questions or labels.
  - Packages are committed UNREVIEWED (build --draft) for provenance, with
    reviewed:false in the manifest. A later review pass adjudicates the
    review-aid queue and rebuilds with --require-reviewed; only then may a
    package be called reviewed. Never claim reviewed from an extraction run.
  - Failed papers are recorded in skillify_stats.json, never papered over.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .common import DATA, SOURCES, polite_get, read_jsonl, sha256_file, write_jsonl

PDF_DIR = DATA / "skillify" / "pdf"
WORK_ROOT = DATA / "skillify" / "work"
PKG_ROOT = SOURCES / "paper_skills"
MANIFEST = SOURCES / "paper_skills.jsonl.gz"
STATS = SOURCES / "skillify_stats.json"

DEFAULT_BUNDLE = Path(os.path.expanduser("~/workspace/skills/paper2agent/paper2skill/scripts/paper_bundle.py"))

# --- state budget: dynamic by complexity (Cameron decision 4) -----------------
#
# Rule, stated plainly. Complexity is a deterministic score from what the
# extraction measured, never invented:
#
#     complexity = chars(paper.md)
#                + 2_000 * sections
#                + 3_000 * (figure crops + table CSVs)
#
# Tiers:
#   small   complexity <= 60_000   -> the whole paper.md is the state.
#   medium  complexity <= 300_000  -> intro/background, methods, results and
#                                     discussion/conclusion sections at full
#                                     length (matched by heading keywords).
#                                     If no headings match, fall back to the
#                                     whole text: prefer more, never less.
#   large   otherwise              -> a section-window over those same key
#                                     sections: the first 60k and the last 20k
#                                     characters, with an explicit truncation
#                                     marker in the middle (metadata, not
#                                     invented content).
#
# In every tier the figure/table caption lines (in-line "Figure N ..."/"Table N ..."
# references from paper.md, deduplicated, in document order) are appended, so
# the state always carries what the figures and tables claim.
#
# The teacher reads the full package; this budget is what the DECISION MODEL
# sees at test time, and it is recorded on each manifest row (state_tier).

FULL_MAX_SCORE = 60_000
SECTION_MAX_SCORE = 300_000
WINDOW_HEAD = 60_000
WINDOW_TAIL = 20_000
CAPTION_LINES_CAP = 120
CAPTION_CHARS_CAP = 12_000
TRUNC_MARKER = "\n\n[... middle of paper.md truncated by the state-budget window ...]\n\n"

HEADING_RE = re.compile(r"^#{1,4}\s+(.+?)\s*$", re.MULTILINE)
CAPTION_RE = re.compile(r"(?i)(?:^|[\s(])(Figure|Fig\.|Table|Tab\.)\s*S?\d+[a-zA-Z]?")

KEY_SECTIONS: dict[str, tuple[str, ...]] = {
    "intro": ("introduction", "background", "related work", "motivation", "overview"),
    "methods": ("method", "approach", "experiment setup", "experimental setup", "dataset", "data", "architecture", "implementation", "training", "model"),
    "results": ("result", "evaluation", "experiment", "ablation", "benchmark", "analysis", "finding"),
    "discussion": ("discussion", "conclusion", "limitation", "future work", "summary", "takeaway", "remarks"),
}


def split_sections(paper_md: str) -> list[tuple[str, str]]:
    """[(heading, body)] split on markdown headings; leading text before the first heading is kept as ('', body)."""
    parts = HEADING_RE.split(paper_md)
    # parts: [pre, h1, body1, h2, body2, ...]
    out: list[tuple[str, str]] = []
    pre = parts[0].strip()
    if pre:
        out.append(("", pre))
    for i in range(1, len(parts) - 1, 2):
        out.append((parts[i].strip(), parts[i + 1].strip()))
    return out


def select_key_sections(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The intro/methods/results/discussion sections, in document order, matched by heading keywords."""
    wanted = [kw for kws in KEY_SECTIONS.values() for kw in kws]
    picked = [(h, b) for h, b in sections if h and any(kw in h.lower() for kw in wanted)]
    return picked


def captions_from_text(paper_md: str) -> list[str]:
    """Caption proxy: every line with an in-line Figure/Table reference, deduplicated, in order.

    The extractor keeps most captions as in-line prose references, not clean
    caption blocks; this collects those lines. It is a deterministic subset of
    the package text — nothing is invented, rewritten or reordered.
    """
    seen: set[str] = set()
    out: list[str] = []
    total = 0
    for line in paper_md.splitlines():
        line = line.strip()
        if not line or not CAPTION_RE.search(line) or len(line) > 600:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        total += len(line)
        if len(out) >= CAPTION_LINES_CAP or total >= CAPTION_CHARS_CAP:
            break
    return out


def complexity_score(chars: int, n_sections: int, n_figures: int, n_tables: int) -> int:
    return chars + 2_000 * n_sections + 3_000 * (n_figures + n_tables)


def state_budget(paper_md: str, *, figure_count: int, table_count: int) -> dict[str, Any]:
    """Dynamic state budget by complexity. Returns {tier, state_text, complexity, captions, sections}."""
    sections = split_sections(paper_md)
    n_sections = sum(1 for h, _ in sections if h)
    score = complexity_score(len(paper_md), n_sections, figure_count, table_count)
    captions = captions_from_text(paper_md)
    caption_block = "\n".join(captions)

    def with_captions(text: str) -> str:
        text = text.rstrip()
        return f"{text}\n\n--- figure/table references ---\n{caption_block}" if caption_block else text

    if score <= FULL_MAX_SCORE:
        return {"tier": "full", "complexity": score, "sections": n_sections, "captions": len(captions), "state_text": with_captions(paper_md)}
    key = select_key_sections(sections)
    body = "\n\n".join(f"# {h}\n\n{b}" if h else b for h, b in (key or sections))
    if score <= SECTION_MAX_SCORE:
        return {"tier": "sections", "complexity": score, "sections": len(key) or n_sections, "captions": len(captions), "state_text": with_captions(body)}
    if len(body) <= WINDOW_HEAD + WINDOW_TAIL:
        windowed = body
    else:
        windowed = body[:WINDOW_HEAD] + TRUNC_MARKER + body[-WINDOW_TAIL:]
    return {"tier": "window", "complexity": score, "sections": len(key) or n_sections, "captions": len(captions), "state_text": with_captions(windowed)}


# --- subset selection ---------------------------------------------------------

def select_papers(papers: list[dict[str, Any]], limit: int | None, since_year: int | None) -> list[dict[str, Any]]:
    """Most-recent-first subset of papers, optionally bounded by --limit and --since-year."""
    def key(p: dict[str, Any]) -> str:
        return p.get("published") or ""
    rows = sorted(papers, key=key, reverse=True)
    if since_year is not None:
        rows = [p for p in rows if (p.get("published") or "")[:4].isdigit() and int(p["published"][:4]) >= since_year]
    return rows[: limit or None]


def pdf_url(arxiv_id: str, version: str | int | None) -> str:
    v = f"v{version}" if version else ""
    return f"https://arxiv.org/pdf/{arxiv_id}{v}"


def fetch_pdf(arxiv_id: str, version: str | int | None) -> Path:
    """Download the version-pinned PDF into the gitignored staging dir."""
    dest = PDF_DIR / f"{arxiv_id}.pdf"
    if dest.exists() and dest.stat().st_size > 0:
        head = dest.read_bytes()[:5]
        if head.startswith(b"%PDF"):
            return dest
    raw = polite_get(pdf_url(arxiv_id, version), host_gap_s=3.2, timeout=300)
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"not a PDF: {pdf_url(arxiv_id, version)}")
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def locate_paper_bundle() -> Path:
    env = os.environ.get("PAPER_BUNDLE")
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise FileNotFoundError(f"PAPER_BUNDLE={env} is not a file")
    if DEFAULT_BUNDLE.is_file():
        return DEFAULT_BUNDLE
    raise FileNotFoundError(
        "paper_bundle.py not found. Install the paper2agent skill "
        "(~/workspace/skills/paper2agent/) or set PAPER_BUNDLE to its paper_bundle.py."
    )


def run_bundle_step(bundle: Path, args: list[str], *, timeout: float) -> dict[str, Any]:
    """One paper_bundle.py step; returns its JSON result, raising with stderr on failure."""
    proc = subprocess.run([sys.executable, str(bundle), *args], capture_output=True, text=True, timeout=timeout)
    tail = (proc.stderr or proc.stdout or "")[-2000:]
    if proc.returncode != 0:
        raise RuntimeError(f"paper_bundle {' '.join(args[:2])} failed (exit {proc.returncode}): {tail.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"paper_bundle {' '.join(args[:2])} printed no JSON: {tail.strip()}")


def count_package(pkg: Path) -> dict[str, int]:
    """Measured facts about a built package: sections, figure crops, table CSVs."""
    paper_md = pkg / "references" / "paper.md"
    text = paper_md.read_text(encoding="utf-8") if paper_md.is_file() else ""
    figs = sum(1 for p in (pkg / "assets" / "figure").glob("*") if p.is_file()) if (pkg / "assets" / "figure").is_dir() else 0
    tables = sum(1 for p in (pkg / "assets" / "table").glob("*.csv") if p.is_file()) if (pkg / "assets" / "table").is_dir() else 0
    return {"sections": sum(1 for _ in HEADING_RE.finditer(text)), "figures": figs, "tables": tables, "chars": len(text)}


def manifest_record(arxiv_id: str, paper: dict[str, Any], pkg: Path, pdf: Path, *, verify_status: str, review_queue: dict[str, Any]) -> dict[str, Any]:
    counts = count_package(pkg)
    paper_md = pkg / "references" / "paper.md"
    text = paper_md.read_text(encoding="utf-8") if paper_md.is_file() else ""
    budget = state_budget(text, figure_count=counts["figures"], table_count=counts["tables"])
    return {
        "arxiv_id": arxiv_id,
        "title": paper.get("title", ""),
        "published": paper.get("published", ""),
        "package_path": f"sources/paper_skills/{arxiv_id}",
        "pdf_sha256": sha256_file(pdf),
        "pdf_bytes": pdf.stat().st_size,
        "sections": counts["sections"],
        "figure_count": counts["figures"],
        "table_count": counts["tables"],
        "captions": budget["captions"],
        "complexity_score": budget["complexity"],
        "state_tier": budget["tier"],
        "reviewed": False,
        "verification_status": verify_status,
        "review_queue": review_queue,
        "skillified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def bundle_name(arxiv_id: str) -> str:
    """paper_bundle --name requires lowercase hyphenated words (<=63 chars)."""
    return re.sub(r"[^a-z0-9]+", "-", arxiv_id.lower()).strip("-")[:63]


def skillify_paper(arxiv_id: str, paper: dict[str, Any], bundle: Path) -> dict[str, Any]:
    """Full extraction pipeline for one paper. Raises on any failure; the caller records it."""
    pdf = fetch_pdf(arxiv_id, paper.get("version"))
    work = WORK_ROOT / arxiv_id
    pkg = PKG_ROOT / arxiv_id
    # The package dir keeps the verbatim arxiv_id; only the bundle name is slugged.
    name = bundle_name(arxiv_id)
    run_bundle_step(bundle, ["prepare", str(pdf), "--work", str(work), "--name", name, "--title", paper.get("title", arxiv_id), "--main", str(pdf)], timeout=180)
    run_bundle_step(bundle, ["extract", "--work", str(work)], timeout=1800)
    aid = run_bundle_step(bundle, ["review-aid", "--work", str(work)], timeout=600)
    queue: dict[str, Any] = {
        "path": str(aid.get("queue", "")),
        "items": aid.get("queue_items", 0),
        "pages": aid.get("pages", 0),
    }
    run_bundle_step(bundle, ["build", "--work", str(work), "--output", str(pkg), "--draft"], timeout=900)
    verify = run_bundle_step(bundle, ["verify", "--work", str(work)], timeout=600)
    return manifest_record(arxiv_id, paper, pkg, pdf, verify_status=f"extracted-{verify.get('status', 'unknown')}", review_queue=queue)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="skillify at most N papers, most-recent-first")
    ap.add_argument("--since-year", type=int, help="only papers published in this year or later")
    args = ap.parse_args(argv)
    papers = read_jsonl(SOURCES / "papers.jsonl.gz")
    if not papers:
        print("no papers in sources/papers.jsonl.gz; run harvest first", file=sys.stderr)
        return 1
    manifest = {r["arxiv_id"]: r for r in read_jsonl(MANIFEST)}
    todo = select_papers(papers, args.limit, args.since_year)
    bundle = locate_paper_bundle()
    stats: dict[str, Any] = {"skillified": 0, "skipped_already": 0, "failed": [], "todo": len(todo)}
    for paper in todo:
        aid = paper["arxiv_id"]
        if aid in manifest and manifest[aid].get("verification_status", "").startswith("extracted"):
            stats["skipped_already"] += 1
            continue
        try:
            manifest[aid] = skillify_paper(aid, paper, bundle)
            stats["skillified"] += 1
            print(f"skillified {aid} ({manifest[aid]['state_tier']}, complexity {manifest[aid]['complexity_score']})")
        except Exception as err:  # recorded, never papered over
            stats["failed"].append({"arxiv_id": aid, "error": str(err)[:200]})
            print(f"FAILED {aid}: {err}", file=sys.stderr)
    stats["skillified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_jsonl(MANIFEST, sorted(manifest.values(), key=lambda r: r["arxiv_id"]))
    STATS.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("skillified", "skipped_already", "failed", "todo")}, indent=2))
    return 0 if stats["skillified"] or stats["skipped_already"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
