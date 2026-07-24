#!/usr/bin/env python3
# Solo personal project, no connection to employer, built with public/free-tier only.
"""Pull open-access, openly-licensed books from OAPEN as a provenance-verified
training-corpus proposal. Read-only against OAPEN's public REST API
(library.oapen.org); Python stdlib only, no new deps.

OAPEN is the content host behind the Directory of Open Access Books (DOAB):
peer-reviewed scholarly books, each with a pre-extracted `.pdf.txt` plain-text
bitstream and a `dc.rights` license field. This is the "external validated
sources" the operator asked for — real, peer-reviewed, openly licensed.

Provenance SOP (tasks/artifacts/data_provenance_SOP.md): every book ships with
its verified license recorded, and only TRAINING-SAFE licenses are included:

  CC0, CC-BY, CC-BY-SA   -> include  (permissive; derivatives allowed)
  CC-BY-NC, CC-BY-NC-SA  -> excluded by default (NonCommercial); --allow-nc to
                            include, and each such row is flagged nc=true
  any *-ND (NoDerivatives)-> ALWAYS excluded — training a model on the text is a
                            derivative use, which an ND license forbids
  no dc.rights            -> excluded  (gratis OA is not an open license; a book
                            with no recorded license cannot be classified REAL)

Nothing here auto-ingests: the output is an audited proposal artifact.

Usage:
  python pull_oapen_books.py --target 10 --out <dir>            # sample (excerpts)
  python pull_oapen_books.py --target 500 --full --out <dir>    # full-text pull
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OAPEN = "https://library.oapen.org"
UA = "dottie-research/1.0 (solo personal project; OA books provenance audit)"

SAFE = {"CC0", "CC-BY", "CC-BY-SA"}       # permissive, derivatives allowed
NC = {"CC-BY-NC", "CC-BY-NC-SA"}          # NonCommercial (opt-in via --allow-nc)
# any license containing an "ND" component is always excluded (see is_safe)


def _get(url: str, *, as_json: bool = True, timeout: int = 90) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed host)
        data = r.read()
    return json.loads(data) if as_json else data


def license_code(rights_url: str | None) -> str | None:
    """Map a dc.rights value to a normalized CC license code, or None if the
    value is not a recognizable Creative Commons / public-domain license URL."""
    if not rights_url:
        return None
    u = rights_url.strip().lower()
    if "publicdomain" in u or "/zero/" in u or u.endswith("cc0"):
        return "CC0"
    if "creativecommons.org/licenses/" not in u:
        return None  # e.g. an all-rights-reserved statement — unverifiable as open
    try:
        tok = u.split("/licenses/")[1].split("/")[0]  # "by", "by-nc-nd", ...
    except IndexError:
        return None
    parts = [p for p in tok.split("-") if p]
    if not parts or parts[0] != "by":
        return None
    return "CC-" + "-".join(p.upper() for p in parts)


def is_safe(code: str | None, allow_nc: bool) -> tuple[bool, str]:
    """(included?, reason) for a normalized license code under the SOP rules."""
    if code is None:
        return False, "no verifiable open license"
    if "ND" in code.split("-"):
        return False, "NoDerivatives (training is a derivative use)"
    if code in SAFE:
        return True, "permissive"
    if code in NC:
        return (True, "NonCommercial (allowed via --allow-nc)") if allow_nc else (False, "NonCommercial")
    return False, f"unrecognized license ({code})"


def _md(item: dict) -> dict[str, list[str]]:
    """OAPEN metadata list -> {key: [values]} (a key may repeat, e.g. subjects)."""
    out: dict[str, list[str]] = {}
    for m in item.get("metadata", []) or []:
        out.setdefault(m.get("key", "?"), []).append(m.get("value"))
    return out


def _first(md: dict, key: str) -> str | None:
    v = md.get(key)
    return v[0] if v else None


def search_page(offset: int, limit: int) -> list[dict]:
    q = urllib.parse.quote("dc.rights:*creativecommons* AND dc.language:English")
    url = (f"{OAPEN}/rest/search?query={q}&limit={limit}&offset={offset}"
           "&expand=metadata,bitstreams")
    res = _get(url)
    return res if isinstance(res, list) else []


def fetch_text(item: dict) -> tuple[str | None, str | None]:
    """(text, retrieve_link) from the item's .pdf.txt bitstream, or (None, None)."""
    for b in item.get("bitstreams", []) or []:
        if str(b.get("name", "")).endswith(".pdf.txt") and b.get("retrieveLink"):
            link = b["retrieveLink"]
            raw = _get(f"{OAPEN}{link}", as_json=False)
            return raw.decode("utf-8", errors="replace"), link
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull openly-licensed OA books from OAPEN.")
    ap.add_argument("--target", type=int, default=10, help="training-safe books to collect")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--max-chars", type=int, default=12000,
                    help="chars of text stored per book unless --full (default 12000)")
    ap.add_argument("--full", action="store_true", help="store the complete book text")
    ap.add_argument("--allow-nc", action="store_true", help="also include NonCommercial CC books")
    ap.add_argument("--page", type=int, default=50, help="OAPEN search page size")
    ap.add_argument("--max-pages", type=int, default=40, help="safety cap on pages scanned")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    seen: set[str] = set()
    license_hist: dict[str, int] = {}
    excluded: dict[str, int] = {}
    scanned = 0

    for page in range(args.max_pages):
        if len(rows) >= args.target:
            break
        try:
            items = search_page(page * args.page, args.page)
        except Exception as e:  # noqa: BLE001 — network; report and stop paging
            print(f"search page {page} failed: {e}", file=sys.stderr)
            break
        if not items:
            break
        for item in items:
            if len(rows) >= args.target:
                break
            scanned += 1
            handle = item.get("handle")
            if not handle or handle in seen:
                continue
            seen.add(handle)
            md = _md(item)
            code = license_code(_first(md, "dc.rights"))
            ok, reason = is_safe(code, args.allow_nc)
            if not ok:
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            try:
                text, txt_link = fetch_text(item)
            except Exception as e:  # noqa: BLE001
                excluded[f"text fetch failed: {type(e).__name__}"] = \
                    excluded.get("text fetch failed", 0) + 1
                continue
            if not text or not text.strip():
                excluded["no .pdf.txt bitstream"] = excluded.get("no .pdf.txt bitstream", 0) + 1
                continue
            text = text.strip()
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            stored = text if args.full else text[: args.max_chars]
            rows.append({
                "handle": handle,
                "item_url": f"{OAPEN}/handle/{handle}",
                "doi": _first(md, "oapen.identifier.doi"),
                "isbn": _first(md, "oapen.identifier.isbn"),
                "title": _first(md, "dc.title"),
                "language": _first(md, "dc.language"),
                "license": code,
                "license_url": _first(md, "dc.rights"),
                "nc": code in NC,
                "publisher": _first(md, "publisher.name") or _first(md, "oapen.imprint"),
                "subjects": md.get("dc.subject.other") or md.get("dc.subject.classification") or [],
                "txt_url": f"{OAPEN}{txt_link}" if txt_link else None,
                "text_sha256": sha,
                "text_chars": len(text),
                "stored_chars": len(stored),
                "text": stored,
            })
            license_hist[code] = license_hist.get(code, 0) + 1
            print(f"  + [{code}] {str(_first(md,'dc.title'))[:60]} "
                  f"({len(text):,} chars)", file=sys.stderr)
            time.sleep(0.2)  # be polite to OAPEN

    jsonl = out_dir / "oapen_open_books.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    manifest = {
        "source": "OAPEN (library.oapen.org) — the content host behind DOAB",
        "query": "dc.rights:*creativecommons* AND dc.language:English",
        "classification": "REAL",
        "policy": {
            "included_licenses": sorted(SAFE) + (sorted(NC) if args.allow_nc else []),
            "always_excluded": "any *-ND (NoDerivatives); books with no dc.rights",
            "full_text": args.full,
            "max_chars": None if args.full else args.max_chars,
        },
        "counts": {
            "books_included": len(rows),
            "records_scanned": scanned,
            "by_license": license_hist,
            "excluded": excluded,
        },
    }
    (out_dir / "oapen_open_books_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nwrote {jsonl}: {len(rows)} books "
          f"({', '.join(f'{k}={v}' for k, v in sorted(license_hist.items()))})", file=sys.stderr)
    print(f"scanned {scanned} records; excluded: "
          f"{', '.join(f'{k}={v}' for k, v in sorted(excluded.items()))}", file=sys.stderr)
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
