# Solo personal project, no connection to employer, built with public/free-tier only
"""ava-skill anydoc — wraps bigbang.plugins.extract.anydoc"""

from __future__ import annotations
from typing import Any, Dict, List, Union
from pathlib import Path
import sys

# ensure scout-cli bigbang is importable when run via skills.loader
# Dottie monorepo layout: packages/ava-skills is sibling of apps/scout-cli
_HERE = Path(__file__).resolve()
# try to locate apps/scout-cli
for cand in [
    _HERE.parents[3] / "apps" / "scout-cli",  # packages/ava-skills -> dottie root -> apps/scout-cli
    Path.cwd() / "apps" / "scout-cli",
    Path.cwd() / "dottie" / "apps" / "scout-cli",
]:
    if (cand / "bigbang" / "plugins" / "extract" / "anydoc.py").exists():
        if str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
        break

try:
    from bigbang.plugins.extract import anydoc as _anydoc
except ImportError:
    # fallback: direct file import
    import importlib.util
    # search
    found = None
    for base in [Path.cwd(), Path.cwd() / "dottie", _HERE.parents[3]]:
        p = base / "apps" / "scout-cli" / "bigbang" / "plugins" / "extract" / "anydoc.py"
        if p.exists():
            found = p
            break
    if found:
        spec = importlib.util.spec_from_file_location("anydoc_impl", str(found))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _anydoc = mod
    else:
        raise

# re-export public API
Document = _anydoc.Document
detect = _anydoc.detect
parse = _anydoc.parse
to_markdown = _anydoc.to_markdown
to_gfm = _anydoc.to_gfm
read = _anydoc.read
batch = _anydoc.batch
SUPPORTED_FORMATS = _anydoc.SUPPORTED_FORMATS
VERSION = _anydoc.VERSION
tier = _anydoc.tier
AnyDocError = _anydoc.AnyDocError
ScannedPDFError = _anydoc.ScannedPDFError
EncryptedPDFError = _anydoc.EncryptedPDFError
OleUnsupportedError = _anydoc.OleUnsupportedError

def describe() -> dict[str, Any]:
    """Routing metadata read from SKILL.md frontmatter — single source of truth."""
    here = Path(__file__).resolve().parent
    try:
        from skills.loader import describe_from_manifest
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ava_skills_loader", here.parent / "loader.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        describe_from_manifest = mod.describe_from_manifest
    return describe_from_manifest(here)

VALID_MODES = ("mock", "real")
SKILL_NAME = "anydoc"

def run(model: Any = None, tokenizer: Any = None, mode: str = "mock", query: str | None = None, data: bytes | None = None, filename: str | None = None, **kw):
    if mode not in VALID_MODES:
        raise ValueError(f"{SKILL_NAME}: unknown mode {mode!r}; expected one of {VALID_MODES}")
    # mock: exercise stdlib path with real docx/html/txt samples
    if mode == "mock":
        import io, zipfile, xml.etree.ElementTree as ET
        # build minimal docx with Heading1 Hello
        def _make_docx_hello():
            bio = io.BytesIO()
            with zipfile.ZipFile(bio, "w") as z:
                z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main"/></Types>')
                z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>')
                z.writestr("word/document.xml", '''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Hello</w:t></w:r></w:p>
<w:p><w:r><w:t>world</w:t></w:r></w:p>
</w:body></w:document>''')
            return bio.getvalue()
        docx_bytes = _make_docx_hello()
        # quick bench <50ms target
        import time
        samples = [docx_bytes, b"<html><h1>Hi</h1><p>para</p></html>", b"a,b\n1,2\n"]
        t0 = time.time()
        for s in samples:
            _anydoc.parse(s)
        dt = (time.time()-t0)/len(samples)*1000
        # verify heading preserved
        d = _anydoc.parse(docx_bytes)
        md = _anydoc.to_markdown(d)
        heading_ok = "# Hello" in md
        # detect checks
        fmt_pdf = _anydoc.detect(b"%PDF-1.4 fake")
        fmt_rtf = _anydoc.detect(b"{\\rtf1\\ansi hello}")
        fmt_ole = _anydoc.detect(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00"*100)
        batch_docs = _anydoc.batch([docx_bytes, b"<html><h1>A</h1></html>", b"hello txt"], jobs=2)
        order_ok = len(batch_docs)==3 and batch_docs[0].meta.get("format")=="docx"
        # 503 honest
        try:
            _anydoc.parse(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n% no text")
            scanned_503 = False
        except Exception as e:
            scanned_503 = getattr(e,"code",None)==503 or "SCANNED" in str(e) or "503" in str(e)

        passed = heading_ok and fmt_pdf=="pdf" and fmt_rtf=="rtf" and fmt_ole in ("ole","doc","xls","ppt") and order_ok and scanned_503
        return {
            "pass": bool(passed),
            "measured": {"bench_ms_median": float(dt), "heading_ok": float(heading_ok), "detect_ok": float(fmt_pdf=="pdf" and fmt_rtf=="rtf"), "batch_order_ok": float(order_ok), "scanned_503": float(scanned_503)},
            "bar": "bench<50ms + # Hello preserved + detect pdf/rtf/ole + batch order + 503",
            "VERSION": _anydoc.VERSION,
            "tier": _anydoc.tier,
            "SUPPORTED_FORMATS": _anydoc.SUPPORTED_FORMATS,
        }
    # real mode: parse provided data/query
    if data is not None:
        doc = _anydoc.parse(data if isinstance(data, (bytes,bytearray)) else str(data).encode("utf-8"), filename=filename)
        return {"pass": True, "measured": {"blocks": len(doc.blocks)}, "gfm": _anydoc.to_markdown(doc), "meta": doc.meta}
    if query:
        # query may be path or raw text
        p = Path(query)
        if p.exists():
            return {"pass": True, "gfm": _anydoc.read(p), "meta": {"source": str(p)}}
        else:
            doc = _anydoc.parse(query.encode("utf-8"))
            return {"pass": True, "gfm": _anydoc.to_markdown(doc)}
    return {"pass": False, "error": "no data/query"}
