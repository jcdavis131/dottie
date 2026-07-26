#!/usr/bin/env python3
"""Download independent OER PDFs that map to OpenStax math subjects.

Reads configs/openstax_math_oer_equivalents.yaml and pulls every alternative
with status=verified_pdf + pdf_url from the rights-holder (not OpenStax CDN).

Usage:
  python scripts/download_math_oer_equivalents.py \\
      --out data/research_inbox/math-oer-equivalents
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML required: pip install pyyaml") from exc

UA = "dottie-math-oer-equivalents/0.1 (personal OER curriculum)"


def load_catalog(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def iter_verified(catalog: dict) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for row in catalog.get("equivalents") or []:
        for alt in row.get("alternatives") or []:
            if alt.get("status") != "verified_pdf" or not alt.get("pdf_url"):
                continue
            aid = alt["id"]
            if aid in seen:
                continue
            seen.add(aid)
            out.append(alt)
    for alt in catalog.get("extras") or []:
        if (
            alt.get("status") == "verified_pdf"
            and alt.get("pdf_url")
            and alt["id"] not in seen
        ):
            out.append(alt)
            seen.add(alt["id"])
    return out


def download(url: str, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # resume / skip
    req_head = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    expected = None
    try:
        with urllib.request.urlopen(req_head, timeout=60) as resp:
            cl = resp.headers.get("Content-Length")
            expected = int(cl) if cl else None
            ctype = resp.headers.get("Content-Type", "")
            if "pdf" not in ctype.lower() and expected and expected < 1000:
                return {"status": "error", "error": f"not a pdf content-type={ctype}"}
    except Exception:
        pass
    if dest.exists() and expected and dest.stat().st_size == expected:
        return {"status": "exists", "bytes": dest.stat().st_size}
    if dest.exists() and expected is None and dest.stat().st_size > 100_000:
        return {"status": "exists", "bytes": dest.stat().st_size}

    tmp = dest.with_suffix(dest.suffix + ".partial")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, tmp.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        tmp.replace(dest)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return {"status": "error", "error": str(exc)}
    return {"status": "downloaded", "bytes": dest.stat().st_size}


def write_meta(path: Path, alt: dict) -> None:
    meta = {
        "title": alt.get("title"),
        "license": alt.get("license"),
        "source_url": alt.get("source_url"),
        "pdf_url": alt.get("pdf_url"),
        "id": alt.get("id"),
        "status": alt.get("status"),
        "notes": alt.get("notes"),
        "attribution": (
            f"{alt.get('title')} — independent OER equivalent for OpenStax math shelf. "
            f"License: {alt.get('license')}. Source: {alt.get('source_url')}"
        ),
    }
    path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def coverage_report(catalog: dict) -> dict:
    rows = []
    for row in catalog.get("equivalents") or []:
        alts = row.get("alternatives") or []
        has_pdf = any(
            a.get("status") == "verified_pdf" and a.get("pdf_url") for a in alts
        )
        has_any = bool(alts)
        rows.append(
            {
                "openstax_slug": row["openstax_slug"],
                "openstax_title": row["openstax_title"],
                "n_alts": len(alts),
                "has_verified_pdf": has_pdf,
                "covered": has_any,
            }
        )
    return {
        "openstax_titles": len(rows),
        "covered": sum(1 for r in rows if r["covered"]),
        "with_verified_pdf": sum(1 for r in rows if r["has_verified_pdf"]),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--catalog",
        type=Path,
        default=Path("configs/openstax_math_oer_equivalents.yaml"),
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("data/research_inbox/math-oer-equivalents"),
    )
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    catalog = load_catalog(args.catalog)
    report = coverage_report(catalog)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "coverage_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"coverage: {report['covered']}/{report['openstax_titles']} OpenStax math titles "
        f"have ≥1 independent alt; {report['with_verified_pdf']} have verified PDFs"
    )
    for r in report["rows"]:
        flag = "PDF" if r["has_verified_pdf"] else ("ALT" if r["covered"] else "GAP")
        print(f"  [{flag}] {r['openstax_slug']}")
    if args.report_only:
        return 0

    verified = iter_verified(catalog)
    results = []
    for alt in verified:
        dest = args.out / f"{alt['id']}.pdf"
        print(f"fetch {alt['id']} …")
        rec = download(alt["pdf_url"], dest)
        rec["id"] = alt["id"]
        if rec["status"] in {"downloaded", "exists"}:
            write_meta(args.out / f"{alt['id']}.meta.json", alt)
        results.append(rec)
        print(f"  {rec['status']} {rec.get('bytes', '')} {rec.get('error', '')}")
        time.sleep(args.sleep)

    (args.out / "download_manifest.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    errs = [r for r in results if r["status"] == "error"]
    print(f"done: {len(results) - len(errs)} ok, {len(errs)} errors")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
