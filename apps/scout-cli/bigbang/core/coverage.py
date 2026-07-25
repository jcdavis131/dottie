# Solo personal project, no connection to employer, built with public/free-tier only
"""Coverage — static coverage renderer core (openswap #31: Codecov).

Codecov sells two things: an UPLOADER that ships your coverage report to their
servers, and a WEB APP that renders it and diffs it against your last run. This
adapter deletes both. The report you already produced locally
(`coverage xml` / `pytest --cov`, or the raw `.coverage` sqlite file) is parsed
here with the stdlib, rolled up per module, compared against the previous run
recorded in a local sqlite store, and rendered into ONE self-contained HTML
file. No token, no upload, no service, and the plugin manifest disables the
network axis with an empty domain list — "no coverage report left the box" is
architectural, not a ToS promise.

THE FAILURE MODE THIS MODULE EXISTS TO PREVENT: inventing a zero. A module with
no data is UNKNOWN, and every construction path enforces it:

- `measurement()` produces EITHER a `pct` float OR a non-empty
  `unknown_reason`, never both and never neither, and `check_measurement`
  raises if that is ever violated. `statements is None` (no inventory) and
  `statements == 0` (nothing measurable recorded) are both UNKNOWN — a
  percentage with a zero denominator is not 0%, it is not a percentage.
- The sqlite STORE carries the same invariant as a CHECK constraint
  (`(pct IS NULL) != (unknown_reason IS NULL)`), so a future writer cannot
  persist a reasonless null or a reasoned number.
- A delta is None with a `delta_reason` whenever either side is unknown or the
  module is new/removed. A missing baseline is never a 0.0 delta.
- An unparsable report raises `CoverageError` naming the reason; it never
  degrades into an empty file set, which would render as 0% across the board.
- A `--context` that matches nothing is a hard error listing the contexts that
  DO exist, because silently selecting no rows from `line_bits` would report
  every file as fully uncovered.

What each input format can and cannot answer (this asymmetry is the whole
reason the module is careful):

- Cobertura XML (`coverage xml`, gcovr, and anything else emitting that schema)
  lists every measurable line with a hit count, so it carries BOTH the
  numerator and the denominator, plus branch totals from
  `condition-coverage="50% (1/2)"`.
- coverage.py's `.coverage` sqlite (schema 7) stores EXECUTED lines only, as
  `line_bits` bitmaps. There is no statement inventory in the file at all, so
  a percentage cannot be derived from it — coverage.py itself re-reads and
  re-analyses your source to get the denominator. This module therefore reports
  `covered` as a real measurement and `pct` as UNKNOWN with that reason, and
  says to pass the matching coverage.xml. Guessing a denominator by parsing the
  source with `ast` would be a different tool's answer wearing this one's label.
- Given both, the XML supplies the inventory and the sqlite's executed lines
  are UNIONED into the numerator, then INTERSECTED with the inventory. Lines
  the sqlite executed that the XML never listed are counted separately
  (`executed_outside_inventory`) and never added to the numerator — that is how
  a merge would otherwise print 103%.

Determinism: no wall clock is read here. `generated_ts` and every run
timestamp are injected by the caller, so identical inputs render byte-identical
HTML and tests pin the clock instead of racing it. Line accounting uses SETS of
line numbers, not sums, so a file listed twice (merged reports, one class per
package) cannot double-count, and a line covered in one copy counts as covered.

Not implemented, deliberately and out loud: LCOV `.info` and JaCoCo's native
XML are refused by name rather than mis-parsed (JaCoCo's root element is
`<report>`, and its `<counter>` totals mean something different); per-FILE
deltas are not stored (the store keeps module rows, which is what the report
promises) and the page says so instead of leaving cells blank; and arc data in
a `.coverage` file is reported as present but never turned into branch
percentages, because that needs coverage.py's own source analysis.

WHY THIS IS NOT `runtrack` (#10), whose compare_runs() already computes deltas
against a baseline run: that store's metric column is `value REAL NOT NULL`, so
a coverage figure logged there CANNOT be absent. Recording an unmeasured module
would force a fabricated 0.0 — the exact defect this adapter is built to
prevent. Coverage rows are (statements, covered, pct-or-reason) triples, not
scalars, and the deltas that matter are per-module, not per-metric-key.

ADJACENCY WORTH NAMING: `quality` (#30, SonarQube/CodeClimate) also keeps its own
`runs` table with per-unit deltas and a compare_runs(), so the family now has
three "run history + delta" stores (runtrack, quality, this). They do not measure
the same thing — quality computes per-FUNCTION metrics from the source with `ast`
and its own docstring puts coverage OUT of scope, while this module derives
per-MODULE ratios from report artifacts another tool produced and refuses to walk
the source at all — but the repetition is real and a future consolidation onto one
run/delta substrate is the obvious cleanup. Naming it beats each adapter quietly
believing it invented the pattern.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from bigbang.core import openswap
from bigbang.core.feeds import local  # namespace folding, not retyped (#12)

DB_REL = Path(".scout") / "coverage.db"
SCHEMA_VERSION = "1"

FORMAT_COBERTURA = "cobertura"
FORMAT_COVERAGEPY = "coverage.py-sqlite"
FORMATS = (FORMAT_COBERTURA, FORMAT_COVERAGEPY)

# coverage.py's data file is sqlite from 5.0 on; 4.x wrote a JSON blob behind
# this sentinel, and telling the two apart is the difference between an honest
# error and a mystery.
_SQLITE_MAGIC = b"SQLite format 3\x00"
_LEGACY_JSON_MAGIC = b"!coverage.py:"
# coverage_schema.version as shipped by coverage 6.x/7.x. An unknown version is
# recorded and warned about, not refused: the tables this module reads (file,
# line_bits, context) have been stable, and refusing would be worse than
# parsing while saying the version is unrecognized.
KNOWN_COVERAGE_SCHEMAS = (7,)

_DOCTYPE_RE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)
# "/x/y" or "C:/x" — a path whose module name would start at the filesystem root
_ABSOLUTE_RE = re.compile(r"^(?:/|[A-Za-z]:/)")
# Cobertura branch detail: condition-coverage="50% (1/2)"
_CONDITION_RE = re.compile(r"\((\d+)\s*/\s*(\d+)\)")

# Below display resolution (percentages are shown to 2dp), so a delta that
# cannot be seen is reported as unchanged rather than as noise.
DELTA_EPSILON = 0.005
DEFAULT_DEPTH = 2
ROOT_MODULE = "."

STATUS_IMPROVED = "improved"
STATUS_REGRESSED = "regressed"
STATUS_UNCHANGED = "unchanged"
STATUS_NEW = "new"
STATUS_REMOVED = "removed"
STATUS_UNKNOWN = "unknown"
STATUSES = (
    STATUS_IMPROVED,
    STATUS_REGRESSED,
    STATUS_UNCHANGED,
    STATUS_NEW,
    STATUS_REMOVED,
    STATUS_UNKNOWN,
)

NO_INVENTORY_REASON = (
    "coverage.py's .coverage sqlite records EXECUTED lines only and carries no "
    "statement inventory, so a percentage has no denominator — run `coverage xml` "
    "and pass that report too"
)
NO_STATEMENTS_REASON = (
    "no measurable statements were recorded for this file, so a percentage would "
    "divide by zero (an empty or all-comment module is not 0% covered)"
)

SCOPE_LIMITS = (
    "Cobertura XML (coverage.py's `coverage xml`, gcovr, and anything else "
    "emitting that schema) and coverage.py's .coverage sqlite (schema 7) are "
    "parsed; LCOV .info and JaCoCo's native XML are refused by name rather than "
    "mis-parsed. A .coverage file alone yields covered-line COUNTS and an "
    "UNKNOWN percentage, because that format stores no statement inventory. "
    "Branch percentages come only from Cobertura condition-coverage; arc data "
    "in a .coverage file is reported as present and never converted. Deltas are "
    "per module against a previous run in the local store, never per line"
)


class CoverageError(Exception):
    """A report that cannot be parsed, carrying WHY.

    Raised instead of returning an empty file set: "no files" and "0% covered"
    look identical in a report, and one of them is a lie.
    """


# ---- paths ------------------------------------------------------------------


def normalize_path(raw: str) -> str:
    """One report path -> a comparable posix key (no filesystem access).

    Backslashes fold to "/" so a Windows-generated `.coverage` and a
    posix-style Cobertura `filename` land on the same key; `./` prefixes and
    duplicate separators are removed. Nothing is resolved against the
    filesystem: these paths describe the machine that RAN the tests, which is
    not necessarily this one.
    """
    p = (raw or "").strip().replace("\\", "/")
    while "//" in p:
        p = p.replace("//", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def strip_prefix(path: str, prefixes: tuple[str, ...] | list[str]) -> str:
    """Drop the longest matching source root from an absolute report path.

    Matching is case-insensitive on purpose: a Cobertura `<sources><source>`
    written on Windows routinely differs from coverage.py's stored path only in
    drive-letter case ("C:/x" vs "c:/x"), and treating those as different files
    is how a merge silently reports two half-covered copies of one module.
    """
    key = normalize_path(path)
    best = ""
    for raw in prefixes:
        pref = normalize_path(raw)
        if not pref:
            continue
        if key.lower().startswith(pref.lower() + "/") and len(pref) > len(best):
            best = pref
    return key[len(best) + 1 :] if best else key


def module_of(path: str, depth: int = DEFAULT_DEPTH) -> str:
    """The module a file rolls up into: its first `depth` directory components.

    A file with no directory part belongs to ROOT_MODULE ("."), which is a
    real answer (top-level scripts) and not a missing one.
    """
    if depth < 1:
        raise ValueError(f"depth must be >= 1, got {depth}")
    parts = [p for p in normalize_path(path).split("/") if p and p != "."]
    dirs = parts[:-1]
    return "/".join(dirs[:depth]) if dirs else ROOT_MODULE


# ---- the measurement (value XOR reason) --------------------------------------


def check_measurement(m: dict[str, Any]) -> dict[str, Any]:
    """Enforce the honesty invariant on one reading; return it unchanged.

    EITHER `pct` is a float in 0..100 OR `unknown_reason` is a non-empty
    string. Never both, never neither. `covered` above `statements` means the
    numerator escaped the inventory intersection upstream and is a programming
    error, not a report to render.
    """
    pct = m.get("pct")
    reason = m.get("unknown_reason")
    if (pct is None) == (reason is None):
        raise ValueError(
            f"{m.get('path') or m.get('module')!r}: a reading needs EITHER a pct or a "
            f"reason it has none, got pct={pct!r} reason={reason!r}"
        )
    if reason is not None and not str(reason).strip():
        raise ValueError(f"{m.get('path')!r}: unknown_reason must say why, got {reason!r}")
    if pct is not None:
        if not 0.0 <= float(pct) <= 100.0:
            raise ValueError(f"{m.get('path')!r}: pct {pct!r} is outside 0..100")
        statements = m.get("statements")
        covered = m.get("covered")
        if statements is not None and covered is not None and covered > statements:
            raise ValueError(
                f"{m.get('path')!r}: covered {covered} exceeds statements {statements}"
            )
    return m


def percentage(covered: int, statements: int | None) -> tuple[float | None, str | None]:
    """(pct, unknown_reason) for one covered/statements pair — exactly one is set."""
    if statements is None:
        return None, NO_INVENTORY_REASON
    if statements <= 0:
        return None, NO_STATEMENTS_REASON
    return round(100.0 * covered / statements, 2), None


def measurement(
    *,
    path: str,
    statements: int | None,
    covered: int,
    missing: int | None = None,
    branches: int | None = None,
    branches_covered: int | None = None,
    formats: tuple[str, ...] | list[str] = (),
    executed_outside_inventory: int = 0,
) -> dict[str, Any]:
    """One per-file reading, honesty invariant enforced on construction."""
    pct, reason = percentage(covered, statements)
    branch_pct, branch_reason = (None, "the report carries no branch data")
    if branches is not None and branches > 0 and branches_covered is not None:
        branch_pct = round(100.0 * branches_covered / branches, 2)
        branch_reason = None
    return check_measurement(
        {
            "path": normalize_path(path),
            "module": None,  # filled in by rollup_modules, which owns the depth
            "statements": statements,
            "covered": covered,
            "missing": (statements - covered) if (statements is not None and missing is None) else missing,
            "pct": pct,
            "unknown_reason": reason,
            "branches": branches,
            "branches_covered": branches_covered,
            "branch_pct": branch_pct,
            "branch_unknown_reason": branch_reason,
            "formats": sorted(set(formats)),
            "executed_outside_inventory": int(executed_outside_inventory),
        }
    )


# ---- Cobertura XML ----------------------------------------------------------


def _int_attr(el: ET.Element, name: str) -> int | None:
    raw = (el.get(name) or "").strip()
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _float_attr(el: ET.Element, name: str) -> float | None:
    raw = (el.get(name) or "").strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _find_all(root: ET.Element, name: str) -> list[ET.Element]:
    """Every descendant whose LOCAL tag matches, namespace or not."""
    return [el for el in root.iter() if local(el.tag) == name]


def parse_cobertura(document: str | bytes, *, label: str = "coverage.xml") -> dict[str, Any]:
    """Cobertura XML -> per-file line sets + declared totals. Pure, string-in.

    A DOCTYPE is REFUSED before parsing: stdlib ElementTree never fetches an
    external DTD, but an internal <!ENTITY> chain is still an expansion bomb
    and no coverage tool emits a DOCTYPE, so refusing one closes the whole
    xml.etree attack surface without taking a defusedxml dependency (the same
    call this family already made in feeds #12).

    Line numbers are collected into SETS per file, so the same file appearing
    under two packages (merged reports) cannot double-count, and a line hit in
    either copy counts as hit. The declared `lines-valid`/`lines-covered`
    attributes are recorded but NEVER used as the measurement — they are
    rounded summaries, and a disagreement with the counted lines is reported as
    a note rather than silently preferred.
    """
    raw = document.encode("utf-8", "replace") if isinstance(document, str) else bytes(document)
    if not raw.strip():
        raise CoverageError(f"{label}: empty document")
    if _DOCTYPE_RE.search(raw[:4096]):
        raise CoverageError(f"{label}: refusing a DOCTYPE declaration (entity-expansion risk)")
    try:
        # S314: the DOCTYPE refusal above removes the entity-expansion vector,
        # which is the only xml.etree exposure defusedxml would add here.
        root = ET.fromstring(raw)  # noqa: S314
    except ET.ParseError as e:
        raise CoverageError(f"{label}: not well-formed XML: {e}") from e
    rname = local(root.tag)
    if rname == "report":
        raise CoverageError(
            f"{label}: root element is <report>, which is JaCoCo's native XML, not "
            "Cobertura — convert it (jacoco:report with a cobertura formatter) or "
            "pass a coverage.xml"
        )
    if rname != "coverage":
        raise CoverageError(
            f"{label}: root element is <{rname}>, expected <coverage> (Cobertura)"
        )

    notes: list[str] = []
    sources = [
        normalize_path(el.text or "") for el in _find_all(root, "source") if (el.text or "").strip()
    ]
    files: dict[str, dict[str, Any]] = {}
    classes = 0
    unnamed = 0
    for cls in _find_all(root, "class"):
        filename = (cls.get("filename") or "").strip()
        if not filename:
            unnamed += 1
            continue
        classes += 1
        key = normalize_path(filename)
        rec = files.setdefault(
            key,
            {"statements": set(), "hits": set(), "branches": 0, "branches_covered": 0,
             "branch_lines_undeclared": 0},
        )
        for line in _find_all(cls, "line"):
            number = _int_attr(line, "number")
            if number is None or number <= 0:
                continue
            rec["statements"].add(number)
            if (_int_attr(line, "hits") or 0) > 0:
                rec["hits"].add(number)
            if (line.get("branch") or "").strip().lower() == "true":
                m = _CONDITION_RE.search(line.get("condition-coverage") or "")
                if m:
                    rec["branches_covered"] += int(m.group(1))
                    rec["branches"] += int(m.group(2))
                else:
                    rec["branch_lines_undeclared"] += 1
    if unnamed:
        notes.append(
            f"{label}: {unnamed} <class> element(s) had no filename attribute and were "
            "not counted (their lines are not attributable to a file)"
        )
    undeclared = sum(r["branch_lines_undeclared"] for r in files.values())
    if undeclared:
        notes.append(
            f"{label}: {undeclared} branch line(s) carry no condition-coverage attribute, "
            "so their branch totals are unknown and were left out of the branch figures"
        )
    if not files:
        notes.append(
            f"{label}: the report lists no <class> with a filename, so it measures nothing"
        )
    return {
        "format": FORMAT_COBERTURA,
        "label": label,
        "files": files,
        "sources": sources,
        "declared": {
            "lines_valid": _int_attr(root, "lines-valid"),
            "lines_covered": _int_attr(root, "lines-covered"),
            "line_rate": _float_attr(root, "line-rate"),
            "branch_rate": _float_attr(root, "branch-rate"),
            "version": (root.get("version") or "").strip() or None,
            "timestamp": (root.get("timestamp") or "").strip() or None,
        },
        "classes": classes,
        "notes": notes,
    }


def declared_vs_counted(parsed: dict[str, Any]) -> dict[str, Any]:
    """Compare the XML's own totals against the lines this module counted.

    Kept as a REPORTED discrepancy rather than a correction: the attributes are
    what the producing tool believes, the counted lines are what the document
    actually contains, and when they disagree the reader deserves to know which
    is which instead of getting one of them silently.
    """
    counted_statements = sum(len(r["statements"]) for r in parsed["files"].values())
    counted_covered = sum(len(r["hits"]) for r in parsed["files"].values())
    declared = parsed.get("declared") or {}
    out = {
        "counted_statements": counted_statements,
        "counted_covered": counted_covered,
        "declared_statements": declared.get("lines_valid"),
        "declared_covered": declared.get("lines_covered"),
        "agrees": None,
        "note": None,
    }
    if declared.get("lines_valid") is None or declared.get("lines_covered") is None:
        out["note"] = "the report declares no lines-valid/lines-covered totals to compare"
        return out
    out["agrees"] = (
        declared["lines_valid"] == counted_statements
        and declared["lines_covered"] == counted_covered
    )
    if not out["agrees"]:
        out["note"] = (
            f"{parsed['label']}: declared totals {declared['lines_covered']}/"
            f"{declared['lines_valid']} disagree with the {counted_covered}/"
            f"{counted_statements} lines actually listed in the document; the counted "
            "lines are used"
        )
    return out


# ---- coverage.py .coverage sqlite -------------------------------------------


def numbits_to_lines(blob: bytes | memoryview | None) -> list[int]:
    """coverage.py's `numbits` bitmap -> sorted line numbers.

    The encoding is coverage.py's own: line n sets bit (n % 8) of byte
    (n // 8). Line 0 is not a line, so a bit there is ignored rather than
    emitted as a phantom statement.
    """
    if blob is None:
        return []
    data = bytes(blob)
    out: list[int] = []
    for index, byte in enumerate(data):
        if not byte:
            continue
        for bit in range(8):
            if byte & (1 << bit):
                number = index * 8 + bit
                if number > 0:
                    out.append(number)
    return out


def lines_to_numbits(numbers: list[int] | set[int] | tuple[int, ...]) -> bytes:
    """The inverse of numbits_to_lines (coverage.py's nums_to_numbits).

    Present so a .coverage fixture can be built — and this parser exercised —
    without installing coverage.py, which would be a test-only dependency in a
    stdlib-only family.
    """
    nums = [int(n) for n in numbers if int(n) > 0]
    if not nums:
        return b""
    data = bytearray((max(nums) // 8) + 1)
    for n in nums:
        data[n // 8] |= 1 << (n % 8)
    return bytes(data)


def _sniff_coverage_data(path: Path) -> None:
    """Refuse a non-sqlite .coverage by NAME instead of parsing nothing."""
    head = path.open("rb").read(len(_SQLITE_MAGIC))
    if head.startswith(_LEGACY_JSON_MAGIC):
        raise CoverageError(
            f"{path}: this is coverage.py 4.x's JSON data file, whose format was "
            "dropped in coverage 5 — regenerate it with a current coverage, or pass "
            "the coverage.xml instead"
        )
    if head != _SQLITE_MAGIC:
        raise CoverageError(
            f"{path}: not a sqlite database (first bytes {head[:12]!r}), so it is not a "
            "coverage.py 5+ data file"
        )


def open_readonly(path: str | Path) -> sqlite3.Connection:
    """Open a .coverage file READ-ONLY. `mode=ro` is the enforcement.

    This adapter must never mutate the artifact it reads: a coverage run in
    progress owns that file, and sqlite rejects every write on this connection
    at the engine level rather than on trust.
    """
    p = Path(path)
    if not p.exists():
        raise CoverageError(f"{p}: no such coverage data file")
    _sniff_coverage_data(p)
    # as_uri() gives the absolute percent-encoded form sqlite's URI parser wants
    # on Windows too (file:///C:/...), so paths with spaces still open.
    conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# Four complete literal statements instead of one assembled string: the only
# variable part is the context NAME, which is always a bound parameter, and
# spelling them out means there is no query built at runtime to audit.
_SQL_LINE_BITS = (
    "SELECT file.path AS path, line_bits.numbits AS numbits FROM line_bits"
    " JOIN file ON file.id = line_bits.file_id"
)
_SQL_LINE_BITS_CTX = (
    "SELECT file.path AS path, line_bits.numbits AS numbits FROM line_bits"
    " JOIN file ON file.id = line_bits.file_id"
    " JOIN context ON context.id = line_bits.context_id WHERE context.context = ?"
)
_SQL_ARCS = (
    "SELECT file.path AS path, arc.fromno AS fromno, arc.tono AS tono FROM arc"
    " JOIN file ON file.id = arc.file_id"
)
_SQL_ARCS_CTX = (
    "SELECT file.path AS path, arc.fromno AS fromno, arc.tono AS tono FROM arc"
    " JOIN file ON file.id = arc.file_id"
    " JOIN context ON context.id = arc.context_id WHERE context.context = ?"
)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(r[0])
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def read_coverage_sqlite(
    path: str | Path, *, context: str | None = None
) -> dict[str, Any]:
    """coverage.py's .coverage -> per-file EXECUTED line sets (no denominator).

    `context` selects one measurement context (coverage's `--context`, or
    per-test contexts from `dynamic_context`). A context that matches nothing
    is a hard error listing the contexts that exist, because selecting no rows
    from `line_bits` would otherwise report every file as fully uncovered —
    a fabricated 0%, from a typo.
    """
    p = Path(path)
    conn = open_readonly(p)
    try:
        tables = _table_names(conn)
        missing = {"file", "line_bits"} - tables
        if missing:
            raise CoverageError(
                f"{p}: a coverage.py data file needs the {', '.join(sorted(missing))} "
                f"table(s); this database has {', '.join(sorted(tables)) or 'none'}"
            )
        version = None
        if "coverage_schema" in tables:
            row = conn.execute("SELECT version FROM coverage_schema").fetchone()
            version = None if row is None else int(row[0])
        notes: list[str] = []
        if version is None:
            notes.append(f"{p}: no coverage_schema version recorded in this data file")
        elif version not in KNOWN_COVERAGE_SCHEMAS:
            notes.append(
                f"{p}: coverage_schema version {version} is not one this parser was "
                f"written against ({', '.join(str(v) for v in KNOWN_COVERAGE_SCHEMAS)}); "
                "the file/line_bits tables were read anyway"
            )
        contexts = (
            sorted(str(r[0]) for r in conn.execute("SELECT context FROM context"))
            if "context" in tables
            else []
        )
        has_arcs = _meta_flag(conn, tables, "has_arcs")
        params: tuple[Any, ...] = ()
        if context is not None:
            if "context" not in tables:
                raise CoverageError(
                    f"{p}: --context was given but this data file has no context table"
                )
            if context not in contexts:
                shown = ", ".join(repr(c) for c in contexts) or "none"
                raise CoverageError(
                    f"{p}: no measurement context named {context!r} (recorded contexts: "
                    f"{shown}) — refusing to report zero coverage for a context typo"
                )
            params = (context,)
        # The context-joined variants are only used when a filter was asked for:
        # an unfiltered read wants every context and must not depend on that
        # table existing at all.
        bits_sql = _SQL_LINE_BITS_CTX if context is not None else _SQL_LINE_BITS
        arcs_sql = _SQL_ARCS_CTX if context is not None else _SQL_ARCS

        # Every MEASURED file gets a row, even one with no executed line: with a
        # statement inventory from the XML that file is genuinely 0% covered, and
        # dropping it would hide the least-tested module in the repository.
        files: dict[str, dict[str, Any]] = {
            normalize_path(str(r["path"])): {"executed": set()}
            for r in conn.execute("SELECT path FROM file")
        }

        def sink(raw_path: str) -> set[int]:
            return files.setdefault(normalize_path(raw_path), {"executed": set()})["executed"]

        bits_rows = 0
        for row in conn.execute(bits_sql, params):
            bits_rows += 1
            sink(str(row["path"])).update(numbits_to_lines(row["numbits"]))
        # A --branch run stores ARCS and leaves line_bits empty, so the executed
        # lines have to come from the arc endpoints — coverage.py's own rule
        # (CoverageData.lines: chain both ends of every arc, keep n > 0; the
        # negative pseudo-lines encode entering/leaving a block, not code).
        arc_rows = 0
        if "arc" in tables:
            for row in conn.execute(arcs_sql, params):
                arc_rows += 1
                target = sink(str(row["path"]))
                for number in (row["fromno"], row["tono"]):
                    if number is not None and int(number) > 0:
                        target.add(int(number))
        if arc_rows and not bits_rows:
            notes.append(
                f"{p}: this is a --branch run, so line_bits is empty and the executed "
                f"lines were derived from the {arc_rows} arc row(s) (both endpoints, "
                "negative block markers dropped) exactly as coverage.py derives them"
            )
        if has_arcs:
            notes.append(
                f"{p}: arc (branch) data is present and is reported as present, but it "
                "is NOT converted into branch percentages — branch TOTALS need "
                "coverage.py's own source analysis, and only the Cobertura report "
                "carries them"
            )
        if not any(rec["executed"] for rec in files.values()):
            notes.append(
                f"{p}: the data file records no executed lines at all"
                + (f" for context {context!r}" if context else "")
                + f" ({len(files)} measured file(s), {bits_rows} line_bits row(s), "
                f"{arc_rows} arc row(s))"
            )
        return {
            "format": FORMAT_COVERAGEPY,
            "label": str(p),
            "files": files,
            "sources": [],
            "schema_version": version,
            "has_arcs": has_arcs,
            "contexts": contexts,
            "context": context,
            "notes": notes,
        }
    finally:
        conn.close()


def _meta_flag(conn: sqlite3.Connection, tables: set[str], key: str) -> bool:
    if "meta" not in tables:
        return False
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return bool(row) and str(row[0]).strip().lower() in ("1", "true", "yes")


# ---- combining sources ------------------------------------------------------


def combine(
    parsed: list[dict[str, Any]],
    *,
    depth: int = DEFAULT_DEPTH,
    strip_prefixes: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Merge parsed reports into per-file measurements + a per-module rollout.

    The Cobertura report supplies the statement inventory; a .coverage file
    supplies executed lines. Merging is set arithmetic on line numbers:

        covered = (xml_hits | sqlite_executed) & statements

    An executed line OUTSIDE the inventory is counted in
    `executed_outside_inventory` and never added to the numerator, which is the
    only reason a merged report cannot exceed 100%. A file the sqlite knows and
    the XML does not stays UNKNOWN, with the reason, and is never treated as
    fully covered because "every line we saw ran".

    Absolute paths from a .coverage file are made comparable by stripping the
    Cobertura `<sources><source>` roots declared in the XML — the report's own
    statement about what its filenames are relative to — plus any explicit
    `strip_prefixes`.
    """
    prefixes = list(strip_prefixes)
    for src in parsed:
        prefixes.extend(src.get("sources") or [])
    raw: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    for src in parsed:
        notes.extend(src.get("notes") or [])
        for path, rec in (src.get("files") or {}).items():
            key = strip_prefix(path, prefixes)
            slot = raw.setdefault(
                key,
                {
                    "statements": None,
                    "hits": set(),
                    "executed": set(),
                    "branches": None,
                    "branches_covered": None,
                    "formats": set(),
                },
            )
            slot["formats"].add(src["format"])
            if "statements" in rec:
                if slot["statements"] is None:
                    slot["statements"] = set()
                slot["statements"].update(rec["statements"])
                slot["hits"].update(rec["hits"])
                if rec.get("branches"):
                    slot["branches"] = (slot["branches"] or 0) + int(rec["branches"])
                    slot["branches_covered"] = (slot["branches_covered"] or 0) + int(
                        rec["branches_covered"]
                    )
            if "executed" in rec:
                slot["executed"].update(rec["executed"])

    files: list[dict[str, Any]] = []
    outside_total = 0
    for key in sorted(raw):
        slot = raw[key]
        statements = slot["statements"]
        seen = slot["hits"] | slot["executed"]
        if statements is None:
            covered = len(slot["executed"])
            outside = 0
        else:
            covered = len(seen & statements)
            outside = len(slot["executed"] - statements)
        outside_total += outside
        files.append(
            measurement(
                path=key,
                statements=None if statements is None else len(statements),
                covered=covered,
                branches=slot["branches"],
                branches_covered=slot["branches_covered"],
                formats=tuple(slot["formats"]),
                executed_outside_inventory=outside,
            )
        )
    if outside_total:
        notes.append(
            f"{outside_total} executed line(s) are not in the statement inventory "
            "(blank/comment lines, or a .coverage newer than the coverage.xml) and were "
            "NOT counted toward coverage"
        )
    absolute = [f["path"] for f in files if _ABSOLUTE_RE.match(f["path"])]
    if absolute:
        notes.append(
            f"{len(absolute)} path(s) are absolute (first: {absolute[0]}), so module "
            "names start at the filesystem root rather than at a package — pass "
            "--strip-prefix <root> to roll them up the way the repository is laid out"
        )
    unmatched = [f["path"] for f in files if f["statements"] is None]
    if unmatched and any(s["format"] == FORMAT_COBERTURA for s in parsed):
        notes.append(
            f"{len(unmatched)} file(s) from the .coverage data have no statement "
            "inventory in the XML (first: "
            f"{unmatched[0]}) — if these are the same files under a different root, "
            "pass --strip-prefix so the paths match"
        )
    modules = rollup_modules(files, depth=depth)
    return {
        "depth": depth,
        "executed_outside_inventory": outside_total,
        "strip_prefixes": sorted({normalize_path(p) for p in prefixes if normalize_path(p)}),
        "sources": [
            {
                "label": s["label"],
                "format": s["format"],
                "files": len(s.get("files") or {}),
                "schema_version": s.get("schema_version"),
                "context": s.get("context"),
                "contexts": len(s.get("contexts") or []),
                "declared": s.get("declared"),
            }
            for s in parsed
        ],
        "files": files,
        "modules": modules,
        "totals": totals_of(files),
        "notes": notes,
    }


def _aggregate(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum a set of file readings into one honest group reading.

    ONE implementation for both the per-module rollup and the repository total,
    because two summers drift and then the modules stop adding up to the total.

    Three states are kept apart on purpose, because they are three different
    facts and only one of them is a number:
      - at least one file has a non-empty inventory -> a real percentage over
        (sum covered / sum statements), never a mean of per-file percentages,
        which would weight a 3-line file like a 300-line one;
      - no file has an inventory at all -> statements is None, pct UNKNOWN;
      - every inventory is EMPTY (0 statements) -> pct UNKNOWN because the
        denominator is zero, which is not the same as 0% covered.
    """
    statements = 0
    covered = 0
    with_inventory = 0
    unknown_paths: list[str] = []
    executed_unmeasured = 0
    branches = 0
    branches_covered = 0
    for f in files:
        if f["statements"] is None:
            executed_unmeasured += f["covered"]
        else:
            with_inventory += 1
            statements += f["statements"]
            covered += f["covered"]
        if f["pct"] is None:
            unknown_paths.append(f["path"])
        if f["branches"]:
            branches += f["branches"]
            branches_covered += f["branches_covered"] or 0
    if with_inventory == 0:
        pct: float | None = None
        reason: str | None = (
            f"none of the {len(files)} file(s) here has a statement inventory: "
            + NO_INVENTORY_REASON
        )
    else:
        pct, reason = percentage(covered, statements)
    return {
        "statements": statements if with_inventory else None,
        "covered": covered,
        "missing": (statements - covered) if with_inventory else None,
        "pct": pct,
        "unknown_reason": reason,
        "files": len(files),
        "files_measured": sum(1 for f in files if f["pct"] is not None),
        "files_unknown": len(unknown_paths),
        "unknown_paths": unknown_paths,
        "executed_unmeasured": executed_unmeasured,
        "partial": bool(pct is not None and unknown_paths),
        "branches": branches or None,
        "branches_covered": branches_covered if branches else None,
        "branch_pct": (
            round(100.0 * branches_covered / branches, 2) if branches else None
        ),
    }


def rollup_modules(
    files: list[dict[str, Any]], *, depth: int = DEFAULT_DEPTH
) -> list[dict[str, Any]]:
    """Per-module aggregation: summed counts, never a mean of percentages.

    A module's percentage is (sum covered / sum statements) over the files that
    HAVE an inventory. Averaging per-file percentages would weight a 3-line
    file like a 300-line one. Files with no inventory are counted in
    `files_unknown` and their reasons are carried on the module, so a module
    percentage is never quietly a percentage of a subset; the lines those files
    were SEEN executing are kept in `executed_unmeasured` rather than folded
    into a numerator they have no denominator for.

    Side effect by design: each file record gets its `module` filled in, since
    the depth that decides it lives here and nowhere else.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for f in files:
        name = module_of(f["path"], depth)
        f["module"] = name
        buckets.setdefault(name, []).append(f)
    return [
        check_measurement({"module": name, **_aggregate(buckets[name])})
        for name in sorted(buckets)
    ]


def totals_of(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Repository totals over the files that have an inventory, and what was left out."""
    return check_measurement({"path": "<total>", **_aggregate(files)})


# ---- deltas -----------------------------------------------------------------


def delta_of(
    current: dict[str, Any] | None, baseline: dict[str, Any] | None
) -> dict[str, Any]:
    """One module's delta. `delta` is None with a reason whenever it cannot be a number.

    A missing baseline, a missing current row, or an UNKNOWN percentage on
    either side yields delta=None plus `delta_reason`. It never yields 0.0:
    "unchanged" and "we have nothing to compare" are different facts, and
    collapsing them is how a coverage drop hides.
    """
    name = (current or baseline or {}).get("module")
    row: dict[str, Any] = {
        "module": name,
        "pct": None if current is None else current.get("pct"),
        "baseline_pct": None if baseline is None else baseline.get("pct"),
        "statements": None if current is None else current.get("statements"),
        "baseline_statements": None if baseline is None else baseline.get("statements"),
        "statements_delta": None,
        "covered_delta": None,
        "delta": None,
        "delta_reason": None,
        "status": STATUS_UNKNOWN,
    }
    if current is None:
        row["delta_reason"] = "the module is in the baseline run but not in this one"
        row["status"] = STATUS_REMOVED
        return row
    if baseline is None:
        row["delta_reason"] = "the module was not in the baseline run"
        row["status"] = STATUS_NEW
        return row
    if current.get("statements") is not None and baseline.get("statements") is not None:
        row["statements_delta"] = current["statements"] - baseline["statements"]
        row["covered_delta"] = (current.get("covered") or 0) - (baseline.get("covered") or 0)
    if current.get("pct") is None or baseline.get("pct") is None:
        which = []
        if current.get("pct") is None:
            which.append(f"this run has no percentage ({current.get('unknown_reason')})")
        if baseline.get("pct") is None:
            which.append(
                f"the baseline has no percentage ({baseline.get('unknown_reason')})"
            )
        row["delta_reason"] = "; ".join(which)
        row["status"] = STATUS_UNKNOWN
        return row
    raw = current["pct"] - baseline["pct"]
    row["delta"] = round(raw, 2)
    if raw < -DELTA_EPSILON:
        row["status"] = STATUS_REGRESSED
    elif raw > DELTA_EPSILON:
        row["status"] = STATUS_IMPROVED
    else:
        row["status"] = STATUS_UNCHANGED
    return row


def compare_modules(
    current: list[dict[str, Any]], baseline: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """Per-module deltas against the previous run, including removed modules.

    With no baseline at all every row is `new` and carries the reason — the
    first run of a repository has no history, and pretending otherwise (0.0
    deltas everywhere) would make the first regression invisible.
    """
    base_by_name = {b["module"]: b for b in (baseline or [])}
    rows = [delta_of(c, base_by_name.get(c["module"])) for c in current]
    seen = {c["module"] for c in current}
    rows.extend(
        delta_of(None, b) for name, b in sorted(base_by_name.items()) if name not in seen
    )
    rows.sort(key=lambda r: str(r["module"]))
    counts = dict.fromkeys(STATUSES, 0)
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "have_baseline": baseline is not None,
        "modules": rows,
        "counts": counts,
        "worst": min(
            (r for r in rows if r["delta"] is not None), key=lambda r: r["delta"], default=None
        ),
    }


# ---- rules (policy-as-config) ----------------------------------------------

RULES: dict[str, dict[str, Any]] = {
    "coverage:total-below-threshold": {
        "enabled": True,
        "severity": "error",
        "why": "repository coverage is under the floor the caller asked for",
    },
    "coverage:below-threshold": {
        "enabled": True,
        "severity": "error",
        "why": "a module is under the floor the caller asked for",
    },
    "coverage:regressed": {
        "enabled": True,
        "severity": "error",
        "why": "a module lost more coverage than --max-drop allows versus the last run",
    },
    "coverage:total-unmeasured": {
        "enabled": True,
        "severity": "error",
        "why": "a threshold was requested but nothing could be measured, so it cannot "
        "be satisfied — an unknown must never pass a gate",
    },
    "coverage:no-data": {
        "enabled": True,
        "severity": "warning",
        "why": "a module has no percentage at all, so it is UNKNOWN rather than 0%",
    },
    "coverage:module-partial": {
        "enabled": True,
        "severity": "info",
        "why": "a module's percentage covers only SOME of its files, so the number is "
        "true of a subset — the machine-readable output has to say so too, not just "
        "the page",
    },
    "coverage:no-baseline": {
        "enabled": True,
        "severity": "info",
        "why": "there is no previous run in the store, so no delta exists yet",
    },
    "coverage:executed-outside-inventory": {
        "enabled": True,
        "severity": "info",
        "why": "the .coverage data executed lines the XML never listed, so the two "
        "reports describe different source",
    },
    "coverage:source-unparsable": {
        "enabled": True,
        "severity": "error",
        "why": "a report file could not be parsed, so it was not measured at all",
    },
}


def load_rules(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """RULES with an optional JSON overlay (org policy needs no code edit).

    An unknown rule id or a bad severity is a hard error: silently ignoring a
    typo in a policy file means shipping a gate that does not gate.
    """
    merged = {rid: dict(cfg) for rid, cfg in RULES.items()}
    if path is None:
        return merged
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("rules overlay must be a JSON object of rule -> settings")
    for rid, cfg in raw.items():
        if rid not in merged:
            raise ValueError(f"unknown rule id {rid!r} (see: scout coverage rules)")
        if not isinstance(cfg, dict):
            raise ValueError(f"rule {rid!r}: settings must be a JSON object")
        sev = cfg.get("severity")
        if sev is not None and sev not in openswap.SEVERITIES:
            raise ValueError(
                f"rule {rid!r}: severity must be one of {'|'.join(openswap.SEVERITIES)}"
            )
        merged[rid].update(cfg)
    return merged


def to_diagnostics(
    report: dict[str, Any],
    *,
    min_pct: float | None = None,
    max_drop: float | None = None,
    rules: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Report -> family diagnostics. Pure; thresholds are the caller's policy."""
    rs = rules or load_rules()
    diags: list[dict[str, Any]] = []

    def add(rule: str, path: str, message: str, *, suggestion: str | None = None) -> None:
        cfg = rs.get(rule) or {}
        if not cfg.get("enabled", True):
            return
        diags.append(
            openswap.diagnostic(
                path=path,
                line=0,
                col=1,
                rule=rule,
                severity=cfg.get("severity", "warning"),
                message=message,
                suggestion=suggestion,
            )
        )

    totals = report.get("totals") or {}
    if min_pct is not None:
        if totals.get("pct") is None:
            add(
                "coverage:total-unmeasured",
                "<total>",
                f"--min-pct {min_pct:g} cannot be checked: {totals.get('unknown_reason')}",
                suggestion="run `coverage xml` and pass that report for a denominator",
            )
        elif totals["pct"] < min_pct:
            add(
                "coverage:total-below-threshold",
                "<total>",
                f"total line coverage {totals['pct']:.2f}% is below the required "
                f"{min_pct:g}% ({totals['covered']}/{totals['statements']} statements)",
            )
    for mod in report.get("modules") or []:
        if mod["pct"] is None:
            add(
                "coverage:no-data",
                mod["module"],
                f"no coverage percentage for this module: {mod['unknown_reason']}",
                suggestion=(
                    f"{mod['files_unknown']} of {mod['files']} file(s) have no inventory"
                ),
            )
        else:
            if min_pct is not None and mod["pct"] < min_pct:
                add(
                    "coverage:below-threshold",
                    mod["module"],
                    f"module coverage {mod['pct']:.2f}% is below the required "
                    f"{min_pct:g}% ({mod['covered']}/{mod['statements']} statements)",
                )
            if mod["partial"]:
                add(
                    "coverage:module-partial",
                    mod["module"],
                    f"{mod['pct']:.2f}% is measured over {mod['files_measured']} of "
                    f"{mod['files']} file(s); the other {mod['files_unknown']} have no "
                    "percentage and are excluded rather than counted as zero",
                    suggestion=f"unmeasured: {', '.join(mod['unknown_paths'][:5])}",
                )
    comparison = report.get("comparison") or {}
    if comparison and not comparison.get("have_baseline"):
        add(
            "coverage:no-baseline",
            str(report.get("db") or "<store>"),
            "no previous run in the store, so every module is reported as new and no "
            "delta is computed (this run can be recorded as the baseline)",
            suggestion="scout coverage report --xml coverage.xml --record",
        )
    if max_drop is not None:
        for row in comparison.get("modules") or []:
            if row["delta"] is not None and row["delta"] < -abs(max_drop):
                add(
                    "coverage:regressed",
                    str(row["module"]),
                    f"coverage fell {abs(row['delta']):.2f} points "
                    f"({row['baseline_pct']:.2f}% -> {row['pct']:.2f}%), more than the "
                    f"{abs(max_drop):g}-point drop allowed",
                )
    outside = int(report.get("executed_outside_inventory") or 0)
    if outside:
        add(
            "coverage:executed-outside-inventory",
            "<report>",
            f"{outside} line(s) recorded as executed are not in the statement inventory, "
            "so the .coverage data and the XML describe different source; those lines "
            "were NOT counted toward coverage",
            suggestion="regenerate both reports from the same run",
        )
    for bad in report.get("unparsable") or []:
        add(
            "coverage:source-unparsable",
            str(bad.get("path")),
            f"report not parsed, so nothing in it was measured: {bad.get('error')}",
            suggestion="check the file is a Cobertura coverage.xml or a coverage.py 5+ .coverage",
        )
    return openswap.sort_diagnostics(diags)


# ---- the store --------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    label TEXT,
    depth INTEGER NOT NULL,
    sources TEXT NOT NULL,
    totals TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS modules(
    run_id INTEGER NOT NULL,
    module TEXT NOT NULL,
    statements INTEGER,
    covered INTEGER NOT NULL,
    pct REAL,
    unknown_reason TEXT,
    files INTEGER NOT NULL,
    files_unknown INTEGER NOT NULL,
    UNIQUE(run_id, module),
    -- The honesty invariant, enforced by the STORE and not just by the code
    -- that writes to it: a row has EITHER a percentage OR a reason it has
    -- none. Both operands are 0/1 from IS NULL, so no NULL propagation.
    CHECK ((pct IS NULL) != (unknown_reason IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_modules_run ON modules(run_id);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the coverage history store — its OWN sqlite file.

    Never the #2 uptime ledger: a CI run records a burst of module rows and
    must not contend with monitoring probes for the same write lock.
    """
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
    conn.commit()
    return conn


def record_run(
    conn: sqlite3.Connection, report: dict[str, Any], *, ts: float, label: str | None = None
) -> int:
    """Persist one run's module rows; returns the new run id.

    `ts` is injected, never read from a clock in here, so a recorded history is
    reproducible in a test.
    """
    cur = conn.execute(
        "INSERT INTO runs(ts, label, depth, sources, totals) VALUES(?, ?, ?, ?, ?)",
        (
            float(ts),
            label,
            int(report.get("depth") or DEFAULT_DEPTH),
            json.dumps(report.get("sources") or [], sort_keys=True),
            json.dumps(report.get("totals") or {}, sort_keys=True),
        ),
    )
    run_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO modules(run_id, module, statements, covered, pct, unknown_reason,"
        " files, files_unknown) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                m["module"],
                m["statements"],
                m["covered"],
                m["pct"],
                m["unknown_reason"],
                m["files"],
                m["files_unknown"],
            )
            for m in report.get("modules") or []
        ],
    )
    conn.commit()
    return run_id


def list_runs(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    """Recorded runs, newest first, with their stored totals."""
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"])
        d["totals"] = json.loads(d["totals"])
        out.append(d)
    return out


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    """One recorded run plus its module rows, or None when that id is absent."""
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (int(run_id),)).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["sources"] = json.loads(run["sources"])
    run["totals"] = json.loads(run["totals"])
    run["modules"] = [
        dict(m)
        for m in conn.execute(
            "SELECT module, statements, covered, pct, unknown_reason, files,"
            " files_unknown FROM modules WHERE run_id = ? ORDER BY module ASC",
            (int(run_id),),
        ).fetchall()
    ]
    return run


def latest_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """The most recently recorded run (the default baseline), or None."""
    row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return None if row is None else get_run(conn, int(row["id"]))


def build_report(
    combined: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    generated_ts: float = 0.0,
    title: str | None = None,
    db: str | None = None,
    unparsable: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combined measurements + a baseline run -> the renderable/emittable report."""
    baseline_modules = None if baseline is None else baseline.get("modules")
    report = dict(combined)
    report.update(
        {
            "title": title or "Coverage",
            "generated_ts": float(generated_ts),
            "db": db,
            "baseline": None
            if baseline is None
            else {
                "run_id": baseline.get("id"),
                "ts": baseline.get("ts"),
                "label": baseline.get("label"),
                "totals": baseline.get("totals"),
            },
            "comparison": compare_modules(combined["modules"], baseline_modules),
            "unparsable": list(unparsable or []),
            "scope_limits": SCOPE_LIMITS,
        }
    )
    return report


# ---- the static page --------------------------------------------------------

_CSS = (
    "body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:24px;"
    "background:#f7f7f8;color:#1b1b1f}"
    "h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}"
    ".note{color:#555;font-size:12px;margin:4px 0}"
    ".mono{font-family:ui-monospace,Consolas,monospace}"
    ".banner{padding:12px 16px;border-radius:6px;font-size:20px;font-weight:600;"
    "background:#e8eaf0;display:inline-block;margin:8px 0}"
    ".banner.unk{background:#3a3a44;color:#fff;font-size:15px}"
    "table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}"
    "th,td{padding:6px 8px;border-bottom:1px solid #e3e3e8;text-align:left}"
    "th{background:#eceef3;font-size:12px;text-transform:uppercase;letter-spacing:.03em}"
    "td.num{text-align:right;font-variant-numeric:tabular-nums}"
    ".bar{position:relative;height:10px;width:120px;background:#e3e3e8;border-radius:5px}"
    ".bar>span{position:absolute;left:0;top:0;bottom:0;background:#3f7d3f;border-radius:5px}"
    ".bar.low>span{background:#a33}.bar.mid>span{background:#b8860b}"
    ".bar.unknown{background:repeating-linear-gradient(45deg,#d8d8de,#d8d8de 4px,"
    "#eee 4px,#eee 8px)}"
    ".unk{color:#5b5b66;font-weight:600;letter-spacing:.04em}"
    ".pill{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;"
    "font-weight:600}"
    ".s-improved{background:#dff0d8;color:#2c5c2c}.s-regressed{background:#f7d7d7;color:#8b2020}"
    ".s-unchanged{background:#e8eaf0;color:#44444e}.s-new{background:#dce6f7;color:#24457e}"
    ".s-removed{background:#eee;color:#666}.s-unknown{background:#3a3a44;color:#fff}"
    "footer{margin-top:28px;color:#666;font-size:12px}"
    "ul{font-size:13px}li{margin:2px 0}"
)


def _iso(ts: float | None) -> str:
    """UTC ISO-8601 from an epoch — no locale, no timezone, no strftime."""
    if not ts:
        return "unrecorded"
    t = time.gmtime(float(ts))
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _bar(pct: float | None) -> str:
    """A coverage bar, or a hatched UNKNOWN bar with NO width at all.

    An unknown module gets no `width:` declaration — a zero-width bar reads as
    "0% covered", which is the picture this whole module exists to refuse.
    """
    if pct is None:
        return '<div class="bar unknown" title="no data"></div>'
    klass = "bar low" if pct < 50 else ("bar mid" if pct < 80 else "bar")
    return f'<div class="{klass}"><span style="width:{pct:.2f}%"></span></div>'


def _pct_cell(pct: float | None, reason: str | None) -> str:
    if pct is None:
        return f'<span class="unk" title="{html.escape(str(reason or "no data"))}">UNKNOWN</span>'
    return f"{pct:.2f}%"


def _delta_cell(row: dict[str, Any]) -> str:
    if row["delta"] is None:
        return f'<span class="unk" title="{html.escape(str(row["delta_reason"] or ""))}">n/a</span>'
    sign = "+" if row["delta"] > 0 else ""
    return f"{sign}{row['delta']:.2f}"


def _modules_table(report: dict[str, Any]) -> str:
    by_name = {r["module"]: r for r in report["comparison"]["modules"]}
    rows = []
    for mod in report["modules"]:
        d = by_name.get(mod["module"], {})
        status = str(d.get("status") or STATUS_UNKNOWN)
        unknown_note = f" ({mod['files_unknown']} unknown)" if mod["files_unknown"] else ""
        rows.append(
            "<tr>"
            f'<td class="mono">{html.escape(str(mod["module"]))}</td>'
            f'<td>{_bar(mod["pct"])}</td>'
            f'<td class="num">{_pct_cell(mod["pct"], mod["unknown_reason"])}</td>'
            f'<td class="num">{"" if mod["statements"] is None else mod["covered"]}</td>'
            f'<td class="num">{"" if mod["statements"] is None else mod["statements"]}</td>'
            f'<td class="num">{_pct_cell(d.get("baseline_pct"), d.get("delta_reason"))}</td>'
            f'<td class="num">{_delta_cell(d) if d else ""}</td>'
            f'<td><span class="pill s-{html.escape(status)}">{html.escape(status)}</span></td>'
            f'<td class="num">{mod["files"]}{html.escape(unknown_note)}</td>'
            "</tr>"
        )
    # Modules that vanished since the baseline still get a row: a deleted module
    # is a coverage EVENT, and dropping it from the table hides it.
    for row in report["comparison"]["modules"]:
        if row["status"] != STATUS_REMOVED:
            continue
        rows.append(
            "<tr>"
            f'<td class="mono">{html.escape(str(row["module"]))}</td>'
            f'<td>{_bar(None)}</td>'
            f'<td class="num">{_pct_cell(None, row["delta_reason"])}</td>'
            '<td class="num"></td><td class="num"></td>'
            f'<td class="num">{_pct_cell(row["baseline_pct"], row["delta_reason"])}</td>'
            f'<td class="num">{_delta_cell(row)}</td>'
            f'<td><span class="pill s-removed">{STATUS_REMOVED}</span></td>'
            '<td class="num"></td>'
            "</tr>"
        )
    return (
        "<table><tr><th>module</th><th></th><th>coverage</th><th>covered</th>"
        "<th>statements</th><th>baseline</th><th>delta</th><th>vs last run</th>"
        "<th>files</th></tr>\n" + "\n".join(rows) + "\n</table>"
    )


def render_html(report: dict[str, Any], *, title: str | None = None) -> str:
    """The Codecov web app, deleted: one self-contained HTML file.

    Inline CSS, zero JavaScript, zero external assets, every dynamic string
    through html.escape — it opens from file://, lives in an artifact directory
    or gets pasted into an email. Deterministic: the only timestamps are the
    ones the caller injected, so identical input renders identical bytes.
    """
    e = html.escape
    heading = title or str(report.get("title") or "Coverage")
    totals = report.get("totals") or {}
    parts: list[str] = [f"<h1>{e(heading)}</h1>"]
    if totals.get("pct") is None:
        parts.append(
            f'<div class="banner unk">UNKNOWN — {e(str(totals.get("unknown_reason")))}</div>'
        )
    else:
        parts.append(
            f'<div class="banner">{totals["pct"]:.2f}% '
            f'<span class="note">({totals["covered"]}/{totals["statements"]} '
            "statements)</span></div>"
        )
    src_bits = ", ".join(
        f'{e(str(s["label"]))} [{e(str(s["format"]))}, {int(s["files"])} file(s)]'
        for s in report.get("sources") or []
    )
    base = report.get("baseline")
    parts.append(
        f'<p class="note">Rendered {e(_iso(report.get("generated_ts")))} from '
        f'{src_bits or "no source"}. Baseline: '
        + (
            f'run {int(base["run_id"])} recorded {e(_iso(base.get("ts")))}'
            if base
            else "none recorded yet, so every module reads as new"
        )
        + ". Nothing was uploaded: this page was rendered on this box from a report "
        "that never left it.</p>"
    )
    if totals.get("files_unknown"):
        parts.append(
            f'<p class="note">{int(totals["files_unknown"])} of '
            f'{int(totals["files"])} file(s) have no percentage of their own (no '
            "statement inventory, or nothing measurable recorded in them). They are "
            "listed as UNKNOWN below, never as 0%.</p>"
        )
    parts.append("<h2>Modules</h2>")
    parts.append(_modules_table(report))
    counts = (report.get("comparison") or {}).get("counts") or {}
    parts.append(
        '<p class="note">vs last run: '
        + ", ".join(f"{int(counts.get(s, 0))} {s}" for s in STATUSES)
        + ". Per-FILE deltas are not stored (the history keeps module rows), so no "
        "per-file delta is shown rather than an empty cell implying zero.</p>"
    )

    unknown_files = [f for f in report.get("files") or [] if f["pct"] is None]
    parts.append("<h2>Unmeasured</h2>")
    if unknown_files:
        items = "\n".join(
            f'<li><span class="mono">{e(str(f["path"]))}</span> — '
            f'{e(str(f["unknown_reason"]))} (executed lines seen: {int(f["covered"])})</li>'
            for f in unknown_files
        )
        parts.append(f"<ul>\n{items}\n</ul>")
    else:
        parts.append(
            '<p class="note">Every file in this report carried a statement inventory.</p>'
        )

    if report.get("unparsable"):
        items = "\n".join(
            f'<li><span class="mono">{e(str(b.get("path")))}</span> — '
            f'{e(str(b.get("error")))}</li>'
            for b in report["unparsable"]
        )
        parts.append(f"<h2>Not parsed</h2>\n<ul>\n{items}\n</ul>")
    if report.get("notes"):
        items = "\n".join(f"<li>{e(str(n))}</li>" for n in report["notes"])
        parts.append(f"<h2>Notes</h2>\n<ul>\n{items}\n</ul>")
    parts.append(
        f'<footer>Static page from <span class="mono">scout coverage report</span> '
        f"(openswap #31 — Codecov replaced by a file). No upload, no token, no "
        f"JavaScript, no external assets. Scope: {e(SCOPE_LIMITS)}</footer>"
    )
    body = "\n".join(parts)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(heading)}</title>
<style>{_CSS}</style></head>
<body>
{body}
</body></html>
"""
