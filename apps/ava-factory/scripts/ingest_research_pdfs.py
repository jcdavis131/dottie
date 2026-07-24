#!/usr/bin/env python3
"""Local PDF/MD → research_corpus markdown chunks (training track).

Privacy: extraction is local only (PyMuPDF → pdfminer → pdftotext). Never sends
paper bytes to the network. Never downloads from upload mirrors.

Usage:
  python scripts/ingest_research_pdfs.py \\
      --inbox data/research_inbox/causal \\
      --out data/research_corpus \\
      --domain causal

Each PDF may ship a sidecar `<name>.meta.json`:
  {"license": "cc-by-4.0", "source_url": "https://...", "title": "..."}
Without a sidecar, ingest still works but records license=unknown (operator must
fix before activating mixture weight > 0).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def extract_text(pdf_path: Path) -> str:
    text = ""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        parts = [page.get_text() for page in doc]
        text = "\n".join(parts)
        if len(text.strip()) > 100:
            return text
    except Exception as exc:  # noqa: BLE001 — best-effort chain
        print(f"fitz failed: {exc}", file=sys.stderr)
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract

        text = pdfminer_extract(str(pdf_path))
        if len(text.strip()) > 100:
            return text
    except Exception as exc:  # noqa: BLE001
        print(f"pdfminer failed: {exc}", file=sys.stderr)
    try:
        result = subprocess.run(
            ["pdftotext", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and len(result.stdout) > 100:
            return result.stdout
    except Exception as exc:  # noqa: BLE001
        print(f"pdftotext failed: {exc}", file=sys.stderr)
    return text


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return s[:80] or "doc"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_meta(path: Path) -> dict:
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    if not meta_path.exists():
        # also accept foo.meta.json beside foo.pdf
        alt = path.parent / f"{path.stem}.meta.json"
        meta_path = alt if alt.exists() else meta_path
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def ingest_one(path: Path, out_domain: Path, manifest: list[dict]) -> None:
    meta = load_meta(path)
    if path.suffix.lower() == ".pdf":
        body = extract_text(path)
    else:
        body = path.read_text(encoding="utf-8", errors="replace")
    body = body.strip()
    if len(body) < 100:
        print(f"skip (too short): {path}", file=sys.stderr)
        return
    slug = slugify(meta.get("title") or path.stem)
    digest = sha256_file(path) if path.suffix.lower() == ".pdf" else hashlib.sha256(body.encode()).hexdigest()
    out_path = out_domain / f"{slug}.md"
    title = meta.get("title") or path.stem
    license_ = meta.get("license") or "unknown"
    source_url = meta.get("source_url") or ""
    front = (
        f"---\n"
        f"title: {title!r}\n"
        f"license: {license_}\n"
        f"source_url: {source_url!r}\n"
        f"sha256: {digest}\n"
        f"origin_file: {path.name!r}\n"
        f"---\n\n"
    )
    out_domain.mkdir(parents=True, exist_ok=True)
    out_path.write_text(front + body + "\n", encoding="utf-8")
    rec = {
        "slug": slug,
        "out": str(out_path),
        "license": license_,
        "source_url": source_url,
        "sha256": digest,
        "chars": len(body),
    }
    manifest.append(rec)
    print(f"wrote {out_path} ({len(body)} chars, license={license_})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inbox", type=Path, required=True, help="dir of PDFs/MD (+ optional sidecars)")
    ap.add_argument("--out", type=Path, required=True, help="research_corpus root")
    ap.add_argument(
        "--domain",
        default=None,
        help="domain shelf (math|statistics|causal|physics|psychology). "
        "Default: inbox directory name.",
    )
    args = ap.parse_args()
    inbox: Path = args.inbox
    if not inbox.is_dir():
        print(f"inbox not a directory: {inbox}", file=sys.stderr)
        return 2
    domain = (args.domain or inbox.name).lower()
    if domain in {"research_inbox", "inbox", "pdfs"}:
        print("refuse generic domain; pass --domain explicitly", file=sys.stderr)
        return 2
    out_domain = args.out / domain
    manifest: list[dict] = []
    paths = sorted(
        p
        for p in inbox.iterdir()
        if p.suffix.lower() in {".pdf", ".md", ".txt"} and p.is_file()
    )
    if not paths:
        print(f"no pdf/md/txt in {inbox}", file=sys.stderr)
        return 1
    for path in paths:
        ingest_one(path, out_domain, manifest)
    man_path = out_domain / "manifest.jsonl"
    with man_path.open("w", encoding="utf-8") as f:
        for rec in manifest:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    unknown = [r for r in manifest if r["license"] == "unknown"]
    if unknown:
        print(
            f"WARN: {len(unknown)} file(s) lack license sidecar — "
            "keep mixture weight at 0 until fixed.",
            file=sys.stderr,
        )
    print(f"manifest -> {man_path} ({len(manifest)} docs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
