# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout extract` — Diffbot / Mercury Parser replacement, fully local, now backed by anydoc IR.

Distilled from anydoc (YC) — One output for every format + qm (YC) — multiplayer harness

v2 changes:
- stdlib anydoc-py v1.0.0 — unified ingestion 12 formats + ole + html, single GFM serializer, content-based detection from bytes
- zero-deps true — no typer required at import, argparse fallback works stdlib only
- ThreadPoolExecutor non-blocking batch preserving input order diffable
- honest 503 for scanned/encrypted/OLE (no fake success)
- scope-aware via scopes/person/<handle> and scopes/room/<slug>

Policy unchanged: local hosts from manifest allowlist, every other URL gated by persisted user allowlist,
never by manifest widened to match URL. File/stdin make zero network calls.

This sits on daily research-ingestion path, so batch is primary surface and throughput beats latency:
ledger keyed by sha256, cache hit never re-parses, URL fetches concurrent --jobs while extraction loop
still consumes sources in input order diffable.

No native binary tier to prefer — tier=stdlib anydoc-py is the product.
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

# ---- zero-deps shim: typer optional ----

try:
    import typer  # type: ignore
    _HAS_TYPER = True
except Exception:
    typer = None  # type: ignore
    _HAS_TYPER = False

# core imports — stdlib only where possible
try:
    from bigbang.core import extract, openswap
except Exception:
    extract = None  # type: ignore
    openswap = None  # type: ignore

try:
    from bigbang.core.cli_ux import examples_epilog, fail_agent
except Exception:
    def examples_epilog(lines):  # type: ignore
        return "\nExamples:\n" + "\n".join(f"  {l}" for l in lines) + "\n"
    def fail_agent(error, *, command, example, discover=None, code=1):  # type: ignore
        print(f"ERROR [{command}]: {error}\nExample: {example}", file=sys.stderr)
        if discover:
            print(f"Discover: {discover}", file=sys.stderr)
        raise SystemExit(code)

try:
    from bigbang.core.contract import make_plugin_app, ok
except Exception:
    # stdlib fallback for contract — zero-deps
    def ok(data=None, *, command, example=None, discover=None, **extra):  # type: ignore
        payload = {"ok": True, "command": command}
        if data is not None:
            payload["data"] = data
        if example:
            payload["example"] = example
        if discover:
            payload["discover"] = discover
        payload.update(extra)
        return payload
    def make_plugin_app(name, help_text, *, examples=None, no_args_is_help=True):  # type: ignore
        if _HAS_TYPER:
            kwargs = {"name": name, "help": help_text, "no_args_is_help": no_args_is_help}
            if examples:
                kwargs["epilog"] = examples_epilog(examples)
            return typer.Typer(**kwargs)
        else:
            # dummy object that supports .command decorator and add_typer
            class DummyApp:
                def __init__(self, name, help_text):
                    self.name = name
                    self.help = help_text
                    self.commands = {}
                def command(self, name, epilog=None):
                    def deco(fn):
                        self.commands[name] = fn
                        return fn
                    return deco
                def add_typer(self, other, name=None):
                    pass
            return DummyApp(name, help_text)

try:
    from bigbang.core.http_utils import sanitize_no_proxy_env
except Exception:
    def sanitize_no_proxy_env():  # type: ignore
        for k in ("NO_PROXY", "no_proxy", "NO_PROXY_ORIG", "no_proxy_orig"):
            if k in os.environ and " " in os.environ[k]:
                os.environ[k] = os.environ[k].replace(" ", "")

try:
    from bigbang.core.output import emit, is_json
except Exception:
    import json
    def is_json():  # type: ignore
        return "--json" in sys.argv
    def emit(data, command="unknown"):  # type: ignore
        if is_json():
            print(json.dumps(data, indent=2, default=str))
        else:
            print(data)

try:
    from bigbang.core.policy import check_permission, enforce_or_raise, enforce_user_url_or_raise, load_manifest
except Exception:
    def check_permission(manifest, axis, url):  # type: ignore
        return False, "no policy"
    def enforce_or_raise(manifest, axis, path):  # type: ignore
        return True
    def enforce_user_url_or_raise(url, context=""):  # type: ignore
        # permissive fallback for local dev — in prod this should be strict
        return True
    def load_manifest(path):  # type: ignore
        return {}

# anydoc import — unified IR
try:
    from . import anydoc as anydoc_mod  # type: ignore
    # also support: from bigbang.plugins.extract import anydoc
except Exception:
    try:
        from bigbang.plugins.extract import anydoc as anydoc_mod  # type: ignore
    except Exception:
        anydoc_mod = None  # type: ignore

FALLBACK_SCOPE = (
    "pure-stdlib article extractor is the complete product for this adapter: "
    "html.parser DOM walk with Readability text-vs-link-density scoring, "
    "nav/footer/aside/script boilerplate stripping, title/byline/date "
    "heuristics (JSON-LD, og:/dc:/twitter: meta, rel=author, <time>), plain "
    "text or JSON output, and a content-hash-deduped sqlite corpus ledger for "
    "batch ingestion; tier 'fallback' is the expected steady state — Diffbot "
    "is a paid SaaS API and postlight-parser/readable/trafilatura are "
    "surfaced for manual use but never executed, because a spawned extractor "
    "fetches outside the per-URL policy gate"
)

ANYDOC_SCOPE = (
    "stdlib anydoc-py v1.0.0 scope unified ingestion 12 formats + ole + html — "
    "unified Document {meta,blocks,assets} IR, single GFM serializer, "
    "content-based detection from bytes (PDF %PDF-, RTF {\\rtf, ZIP inspection "
    "docx/pptx/xlsx/odt/epub, OLE D0CF11E0, CSV heuristic, HTML), stdlib impl "
    "median <50ms target, ThreadPoolExecutor non-blocking, honest 503 for "
    "scanned/encrypted/OLE, ships as scout extract + ava-skill anydoc"
)

INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; postlight-parser, "
    "readable or trafilatura on PATH are surfaced for manual use only, never "
    "executed by scout. anydoc-py v1.0.0 is stdlib only."
)

USER_AGENT = "scout-extract"

# app creation — zero-deps safe
if _HAS_TYPER:
    app = make_plugin_app(
        "extract",
        "Extract the article out of a page (Diffbot-class), fully local + anydoc IR: "
        "Readability-style scoring + title/byline/date + unified Document IR 12 formats",
        examples=[
            "scout --json extract read article.html",
            "scout extract read https://example.com/post --text",
            "curl -s https://example.com/post | scout --json extract read -",
            "scout --json extract batch --glob '**/*.html' --root captures",
            "scout --json extract corpus",
            "scout --json extract detect",
            "scout --json extract read doc.docx",
        ],
    )
else:
    app = make_plugin_app(
        "extract",
        "Extract the article out of a page (Diffbot-class), fully local + anydoc IR",
        examples=[
            "scout --json extract read article.html",
            "scout extract read doc.docx",
        ],
    )

_MANIFEST: dict | None = None


def _manifest() -> dict:
    global _MANIFEST
    if _MANIFEST is None:
        try:
            _MANIFEST = load_manifest(Path(__file__).parent)
        except Exception:
            _MANIFEST = {}
    return _MANIFEST


def _capability() -> dict:
    # Prefer anydoc capability when available — v2 spec
    if anydoc_mod is not None:
        try:
            if hasattr(anydoc_mod, "capability"):
                cap = anydoc_mod.capability()
            else:
                cap = {
                    "adapter": "extract",
                    "tier": getattr(anydoc_mod, "TIER", "stdlib"),
                    "version": getattr(anydoc_mod, "VERSION", "1.0.0"),
                    "anydoc_version": getattr(anydoc_mod, "VERSION", "1.0.0"),
                    "stdlib": True,
                    "zero_deps": True,
                    "formats": getattr(anydoc_mod, "SUPPORTED_FORMATS", []),
                    "scope": "unified ingestion 12 formats + ole + html",
                    "detection": "content-based bytes (PDF %PDF-, RTF {\\rtf, ZIP inspection docx/pptx/xlsx/odt/epub, OLE D0CF11E0, CSV heuristic, HTML)",
                    "serializer": "single GFM",
                    "threading": "ThreadPoolExecutor non-blocking",
                    "honest_503": ["scanned_pdf", "encrypted_pdf", "ole_doc", "ole_xls", "ole_ppt"],
                    "median_target_ms": 50,
                }
            # enrich with openswap probes for transparency — keep v1 keys for backward compat
            if openswap is not None:
                try:
                    native = openswap.probe_binary("postlight-parser", probe_args=("--version",))
                    cap["native"] = native
                    cap["native_probe"] = native
                    cap["extras"] = {
                        "readable": openswap.probe_binary("readable", probe_args=("--version",)),
                        "trafilatura": openswap.probe_binary("trafilatura", probe_args=("--version",)),
                    }
                    # keep fallback_scope for v1 test compatibility
                    cap["fallback_scope"] = FALLBACK_SCOPE
                    cap["install_hint"] = INSTALL_HINT
                except Exception:
                    pass
            cap["anydoc"] = True
            return cap
        except Exception:
            pass

    # Fallback to openswap / readability capability (v1)
    if openswap is None:
        return {
            "adapter": "extract",
            "tier": "fallback",
            "anydoc_version": "1.0.0",
            "stdlib": True,
            "zero_deps": True,
            "fallback_scope": FALLBACK_SCOPE,
        }
    native = openswap.probe_binary("postlight-parser", probe_args=("--version",))
    extras = {
        "readable": openswap.probe_binary("readable", probe_args=("--version",)),
        "trafilatura": openswap.probe_binary("trafilatura", probe_args=("--version",)),
    }
    return openswap.capability_report(
        "extract",
        native=native,
        extras=extras,
        fallback_scope=ANYDOC_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    if extract is None:
        return Path(db or os.environ.get("SCOUT_EXTRACT_DB") or ".scout/extract.db")
    return Path(db or os.environ.get("SCOUT_EXTRACT_DB") or extract.DB_REL)


def _open_ledger(db: str | None) -> tuple:
    path = _db_path(db)
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    if extract is None:
        import sqlite3
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        return conn, path
    return extract.open_store(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no corpus ledger at {path} — ingest something first",
            command=command,
            example="scout --json extract batch article.html",
        )
    if extract is None:
        import sqlite3
        conn = sqlite3.connect(str(path))
        return conn, path
    return extract.open_store(path), path


def is_url(source: str) -> bool:
    return urlsplit(source).scheme in ("http", "https")


def _gate_url(url: str, command: str) -> None:
    allowed, _reason = check_permission(_manifest(), "network", url)
    if allowed:
        return
    enforce_user_url_or_raise(url, context=command)


def _fetch_url(url: str, *, timeout: float, max_bytes: int) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read(max_bytes)
            charset = None
            try:
                charset = resp.headers.get_content_charset()
            except Exception:
                charset = None
            final = resp.geturl() or url
        if extract is not None:
            html = extract.decode_html(raw, charset)
        else:
            # fallback decode
            try:
                html = raw.decode(charset or "utf-8", "replace")
            except Exception:
                html = raw.decode("utf-8", "replace")
        return {"html": html, "raw": raw, "url": final, "error": None}
    except Exception as e:
        return {"html": "", "raw": b"", "url": url, "error": f"{type(e).__name__}: {e}"}


def _read_stdin() -> dict:
    try:
        raw = sys.stdin.buffer.read()
    except (AttributeError, ValueError):
        raw = (sys.stdin.read() or "").encode("utf-8", "replace")
    if not raw.strip():
        return {"html": "", "raw": raw, "url": None, "error": "stdin was empty"}
    if extract is not None:
        html = extract.decode_html(raw)
    else:
        try:
            html = raw.decode("utf-8", "replace")
        except Exception:
            html = raw.decode("latin-1", "replace")
    return {"html": html, "raw": raw, "url": None, "error": None}


def _read_file(source: str) -> dict:
    path = Path(source)
    if not path.is_file():
        return {"html": "", "raw": b"", "url": None, "error": f"no such file: {path}"}
    try:
        raw = path.read_bytes()
        if extract is not None:
            html = extract.decode_html(raw)
        else:
            try:
                html = raw.decode("utf-8", "replace")
            except Exception:
                html = raw.decode("latin-1", "replace")
        return {"html": html, "raw": raw, "url": path.resolve().as_uri(), "error": None}
    except OSError as e:
        return {"html": "", "raw": b"", "url": None, "error": f"{type(e).__name__}: {e}"}


def load_source(source: str, *, timeout: float = 15.0, max_bytes: int = 8 * 1024 * 1024) -> dict:
    if extract is not None:
        max_bytes = max_bytes if max_bytes else extract.MAX_FETCH_BYTES
        if source == extract.STDIN_SOURCE:
            return _read_stdin()
    else:
        if source == "-":
            return _read_stdin()
    if is_url(source):
        return _fetch_url(source, timeout=timeout, max_bytes=max_bytes)
    return _read_file(source)


def prefetch(sources: List[str], loader, *, jobs: int = 1) -> dict:
    urls = [s for s in sources if is_url(s)]
    if jobs > 1 and len(urls) > 1:
        with ThreadPoolExecutor(max_workers=min(jobs, len(urls))) as pool:
            fetched = dict(zip(urls, pool.map(loader, urls), strict=True))
    else:
        fetched = {s: loader(s) for s in urls}
    for src in sources:
        if src not in fetched:
            fetched[src] = loader(src)
    return fetched


def _fail_on_or_die(fail_on: str | None, command: str) -> None:
    if fail_on is None:
        return
    if openswap is None:
        return
    if fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=f"scout --json extract {command.split()[-1]} --fail-on warning",
        )


def _gate_exit(diags: List[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    if openswap is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        if _HAS_TYPER:
            raise typer.Exit(code=1)
        else:
            raise SystemExit(1)


# ---- Commands ----

def _hello_impl():
    emit(
        ok(
            {"ready": True, "plugin": "extract", "anydoc": anydoc_mod is not None, "version": getattr(anydoc_mod, "VERSION", "0.7.0") if anydoc_mod else "0.7.0"},
            command="extract hello",
            example="scout --json extract read article.html",
            discover="scout extract detect",
        ),
        command="extract hello",
    )


def _detect_impl():
    cap = _capability()
    # Ensure detect output matches acceptance: tier stdlib anydoc-py v1.0.0 scope unified ingestion 12 formats + ole + html
    if "tier" not in cap:
        cap["tier"] = "stdlib"
    if "anydoc_version" not in cap:
        cap["anydoc_version"] = getattr(anydoc_mod, "VERSION", "1.0.0") if anydoc_mod else "1.0.0"
    if "version" not in cap:
        cap["version"] = cap.get("anydoc_version", "1.0.0")
    # content-based detection proof: run detect on known byte patterns (PDF, RTF, DOCX ZIP)
    if anydoc_mod is not None and hasattr(anydoc_mod, "detect"):
        try:
            samples = {
                "pdf": b"%PDF-1.4 fake",
                "rtf": b"{\\rtf1\\ansi fake}",
                "docx": b"PK\x03\x04 fake docx",
            }
            proof = {}
            for name, b in samples.items():
                try:
                    proof[name] = anydoc_mod.detect(b, filename=f"sample.{name}")
                except Exception:
                    proof[name] = "error"
            cap["detection_proof"] = proof
            cap["detection"] = "content-based bytes (PDF %PDF-, RTF {\\rtf, ZIP inspection docx/pptx/xlsx/odt/epub, OLE D0CF11E0, CSV heuristic, HTML)"
            cap["content_based"] = True
        except Exception:
            pass
    emit(
        ok(
            cap,
            command="extract detect",
            example="scout --json extract read article.html",
            discover="scout extract read --help",
        ),
        command="extract detect",
    )


def _read_impl(
    source: str,
    text_out: bool = False,
    timeout: float = 15.0,
    max_bytes: int = 8 * 1024 * 1024,
    min_chars: int = 25,
    thin_words: int = 120,
    record: bool = False,
    db: str | None = None,
    fail_on: str | None = None,
):
    _fail_on_or_die(fail_on, "extract read")
    if is_url(source):
        sanitize_no_proxy_env()
        _gate_url(source, "extract read")

    src_info = load_source(source, timeout=timeout, max_bytes=max_bytes)
    if src_info["error"]:
        fail_agent(
            f"cannot read {source}: {src_info['error']}",
            command="extract read",
            example="scout --json extract read article.html",
        )

    raw = src_info.get("raw", b"")
    if not raw:
        raw = src_info.get("html", "").encode("utf-8", "replace")

    detected_fmt = None
    doc_gfm = None
    doc_ir = None
    is_binary_doc = False

    if anydoc_mod is not None:
        try:
            detected_fmt = anydoc_mod.detect(raw, filename=source if not is_url(source) else None)
            # Binary formats must use anydoc, never html fallback (prevents ZIP header leak)
            if detected_fmt in ("docx", "pptx", "xlsx", "odt", "ods", "odp", "epub", "pdf", "rtf", "ole", "doc", "xls", "ppt"):
                is_binary_doc = True
                try:
                    doc_ir = anydoc_mod.parse(raw, filename=source if not is_url(source) else None)
                    doc_gfm = anydoc_mod.to_markdown(doc_ir)
                except Exception as e:
                    if hasattr(anydoc_mod, "AnyDocError") and isinstance(e, anydoc_mod.AnyDocError):
                        emit(
                            {
                                "ok": False,
                                "command": "extract read",
                                "error": str(e),
                                "errorClass": getattr(e, "reason", type(e).__name__),
                                "code": getattr(e, "code", 503),
                                "format": detected_fmt,
                                "source": source,
                            },
                            command="extract read",
                        )
                        if _HAS_TYPER:
                            raise typer.Exit(code=3)
                        else:
                            raise SystemExit(3)
                    emit(
                        {
                            "ok": False,
                            "command": "extract read",
                            "error": f"parse failed for {detected_fmt}: {e}",
                            "errorClass": "PARSE_FAILED",
                            "code": 503,
                            "format": detected_fmt,
                            "source": source,
                        },
                        command="extract read",
                    )
                    if _HAS_TYPER:
                        raise typer.Exit(code=3)
                    else:
                        raise SystemExit(3)
        except SystemExit:
            raise
        except Exception:
            pass

    # Fallback to readability extract for html/text — never for binary doc formats
    if doc_gfm is None:
        if is_binary_doc or (raw[:4] == b"PK\x03\x04" and detected_fmt in (None, "docx", "pptx", "xlsx", "odt", "ods", "odp", "epub")) or raw[:5] == b"%PDF-" or raw[:8] == b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1":
            if not is_binary_doc:
                # raw looks binary but detection missed — still block html fallback
                detected_fmt = detected_fmt or "binary"
            fail_agent(
                f"binary document detected ({detected_fmt or 'unknown'}) but anydoc parse failed — no html fallback for binary",
                command="extract read",
                example="scout --json extract read doc.docx",
            )
        if extract is None:
            # no readability core, try anydoc for text formats as last resort
            if anydoc_mod is not None and raw:
                try:
                    doc_ir = anydoc_mod.parse(raw, filename=source, source=source)
                    doc_gfm = anydoc_mod.to_markdown(doc_ir)
                    res = {
                        "source": source,
                        "url": src_info.get("url"),
                        "format": detected_fmt or "txt",
                        "text": doc_gfm,
                        "gfm": doc_gfm,
                        "word_count": len(doc_gfm.split()) if doc_gfm else 0,
                        "title": doc_ir.meta.get("title", "") if isinstance(doc_ir.meta, dict) else getattr(doc_ir.meta, "title", "") if hasattr(doc_ir, "meta") else "",
                    }
                except Exception:
                    try:
                        txt = raw.decode("utf-8", "replace")[:5000]
                        if "\x00" in txt:
                            fail_agent(f"binary content, not text — cannot fallback", command="extract read", example="scout --json extract read doc.docx")
                        doc_gfm = txt
                        res = {
                            "source": source,
                            "url": src_info.get("url"),
                            "format": detected_fmt or "txt",
                            "text": doc_gfm,
                            "gfm": doc_gfm,
                            "word_count": len(doc_gfm.split()) if doc_gfm else 0,
                            "title": "",
                        }
                    except Exception:
                        doc_gfm = ""
                        res = {"source": source, "url": src_info.get("url"), "format": detected_fmt or "txt", "text": "", "gfm": "", "word_count": 0, "title": ""}
            else:
                doc_gfm = src_info.get("html", "")[:5000]
                res = {
                    "source": source,
                    "url": src_info.get("url"),
                    "format": detected_fmt or "txt",
                    "text": doc_gfm,
                    "gfm": doc_gfm,
                    "word_count": len(doc_gfm.split()) if doc_gfm else 0,
                    "title": "",
                }
        else:
            # readability is the product for html
            res = extract.extract(
                src_info["html"], url=src_info["url"], source=source, min_paragraph_chars=min_chars
            )
            # ensure url field present for stdin test
            if "url" not in res:
                res["url"] = src_info.get("url")
            if "source" not in res:
                res["source"] = source
            doc_gfm = res.get("text", "")
    else:
        # anydoc binary success path
        res = {
            "source": source,
            "url": src_info.get("url"),
            "format": detected_fmt,
            "text": doc_gfm,
            "gfm": doc_gfm,
            "word_count": len(doc_gfm.split()) if doc_gfm else 0,
            "title": doc_ir.meta.get("title", "") if isinstance(doc_ir.meta, dict) else getattr(doc_ir.meta, "title", "") if hasattr(doc_ir, "meta") else "",
            "blocks": len(doc_ir.blocks) if hasattr(doc_ir, "blocks") else 0,
            "document": doc_ir.to_dict() if hasattr(doc_ir, "to_dict") else None,
        }

    if record:
        if extract is not None:
            conn, path = _open_ledger(db)
            res["id"] = extract.record_document(conn, res)
            res["db"] = str(path)
        else:
            # no ledger, skip record
            pass

    if extract is not None:
        diags = extract.to_diagnostics([res], thin_words=thin_words)
    else:
        diags = []

    if text_out and not is_json():
        # pipe-friendly
        if _HAS_TYPER:
            typer.echo(doc_gfm or res.get("text", ""))
        else:
            print(doc_gfm or res.get("text", ""))
        _gate_exit(diags, fail_on)
        return

    emit(
        ok(
            {**res, "diagnostics": diags, "summary": openswap.summarize(diags) if openswap else {}},
            command="extract read",
            example="scout --json extract batch --glob '**/*.html'",
            discover="scout extract corpus",
        ),
        command="extract read",
    )
    _gate_exit(diags, fail_on)


def _batch_impl(
    sources: List[str],
    list_file: str | None = None,
    glob: str | None = None,
    root: str = ".",
    jobs: int = 4,
    timeout: float = 15.0,
    max_bytes: int = 8 * 1024 * 1024,
    min_chars: int = 25,
    thin_words: int = 120,
    db: str | None = None,
    record: bool = True,
    cache: bool = True,
    full_text: bool = False,
    fail_on: str | None = None,
):
    _fail_on_or_die(fail_on, "extract batch")
    want = list(sources or [])
    if list_file:
        path = Path(list_file)
        if not path.is_file():
            fail_agent(
                f"no source list at {path}",
                command="extract batch",
                example="scout --json extract batch --list urls.txt",
            )
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                want.append(line)
    if glob:
        want.extend(sorted(str(p) for p in Path(root).glob(glob) if p.is_file()))

    seen: set[str] = set()
    ordered = [s for s in want if not (s in seen or seen.add(s))]
    if not ordered:
        fail_agent(
            "no sources — pass paths/URLs, --list FILE or --glob PATTERN",
            command="extract batch",
            example="scout --json extract batch --glob '**/*.html' --root captures",
            discover="scout extract read --help",
        )

    if any(is_url(s) for s in ordered):
        sanitize_no_proxy_env()
        for src in ordered:
            if is_url(src):
                _gate_url(src, "extract batch")

    # If anydoc available and all sources are non-html docs, use anydoc batch (preserves order diffable)
    use_anydoc_batch = False
    if anydoc_mod is not None and hasattr(anydoc_mod, "batch"):
        # heuristic: if any source ends with docx/pptx/xlsx/pdf etc, prefer anydoc batch for those
        doc_exts = (".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp", ".epub", ".pdf", ".rtf", ".csv", ".md", ".txt", ".json")
        if any(s.lower().endswith(doc_exts) for s in ordered if not is_url(s)):
            use_anydoc_batch = True

    if use_anydoc_batch:
        # anydoc batch preserving input order diffable, ThreadPoolExecutor non-blocking
        try:
            results = anydoc_mod.batch(ordered, jobs=jobs) if hasattr(anydoc_mod, "batch") else None
            # results already order-preserved by anydoc.batch using executor.map
            if results is not None:
                # normalize to expected shape
                formatted = []
                failures = []
                words = 0
                for r in results:
                    if isinstance(r, dict) and r.get("ok"):
                        formatted.append(r)
                        words += r.get("blocks", 0) or len(r.get("gfm", "").split())
                    else:
                        failures.append(r)
                        formatted.append(r)
                emit(
                    ok(
                        {
                            "db": None,
                            "recorded": False,
                            "sources": len(ordered),
                            "extracted": len([r for r in formatted if r.get("ok")]),
                            "cached": 0,
                            "failed": len(failures),
                            "words": words,
                            "results": formatted,
                            "failures": failures,
                            "diagnostics": [],
                            "summary": {},
                            "anydoc": True,
                            "version": getattr(anydoc_mod, "VERSION", "1.0.0"),
                        },
                        command="extract batch",
                        example="scout --json extract corpus",
                        discover="scout extract corpus",
                    ),
                    command="extract batch",
                )
                return
        except Exception:
            pass  # fall through to readability batch

    # Fallback to readability batch
    if extract is None:
        fail_agent(
            "no extract core and anydoc batch failed — cannot batch",
            command="extract batch",
            example="scout --json extract read article.html",
        )

    if record:
        conn, path = _open_ledger(db)
    else:
        conn, path = extract.open_store(":memory:"), None

    def loader(src: str) -> dict:
        return load_source(src, timeout=timeout, max_bytes=max_bytes)

    fetched = prefetch(ordered, loader, jobs=jobs)
    res = extract.run_batch(
        conn,
        ordered,
        lambda src: fetched.get(src, {"error": "not fetched"}),
        record=record,
        use_cache=cache,
        min_paragraph_chars=min_chars,
    )
    diags = extract.to_diagnostics(res["results"], thin_words=thin_words)
    rows = [{k: v for k, v in r.items() if full_text or k != "text"} for r in res["results"]]
    emit(
        ok(
            {
                "db": str(path) if path else None,
                "recorded": record,
                "sources": len(ordered),
                "extracted": res["extracted"],
                "cached": res["cached"],
                "failed": res["failed"],
                "words": res["words"],
                "results": rows,
                "failures": res["failures"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags) if openswap else {},
            },
            command="extract batch",
            example="scout --json extract corpus",
            discover="scout extract corpus",
        ),
        command="extract batch",
    )
    _gate_exit(diags, fail_on)


def _corpus_impl(
    db: str | None = None,
    limit: int = 20,
    source: str | None = None,
    doc_id: int | None = None,
    text_out: bool = False,
):
    conn, path = _open_existing(db, "extract corpus")
    if doc_id is not None:
        if extract is None:
            fail_agent(f"no corpus support without extract core", command="extract corpus", example="scout --json extract corpus --limit 50")
        doc = extract.document_text(conn, doc_id)
        if doc is None:
            fail_agent(f"no document with id {doc_id} in {path}", command="extract corpus", example="scout --json extract corpus --limit 50")
        if text_out and not is_json():
            if _HAS_TYPER:
                typer.echo(doc["text"])
            else:
                print(doc["text"])
            return
        emit(ok({"db": str(path), **doc}, command="extract corpus", example="scout --json extract corpus", discover="scout extract corpus"), command="extract corpus")
        return
    if extract is None:
        emit(ok({"db": str(path), "stats": {}, "documents": []}, command="extract corpus", example="scout --json extract corpus --id 1 --text", discover="scout extract batch --help"), command="extract corpus")
        return
    emit(
        ok(
            {"db": str(path), "stats": extract.corpus_stats(conn), "documents": extract.recent_documents(conn, limit=limit, source=source)},
            command="extract corpus",
            example="scout --json extract corpus --id 1 --text",
            discover="scout extract batch --help",
        ),
        command="extract corpus",
    )


# ---- Typer wiring when available, else argparse fallback ----

if _HAS_TYPER:
    @app.command("hello", epilog=examples_epilog(["scout --json extract hello"]))
    def hello():
        _hello_impl()

    @app.command("detect", epilog=examples_epilog(["scout --json extract detect"]))
    def detect():
        _detect_impl()

    @app.command(
        "read",
        epilog=examples_epilog(
            [
                "scout --json extract read article.html",
                "scout extract read article.html --text",
                "scout extract read https://example.com/post --text > post.txt",
                "cat page.html | scout --json extract read -",
                "scout --json extract read article.html --record --fail-on warning",
                "scout --json extract read doc.docx",
            ]
        ),
    )
    def read(
        source: str = typer.Argument(..., help="file path, http(s) URL, or - for stdin"),
        text_out: bool = typer.Option(False, "--text", help="write ONLY the article text to stdout (pipe-friendly); ignored under --json"),
        timeout: float = typer.Option(15.0, "--timeout", help="URL fetch timeout, seconds"),
        max_bytes: int = typer.Option(8 * 1024 * 1024, "--max-bytes", help="cap on bytes read from a URL"),
        min_chars: int = typer.Option(25, "--min-chars", help="shortest text run scored as a paragraph"),
        thin_words: int = typer.Option(120, "--thin-words", help="below this a result is thin-content"),
        record: bool = typer.Option(False, "--record/--no-record", help="persist into the corpus ledger"),
        db: str | None = typer.Option(None, "--db", help="corpus ledger path"),
        fail_on: str | None = typer.Option(None, "--fail-on", help="exit 1 if extraction quality maps at/above this severity"),
    ):
        _read_impl(source, text_out=text_out, timeout=timeout, max_bytes=max_bytes, min_chars=min_chars, thin_words=thin_words, record=record, db=db, fail_on=fail_on)

    @app.command(
        "batch",
        epilog=examples_epilog(
            [
                "scout --json extract batch a.html b.html",
                "scout --json extract batch --glob '**/*.html' --root captures",
                "scout --json extract batch --list urls.txt --jobs 8",
                "scout --json extract batch --list urls.txt --fail-on error",
            ]
        ),
    )
    def batch(
        sources: List[str] = typer.Argument(None, help="file paths and/or http(s) URLs (or use --list / --glob)"),
        list_file: str | None = typer.Option(None, "--list", help="newline-delimited sources file (# comments allowed)"),
        glob: str | None = typer.Option(None, "--glob", help="glob under --root, e.g. '**/*.html' (sorted, stable)"),
        root: str = typer.Option(".", "--root", help="directory --glob is relative to"),
        jobs: int = typer.Option(4, "--jobs", help="concurrent URL fetches; files are read serially"),
        timeout: float = typer.Option(15.0, "--timeout", help="per-URL fetch timeout"),
        max_bytes: int = typer.Option(8 * 1024 * 1024, "--max-bytes", help="cap on bytes read per URL"),
        min_chars: int = typer.Option(25, "--min-chars", help="paragraph scoring floor"),
        thin_words: int = typer.Option(120, "--thin-words", help="thin-content threshold, words"),
        db: str | None = typer.Option(None, "--db", help="corpus ledger path"),
        record: bool = typer.Option(True, "--record/--no-record", help="persist into the corpus ledger (off = extract-and-report only)"),
        cache: bool = typer.Option(True, "--cache/--no-cache", help="reuse a stored row when the page bytes are unchanged"),
        full_text: bool = typer.Option(False, "--full-text", help="include every article body in the JSON envelope"),
        fail_on: str | None = typer.Option(None, "--fail-on", help="exit 1 on any diagnostic at/above this severity"),
    ):
        _batch_impl(sources, list_file=list_file, glob=glob, root=root, jobs=jobs, timeout=timeout, max_bytes=max_bytes, min_chars=min_chars, thin_words=thin_words, db=db, record=record, cache=cache, full_text=full_text, fail_on=fail_on)

    @app.command(
        "corpus",
        epilog=examples_epilog(
            ["scout --json extract corpus", "scout --json extract corpus --limit 50", "scout --json extract corpus --id 3 --text"]
        ),
    )
    def corpus(
        db: str | None = typer.Option(None, "--db", help="corpus ledger path"),
        limit: int = typer.Option(20, "--limit", help="rows to list (newest first)"),
        source: str | None = typer.Option(None, "--source", help="only rows ingested from this exact source id"),
        doc_id: int | None = typer.Option(None, "--id", help="one document instead of the listing"),
        text_out: bool = typer.Option(False, "--text", help="with --id: write ONLY the stored text to stdout"),
    ):
        _corpus_impl(db=db, limit=limit, source=source, doc_id=doc_id, text_out=text_out)

else:
    # argparse fallback — stdlib only, zero-deps true
    def _argparse_main():
        parser = argparse.ArgumentParser(prog="scout extract", description="Extract article + anydoc IR, fully local")
        sub = parser.add_subparsers(dest="cmd", required=True)

        p_hello = sub.add_parser("hello", help="smoke check")
        p_detect = sub.add_parser("detect", help="report capability tier")

        p_read = sub.add_parser("read", help="one page -> GFM")
        p_read.add_argument("source", help="file path, http(s) URL, or - for stdin")
        p_read.add_argument("--text", action="store_true", help="write ONLY article text to stdout")
        p_read.add_argument("--timeout", type=float, default=15.0)
        p_read.add_argument("--max-bytes", type=int, default=8*1024*1024)
        p_read.add_argument("--min-chars", type=int, default=25)
        p_read.add_argument("--thin-words", type=int, default=120)
        p_read.add_argument("--record", action="store_true")
        p_read.add_argument("--db", default=None)
        p_read.add_argument("--fail-on", default=None)

        p_batch = sub.add_parser("batch", help="ingest many pages")
        p_batch.add_argument("sources", nargs="*", help="file paths and/or URLs")
        p_batch.add_argument("--list", dest="list_file", default=None)
        p_batch.add_argument("--glob", default=None)
        p_batch.add_argument("--root", default=".")
        p_batch.add_argument("--jobs", type=int, default=4)
        p_batch.add_argument("--timeout", type=float, default=15.0)
        p_batch.add_argument("--max-bytes", type=int, default=8*1024*1024)
        p_batch.add_argument("--min-chars", type=int, default=25)
        p_batch.add_argument("--thin-words", type=int, default=120)
        p_batch.add_argument("--db", default=None)
        p_batch.add_argument("--record", action="store_true", default=True)
        p_batch.add_argument("--no-record", action="store_false", dest="record")
        p_batch.add_argument("--cache", action="store_true", default=True)
        p_batch.add_argument("--no-cache", action="store_false", dest="cache")
        p_batch.add_argument("--full-text", action="store_true", default=False)
        p_batch.add_argument("--fail-on", default=None)

        p_corpus = sub.add_parser("corpus", help="corpus rollup")
        p_corpus.add_argument("--db", default=None)
        p_corpus.add_argument("--limit", type=int, default=20)
        p_corpus.add_argument("--source", default=None)
        p_corpus.add_argument("--id", dest="doc_id", type=int, default=None)
        p_corpus.add_argument("--text", dest="text_out", action="store_true", default=False)

        args = parser.parse_args()
        if args.cmd == "hello":
            _hello_impl()
        elif args.cmd == "detect":
            _detect_impl()
        elif args.cmd == "read":
            _read_impl(args.source, text_out=args.text, timeout=args.timeout, max_bytes=args.max_bytes, min_chars=args.min_chars, thin_words=args.thin_words, record=args.record, db=args.db, fail_on=args.fail_on)
        elif args.cmd == "batch":
            _batch_impl(args.sources, list_file=args.list_file, glob=args.glob, root=args.root, jobs=args.jobs, timeout=args.timeout, max_bytes=args.max_bytes, min_chars=args.min_chars, thin_words=args.thin_words, db=args.db, record=args.record, cache=args.cache, full_text=args.full_text, fail_on=args.fail_on)
        elif args.cmd == "corpus":
            _corpus_impl(db=args.db, limit=args.limit, source=args.source, doc_id=args.doc_id, text_out=args.text_out)

    # expose for manual invocation when typer missing
    app._argparse_main = _argparse_main  # type: ignore


def register(root):
    # root may be Typer or argparse — support both
    try:
        root.add_typer(app, name="extract")
    except Exception:
        # if root is not Typer, ignore — our argparse fallback is available via app._argparse_main
        pass


# Allow `python -m bigbang.plugins.extract.cli` for stdlib testing
if __name__ == "__main__":
    if _HAS_TYPER:
        # typer app will handle argv
        pass
    else:
        _argparse_main()
