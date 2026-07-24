#!/usr/bin/env python3
# Solo personal project, no connection to employer, built with public/free-tier only.
"""Harvest openly-licensed English books from OAPEN via OAI-PMH — the scaled path.

The REST wildcard search (`pull_oapen_books.py`) caps at ~600 records. OAI-PMH
enumerates the FULL catalog (~57k records) with `metadataPrefix=dim`, which
carries per-record `dc.language` + `dc.rights` (the CC license URL) — everything
the license+language gate needs, uncapped. For each qualifying (English,
training-safe CC) handle, the `.pdf.txt` is fetched via the REST bitstream API.

Reuses the license gate + text fetch from pull_oapen_books (same provenance SOP):
CC-BY / CC-BY-SA / CC0 only; ND always excluded (training is a derivative use);
NC excluded by default; dedup by content sha256; nothing auto-ingests.

Usage: python pull_oapen_oai.py --target 300 --full --out <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

from pull_oapen_books import (  # reuse the vetted gate + fetch + helpers
    OAPEN, UA, _get, _md, _first, gate_rights, fetch_text,
)

OAI = f"{OAPEN}/oai/request"
_HANDLE_PREFIX = "oai:library.oapen.org:"


def _local(tag: str) -> str:
    return tag.split("}")[-1]  # strip XML namespace


def _is_english(langs: list[str]) -> bool:
    return any(l in ("english", "en", "eng") for l in langs)


def oai_records(max_pages: int):
    """Yield (handle, langs, rights_urls) per OAI `dim` record, paginated via
    resumptionToken. Read-only."""
    token = None
    for _ in range(max_pages):
        url = (f"{OAI}?verb=ListRecords&resumptionToken={urllib.parse.quote(token)}"
               if token else f"{OAI}?verb=ListRecords&metadataPrefix=dim")
        raw = _get(url, as_json=False)
        root = ET.fromstring(raw)
        token = None
        for el in root.iter():
            lt = _local(el.tag)
            if lt == "resumptionToken":
                token = (el.text or "").strip() or None
            elif lt == "record":
                handle, langs, rights = None, [], []
                for sub in el.iter():
                    slt = _local(sub.tag)
                    txt = (sub.text or "").strip()
                    if slt == "identifier" and txt.startswith(_HANDLE_PREFIX):
                        handle = txt[len(_HANDLE_PREFIX):]
                    elif slt == "field":
                        elem = sub.get("element")
                        if elem == "language":
                            langs.append(txt.lower())
                        elif elem == "rights":
                            rights.append(txt)
                if handle:
                    yield handle, langs, rights
        if not token:
            break


def fetch_item(handle: str) -> dict:
    """REST item (metadata + bitstreams) for a handle — for text fetch + fields."""
    return _get(f"{OAPEN}/rest/handle/{handle}?expand=metadata,bitstreams")


def main() -> int:
    ap = argparse.ArgumentParser(description="OAI-PMH harvest of openly-licensed OAPEN books.")
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=int, default=12000)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--allow-nc", action="store_true")
    ap.add_argument("--max-pages", type=int, default=400, help="OAI pages scanned (88 records/page)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    jf = (out_dir / "oapen_open_books.jsonl").open("w", encoding="utf-8")  # incremental — checkpoint-safe
    n_books = 0
    seen: set[str] = set()
    seen_sha: set[str] = set()
    lic_hist: dict[str, int] = {}
    excluded: dict[str, int] = {}
    scanned = 0

    try:
        for handle, langs, rights in oai_records(args.max_pages):
            if n_books >= args.target:
                break
            scanned += 1
            if handle in seen:
                continue
            seen.add(handle)
            if not _is_english(langs):
                excluded["non-English"] = excluded.get("non-English", 0) + 1
                continue
            ok, code, license_url, reason = gate_rights(rights, args.allow_nc)
            if not ok:
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            try:
                item = fetch_item(handle)
                text, txt_link = fetch_text(item)
            except Exception as e:  # noqa: BLE001 — network; drop this book
                excluded[f"fetch failed: {type(e).__name__}"] = \
                    excluded.get("fetch failed", 0) + 1
                continue
            if not text or not text.strip():
                excluded["no .pdf.txt"] = excluded.get("no .pdf.txt", 0) + 1
                continue
            text = text.strip()
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if sha in seen_sha:
                excluded["duplicate content"] = excluded.get("duplicate content", 0) + 1
                continue
            seen_sha.add(sha)
            md = _md(item)
            stored = text if args.full else text[: args.max_chars]
            row = {
                "handle": handle, "item_url": f"{OAPEN}/handle/{handle}",
                "doi": _first(md, "oapen.identifier.doi"), "isbn": _first(md, "oapen.identifier.isbn"),
                "title": _first(md, "dc.title"), "language": _first(md, "dc.language"),
                "license": code, "license_url": license_url, "nc": bool(reason == "NonCommercial (allowed via --allow-nc)"),
                "publisher": _first(md, "publisher.name") or _first(md, "oapen.imprint"),
                "subjects": md.get("dc.subject.other") or md.get("dc.subject.classification") or [],
                "txt_url": f"{OAPEN}{txt_link}" if txt_link else None,
                "text_sha256": sha, "text_chars": len(text), "stored_chars": len(stored), "text": stored,
            }
            jf.write(json.dumps(row, ensure_ascii=False) + "\n")
            jf.flush()  # checkpoint each book — survive a kill/timeout
            n_books += 1
            lic_hist[code] = lic_hist.get(code, 0) + 1
            if n_books % 25 == 0:
                print(f"  ...{n_books} books ({scanned} scanned)", file=sys.stderr)
            time.sleep(0.15)
    except Exception as e:  # noqa: BLE001 — harvest error; keep what we have
        print(f"harvest stopped: {e}", file=sys.stderr)
    finally:
        jf.close()

    (out_dir / "oapen_open_books_manifest.json").write_text(json.dumps({
        "source": "OAPEN via OAI-PMH (metadataPrefix=dim) — full-catalog harvest",
        "classification": "REAL",
        "policy": {"included": ["CC-BY", "CC-BY-SA", "CC0"] + (["CC-BY-NC*"] if args.allow_nc else []),
                   "excluded": "*-ND, non-English, no CC license, duplicate content", "full_text": args.full},
        "counts": {"books": n_books, "scanned": scanned, "by_license": lic_hist, "excluded": excluded},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nwrote {n_books} books ({', '.join(f'{k}={v}' for k, v in sorted(lic_hist.items()))}); "
          f"scanned {scanned}; excluded {', '.join(f'{k}={v}' for k, v in sorted(excluded.items()))}",
          file=sys.stderr)
    return 0 if n_books else 1


if __name__ == "__main__":
    raise SystemExit(main())
