# Solo personal project, no connection to employer, built with public/free-tier only
"""Search — local full-text search core (openswap #20: Elastic Cloud / Algolia).

Elastic's hosted cluster rebuilt on the stdlib with the cluster deleted: one
sqlite3 FTS5 virtual table on this box holds the corpus, BM25 does the ranking,
and snippet() does the highlighting. There is no node, no shard, no API key, no
hosted index — the file IS the search engine. That is the whole product: Elastic
Cloud's value proposition is the managed cluster, so "fully local, zero egress"
is the honest replacement and the plugin's detect() reports tier=fallback as the
expected steady state (like uptime and runtrack — no local native binary is a
superset of this core to prefer).

FTS5 is a compile-time option, so its availability is PROBED, never assumed:
fts5_probe() builds a throwaway in-memory table, inserts a row, and demands that
our tokenizer, bm25() and snippet() all work end to end. open_index() raises
Fts5UnavailableError when that probe fails, so a build without FTS5 fails loudly at
open time instead of silently indexing nothing (the whole point of [B] in the
family contract: never a silent no-op).

The index (its own file, .scout/search.db — never the #2 uptime ledger, whose
write lock belongs to monitoring):
- files(id, path, mtime, size, sha256, chars, indexed_ts) — one row per indexed
  file; the stat/hash fields are what makes reindexing incremental.
- docs — FTS5 virtual table (path, body) sharing files.id as its rowid, so a
  hit joins straight back to its file row.
- meta(key, value) — schema_version, tokenizer, and the union of indexed roots.

The deterministic surface: iter_files (sorted walk, glob include/exclude, pruned
vendor dirs), read_document (explicit skip reasons — never a silent drop),
index_paths (added/updated/unchanged/removed/skipped, prune scoped to the roots
being indexed), query (BM25 ranking + snippet highlighting + path filter +
pagination) and stats (corpus rollup plus a stat-only staleness audit).
Everything takes an explicit `now`, paths are stored POSIX-normalized, and the
only I/O is reading the corpus and sqlite3 — so tests are deterministic and
Windows/POSIX read the same index.

Reindex honesty: mode="mtime" (default) re-reads a file only when its mtime or
size moved — fast, and it MISSES an edit that preserves both. mode="hash" reads
every candidate and compares sha256, catching mtime-preserving edits at the cost
of the read. Both modes are named in the output; neither pretends to be the
other.

Extension points:
- Tokenizer: TOKENIZER is one string in one place (schema + probe read the same
  constant). Swapping in 'porter unicode61' or a custom separator set is a
  one-line change plus a reindex.
- Ranking: query(path_weight=, body_weight=) are the BM25 column weights — raise
  path_weight to favor filename matches, drop it to 0.0 to rank on body alone.
- Corpus shape: include/exclude globs and exclude_dirs are plain arguments, so a
  caller can index a docs tree, a source tree, or one file, and the CLI can turn
  them into config later without touching this core.
- Gates: to_diagnostics maps a stale/missing/skipped report onto the family
  diagnostic schema, so `stats --fail-on warning` gates CI on "the index no
  longer matches the disk it claims to describe".
- No network tier ever: the plugin manifest disables the network axis entirely,
  so "no document ever left the box" is architectural, not a promise.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from bigbang.core import leaks, openswap, prose, seo

DB_REL = Path(".scout") / "search.db"
SCHEMA_VERSION = "1"

# One tokenizer string, used by BOTH the schema and the capability probe, so a
# build that cannot honor it fails at probe time instead of mid-index.
# remove_diacritics 2 folds "café" onto "cafe" (needs sqlite >= 3.27).
TOKENIZER = "unicode61 remove_diacritics 2"

# Text extensions indexed when the caller passes no --glob. Derived from the
# sibling adapters' lists (prose #1, seo #3) instead of retyped: a hand-copied
# extension list is exactly how links #4's DOC_EXTS drifted from seo.HTML_EXTS.
DEFAULT_EXTS: tuple[str, ...] = tuple(
    sorted(
        {
            *prose.PROSE_EXTS,
            *seo.HTML_EXTS,
            ".rst",
            ".json",
            ".jsonl",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".conf",
            ".csv",
            ".tsv",
            ".log",
            ".py",
            ".pyi",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".sh",
            ".ps1",
            ".sql",
            ".c",
            ".h",
            ".cpp",
            ".go",
            ".rs",
            ".java",
            ".rb",
            ".env",
        }
    )
)

# Vendor/VCS dirs pruned by default — derived from the leaks #7 scanner's list
# for the same anti-drift reason (one place to add ".turbo" and every adapter
# that walks a tree gets it).
DEFAULT_EXCLUDE_DIRS: tuple[str, ...] = tuple(leaks.DEFAULT_CONFIG["exclude_dirs"])

DEFAULT_MAX_FILE_KB = 1024
BINARY_SNIFF_BYTES = 8192

DEFAULT_LIMIT = 10
DEFAULT_SNIPPET_TOKENS = 16
# BM25 column weights: a query term in the PATH is a strong signal (filenames
# are curated), but body text is the corpus, so path is only 2x by default.
DEFAULT_PATH_WEIGHT = 2.0
DEFAULT_BODY_WEIGHT = 1.0
MARK_OPEN = "["
MARK_CLOSE = "]"
# ASCII by default: an index/query report is read on cp1252 consoles too.
ELLIPSIS = " ... "

MODE_MTIME = "mtime"
MODE_HASH = "hash"
REINDEX_MODES = (MODE_MTIME, MODE_HASH)

# float mtimes survive a sqlite REAL round-trip exactly, but comparing them
# with == invites a 1-ULP reindex storm; a microsecond is far below any real edit.
MTIME_EPSILON = 1e-6

SKIP_REASONS = ("too-large", "binary", "unreadable")

_BODY_COLUMN = 1  # docs(path=0, body=1) — the column snippet() highlights

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    chars INTEGER NOT NULL,
    indexed_ts REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    path, body, tokenize='{TOKENIZER}'
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


# The probe's own query. S608 is suppressed because the only interpolation is our
# own int constant (snippet()'s column index) and no caller input reaches it.
_PROBE_SQL = f"""
SELECT bm25(probe, 2.0, 1.0),
       snippet(probe, {_BODY_COLUMN}, '[', ']', '...', 4)
FROM probe WHERE probe MATCH 'quick'
"""  # noqa: S608


class Fts5UnavailableError(RuntimeError):
    """This sqlite3 build cannot do FTS5 — fail honestly, never degrade silently."""


# ---- capability probe -------------------------------------------------------


def fts5_probe() -> dict[str, Any]:
    """End-to-end FTS5 probe: virtual table + our tokenizer + bm25() + snippet().

    "FTS5 compiled in" is not enough to promise this adapter's behavior: an older
    build rejects `remove_diacritics 2`, and a hit with no working snippet() is a
    search engine with no highlighting. So the probe writes a row and demands a
    highlighted snippet back. Pure in-memory — no file, no network.
    """
    report: dict[str, Any] = {
        "available": False,
        "sqlite_version": sqlite3.sqlite_version,
        "tokenizer": TOKENIZER,
        "error": None,
    }
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE probe USING fts5(a, b, tokenize='{TOKENIZER}')"
            )
            conn.execute("INSERT INTO probe(a, b) VALUES('p', 'the quick brown fox')")
            row = conn.execute(_PROBE_SQL).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:  # no FTS5, or a tokenizer this build rejects
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report
    if row is None or not isinstance(row[0], (int, float)) or "[quick]" not in (row[1] or ""):
        report["error"] = (
            "FTS5 present but bm25()/snippet() did not return a usable ranked "
            f"snippet (got {row!r})"
        )
        return report
    report["available"] = True
    return report


def fts5_available() -> tuple[bool, str]:
    """(available, reason) — 'ok' when this build can serve the whole adapter."""
    report = fts5_probe()
    return bool(report["available"]), report["error"] or "ok"


# ---- index lifecycle --------------------------------------------------------


def open_index(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the search index — its OWN sqlite file.

    Raises Fts5UnavailableError when this interpreter's sqlite3 cannot do FTS5, so the
    failure lands at open time with the real sqlite error attached instead of
    surfacing later as an index that silently matches nothing.
    """
    available, reason = fts5_available()
    if not available:
        raise Fts5UnavailableError(
            "this interpreter's sqlite3 cannot do FTS5 as this adapter needs it "
            f"(sqlite {sqlite3.sqlite_version}, tokenizer {TOKENIZER!r}): {reason}"
        )
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('tokenizer', ?)", (TOKENIZER,)
    )
    conn.commit()
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return default if row is None else row["value"]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))


def indexed_roots(conn: sqlite3.Connection) -> list[str]:
    """The union of roots ever indexed into this file (for stats/provenance)."""
    raw = get_meta(conn, "roots", "[]")
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return sorted(str(r) for r in value) if isinstance(value, list) else []


# ---- corpus discovery -------------------------------------------------------


def norm_path(path: str | Path) -> str:
    """The one canonical stored form of a path: forward slashes, no './' noise.

    Windows-safe by construction — the index holds POSIX-style strings, so a
    caller's backslashes can never shard the same file into two rows.
    """
    return Path(path).as_posix()


def default_include() -> tuple[str, ...]:
    """Include globs used when the caller names none: the text-extension set."""
    return tuple(f"*{ext}" for ext in DEFAULT_EXTS)


def glob_match(patterns: tuple[str, ...] | list[str], path: str) -> bool:
    """True when `path` matches any pattern.

    A pattern containing "/" is matched against the whole normalized path,
    otherwise against the file name alone (so "*.md" means "any .md anywhere",
    while "docs/*.md" means what it looks like). Matching lowercases both sides,
    so "*.md" also catches "READY.MD" and the result does not change with the
    host filesystem's case rules.
    """
    norm = norm_path(path)
    name = norm.rsplit("/", 1)[-1]
    for pat in patterns:
        pat = str(pat)
        candidate = norm if "/" in pat else name
        if fnmatch.fnmatchcase(candidate.lower(), pat.lower()):
            return True
    return False


def iter_files(
    roots: list[str | Path] | tuple[str | Path, ...],
    *,
    include: list[str] | tuple[str, ...] | None = None,
    exclude: list[str] | tuple[str, ...] | None = None,
    exclude_dirs: list[str] | tuple[str, ...] | None = None,
    follow_symlinks: bool = False,
) -> list[tuple[str, Path]]:
    """Discover the corpus: sorted, deduped [(stored_path, real Path)].

    A root that is a FILE is taken as-is (so `index README.md docs/` works); a
    root that is a directory is walked with vendor/VCS dirs pruned. Symlinks are
    not followed by default (a link loop is not a corpus). Include globs default
    to default_include(); excludes win over includes. Order is sorted by stored
    path so an index pass is reproducible, and a file reachable from two roots is
    yielded once.
    """
    inc = tuple(include) if include else default_include()
    exc = tuple(exclude or ())
    skip_dirs = set(exclude_dirs) if exclude_dirs is not None else set(DEFAULT_EXCLUDE_DIRS)
    found: dict[str, Path] = {}

    def _accept(stored: str, real: Path) -> None:
        if exc and glob_match(exc, stored):
            return
        if not glob_match(inc, stored):
            return
        found.setdefault(stored, real)

    for root in roots:
        rp = Path(root)
        if rp.is_file():
            _accept(norm_path(rp), rp)
            continue
        if not rp.is_dir():
            continue  # a missing root contributes nothing; the caller reports it
        for dirpath, dirnames, filenames in os.walk(rp, followlinks=follow_symlinks):
            dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
            base = Path(dirpath)
            for name in sorted(filenames):
                real = base / name
                _accept(norm_path(real), real)
    return [(stored, found[stored]) for stored in sorted(found)]


def read_document(
    path: str | Path, *, max_kb: int = DEFAULT_MAX_FILE_KB
) -> tuple[str | None, str | None, dict[str, Any]]:
    """One file -> (text, skip_reason, {size, mtime, sha256}).

    Skips are explicit, never silent (the leaks #7 doctrine): too-large, binary
    (a NUL byte in the first 8 KiB), unreadable. Text decodes with
    errors='replace' so one stray byte cannot abort a whole index pass, and the
    sha256 is of the RAW bytes so it is a fact about the file, not about our
    decoding.

    utf-8-sig, not utf-8: PowerShell's Set-Content/Out-File write a UTF-8 BOM by
    default on this box, and a BOM left in the text glues itself to the first
    token and shows up inside every snippet of that file. Dropping it is the
    Windows-real behavior; a BOM-less file decodes identically.
    """
    p = Path(path)
    try:
        st = p.stat()
        if st.st_size > max_kb * 1024:
            return None, "too-large", {"size": int(st.st_size), "mtime": float(st.st_mtime)}
        data = p.read_bytes()
    except OSError:
        return None, "unreadable", {}
    meta = {
        "size": int(st.st_size),
        "mtime": float(st.st_mtime),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if b"\x00" in data[:BINARY_SNIFF_BYTES]:
        return None, "binary", meta
    return data.decode("utf-8-sig", errors="replace"), None, meta


# ---- indexing ---------------------------------------------------------------


def _stat_matches(row: sqlite3.Row | dict[str, Any], st: os.stat_result) -> bool:
    return int(row["size"]) == int(st.st_size) and abs(
        float(row["mtime"]) - float(st.st_mtime)
    ) <= MTIME_EPSILON


def _under_root(stored: str, root: str) -> bool:
    """Is `stored` inside `root` (both normalized)? Used to scope pruning.

    "." is the walk's own shape: os.walk(".") yields child paths with no "./"
    prefix, so a root of "." owns every RELATIVE stored path and no absolute one.
    """
    if root in (".", ""):
        return not Path(stored).is_absolute()
    return stored == root or stored.startswith(root.rstrip("/") + "/")


def index_paths(
    conn: sqlite3.Connection,
    roots: list[str | Path] | tuple[str | Path, ...],
    *,
    include: list[str] | tuple[str, ...] | None = None,
    exclude: list[str] | tuple[str, ...] | None = None,
    exclude_dirs: list[str] | tuple[str, ...] | None = None,
    max_kb: int = DEFAULT_MAX_FILE_KB,
    mode: str = MODE_MTIME,
    prune: bool = True,
    force: bool = False,
    optimize: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    """Index (or incrementally reindex) the corpus under `roots`.

    Per file: unchanged -> skipped cheaply, changed -> body replaced in the FTS
    table, new -> inserted. `mode` decides what "changed" means (see the module
    doc: mtime is fast and misses mtime-preserving edits, hash re-reads and does
    not). `force` reindexes every candidate regardless. With `prune`, rows whose
    file is gone are deleted — but ONLY rows under the roots being indexed, so
    reindexing docs/ never silently drops src/. `optimize` merges the FTS b-tree
    afterwards (worth it after a big bulk pass, pointless after a one-file one).

    Pruning is further scoped to roots that EXIST: a root we cannot see right now
    (unmounted drive, renamed directory, typo) is not evidence that its files are
    gone, so its rows are kept and the root is reported in `missing_roots`
    instead. Losing an index to a temporarily absent path is not acceptable
    behavior for a command whose whole job is to be re-run.

    Raises ValueError on an unknown mode or a non-positive max_kb — a typo must
    not quietly become "index nothing".
    """
    if mode not in REINDEX_MODES:
        raise ValueError(f"mode must be one of {REINDEX_MODES}, got {mode!r}")
    if int(max_kb) < 1:
        raise ValueError(f"max_kb must be >= 1, got {max_kb!r}")
    now = time.time() if now is None else float(now)
    roots_norm = sorted({norm_path(r) for r in roots})
    missing_roots = [norm_path(r) for r in roots if not Path(r).exists()]

    existing = {row["path"]: dict(row) for row in conn.execute("SELECT * FROM files")}
    result: dict[str, Any] = {
        "roots": roots_norm,
        "missing_roots": sorted(set(missing_roots)),
        "mode": mode,
        "forced": bool(force),
        "pruned": bool(prune),
        "added": 0,
        "updated": 0,
        "unchanged": 0,
        "removed": 0,
        "bytes_read": 0,
        "skipped": {},
        "skipped_files": [],
        "removed_paths": [],
    }

    def _skip(stored: str, reason: str) -> None:
        result["skipped"][reason] = result["skipped"].get(reason, 0) + 1
        result["skipped_files"].append({"path": stored, "reason": reason})

    def _drop(row: dict[str, Any]) -> None:
        conn.execute("DELETE FROM docs WHERE rowid = ?", (row["id"],))
        conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
        result["removed"] += 1
        result["removed_paths"].append(row["path"])

    seen: set[str] = set()
    for stored, real in iter_files(
        roots,
        include=include,
        exclude=exclude,
        exclude_dirs=exclude_dirs,
    ):
        seen.add(stored)
        row = existing.get(stored)
        try:
            st = real.stat()
        except OSError:
            _skip(stored, "unreadable")
            continue
        if row and not force and mode == MODE_MTIME and _stat_matches(row, st):
            result["unchanged"] += 1
            continue
        text, skip_reason, meta = read_document(real, max_kb=max_kb)
        if skip_reason is not None:
            _skip(stored, skip_reason)
            # a file that WAS indexed and has since become unindexable must not
            # keep serving stale hits
            if row and prune:
                _drop(row)
            continue
        result["bytes_read"] += int(meta["size"])
        if row and not force and mode == MODE_HASH and row["sha256"] == meta["sha256"]:
            # identical content: refresh the cheap stat fields so the next mtime
            # pass stops re-reading it, but leave the FTS row alone
            conn.execute(
                "UPDATE files SET mtime = ?, size = ?, indexed_ts = ? WHERE id = ?",
                (meta["mtime"], meta["size"], now, row["id"]),
            )
            result["unchanged"] += 1
            continue
        if row:
            conn.execute(
                "UPDATE files SET mtime = ?, size = ?, sha256 = ?, chars = ?, "
                "indexed_ts = ? WHERE id = ?",
                (meta["mtime"], meta["size"], meta["sha256"], len(text), now, row["id"]),
            )
            conn.execute("DELETE FROM docs WHERE rowid = ?", (row["id"],))
            conn.execute(
                "INSERT INTO docs(rowid, path, body) VALUES(?, ?, ?)",
                (row["id"], stored, text),
            )
            result["updated"] += 1
            continue
        cur = conn.execute(
            "INSERT INTO files(path, mtime, size, sha256, chars, indexed_ts) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (stored, meta["mtime"], meta["size"], meta["sha256"], len(text), now),
        )
        conn.execute(
            "INSERT INTO docs(rowid, path, body) VALUES(?, ?, ?)",
            (int(cur.lastrowid), stored, text),
        )
        result["added"] += 1

    if prune:
        prune_roots = [r for r in roots_norm if Path(r).exists()]
        for stored, row in sorted(existing.items()):
            if stored in seen:
                continue
            if any(_under_root(stored, root) for root in prune_roots):
                _drop(row)

    result["skipped_files"].sort(key=lambda s: s["path"])
    result["removed_paths"].sort()
    set_meta(conn, "roots", json.dumps(sorted({*indexed_roots(conn), *roots_norm})))
    conn.commit()
    if optimize:
        conn.execute("INSERT INTO docs(docs) VALUES('optimize')")
        conn.commit()
    result["documents"] = int(conn.execute("SELECT count(*) FROM files").fetchone()[0])
    return result


# ---- query ------------------------------------------------------------------


def literal_match(text: str) -> str:
    """Quote a user string as ONE FTS5 phrase — operators become plain words.

    Doubling embedded quotes is what keeps `he said "hi"` from ending the phrase
    early, and it is why --literal cannot be a syntax error.
    """
    return '"' + str(text).replace('"', '""') + '"'


_GLOB_META = ("*", "?", "[")

# One WHERE clause, shared by the page and its count, so `total` can never
# disagree with the hits it is supposed to be counting.
_WHERE = """
WHERE docs MATCH :match
  AND (:pathglob IS NULL
       OR lower(files.path) GLOB :pathglob
       OR (:pathexact IS NOT NULL AND lower(files.path) = :pathexact))
"""

# S608 is suppressed on both of these: the only interpolation is _WHERE, a module
# constant. Every value a caller can influence (match text, path filter, weights,
# snippet markers, limit/offset) is a bound :parameter — see `query`.
_HIT_SQL = f"""
SELECT files.id AS id, files.path AS path, files.mtime AS mtime,
       files.size AS size, files.chars AS chars, files.indexed_ts AS indexed_ts,
       bm25(docs, :wpath, :wbody) AS bm25,
       snippet(docs, :bodycol, :mopen, :mclose, :ellipsis, :tokens) AS snippet
FROM docs JOIN files ON files.id = docs.rowid
{_WHERE}
ORDER BY bm25 ASC, files.path ASC
LIMIT :limit OFFSET :offset
"""  # noqa: S608

_COUNT_SQL = f"""
SELECT count(*) FROM docs JOIN files ON files.id = docs.rowid
{_WHERE}
"""  # noqa: S608


def path_filter(path_glob: str | None) -> tuple[str | None, str | None]:
    """A --path value -> (glob, exact) for the SQL filter, both lowercased.

    A value carrying glob metacharacters is used as written. A WILDCARD-FREE
    value is treated as a path or a subtree ("docs" matches docs itself and
    everything under docs/), which is both what people mean and the only form
    no shell — nor click's cmd.exe wildcard emulation on Windows — can rewrite
    behind our back.
    """
    if not path_glob:
        return None, None
    raw = str(path_glob)
    if any(meta in raw for meta in _GLOB_META):
        return raw.lower(), None
    exact = norm_path(raw).lower()
    return exact.rstrip("/") + "/*", exact


def query(
    conn: sqlite3.Connection,
    text: str,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    literal: bool = False,
    path_glob: str | None = None,
    snippet_tokens: int = DEFAULT_SNIPPET_TOKENS,
    mark: tuple[str, str] = (MARK_OPEN, MARK_CLOSE),
    ellipsis: str = ELLIPSIS,
    path_weight: float = DEFAULT_PATH_WEIGHT,
    body_weight: float = DEFAULT_BODY_WEIGHT,
) -> dict[str, Any]:
    """Rank the corpus against an FTS5 query; return hits with snippets.

    `text` is FTS5 query syntax by default (phrases, AND/OR/NOT, `term*`
    prefixes, `path: term` column filters) — pass literal=True to search the
    string itself. Ranking is BM25 with per-column weights; `score` is -bm25 so
    bigger is better, while `bm25` keeps the engine's raw (negative) number for
    anyone checking our arithmetic. `path_glob` narrows to matching paths inside
    SQL (see path_filter), so `total` and the page stay consistent. Ties break on
    path, so equal scores still come back in a stable order.

    Raises ValueError on an empty query, a bad limit/offset, or FTS5 syntax the
    engine rejects (with sqlite's own message attached — a malformed query is
    reported, never silently turned into zero hits).
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("query text must be a non-empty string")
    if int(limit) < 1:
        raise ValueError(f"limit must be >= 1, got {limit!r}")
    if int(offset) < 0:
        raise ValueError(f"offset must be >= 0, got {offset!r}")
    if int(snippet_tokens) < 1:
        raise ValueError(f"snippet tokens must be >= 1, got {snippet_tokens!r}")
    match = literal_match(text) if literal else str(text)
    pathglob, pathexact = path_filter(path_glob)
    params = {
        "match": match,
        "pathglob": pathglob,
        "pathexact": pathexact,
        "wpath": float(path_weight),
        "wbody": float(body_weight),
        "bodycol": _BODY_COLUMN,
        "mopen": mark[0],
        "mclose": mark[1],
        "ellipsis": ellipsis,
        "tokens": int(snippet_tokens),
        "limit": int(limit),
        "offset": int(offset),
    }
    try:
        total = int(conn.execute(_COUNT_SQL, params).fetchone()[0])
        rows = conn.execute(_HIT_SQL, params).fetchall()
    except sqlite3.OperationalError as exc:  # fts5 syntax errors land here
        raise ValueError(f"bad FTS5 query {match!r}: {exc}") from exc
    hits = []
    for i, row in enumerate(rows):
        hit = dict(row)
        hit["rank"] = int(offset) + i + 1
        hit["score"] = round(-float(row["bm25"]), 8)
        hits.append(hit)
    return {
        "query": text,
        "match": match,
        "literal": bool(literal),
        "path_glob": path_glob,
        "path_filter": {"glob": pathglob, "exact": pathexact},
        "weights": {"path": float(path_weight), "body": float(body_weight)},
        "total": total,
        "limit": int(limit),
        "offset": int(offset),
        "returned": len(hits),
        "hits": hits,
    }


# ---- stats + staleness ------------------------------------------------------


def stats(conn: sqlite3.Connection, *, check: bool = True, limit: int = 20) -> dict[str, Any]:
    """Corpus rollup, plus (by default) a stat-only audit of index freshness.

    The audit never reads a file body: it stats every indexed path and reports
    `missing` (the file is gone) and `stale` (mtime/size moved since we indexed
    it). That is what makes "this index still describes the disk" a checkable
    claim rather than an assumption — and with to_diagnostics it becomes a CI
    gate. Lists are capped at `limit`; the counts are always complete.
    """
    rows = conn.execute(
        "SELECT path, mtime, size, chars, indexed_ts FROM files ORDER BY path"
    ).fetchall()
    by_ext: dict[str, int] = {}
    total_bytes = 0
    total_chars = 0
    for row in rows:
        suffix = Path(row["path"]).suffix.lower() or "(none)"
        by_ext[suffix] = by_ext.get(suffix, 0) + 1
        total_bytes += int(row["size"])
        total_chars += int(row["chars"])
    out: dict[str, Any] = {
        "documents": len(rows),
        "bytes": total_bytes,
        "chars": total_chars,
        "by_extension": dict(sorted(by_ext.items())),
        "roots": indexed_roots(conn),
        "tokenizer": get_meta(conn, "tokenizer", TOKENIZER),
        "schema_version": get_meta(conn, "schema_version", SCHEMA_VERSION),
        "sqlite_version": sqlite3.sqlite_version,
        "oldest_mtime": min((float(r["mtime"]) for r in rows), default=None),
        "newest_mtime": max((float(r["mtime"]) for r in rows), default=None),
        "last_indexed_ts": max((float(r["indexed_ts"]) for r in rows), default=None),
        "checked": bool(check),
        "missing": [],
        "stale": [],
        "missing_count": 0,
        "stale_count": 0,
    }
    if not check:
        return out
    for row in rows:
        p = Path(row["path"])
        try:
            st = p.stat()
        except OSError:
            out["missing_count"] += 1
            if len(out["missing"]) < limit:
                out["missing"].append(row["path"])
            continue
        if not _stat_matches(row, st):
            out["stale_count"] += 1
            if len(out["stale"]) < limit:
                out["stale"].append(
                    {
                        "path": row["path"],
                        "indexed_size": int(row["size"]),
                        "size": int(st.st_size),
                        "indexed_mtime": float(row["mtime"]),
                        "mtime": float(st.st_mtime),
                    }
                )
    return out


# ---- family schema ----------------------------------------------------------

_SKIP_SEVERITY = {
    # a locked/permission-denied file is an operational problem
    "unreadable": "warning",
    # these two are the caller's own policy choices, but a query that misses a
    # file nobody told it about is the failure mode worth surfacing
    "too-large": "info",
    "binary": "info",
}


def to_diagnostics(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Map an index/stats report onto the family diagnostic schema.

    missing (an indexed file is gone) and stale (mtime/size drift since it was
    indexed) are warnings: `stats --fail-on warning` is the cron/CI gate that
    says "reindex before you trust a query". Skipped files are info, except
    unreadable, which is a warning. Accepts either report shape (or one dict
    carrying both), so callers never branch on which command produced it.
    """
    diags: list[dict[str, Any]] = []
    for path in report.get("missing") or []:
        diags.append(
            openswap.diagnostic(
                path=str(path),
                line=0,
                col=0,
                rule="search:missing",
                severity="warning",
                message="indexed file is gone from disk — reindex to drop it",
                suggestion="scout search index <root>",
                source="search",
            )
        )
    for entry in report.get("stale") or []:
        path = entry.get("path") if isinstance(entry, dict) else str(entry)
        diags.append(
            openswap.diagnostic(
                path=str(path),
                line=0,
                col=0,
                rule="search:stale",
                severity="warning",
                message="file changed since it was indexed — hits may be out of date",
                suggestion="scout search index <root>",
                source="search",
            )
        )
    for entry in report.get("skipped_files") or []:
        reason = str(entry.get("reason", "unreadable"))
        diags.append(
            openswap.diagnostic(
                path=str(entry.get("path", "?")),
                line=0,
                col=0,
                rule=f"search:skipped:{reason}",
                severity=_SKIP_SEVERITY.get(reason, "info"),
                message=f"not indexed ({reason}) — queries cannot match it",
                source="search",
            )
        )
    return openswap.sort_diagnostics(diags)
