# Solo personal project, no connection to employer, built with public/free-tier only
"""reviewgraph core — local-first code-intelligence graph for AI-assisted review.

Design (stdlib only, no tree-sitter, no new deps):
- Python files parsed with `ast`; JS/TS with a lightweight regex extractor.
- Persistent store: SQLite at `<root>/.scout/reviewgraph.db`.
- Nodes: files, classes, functions/methods. Edges: imports (file→file),
  defines (file→symbol), calls (symbol→symbol, best-effort), inherits.
- Incremental: files table keeps mtime_ns + sha256; only changed files re-parse.
- Raw refs (import/call/inherit targets) are stored per source file and edges
  are re-resolved after every index run, so incremental re-index never leaves
  dangling cross-file edges.
"""

from __future__ import annotations

import ast
import hashlib
import json
import posixpath
import re
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

SCHEMA_VERSION = "1"
DB_REL = Path(".scout") / "reviewgraph.db"

PY_SUFFIXES = {".py"}
JS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".scout",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
    "site-packages",
    ".idea",
    ".vscode",
    ".tox",
}
MAX_FILE_BYTES = 2_000_000
CHARS_PER_TOKEN = 4  # honest approximation, documented in output

_JS_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "function",
    "new",
    "typeof",
    "await",
    "else",
    "do",
    "in",
    "of",
    "super",
    "import",
    "require",
    "constructor",
    "throw",
    "delete",
    "void",
    "yield",
    "instanceof",
    "case",
}


class ReviewGraphError(Exception):
    """User-facing failure (bad root, missing index, not a git repo, ...)."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


def db_path(root: Path) -> Path:
    return Path(root) / DB_REL


def _resolve_root(root: str | Path) -> Path:
    p = Path(root).expanduser()
    if not p.exists() or not p.is_dir():
        raise ReviewGraphError(f"root is not a directory: {p}")
    return p.resolve()


def open_db(root: Path, *, create: bool = False) -> sqlite3.Connection:
    """Open the graph DB. When create=False the index must already exist."""
    dbp = db_path(root)
    if not dbp.exists() and not create:
        raise ReviewGraphError(
            f"no index at {dbp} — run `scout reviewgraph index --root {root}` first"
        )
    if create:
        dbp.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(dbp))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,        -- POSIX-relative to root
            lang TEXT NOT NULL,           -- python | javascript
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,           -- file | class | function | method
            path TEXT NOT NULL,
            name TEXT NOT NULL,
            qualname TEXT NOT NULL UNIQUE, -- files: path; symbols: path::Qual.Name
            lineno INTEGER NOT NULL DEFAULT 0,
            end_lineno INTEGER NOT NULL DEFAULT 0,
            signature TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS refs (
            src_path TEXT NOT NULL,       -- owner file (refs die with the file)
            src_qualname TEXT NOT NULL,   -- '' = module level
            kind TEXT NOT NULL,           -- import | call | inherit
            target TEXT NOT NULL,         -- module string or (dotted) name
            level INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS edges (
            src INTEGER NOT NULL,
            dst INTEGER NOT NULL,
            kind TEXT NOT NULL,           -- imports | defines | calls | inherits
            UNIQUE(src, dst, kind)
        );
        CREATE TABLE IF NOT EXISTS warnings (
            path TEXT NOT NULL,
            message TEXT NOT NULL,
            ts TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
        CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
        CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, kind);
        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src, kind);
        CREATE INDEX IF NOT EXISTS idx_refs_src ON refs(src_path);
        """
    )
    ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if ver and ver["value"] != SCHEMA_VERSION:
        if not create:
            conn.close()
            raise ReviewGraphError(
                f"index schema {ver['value']} != {SCHEMA_VERSION} — "
                "re-run `scout reviewgraph index`"
            )
        # stale schema on re-index: wipe and rebuild from scratch
        for table in ("meta", "files", "nodes", "refs", "edges", "warnings"):
            # S608 suppressed on the line below: `table` iterates a hardcoded literal tuple three lines up — no
            # caller input reaches it. A table NAME cannot be bound as a parameter in
            # SQL (only values can), so an f-string is the only way to express this;
            # there is no safer rewrite to switch to.
            conn.execute(f"DELETE FROM {table}")  # noqa: S608
        conn.commit()
    return conn


# ---------------------------------------------------------------------------
# extraction — Python (ast)
# ---------------------------------------------------------------------------


def _py_call_target(func: ast.expr) -> str | None:
    """Dotted best-effort name for a call target; None when not name-like."""
    parts: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif parts:
        # call on a non-name base, e.g. f().save — keep the attr chain only
        pass
    else:
        return None
    return ".".join(reversed(parts))


def _py_signature(node: ast.AST) -> str:
    try:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            return f"{prefix} {node.name}({ast.unparse(node.args)})"
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            return f"class {node.name}({bases})" if bases else f"class {node.name}"
    except Exception:
        pass
    return getattr(node, "name", "")


def _extract_python(rel_path: str, text: str) -> tuple[list[dict], list[dict]]:
    """Return (symbols, refs) for one Python file. Raises SyntaxError upward."""
    tree = ast.parse(text)
    symbols: list[dict] = []
    refs: list[dict] = []

    def add_ref(owner: str, kind: str, target: str | None, level: int = 0) -> None:
        if target:
            refs.append(
                {"src_qualname": owner, "kind": kind, "target": target, "level": level}
            )

    def visit(node: ast.AST, scope: list[str], owner: str, in_class: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = ".".join(scope + [node.name])
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            symbols.append(
                {
                    "name": node.name,
                    "qualname": f"{rel_path}::{qual}",
                    "kind": "method" if in_class else "function",
                    "lineno": start,
                    "end_lineno": node.end_lineno or node.lineno,
                    "signature": _py_signature(node),
                }
            )
            for child in ast.iter_child_nodes(node):
                visit(child, scope + [node.name], f"{rel_path}::{qual}", False)
            return
        if isinstance(node, ast.ClassDef):
            qual = ".".join(scope + [node.name])
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            symbols.append(
                {
                    "name": node.name,
                    "qualname": f"{rel_path}::{qual}",
                    "kind": "class",
                    "lineno": start,
                    "end_lineno": node.end_lineno or node.lineno,
                    "signature": _py_signature(node),
                }
            )
            for base in node.bases:
                add_ref(f"{rel_path}::{qual}", "inherit", _py_call_target(base))
            for child in ast.iter_child_nodes(node):
                visit(child, scope + [node.name], f"{rel_path}::{qual}", True)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                add_ref("", "import", alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            add_ref("", "import", mod or ".", node.level)
            for alias in node.names:
                if alias.name != "*":
                    target = f"{mod}.{alias.name}" if mod else alias.name
                    add_ref("", "import", target, node.level)
        elif isinstance(node, ast.Call):
            add_ref(owner, "call", _py_call_target(node.func))
        for child in ast.iter_child_nodes(node):
            visit(child, scope, owner, in_class)

    for top in tree.body:
        visit(top, [], "", False)
    return symbols, refs


# ---------------------------------------------------------------------------
# extraction — JS/TS (regex, best-effort by design)
# ---------------------------------------------------------------------------

_JS_LINE_COMMENT = re.compile(r"//[^\n]*")
_JS_STRING = re.compile(
    r"('(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`)", re.S
)
_JS_IMPORT = re.compile(
    r"""(?:^|\s)(?:import\s+(?:[\w{}\s,*$]+\s+from\s+)?|import\s*\(\s*|export\s+[\w{}\s,*$]*\s+from\s+|require\s*\(\s*)['"]([^'"]+)['"]""",
    re.M,
)
_JS_FUNC = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(",
    re.M,
)
_JS_ARROW = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
    r"(?:\([^)\n]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=>",
    re.M,
)
_JS_FUNC_EXPR = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function",
    re.M,
)
_JS_CLASS = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"
    r"(?:\s+extends\s+([A-Za-z_$][\w$.]*))?",
    re.M,
)
_JS_CALL = re.compile(r"(^|[^\w$.])([A-Za-z_$][\w$]*)\s*\(")


def _js_sanitize(text: str) -> str:
    """Blank comments/strings but preserve line structure (for line numbers)."""

    def _blank(match: re.Match) -> str:
        return "".join(c if c == "\n" else " " for c in match.group(0))

    # order matters: block comments can contain //, strings can contain both
    text = re.sub(r"/\*.*?\*/", _blank, text, flags=re.S)
    text = _JS_STRING.sub(
        lambda m: (
            m.group(0)[0] + " " * (len(m.group(0)) - 2) + m.group(0)[-1]
            if len(m.group(0)) >= 2 and "\n" not in m.group(0)
            else _blank(m)
        ),
        text,
    )
    text = _JS_LINE_COMMENT.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _js_block_end(clean: str, start_line: int) -> int:
    """1-based end line of the brace block opening at/after start_line (capped)."""
    lines = clean.splitlines()
    depth = 0
    opened = False
    limit = min(len(lines), start_line + 400)
    for i in range(start_line - 1, limit):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
                if opened and depth <= 0:
                    return i + 1
        if not opened and i >= start_line + 2:
            return start_line  # expression body / no block found near decl
    return limit


def _extract_js(rel_path: str, text: str) -> tuple[list[dict], list[dict]]:
    """Regex extraction: imports/exports, function decls, classes, calls."""
    clean = _js_sanitize(text)
    symbols: list[dict] = []
    refs: list[dict] = []
    decl_positions: set[tuple[int, str]] = set()

    def line_of(pos: int) -> int:
        return clean.count("\n", 0, pos) + 1

    for pat, kind in (
        (_JS_FUNC, "function"),
        (_JS_ARROW, "function"),
        (_JS_FUNC_EXPR, "function"),
        (_JS_CLASS, "class"),
    ):
        for m in pat.finditer(clean):
            name = m.group(1)
            lineno = line_of(m.start())
            if any(s["lineno"] == lineno and s["name"] == name for s in symbols):
                continue
            end = _js_block_end(clean, lineno)
            sig = text.splitlines()[lineno - 1].strip()
            sig = sig.split("{")[0].strip()[:160]
            symbols.append(
                {
                    "name": name,
                    "qualname": f"{rel_path}::{name}",
                    "kind": kind,
                    "lineno": lineno,
                    "end_lineno": max(end, lineno),
                    "signature": sig,
                }
            )
            decl_positions.add((lineno, name))
            if kind == "class" and pat is _JS_CLASS and m.group(2):
                refs.append(
                    {
                        "src_qualname": f"{rel_path}::{name}",
                        "kind": "inherit",
                        "target": m.group(2).split(".")[-1],
                        "level": 0,
                    }
                )

    # imports (raw text — module strings are blanked in `clean`); skip lines
    # that are visibly commented out
    raw_lines = text.splitlines()
    for m in _JS_IMPORT.finditer(text):
        lineno = text.count("\n", 0, m.start(1)) + 1
        stripped = raw_lines[lineno - 1].lstrip() if lineno <= len(raw_lines) else ""
        if stripped.startswith(("//", "*", "/*")):
            continue
        refs.append(
            {"src_qualname": "", "kind": "import", "target": m.group(1), "level": 0}
        )

    # best-effort calls, attributed to the innermost enclosing declared symbol
    spans = sorted(symbols, key=lambda s: (s["lineno"], -s["end_lineno"]))

    def owner_of(lineno: int) -> str:
        best = ""
        best_size = None
        for s in spans:
            if s["lineno"] <= lineno <= s["end_lineno"]:
                size = s["end_lineno"] - s["lineno"]
                if best_size is None or size <= best_size:
                    best, best_size = s["qualname"], size
        return best

    seen: set[tuple[str, str]] = set()
    for m in _JS_CALL.finditer(clean):
        name = m.group(2)
        lineno = line_of(m.start(2))
        if name in _JS_KEYWORDS or (lineno, name) in decl_positions:
            continue
        owner = owner_of(lineno)
        if (owner, name) in seen:
            continue
        seen.add((owner, name))
        refs.append({"src_qualname": owner, "kind": "call", "target": name, "level": 0})

    return symbols, refs


# ---------------------------------------------------------------------------
# indexing
# ---------------------------------------------------------------------------


def _lang_of(path: Path) -> str | None:
    if path.suffix in PY_SUFFIXES:
        return "python"
    if path.suffix in JS_SUFFIXES:
        return "javascript"
    return None


def _iter_source_files(root: Path) -> Iterable[Path]:
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if entry.is_dir():
                if (
                    name in SKIP_DIRS
                    or name.startswith(".")
                    or name.endswith(".egg-info")
                ):
                    continue
                stack.append(entry)
            elif entry.is_file() and _lang_of(entry):
                yield entry


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def index_repo(root: str | Path) -> dict[str, Any]:
    """Build or incrementally refresh the graph. Returns index stats."""
    root = _resolve_root(root)
    t0 = time.time()
    conn = open_db(root, create=True)
    try:
        prev = {
            r["path"]: (r["mtime_ns"], r["sha256"])
            for r in conn.execute("SELECT path, mtime_ns, sha256 FROM files")
        }
        seen: set[str] = set()
        parsed = 0
        unchanged = 0
        warnings = 0
        for fpath in _iter_source_files(root):
            rel = fpath.relative_to(root).as_posix()
            seen.add(rel)
            try:
                stat = fpath.stat()
            except OSError:
                continue
            mtime_ns = stat.st_mtime_ns
            if rel in prev and prev[rel][0] == mtime_ns:
                unchanged += 1
                continue
            if stat.st_size > MAX_FILE_BYTES:
                _replace_file(
                    conn, rel, _lang_of(fpath) or "python", mtime_ns, "oversize", [], []
                )
                _warn(conn, rel, f"skipped: file larger than {MAX_FILE_BYTES} bytes")
                warnings += 1
                continue
            raw = fpath.read_bytes()
            digest = _sha256(raw)
            if rel in prev and prev[rel][1] == digest:
                # touched but identical — just refresh mtime bookkeeping
                conn.execute(
                    "UPDATE files SET mtime_ns=?, indexed_at=? WHERE path=?",
                    (mtime_ns, _now_iso(), rel),
                )
                unchanged += 1
                continue
            lang = _lang_of(fpath) or "python"
            text = raw.decode("utf-8", errors="replace")
            try:
                if lang == "python":
                    syms, refs = _extract_python(rel, text)
                else:
                    syms, refs = _extract_js(rel, text)
            except SyntaxError as e:
                _replace_file(conn, rel, lang, mtime_ns, digest, [], [])
                _warn(
                    conn,
                    rel,
                    f"unparseable, symbols skipped: {e.msg} (line {e.lineno})",
                )
                warnings += 1
                continue
            except RecursionError:
                _replace_file(conn, rel, lang, mtime_ns, digest, [], [])
                _warn(conn, rel, "unparseable, symbols skipped: recursion limit")
                warnings += 1
                continue
            _replace_file(conn, rel, lang, mtime_ns, digest, syms, refs)
            parsed += 1

        removed = set(prev) - seen
        for rel in removed:
            conn.execute("DELETE FROM files WHERE path=?", (rel,))
            conn.execute("DELETE FROM nodes WHERE path=?", (rel,))
            conn.execute("DELETE FROM refs WHERE src_path=?", (rel,))
            conn.execute("DELETE FROM warnings WHERE path=?", (rel,))

        edge_counts = _rebuild_edges(conn)
        now = _now_iso()
        for k, v in (
            ("schema_version", SCHEMA_VERSION),
            ("root", str(root)),
            ("last_index_at", now),
        ):
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, v),
            )
        conn.commit()
        totals = _counts(conn)
        return {
            "root": str(root),
            "db": str(db_path(root)),
            "indexed": parsed,
            "unchanged": unchanged,
            "removed": len(removed),
            "warnings": warnings,
            "edges": edge_counts,
            "totals": totals,
            "duration_ms": int((time.time() - t0) * 1000),
        }
    finally:
        conn.close()


def _warn(conn: sqlite3.Connection, rel: str, message: str) -> None:
    conn.execute(
        "INSERT INTO warnings(path, message, ts) VALUES(?, ?, ?)",
        (rel, message, _now_iso()),
    )


def _replace_file(
    conn: sqlite3.Connection,
    rel: str,
    lang: str,
    mtime_ns: int,
    digest: str,
    symbols: Sequence[dict],
    refs: Sequence[dict],
) -> None:
    conn.execute("DELETE FROM nodes WHERE path=?", (rel,))
    conn.execute("DELETE FROM refs WHERE src_path=?", (rel,))
    conn.execute("DELETE FROM warnings WHERE path=?", (rel,))
    conn.execute(
        "INSERT INTO files(path, lang, mtime_ns, sha256, indexed_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET lang=excluded.lang, mtime_ns=excluded.mtime_ns, "
        "sha256=excluded.sha256, indexed_at=excluded.indexed_at",
        (rel, lang, mtime_ns, digest, _now_iso()),
    )
    conn.execute(
        "INSERT INTO nodes(kind, path, name, qualname) VALUES('file', ?, ?, ?)",
        (rel, PurePosixPath(rel).name, rel),
    )
    for s in symbols:
        conn.execute(
            "INSERT OR IGNORE INTO nodes(kind, path, name, qualname, lineno, end_lineno, signature)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                s["kind"],
                rel,
                s["name"],
                s["qualname"],
                s["lineno"],
                s["end_lineno"],
                s["signature"],
            ),
        )
    dedup: set[tuple[str, str, str, int]] = set()
    for r in refs:
        key = (r["src_qualname"], r["kind"], r["target"], r["level"])
        if key in dedup:
            continue
        dedup.add(key)
        conn.execute(
            "INSERT INTO refs(src_path, src_qualname, kind, target, level) VALUES(?,?,?,?,?)",
            (rel, r["src_qualname"], r["kind"], r["target"], r["level"]),
        )


# ---------------------------------------------------------------------------
# edge resolution (re-run wholesale after each index pass)
# ---------------------------------------------------------------------------


def _resolve_module_path(
    files: set[str], src_path: str, target: str, level: int, lang: str
) -> str | None:
    """Map an import target to an indexed file path (None = external/unknown)."""
    if lang == "javascript":
        if not target.startswith("."):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(src_path), target))
        for suffix in ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
            if base + suffix in files:
                return base + suffix
        for idx in ("index.ts", "index.tsx", "index.js", "index.jsx"):
            cand = posixpath.join(base, idx)
            if cand in files:
                return cand
        return None
    # python
    if level > 0:
        pkg = PurePosixPath(src_path).parent
        for _ in range(level - 1):
            pkg = pkg.parent
        parts = list(pkg.parts)
        if target and target != ".":
            parts += target.split(".")
        cand = "/".join(parts)
        for suffix in (".py", "/__init__.py"):
            if cand + suffix in files:
                return cand + suffix
        return None
    mod = target.replace(".", "/")
    # try from every ancestor of the importing file so monorepo roots still resolve
    prefixes = [""]
    parent = PurePosixPath(src_path).parent
    while str(parent) != ".":
        prefixes.append(parent.as_posix() + "/")
        parent = parent.parent
    for prefix in prefixes:
        for suffix in (".py", "/__init__.py"):
            cand = f"{prefix}{mod}{suffix}"
            if cand in files:
                return cand
    return None


def _rebuild_edges(conn: sqlite3.Connection) -> dict[str, int]:
    """Re-resolve all refs into the edges table. Cheap at personal-repo scale."""
    conn.execute("DELETE FROM edges")
    files: set[str] = {r["path"] for r in conn.execute("SELECT path FROM files")}
    langs = {r["path"]: r["lang"] for r in conn.execute("SELECT path, lang FROM files")}
    file_node: dict[str, int] = {}
    sym_by_name: dict[str, list[sqlite3.Row]] = {}
    sym_by_qual: dict[str, int] = {}
    for r in conn.execute("SELECT id, kind, path, name, qualname FROM nodes"):
        if r["kind"] == "file":
            file_node[r["path"]] = r["id"]
        else:
            sym_by_name.setdefault(r["name"], []).append(r)
            sym_by_qual[r["qualname"]] = r["id"]

    counts = {"imports": 0, "defines": 0, "calls": 0, "inherits": 0}

    def add_edge(src: int, dst: int, kind: str) -> None:
        if src == dst:
            return
        cur = conn.execute(
            "INSERT OR IGNORE INTO edges(src, dst, kind) VALUES(?,?,?)",
            (src, dst, kind),
        )
        if cur.rowcount:
            counts[kind] += 1

    for path, node_id in file_node.items():
        for r in conn.execute(
            "SELECT id FROM nodes WHERE path=? AND kind!='file'", (path,)
        ):
            add_edge(node_id, r["id"], "defines")

    imported_by_src: dict[str, set[str]] = {}
    rows = list(
        conn.execute("SELECT src_path, src_qualname, kind, target, level FROM refs")
    )
    for r in rows:
        if r["kind"] != "import":
            continue
        dst_path = _resolve_module_path(
            files,
            r["src_path"],
            r["target"],
            r["level"],
            langs.get(r["src_path"], "python"),
        )
        if dst_path and dst_path != r["src_path"]:
            imported_by_src.setdefault(r["src_path"], set()).add(dst_path)
            add_edge(file_node[r["src_path"]], file_node[dst_path], "imports")

    for r in rows:
        if r["kind"] not in ("call", "inherit"):
            continue
        name = r["target"].split(".")[-1]
        cands = sym_by_name.get(name, [])
        if r["kind"] == "inherit":
            cands = [c for c in cands if c["kind"] == "class"]
        if not cands:
            continue
        same_file = [c for c in cands if c["path"] == r["src_path"]]
        imported = imported_by_src.get(r["src_path"], set())
        in_imports = [c for c in cands if c["path"] in imported]
        if same_file:
            picked = same_file[:3]
        elif in_imports:
            picked = in_imports[:3]
        elif len(cands) == 1:
            picked = cands
        else:
            continue  # ambiguous across the repo — skip, best-effort by design
        src_id = sym_by_qual.get(r["src_qualname"]) or file_node.get(r["src_path"])
        if not src_id:
            continue
        edge_kind = "calls" if r["kind"] == "call" else "inherits"
        for c in picked:
            add_edge(src_id, c["id"], edge_kind)
    return counts


def _counts(conn: sqlite3.Connection) -> dict[str, Any]:
    files = conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    symbols = {
        r["kind"]: r["c"]
        for r in conn.execute(
            "SELECT kind, COUNT(*) c FROM nodes WHERE kind!='file' GROUP BY kind"
        )
    }
    edges = {
        r["kind"]: r["c"]
        for r in conn.execute("SELECT kind, COUNT(*) c FROM edges GROUP BY kind")
    }
    warnings = conn.execute("SELECT COUNT(*) c FROM warnings").fetchone()["c"]
    return {
        "files": files,
        "symbols": sum(symbols.values()),
        "symbols_by_kind": symbols,
        "edges": sum(edges.values()),
        "edges_by_kind": edges,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def graph_status(root: str | Path) -> dict[str, Any]:
    root = _resolve_root(root)
    conn = open_db(root)
    try:
        meta = {
            r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")
        }
        stale = 0
        missing = 0
        for r in conn.execute("SELECT path, mtime_ns FROM files"):
            p = root / r["path"]
            try:
                if p.stat().st_mtime_ns != r["mtime_ns"]:
                    stale += 1
            except OSError:
                missing += 1
        dbp = db_path(root)
        return {
            "root": str(root),
            "db": str(dbp),
            "db_bytes": dbp.stat().st_size,
            "last_index_at": meta.get("last_index_at"),
            "stale_files": stale,
            "missing_files": missing,
            **_counts(conn),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# git helpers + diff parsing
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _require_git_repo(root: Path) -> str:
    """Return the subtree prefix of root inside its git repo, or raise."""
    try:
        r = _git(root, "rev-parse", "--is-inside-work-tree")
    except FileNotFoundError:
        raise ReviewGraphError("git executable not found on PATH") from None
    if r.returncode != 0 or r.stdout.strip() != "true":
        raise ReviewGraphError(f"{root} is not inside a git repository")
    head = _git(root, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0:
        raise ReviewGraphError("git repository has no commits yet — commit first")
    prefix = _git(root, "rev-parse", "--show-prefix").stdout.strip()
    return prefix  # '' when root is the repo toplevel, else 'apps/x/' style


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_diff(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """`git diff --unified=0` → {new_path: [(start_line, end_line), ...]}."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            current = (
                None
                if target == "/dev/null"
                else target[2:]
                if target.startswith("b/")
                else target
            )
        elif line.startswith("--- "):
            continue
        elif current is not None and line.startswith("@@"):
            m = _HUNK_RE.match(line)
            if not m:
                continue
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            if count == 0:
                # pure deletion — touch the line either side of the cut point
                ranges.setdefault(current, []).append((max(start, 1), start + 1))
            else:
                ranges.setdefault(current, []).append((start, start + count - 1))
    return ranges


def _deleted_paths(diff_text: str) -> set[str]:
    """Old-side paths whose new side is /dev/null (file deletions)."""
    deleted: set[str] = set()
    pending: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("--- "):
            target = line[4:].strip()
            pending = target[2:] if target.startswith("a/") else target
        elif line.startswith("+++ "):
            if line[4:].strip() == "/dev/null" and pending and pending != "/dev/null":
                deleted.add(pending)
            pending = None
    return deleted


def _collect_diff(root: Path, diff_ref: str | None) -> dict[str, Any]:
    """Changed line ranges (root-relative) from git, plus untracked source files."""
    prefix = _require_git_repo(root)
    ref = diff_ref or "HEAD"
    r = _git(root, "diff", ref, "--unified=0", "--no-color", "--", ".")
    if r.returncode != 0:
        raise ReviewGraphError(f"git diff {ref} failed: {r.stderr.strip()[:200]}")

    def to_rel(p: str) -> str | None:
        if prefix and not p.startswith(prefix):
            return None  # changed outside --root subtree
        return p[len(prefix) :] if prefix else p

    ranges: dict[str, list[tuple[int, int]]] = {}
    outside = 0
    for path, spans in _parse_diff(r.stdout).items():
        rel = to_rel(path)
        if rel is None:
            outside += 1
        else:
            ranges[rel] = spans
    deleted = set()
    for path in _deleted_paths(r.stdout):
        rel = to_rel(path)
        if rel:
            deleted.add(rel)

    untracked: list[str] = []
    st = _git(root, "status", "--porcelain", "--untracked-files=all", "--", ".")
    if st.returncode == 0:
        for line in st.stdout.splitlines():
            if line.startswith("??"):
                rel = to_rel(line[3:].strip())
                if rel and _lang_of(Path(rel)):
                    untracked.append(rel)
    return {
        "ref": ref,
        "ranges": ranges,
        "deleted": deleted,
        "untracked": untracked,
        "outside_root": outside,
    }


# ---------------------------------------------------------------------------
# blast radius
# ---------------------------------------------------------------------------


def _fan_in(conn: sqlite3.Connection) -> dict[int, int]:
    """node id → incoming calls+inherits (symbols) / incoming imports (files)."""
    fan: dict[int, int] = {}
    for r in conn.execute(
        "SELECT dst, COUNT(*) c FROM edges WHERE kind IN ('calls','inherits','imports') "
        "GROUP BY dst"
    ):
        fan[r["dst"]] = r["c"]
    return fan


def _changed_symbols_for(
    conn: sqlite3.Connection, rel: str, spans: list[tuple[int, int]]
) -> list[sqlite3.Row]:
    rows = list(
        conn.execute(
            "SELECT id, kind, path, name, qualname, lineno, end_lineno, signature "
            "FROM nodes WHERE path=? AND kind!='file'",
            (rel,),
        )
    )
    hit = [
        r
        for r in rows
        if any(r["lineno"] <= hi and r["end_lineno"] >= lo for lo, hi in spans)
    ]
    # innermost wins: drop symbols that strictly contain another hit symbol
    out = []
    for r in hit:
        contains_other = any(
            o is not r
            and r["lineno"] <= o["lineno"]
            and o["end_lineno"] <= r["end_lineno"]
            and (o["lineno"] > r["lineno"] or o["end_lineno"] < r["end_lineno"])
            for o in hit
        )
        if not contains_other:
            out.append(r)
    return out


def compute_blast(
    root: str | Path, diff_ref: str | None = None, hops: int = 2
) -> dict[str, Any]:
    """Blast radius of the working diff: reverse-dependency walk to N hops."""
    root = _resolve_root(root)
    conn = open_db(root)
    try:
        diff = _collect_diff(root, diff_ref)
        indexed = {r["path"] for r in conn.execute("SELECT path FROM files")}
        node_by_id: dict[int, sqlite3.Row] = {
            r["id"]: r
            for r in conn.execute(
                "SELECT id, kind, path, name, qualname, lineno, end_lineno, signature FROM nodes"
            )
        }
        file_node = {
            r["path"]: r["id"] for r in node_by_id.values() if r["kind"] == "file"
        }
        fan = _fan_in(conn)

        changed_files: list[dict] = []
        changed_syms: dict[int, sqlite3.Row] = {}
        for rel, spans in sorted(diff["ranges"].items()):
            entry = {"path": rel, "status": "modified", "indexed": rel in indexed}
            changed_files.append(entry)
            if rel in indexed:
                for row in _changed_symbols_for(conn, rel, spans):
                    changed_syms[row["id"]] = row
        for rel in sorted(diff["deleted"]):
            changed_files.append(
                {"path": rel, "status": "deleted", "indexed": rel in indexed}
            )
        for rel in sorted(diff["untracked"]):
            changed_files.append(
                {"path": rel, "status": "untracked", "indexed": rel in indexed}
            )
            if rel in indexed:  # whole new file — every symbol counts as changed
                for row in conn.execute(
                    "SELECT id, kind, path, name, qualname, lineno, end_lineno, signature "
                    "FROM nodes WHERE path=? AND kind!='file'",
                    (rel,),
                ):
                    changed_syms[row["id"]] = row

        # BFS over reverse edges: callers, subclasses (symbol) + importers (file)
        dist: dict[int, int] = {}
        via: dict[int, str] = {}
        frontier: list[int] = []
        for sid, row in changed_syms.items():
            dist[sid] = 0
            frontier.append(sid)
        for entry in changed_files:
            nid = file_node.get(entry["path"])
            if nid is not None and nid not in dist:
                dist[nid] = 0
                frontier.append(nid)

        for hop in range(1, max(hops, 0) + 1):
            nxt: list[int] = []
            for nid in frontier:
                node = node_by_id.get(nid)
                if node is None:
                    continue
                if node["kind"] == "file":
                    q = ("SELECT src FROM edges WHERE dst=? AND kind='imports'", (nid,))
                    label = f"imports {node['path']}"
                else:
                    q = (
                        "SELECT src FROM edges WHERE dst=? AND kind IN ('calls','inherits')",
                        (nid,),
                    )
                    label = f"depends on {node['qualname']}"
                for r in conn.execute(*q):
                    src = r["src"]
                    if src not in dist:
                        dist[src] = hop
                        via[src] = label
                        nxt.append(src)
            frontier = nxt

        impacted = []
        for nid, d in dist.items():
            if d == 0:
                continue
            node = node_by_id.get(nid)
            if node is None:
                continue
            impacted.append(
                {
                    "type": "file" if node["kind"] == "file" else "symbol",
                    "kind": node["kind"],
                    "name": node["qualname"],
                    "path": node["path"],
                    "signature": node["signature"],
                    "distance": d,
                    "fan_in": fan.get(nid, 0),
                    "via": via.get(nid, ""),
                }
            )
        impacted.sort(key=lambda x: (x["distance"], -x["fan_in"], x["name"]))

        changed_symbols = [
            {
                "qualname": r["qualname"],
                "path": r["path"],
                "kind": r["kind"],
                "lines": [r["lineno"], r["end_lineno"]],
                "signature": r["signature"],
                "fan_in": fan.get(r["id"], 0),
            }
            for r in sorted(changed_syms.values(), key=lambda x: x["qualname"])
        ]
        return {
            "ref": diff["ref"],
            "hops": hops,
            "changed_files": changed_files,
            "changed_symbols": changed_symbols,
            "impacted": impacted,
            "counts": {
                "changed_files": len(changed_files),
                "changed_symbols": len(changed_symbols),
                "impacted_symbols": sum(1 for i in impacted if i["type"] == "symbol"),
                "impacted_files": sum(1 for i in impacted if i["type"] == "file"),
                "outside_root": diff["outside_root"],
            },
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# review context (the flagship — compact JSON for an AI reviewer)
# ---------------------------------------------------------------------------


def _snippet(root: Path, path: str, lo: int, hi: int, cap: int) -> tuple[str, bool]:
    try:
        lines = (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "<file missing on disk>", False
    chunk = lines[lo - 1 : hi]
    truncated = len(chunk) > cap
    if truncated:
        chunk = chunk[:cap] + ["... <truncated>"]
    return "\n".join(chunk), truncated


def _import_cycles(conn: sqlite3.Connection, limit: int = 10) -> list[list[str]]:
    """File-level import cycles via iterative Tarjan SCC (size > 1 only)."""
    node_path = {
        r["id"]: r["path"]
        for r in conn.execute("SELECT id, path FROM nodes WHERE kind='file'")
    }
    adj: dict[int, list[int]] = {}
    for r in conn.execute("SELECT src, dst FROM edges WHERE kind='imports'"):
        adj.setdefault(r["src"], []).append(r["dst"])

    index: dict[int, int] = {}
    low: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    counter = [0]
    sccs: list[list[str]] = []

    for start in node_path:
        if start in index:
            continue
        work: list[tuple[int, int]] = [(start, 0)]
        while work:
            v, pi = work[-1]
            if pi == 0:
                index[v] = low[v] = counter[0]
                counter[0] += 1
                stack.append(v)
                on_stack.add(v)
            recurse = False
            neighbors = adj.get(v, [])
            for i in range(pi, len(neighbors)):
                w = neighbors[i]
                if w not in index:
                    work[-1] = (v, i + 1)
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    sccs.append(sorted(node_path[n] for n in comp))
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
        if len(sccs) >= limit:
            break
    return sccs[:limit]


def build_context(
    root: str | Path,
    diff_ref: str | None = None,
    hops: int = 2,
    budget_tokens: int = 4000,
) -> dict[str, Any]:
    """Compact review-context JSON, trimmed to ~budget_tokens (chars/4)."""
    root = _resolve_root(root)
    blast = compute_blast(root, diff_ref=diff_ref, hops=hops)
    conn = open_db(root)
    try:
        cycles = _import_cycles(conn)
        stale = graph_status(root)
    finally:
        conn.close()

    changed_paths = {c["path"] for c in blast["changed_files"]}
    risk_notes: list[str] = []
    for s in blast["changed_symbols"]:
        if s["fan_in"] >= 5:
            risk_notes.append(
                f"high fan-in: {s['qualname']} has {s['fan_in']} inbound dependents — "
                "small changes ripple wide"
            )
    for cyc in cycles:
        if changed_paths & set(cyc):
            risk_notes.append("import cycle touched: " + " -> ".join(cyc))
    unindexed = [c["path"] for c in blast["changed_files"] if not c["indexed"]]
    if unindexed:
        risk_notes.append(
            f"{len(unindexed)} changed file(s) not in the index (run `scout reviewgraph index`): "
            + ", ".join(unindexed[:5])
        )
    if stale["stale_files"]:
        risk_notes.append(
            f"index is stale for {stale['stale_files']} file(s) — symbol line ranges may drift"
        )

    dependents = [
        i for i in blast["impacted"] if i["type"] == "symbol" and i["distance"] == 1
    ]
    dependents.sort(key=lambda x: (-x["fan_in"], x["name"]))
    impacted_files = sorted(
        {i["path"] for i in blast["impacted"]} | {i["path"] for i in dependents}
    )

    # highest fan-in first so the riskiest changed symbols keep their snippets
    changed_ranked = sorted(
        blast["changed_symbols"], key=lambda s: (-s["fan_in"], s["qualname"])
    )
    snippet_cap = 80
    max_dependents = len(dependents)
    full_snips = len(changed_ranked)  # first N changed get snippets; rest sig-only
    max_changed = len(changed_ranked)

    def assemble(cap: int, dep_n: int, snips: int, changed_n: int) -> dict[str, Any]:
        changed = []
        for i, s in enumerate(changed_ranked[:changed_n]):
            entry = {
                "qualname": s["qualname"],
                "kind": s["kind"],
                "path": s["path"],
                "lines": s["lines"],
                "fan_in": s["fan_in"],
                "signature": s["signature"],
            }
            if i < snips:
                text, truncated = _snippet(
                    root, s["path"], s["lines"][0], s["lines"][1], cap
                )
                entry["snippet"] = text
                entry["snippet_truncated"] = truncated
            changed.append(entry)
        return {
            "ref": blast["ref"],
            "hops": hops,
            "budget_tokens": budget_tokens,
            "token_estimate": 0,  # filled below; estimate = serialized chars / 4
            "changed_files": blast["changed_files"],
            "changed_symbols": changed,
            "changed_omitted": max(len(changed_ranked) - changed_n, 0),
            "direct_dependents": [
                {
                    "qualname": d["name"],
                    "kind": d["kind"],
                    "path": d["path"],
                    "signature": d["signature"],
                    "fan_in": d["fan_in"],
                    "via": d["via"],
                }
                for d in dependents[:dep_n]
            ],
            "dependents_omitted": max(len(dependents) - dep_n, 0),
            "impacted_files": impacted_files,
            "risk_notes": risk_notes,
            "counts": blast["counts"],
        }

    def estimate(payload: dict[str, Any]) -> int:
        return len(json.dumps(payload, default=str)) // CHARS_PER_TOKEN

    payload = assemble(snippet_cap, max_dependents, full_snips, max_changed)
    while estimate(payload) > budget_tokens:
        if max_dependents > 5:
            max_dependents = max(5, max_dependents // 2)
        elif snippet_cap > 10:
            snippet_cap //= 2
        elif full_snips > 3:
            full_snips = max(3, full_snips // 2)
        elif max_dependents > 0:
            max_dependents -= 1
        elif full_snips > 0:
            full_snips -= 1
        elif max_changed > 10:
            max_changed = max(10, max_changed // 2)
        elif max_changed > 3:
            max_changed -= 1
        else:
            break  # nothing left to trim — report honestly over budget
        payload = assemble(snippet_cap, max_dependents, full_snips, max_changed)
    payload["token_estimate"] = estimate(payload)
    return payload


# ---------------------------------------------------------------------------
# repo-level risks
# ---------------------------------------------------------------------------


def compute_risks(
    root: str | Path, top: int = 10, churn_commits: int = 500
) -> dict[str, Any]:
    """Top fan-in symbols, import cycles, churn-coupled files."""
    root = _resolve_root(root)
    conn = open_db(root)
    try:
        fan = _fan_in(conn)
        nodes = {
            r["id"]: r
            for r in conn.execute("SELECT id, kind, path, name, qualname FROM nodes")
        }
        sym_fan = sorted(
            (
                {
                    "qualname": nodes[nid]["qualname"],
                    "kind": nodes[nid]["kind"],
                    "path": nodes[nid]["path"],
                    "fan_in": c,
                }
                for nid, c in fan.items()
                if nid in nodes and nodes[nid]["kind"] != "file"
            ),
            key=lambda x: (-x["fan_in"], x["qualname"]),
        )[:top]

        cycles = _import_cycles(conn)

        importer_count = {
            nodes[nid]["path"]: c
            for nid, c in fan.items()
            if nid in nodes and nodes[nid]["kind"] == "file"
        }
        indexed = {r["path"] for r in conn.execute("SELECT path FROM files")}
    finally:
        conn.close()

    churn_coupled: list[dict] = []
    churn_note = None
    try:
        prefix = _require_git_repo(root)
        log = _git(
            root,
            "log",
            f"-n{churn_commits}",
            "--pretty=format:",
            "--name-only",
            "--",
            ".",
        )
        churn: dict[str, int] = {}
        for line in log.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            rel = line[len(prefix) :] if prefix and line.startswith(prefix) else line
            if rel in indexed:
                churn[rel] = churn.get(rel, 0) + 1
        churn_coupled = sorted(
            (
                {
                    "path": p,
                    "churn": c,
                    "importers": importer_count.get(p, 0),
                    "score": c * (1 + importer_count.get(p, 0)),
                }
                for p, c in churn.items()
                if importer_count.get(p, 0) > 0
            ),
            key=lambda x: (-x["score"], x["path"]),
        )[:top]
    except ReviewGraphError as e:
        churn_note = str(e)

    out: dict[str, Any] = {
        "root": str(root),
        "top_fan_in": sym_fan,
        "import_cycles": cycles,
        "churn_coupled": churn_coupled,
    }
    if churn_note:
        out["churn_note"] = churn_note
    return out
