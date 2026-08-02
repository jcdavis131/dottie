#!/usr/bin/env python3
"""(docstring -> function) pair extraction for code-embedding training.

Solo personal project, no connection to employer, built with public/free-tier only

Implements Phase 1 + Phase 3 of the SOTA code-embedding guide: weakly-supervised
AST extraction with context packing, plus the three mitigations the guide names as
mandatory. **stdlib `ast` only** — no tree-sitter, no Ray, no new dependency, in
keeping with the openswap doctrine. That also means Python-only for now; the guide's
multi-language Registry/Strategy router is a later increment and is deliberately
NOT faked here (see LANGUAGES).

WHAT THIS IS NOT. The guide's Phase 4 wants a Ray cluster over `s3://` parquet and
Phase 5 wants Qwen2.5-Coder-32B-AWQ at tensor_parallel_size=2. Measured on this box
2026-07-25: 1,896 MB RAM free, 23.6 GB disk, ONE 12 GB GPU. Neither is possible
here, and pretending otherwise would produce a pipeline that cannot run. This module
is the part that runs anywhere and that every later phase consumes.

The three vulnerabilities from Phase 1, and what is done about each:

  V1 GARBAGE DOCSTRINGS — "@return the value" destroys semantic mapping.
     Mitigated by heuristic_ok(): minimum word count, TODO/FIXME rejection, and
     rejection of docstrings that are mostly parameter boilerplate. The guide also
     proposes cross-entropy scoring of docstring-vs-code; that needs a model, so it
     is left to a later stage rather than approximated badly here.

  V2 SEMANTIC GAP — docstrings say what an API does; developers search for how to
     solve a problem. NOT mitigated here. It requires synthetic query generation
     (Phase 5, needs a GPU-served LLM). Pairs emitted by this module carry
     `"source": "docstring"` precisely so a later synthetic layer is
     distinguishable in the mixture rather than silently blended.

  V3 CONTEXT STRIPPING — an isolated function loses its class and imports.
     Mitigated by pack_context(): imports + enclosing class line + the function.

Usage:
    python scripts/ast_pairs.py --path apps/scout-cli --out pairs.jsonl
    python scripts/ast_pairs.py --path . --stats-only
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

LANGUAGES = ("python",)  # honest scope; extend via a real extractor, never a stub

MIN_DOC_WORDS = 5
MIN_CODE_CHARS = 40
MAX_IMPORTS_PACKED = 20

_REJECT = re.compile(r"(?i)\b(todo|fixme|xxx|hack|deprecated)\b")
# Sphinx/epydoc field lines — self-contained, one line each.
_FIELD_LINE = re.compile(r"^\s*(:param|:return|:rtype|:raises|:type|@param|@return|@throws)", re.I)
# Google/NumPy section HEADERS. Everything indented beneath one belongs to it.
_SECTION_HEADER = re.compile(
    r"^\s*(Args|Arguments|Returns|Yields|Raises|Attributes|Parameters|Examples?|Note|Notes)\s*:\s*$",
    re.I,
)


def _prose_lines(doc: str) -> list[str]:
    """Description lines only — field lines and whole indented sections removed.

    The first cut matched only the section HEADER, so a Google-style docstring
    like "Args:\\n    x: a thing\\nReturns:\\n    another thing" kept its indented
    continuation lines as prose, counted 5 words, and passed the floor. Boilerplate
    must not be able to pad a docstring over the word count — that is the whole
    point of V1.
    """
    out, in_section, section_indent = [], False, 0
    for raw in doc.splitlines():
        if not raw.strip():
            in_section = False
            continue
        indent = len(raw) - len(raw.lstrip())
        if _SECTION_HEADER.match(raw):
            in_section, section_indent = True, indent
            continue
        if in_section:
            if indent > section_indent:
                continue  # body of the section
            in_section = False  # dedented back out of it
        if _FIELD_LINE.match(raw):
            continue
        out.append(raw)
    return out


def heuristic_ok(doc: str) -> tuple[bool, str]:
    """V1. (keep, reason) — reason is returned so rejections are auditable."""
    if not doc or not doc.strip():
        return False, "empty"
    if _REJECT.search(doc):
        return False, "contains TODO/FIXME/HACK marker"
    prose = _prose_lines(doc)
    if not prose:
        return False, "entirely parameter boilerplate"
    words = " ".join(prose).split()
    if len(words) < MIN_DOC_WORDS:
        return False, f"{len(words)} words < {MIN_DOC_WORDS}"
    return True, "ok"


def _imports(tree: ast.Module) -> list[str]:
    out = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            try:
                out.append(ast.unparse(node))
            except Exception:  # pragma: no cover - unparse is total in 3.9+
                pass
    return out[:MAX_IMPORTS_PACKED]


def pack_context(func_src: str, imports: list[str], class_name: str | None) -> str:
    """V3. Imports + enclosing class + the function, as the guide specifies."""
    parts = []
    if imports:
        parts.append("\n".join(imports))
    if class_name:
        parts.append(f"class {class_name}:")
        parts.append("\n".join("    " + ln for ln in func_src.splitlines()))
    else:
        parts.append(func_src)
    return "\n\n".join(parts)


def _strip_docstring(node) -> str:
    """The positive must not contain the query, or the task is trivial."""
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        return ""
    clone = type(node)(
        name=node.name,
        args=node.args,
        body=body,
        decorator_list=[],
        returns=None,
        type_comment=None,
    )
    ast.fix_missing_locations(clone)
    try:
        return ast.unparse(clone)
    except Exception:  # pragma: no cover
        return ""


def extract_file(source: str, path: str = "<memory>"):
    """Yield pair dicts. Never raises on bad input — returns [] with a reason."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [], [{"path": path, "reason": f"unparseable: {str(e)[:60]}"}]

    imports = _imports(tree)
    pairs, rejected = [], []

    def visit(node, class_name=None):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, class_name=child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(child) or ""
                keep, reason = heuristic_ok(doc)
                if not keep:
                    rejected.append(
                        {"path": path, "symbol": child.name, "reason": reason}
                    )
                    continue
                body = _strip_docstring(child)
                if len(body) < MIN_CODE_CHARS:
                    rejected.append(
                        {"path": path, "symbol": child.name, "reason": "body too short"}
                    )
                    continue
                pairs.append(
                    {
                        "query": " ".join(doc.split()),
                        "positive": pack_context(body, imports, class_name),
                        "language": "python",
                        "path": path,
                        "symbol": (f"{class_name}." if class_name else "") + child.name,
                        # V2: mark provenance so a later synthetic layer stays
                        # distinguishable in the mixture instead of blending in.
                        "source": "docstring",
                    }
                )
                # nested functions inherit the same class context
                visit(child, class_name=class_name)
            else:
                visit(child, class_name=class_name)

    visit(tree)
    return pairs, rejected


def walk(base: Path):
    skip = {".git", "__pycache__", ".venv", "venv", "node_modules", ".ruff_cache",
            ".pytest_cache", "site-packages", "build", "dist"}
    for p in base.rglob("*.py"):
        if skip & set(p.parts):
            continue
        yield p



def _untracked_count(base, rels) -> int:
    """How many scanned paths git does not track. -1 if git cannot answer."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(base), "ls-files", "-z"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return -1
    except (OSError, subprocess.SubprocessError):
        return -1
    tracked = {x for x in out.stdout.split(chr(0)) if x}
    return sum(1 for r in rels if r not in tracked)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default=".", help="tree to mine")
    ap.add_argument("--out", help="JSONL output; omit to print stats only")
    ap.add_argument("--stats-only", action="store_true")
    args = ap.parse_args()

    base = Path(args.path).resolve()
    all_pairs, all_rej, files = [], [], 0
    scanned_rel: list[str] = []
    for p in walk(base):
        files += 1
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        pairs, rej = extract_file(src, str(p.relative_to(base)).replace("\\", "/"))
        all_pairs += pairs
        all_rej += rej
        scanned_rel.append(str(p.relative_to(base)).replace(chr(92), "/"))

    reasons = {}
    for r in all_rej:
        key = re.sub(r"\d+", "N", r["reason"])
        reasons[key] = reasons.get(key, 0) + 1

    # How much of the corpus is NOT repo source. This walk skips .venv and friends but
    # has no gitignore awareness, so generated output is mined as if it were code.
    # Measured 2026-08-02: 585 of 1,286 scanned files were model-written candidate_*.py
    # under apps/dottie/data/research/workspaces/, contributing 557 of 3,343 pairs
    # (16.7%). The Dottie Research runner adds 3 every 15 minutes, so this grows ~382
    # pairs/day with machine uptime -- which is why floors measured from this output go
    # stale in hours rather than weeks.
    #
    # REPORTED, NOT FILTERED. Excluding them changes what every downstream number means,
    # including the hard-negative floors and the encoder bars; that is a decision, not a
    # counting fix. Printing it ends the silence without making the choice.
    n_untracked = _untracked_count(base, scanned_rel)
    if n_untracked < 0:
        print(f"files scanned : {files}  (git unavailable - untracked share unknown)")
    else:
        pct = n_untracked / files * 100 if files else 0.0
        print(f"files scanned : {files}  ({n_untracked} untracked/generated, {pct:.1f}%)")
    print(f"pairs kept    : {len(all_pairs)}")
    print(f"rejected      : {len(all_rej)}")
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"    {n:6}  {reason}")
    if all_pairs:
        keep_rate = len(all_pairs) / (len(all_pairs) + len(all_rej))
        print(f"keep rate     : {keep_rate:.1%}")

    if args.out and not args.stats_only:
        with Path(args.out).open("w", encoding="utf-8", newline="\n") as fh:
            for rec in all_pairs:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"wrote {len(all_pairs)} pairs -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
