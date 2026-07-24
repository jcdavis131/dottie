#!/usr/bin/env python3
"""Download all OpenStax K12 / AP textbook PDFs (openly licensed).

Source of truth: OpenStax CMS API (`books.Book` pages with non-empty
`k12book_subjects` and/or `is_ap=true`). PDFs come from
`assets.openstax.org` — the rights-holder CDN, not mirrors.

Each file gets a sidecar `.meta.json` with license + source_url for the
research-pdf ingest track (see docs/AGENTIC_CURRICULUM.md).

Usage:
  python scripts/download_openstax_k12.py \\
      --out data/research_inbox/openstax-k12 \\
      --only-live

Idempotent / resumable: skips files whose size matches Content-Length.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API = "https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&fields=*&limit=200"
UA = "dottie-openstax-k12/0.1 (personal OER curriculum; +https://github.com/jcdavis131/dottie)"


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "misc"


def fetch_catalog() -> list[dict]:
    req = urllib.request.Request(API, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    out: list[dict] = []
    for b in data["items"]:
        k12subs = b.get("k12book_subjects") or []
        if not (k12subs or b.get("is_ap")):
            continue
        cats = [s.get("subject_category") or s.get("subject_name") for s in k12subs]
        category = cats[0] if cats else ("AP" if b.get("is_ap") else "Uncategorized")
        pdf = b.get("high_resolution_pdf_url") or b.get("pdf_url")
        out.append(
            {
                "id": b["id"],
                "slug": b["meta"]["slug"],
                "title": b["title"],
                "state": b.get("book_state"),
                "is_ap": bool(b.get("is_ap")),
                "category": category,
                "subjects": [s.get("subject_name") for s in k12subs],
                "pdf_url": pdf,
                "license_name": b.get("license_name"),
                "license_url": b.get("license_url"),
                "license_version": b.get("license_version"),
                "html_url": b["meta"].get("html_url"),
                "webview": b.get("webview_rex_link") or b.get("webview_link"),
            }
        )
    return out


def head_length(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
    except Exception:  # noqa: BLE001
        return None


def download_one(book: dict, out_root: Path, force: bool = False) -> dict:
    if not book.get("pdf_url"):
        return {"slug": book["slug"], "status": "skip_no_pdf"}
    cat = slugify(book["category"])
    dest_dir = out_root / cat
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{book['slug']}.pdf"
    meta_path = dest_dir / f"{book['slug']}.meta.json"
    expected = head_length(book["pdf_url"])
    if dest.exists() and not force:
        if expected is None or dest.stat().st_size == expected:
            _write_meta(meta_path, book, dest)
            return {
                "slug": book["slug"],
                "status": "exists",
                "bytes": dest.stat().st_size,
                "path": str(dest),
            }
    tmp = dest.with_suffix(".pdf.partial")
    req = urllib.request.Request(book["pdf_url"], headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, tmp.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        tmp.replace(dest)
    except Exception as exc:  # noqa: BLE001
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return {"slug": book["slug"], "status": "error", "error": str(exc)}
    _write_meta(meta_path, book, dest)
    return {
        "slug": book["slug"],
        "status": "downloaded",
        "bytes": dest.stat().st_size,
        "path": str(dest),
    }


def _write_meta(meta_path: Path, book: dict, dest: Path) -> None:
    license_name = book.get("license_name") or "unknown"
    # Normalize to short token for ingest sidecars
    lic = "cc-by-4.0"
    url = (book.get("license_url") or "").lower()
    name = license_name.lower()
    if "noncommercial" in name or "by-nc" in url:
        lic = "cc-by-nc-sa-4.0" if "sharealike" in name or "sa" in url else "cc-by-nc-4.0"
    elif "sharealike" in name or "by-sa" in url:
        lic = "cc-by-sa-4.0"
    elif "attribution" in name or "by/" in url:
        lic = "cc-by-4.0"
    meta = {
        "title": book["title"],
        "license": lic,
        "license_name": license_name,
        "license_url": book.get("license_url"),
        "source_url": book.get("html_url") or book.get("webview"),
        "pdf_url": book.get("pdf_url"),
        "openstax_slug": book["slug"],
        "openstax_id": book["id"],
        "category": book["category"],
        "subjects": book.get("subjects"),
        "is_ap": book.get("is_ap"),
        "book_state": book.get("state"),
        "sha256_note": "compute via ingest_research_pdfs.py on extract",
        "bytes": dest.stat().st_size if dest.exists() else None,
        "attribution": (
            f"{book['title']} by OpenStax is licensed under {license_name}. "
            "Downloaded from the OpenStax CDN for personal OER training use."
        ),
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("data/research_inbox/openstax-k12"),
        help="inbox root (category subdirs created)",
    )
    ap.add_argument("--only-live", action="store_true", default=True)
    ap.add_argument("--include-retired", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--catalog-only", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.4, help="pause between launches")
    args = ap.parse_args()

    catalog = fetch_catalog()
    if args.include_retired:
        books = [b for b in catalog if b.get("pdf_url")]
    else:
        books = [
            b
            for b in catalog
            if b.get("pdf_url") and b.get("state") in {"live", "deprecated"}
        ]

    args.out.mkdir(parents=True, exist_ok=True)
    cat_path = args.out / "catalog.json"
    cat_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"catalog: {len(catalog)} k12/ap books → {cat_path}")
    print(f"download set: {len(books)} (workers={args.workers})")
    if args.catalog_only:
        return 0

    results: list[dict] = []
    # Serial-ish: submit with small sleep to be polite to CDN
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = []
        for b in sorted(books, key=lambda x: x["slug"]):
            futs.append(ex.submit(download_one, b, args.out, args.force))
            time.sleep(args.sleep)
        for fut in as_completed(futs):
            rec = fut.result()
            results.append(rec)
            print(f"{rec.get('status'):10} {rec.get('slug')} {rec.get('bytes', '')}")

    summary = {
        "downloaded": sum(1 for r in results if r["status"] == "downloaded"),
        "exists": sum(1 for r in results if r["status"] == "exists"),
        "errors": [r for r in results if r["status"] == "error"],
        "bytes": sum(r.get("bytes") or 0 for r in results if r.get("bytes")),
    }
    (args.out / "download_manifest.json").write_text(
        json.dumps({"summary": summary, "results": results}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"done: downloaded={summary['downloaded']} exists={summary['exists']} "
        f"errors={len(summary['errors'])} bytes={summary['bytes']/1e9:.2f}GB"
    )
    if summary["errors"]:
        for e in summary["errors"]:
            print("ERR", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
