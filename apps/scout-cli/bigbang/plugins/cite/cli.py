# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout cite` — Zotero-storage / citation-SaaS replacement, fully local (openswap #33).

A reference library with the sync tier deleted. The paid thing here is not the
free local reader: it is the STORAGE — your library, your unpublished reading
list and your draft bibliography living in someone else's database, metered by
gigabyte — plus the hosted "format my citation" APIs around it. `import` parses
a .bib or CSL-JSON file into a local sqlite library, `format` renders a
bibliography in five deterministic styles, `list` queries the library and
`roundtrip` runs the fidelity experiment. The manifest disables the network axis
entirely, so "the reading list never left the box" is architectural rather than
a ToS promise.

All deterministic logic (the brace-aware BibTeX tokenizer, LaTeX-accent
decoding, BibTeX name splitting, the sqlite store, the CSL-JSON mapping and the
style renderers) lives in bigbang/core/cite.py. This surface owns the ONE real
I/O — Path.read_text on the file you name — plus the fs_write gate on the
library, and nothing else.

Round-trip fidelity is the contract, and this CLI keeps it enforceable rather
than aspirational:
- a malformed entry is REJECTED and reported with its rule, line and raw text,
  never half-imported, and `--on-conflict fail` writes NOTHING when any key
  already exists (validation runs before the first INSERT);
- `--no-record` is a real dry run: parse, report, touch nothing;
- `roundtrip` re-emits every stored entry, parses the emission back and diffs
  it, AND diffs the normalized field rows against a re-parse of the original
  text that was imported. `lost_fields` is measured, not promised.

There is no native tier and there will not be one. Zotero ships no CLI, and the
adjacent local tools (pandoc --citeproc, biber, bibtool) are PROBED for
awareness and NEVER executed: their output moves with their version and with a
downloaded .csl style file, so a bibliography gated on one would be
irreproducible across boxes (the links #4 doctrine — a gate whose answer moves
with PATH is flaky by construction). `native_used` is False on EVERY tier.

Deliberately NOT duplicated: full-text ranking over the library is searchindex
#20's job (sqlite FTS5) and `list` stays a field/substring filter so there is
not a second index to keep in sync; near-duplicate TEXT detection is dupes #28's
job, and the duplicate detection here is exact-key and normalized-DOI only —
the classic double-import, not shingling.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from bigbang.core import cite, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib citation manager is the complete product for this adapter: a "
    "brace-aware BibTeX tokenizer (@string macros, # concatenation, () and {} "
    "bodies, nested braces) that REFUSES a malformed entry instead of importing "
    "part of it, LaTeX-accent decoding for display, BibTeX name splitting in all "
    "three comma forms with von particles, CSL-JSON in and out, an indexed "
    "sqlite reference library, five deterministic output styles (apa, mla, "
    "chicago, ieee, bibtex) plus csl-json, and a measured round-trip fidelity "
    "audit; tier 'fallback' is the expected steady state (Zotero ships no CLI, "
    "and every adjacent local tool needs a downloaded .csl style file whose "
    "output moves with its version)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; install pandoc or biber "
    "separately only if you need a CSL style this plugin does not ship (this "
    "plugin never executes them, so its output cannot move with their version)"
)
NEVER_EXECUTED = (
    "pandoc/biber/bibtool are probed for awareness and NEVER executed to produce "
    "a citation: their rendering depends on their version and on a downloaded "
    ".csl style file, so a bibliography gated on one would differ between this "
    "box and CI — and a citation that changes shape between runs is not "
    "reproducible research"
)

INPUT_FORMATS = ("auto", "bibtex", "csl")

app = make_plugin_app(
    "cite",
    "Citation manager (Zotero-storage-class), fully local: BibTeX/CSL-JSON "
    "parser + sqlite reference library + deterministic bibliography, zero egress",
    examples=[
        "scout --json cite import refs.bib",
        "scout --json cite list --author doe --year-min 2015",
        "scout --json cite format --style apa --sort author",
        "scout --json cite roundtrip --fail-on error",
        "scout --json cite detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only when used
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _egress_guard(command: str) -> dict:
    """Assert the manifest still declares ZERO egress, or refuse to run.

    The inverse of an enforce_or_raise call site: this plugin makes no outbound
    call — a DOI is shape-checked, never resolved — so the thing worth checking
    is that nobody widened the axis to allow one. A privacy guarantee that lives
    only in a docstring is a promise; one that fails the command is a contract.
    """
    net = (_manifest().get("capabilities") or {}).get("network") or {}
    if net.get("enabled") or (net.get("domains") or []):
        fail_agent(
            "manifest declares network access for a plugin whose whole premise is "
            "zero egress — refusing to run until capabilities.network is disabled "
            "with an empty domain list",
            command=command,
            example="scout --json cite detect",
        )
    return {
        "network_enabled": False,
        "domains": [],
        "reads": "local .bib/.csl-json files only",
        "doi": "shape-checked, never resolved",
    }


def _capability() -> dict:
    # Zotero ships no CLI, so `native` stays a truthful probe that reports absent
    # and `native_used` is False on EVERY tier — tier=native must never be able
    # to imply that a binary produced a citation here. pandoc/biber/bibtool are
    # real, local and adjacent, which is exactly why they are surfaced instead of
    # being pretended away.
    native = openswap.probe_binary("zotero", probe_args=("--version",))
    extras = {
        "pandoc": openswap.probe_binary("pandoc", probe_args=("--version",)),
        "biber": openswap.probe_binary("biber", probe_args=("--version",)),
        "bibtool": openswap.probe_binary("bibtool", probe_args=("--version",)),
    }
    report = openswap.capability_report(
        "cite",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    report["native_used"] = False
    report["native_never_executed"] = NEVER_EXECUTED
    report["scope_limits"] = cite.SCOPE_LIMITS
    report["styles"] = list(cite.STYLES)
    return report


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_CITE_DB") or cite.DB_REL)


def _open_new(db: str | None):
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return cite.open_store(path), path


def _dry_or_real(db: str | None, record: bool):
    """The store for an import pass — and for --no-record, no new file.

    A dry run that CREATES the library it was told not to write is not a dry run.
    An existing library is still opened (read-mostly) so key conflicts are
    reported against the real keys; a library that does not exist yet stays
    non-existent and the pass runs against :memory:, which is why `db` comes back
    null instead of naming a file that was never made.
    """
    if record:
        return _open_new(db)
    path = _db_path(db)
    return (cite.open_store(path) if path.exists() else cite.open_store(":memory:")), path


def _open_existing(db: str | None, command: str):
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no citation library at {path} — import a .bib file first",
            command=command,
            example="scout --json cite import refs.bib",
            discover="scout --json cite detect",
        )
    return cite.open_store(path), path


def _rules_or_fail(rules_file: str | None, command: str) -> dict:
    try:
        return cite.load_rules(rules_file)
    except Exception as exc:
        fail_agent(
            f"bad rules overlay: {type(exc).__name__}: {exc}",
            command=command,
            example="scout --json cite rules --rules org-cite.json",
            discover="scout --json cite rules",
        )
        raise  # unreachable: fail_agent exits


def _fail_on_or_fail(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=f"scout --json {command} --fail-on error",
        )


def _import_flags_or_fail(fmt: str, on_conflict: str, fail_on: str | None) -> None:
    """Validate every import flag BEFORE the file is read or the store opened."""
    _fail_on_or_fail(fail_on, "cite import")
    if fmt not in INPUT_FORMATS:
        fail_agent(
            f"--format must be {'|'.join(INPUT_FORMATS)}, got {fmt!r}",
            command="cite import",
            example="scout --json cite import library.json --format csl",
        )
    if on_conflict not in cite.CONFLICT_POLICIES:
        fail_agent(
            f"--on-conflict must be one of {'|'.join(cite.CONFLICT_POLICIES)}, got {on_conflict!r}",
            command="cite import",
            example="scout --json cite import refs.bib --on-conflict replace",
        )


def _style_or_fail(style: str, command: str) -> str:
    low = str(style).lower()
    if low not in cite.STYLES:
        fail_agent(
            f"--style must be one of {'|'.join(cite.STYLES)}, got {style!r}",
            command=command,
            example="scout --json cite format --style apa",
            discover="scout --json cite rules",
        )
    return low


def _read_source(path_arg: str, fmt: str, command: str) -> dict:
    """The ONE real I/O in this plugin: read one local file and parse it.

    Never rewrites the file. A parse that raises (invalid JSON, undecodable
    bytes) becomes an actionable error rather than a traceback, because "which
    file and which line" is the only useful thing to say here.
    """
    p = Path(path_arg)
    if not p.is_file():
        fail_agent(
            f"file not found: {path_arg}",
            command=command,
            example="scout --json cite import refs.bib",
        )
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        fail_agent(
            f"cannot read {p.as_posix()}: {type(exc).__name__}: {exc}",
            command=command,
            example="scout --json cite import refs.bib",
        )
        raise  # unreachable
    resolved = _resolve_format(fmt, p, text)
    try:
        parsed = (
            cite.parse_csl_json(text, path=p.as_posix())
            if resolved == "csl"
            else cite.parse_bibtex(text, path=p.as_posix())
        )
    except (json.JSONDecodeError, ValueError) as exc:
        fail_agent(
            f"{p.as_posix()} is not valid {resolved}: {type(exc).__name__}: {exc}",
            command=command,
            example="scout --json cite import refs.bib --format bibtex",
        )
        raise  # unreachable
    parsed["format"] = resolved
    parsed["source"] = p.as_posix()
    return parsed


def _resolve_format(fmt: str, path: Path, text: str) -> str:
    """auto = extension, then a first-character sniff. Never a coin flip."""
    if fmt != "auto":
        return fmt
    if path.suffix.lower() in (".json", ".csl"):
        return "csl"
    if path.suffix.lower() in (".bib", ".bibtex"):
        return "bibtex"
    return "csl" if text.lstrip()[:1] in ("[", "{") else "bibtex"


def _entry_row(entry: dict) -> dict:
    """The compact library view: enough to identify an entry, honest about gaps."""
    names, role = cite.entry_names(entry)
    return {
        "key": entry["key"],
        "type": entry["type"],
        "year": cite.entry_year(entry),
        "first_author": cite.display_name(names[0], "family-given") if names else None,
        "author_role": role,
        "authors": len(names),
        "title": cite.delatex(entry["fields"].get("title", "")) or None,
        "doi": cite.normalize_doi(entry["fields"].get("doi", "")),
        "fields": len(entry["fields"]),
        "missing_required": cite.missing_required(entry),
    }


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json cite hello"]))
def hello():
    """Smoke check — is the cite surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "cite"},
            command="cite hello",
            example="scout --json cite import refs.bib",
            discover="scout cite detect",
        ),
        command="cite hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json cite detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    data = _capability()
    data["egress"] = _egress_guard("cite detect")
    emit(
        ok(
            data,
            command="cite detect",
            example="scout --json cite import refs.bib",
            discover="scout cite rules",
        ),
        command="cite detect",
    )


@app.command(
    "rules",
    epilog=examples_epilog(
        ["scout --json cite rules", "scout --json cite rules --rules org-cite.json"]
    ),
)
def rules_cmd(
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (org policy, policy-as-config)"
    ),
):
    """Publish the effective rule table, the per-type required fields and the styles."""
    merged = _rules_or_fail(rules_file, "cite rules")
    emit(
        ok(
            {
                "rules": merged,
                "overlay": rules_file,
                "rejecting_rules": sorted(cite.REJECTING_RULES),
                "severities": list(openswap.SEVERITIES),
                "styles": list(cite.STYLES),
                "sort_keys": list(cite.SORT_KEYS),
                "conflict_policies": list(cite.CONFLICT_POLICIES),
                "required_fields": {t: list(f) for t, f in sorted(cite.REQUIRED.items())},
                "no_date_marker": cite.NO_DATE,
                "scope_limits": cite.SCOPE_LIMITS,
            },
            command="cite rules",
            example="scout --json cite import refs.bib --rules org-cite.json",
            discover="scout cite import <file>",
        ),
        command="cite rules",
    )


@app.command(
    "import",
    epilog=examples_epilog(
        [
            "scout --json cite import refs.bib",
            "scout --json cite import library.json --format csl --on-conflict replace",
            "scout --json cite import refs.bib --no-record --fail-on error",
        ]
    ),
)
def import_cmd(
    source: str = typer.Argument(..., help="a .bib or CSL-JSON file (read only, never rewritten)"),
    fmt: str = typer.Option("auto", "--format", help="bibtex|csl|auto (extension, then a first-character sniff)"),
    db: str | None = typer.Option(None, "--db", help=f"library path (default {cite.DB_REL.as_posix()} or $SCOUT_CITE_DB)"),
    on_conflict: str = typer.Option(
        "skip",
        "--on-conflict",
        help="skip|replace|fail — `fail` writes NOTHING if any key already exists",
    ),
    record: bool = typer.Option(
        True,
        "--record/--no-record",
        help="persist entries (off = a real dry run: parse, report, touch nothing)",
    ),
    rules_file: str | None = typer.Option(None, "--rules", help="JSON rules overlay"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 on findings at/above this severity — the CI gate hook"
    ),
):
    """Parse a .bib / CSL-JSON file into the library. Malformed entries are refused."""
    _import_flags_or_fail(fmt, on_conflict, fail_on)
    _egress_guard("cite import")
    rules = _rules_or_fail(rules_file, "cite import")
    parsed = _read_source(source, fmt, "cite import")
    conn, path = _dry_or_real(db, record)
    try:
        result = cite.import_entries(
            conn, parsed["entries"], source=parsed["source"], on_conflict=on_conflict, record=record
        )
    except ValueError as exc:
        fail_agent(
            str(exc),
            command="cite import",
            example="scout --json cite import refs.bib --on-conflict replace",
        )
        raise  # unreachable
    diags = cite.diagnostics_from(
        [*parsed["problems"], *result["problems"]], path=parsed["source"], rules=rules
    )
    emit(
        ok(
            {
                "db": str(path) if record else None,
                "source": parsed["source"],
                "format": parsed["format"],
                "counts": parsed["counts"],
                "macros_defined": sorted(parsed["strings"]),
                **{k: v for k, v in result.items() if k != "problems"},
                "rejected": parsed["rejected"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
                "scope_limits": cite.SCOPE_LIMITS,
            },
            command="cite import",
            example="scout --json cite format --style apa",
            discover="scout cite list",
        ),
        command="cite import",
    )
    _gate(diags, fail_on)


@app.command(
    "list",
    epilog=examples_epilog(
        [
            "scout --json cite list",
            "scout --json cite list --author doe --year-min 2015 --type article",
            "scout --json cite list --doi 10.1000/xyz123",
        ]
    ),
)
def list_cmd(
    key: str | None = typer.Option(None, "--key", help="substring of the citation key"),
    entry_type: str | None = typer.Option(None, "--type", help="exact entry type (article, book, ...)"),
    author: str | None = typer.Option(None, "--author", help="substring of any contributor name (accents decoded)"),
    year_min: int | None = typer.Option(None, "--year-min", help="inclusive lower bound; an undated entry never matches"),
    year_max: int | None = typer.Option(None, "--year-max", help="inclusive upper bound; an undated entry never matches"),
    doi: str | None = typer.Option(None, "--doi", help="exact DOI after normalization (bare, doi: or https://doi.org/ all work)"),
    limit: int = typer.Option(50, "--limit", help="max entries returned"),
    offset: int = typer.Option(0, "--offset", help="skip this many matches (stable key order)"),
    db: str | None = typer.Option(None, "--db", help="library path"),
):
    """Field filters over the library. Read-only; full-text ranking is searchindex #20."""
    _egress_guard("cite list")
    conn, path = _open_existing(db, "cite list")
    try:
        entries = cite.query(
            conn,
            key_contains=key,
            entry_type=entry_type,
            author_contains=author,
            year_min=year_min,
            year_max=year_max,
            doi=doi,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        # a filter that cannot match anything is an error, not an empty result set
        fail_agent(
            str(exc),
            command="cite list",
            example="scout --json cite list --doi 10.1000/xyz123",
            discover="scout --json cite list",
        )
        raise  # unreachable
    emit(
        ok(
            {
                "db": str(path),
                "filters": {
                    "key": key,
                    "type": entry_type,
                    "author": author,
                    "year_min": year_min,
                    "year_max": year_max,
                    "doi": doi,
                    "limit": limit,
                    "offset": offset,
                },
                "count": len(entries),
                "entries": [_entry_row(e) for e in entries],
                "library": cite.library_stats(conn),
            },
            command="cite list",
            example="scout --json cite format --key doe2020 --style ieee",
            discover="scout cite format --style apa",
        ),
        command="cite list",
    )


@app.command(
    "format",
    epilog=examples_epilog(
        [
            "scout --json cite format --style apa --sort author",
            "scout --json cite format --key doe2020 --style ieee",
            "scout --json cite format --file refs.bib --style chicago --strict",
        ]
    ),
)
def format_cmd(
    style: str = typer.Option("apa", "--style", help=f"{'|'.join(cite.STYLES)}"),
    keys: list[str] = typer.Option([], "--key", help="format only these keys (repeatable)"),
    file: str | None = typer.Option(None, "--file", help="format straight from a .bib/CSL file, no library needed"),
    sort: str = typer.Option("key", "--sort", help=f"{'|'.join(cite.SORT_KEYS)} (ties always fall through to the key)"),
    fmt: str = typer.Option("auto", "--format", help="input format when --file is used: bibtex|csl|auto"),
    strict: bool = typer.Option(
        False, "--strict", help="exit 1 if any entry could not be rendered (missing required fields)"
    ),
    db: str | None = typer.Option(None, "--db", help="library path"),
):
    """Render a bibliography. A reference is rendered in full or reported, never holed."""
    low = _style_or_fail(style, "cite format")
    if sort not in cite.SORT_KEYS:
        fail_agent(
            f"--sort must be one of {'|'.join(cite.SORT_KEYS)}, got {sort!r}",
            command="cite format",
            example="scout --json cite format --style apa --sort author",
        )
    _egress_guard("cite format")
    if file is not None:
        parsed = _read_source(file, fmt, "cite format")
        entries, origin, rejected = parsed["entries"], parsed["source"], parsed["rejected"]
    else:
        conn, path = _open_existing(db, "cite format")
        entries = [e for e in (cite.load_entry(conn, k) for k in keys) if e] if keys else cite.query(conn, limit=-1)
        origin, rejected = str(path), []
        missing = sorted(set(keys) - {e["key"] for e in entries})
        if missing:
            fail_agent(
                f"key(s) not in the library: {', '.join(missing)}",
                command="cite format",
                example="scout --json cite list",
                discover="scout --json cite list",
            )
    if not entries:
        fail_agent(
            f"nothing to format from {origin} — the library or file holds no usable entries",
            command="cite format",
            example="scout --json cite import refs.bib",
        )
    biblio = cite.bibliography(entries, low, sort=sort)
    emit(
        ok(
            {
                "source": origin,
                **biblio,
                "rejected": rejected,
                "text": "\n".join(r["text"] for r in biblio["entries"] if r["text"]),
                "scope_limits": cite.SCOPE_LIMITS,
            },
            command="cite format",
            example="scout --json cite roundtrip --fail-on error",
            discover="scout cite rules",
        ),
        command="cite format",
    )
    if strict and biblio["failed"]:
        raise typer.Exit(code=1)


@app.command(
    "roundtrip",
    epilog=examples_epilog(
        [
            "scout --json cite roundtrip",
            "scout --json cite roundtrip --file refs.bib --fail-on error",
            "scout --json cite roundtrip --key doe2020",
        ]
    ),
)
def roundtrip_cmd(
    keys: list[str] = typer.Option([], "--key", help="check only these keys (repeatable)"),
    file: str | None = typer.Option(None, "--file", help="check a .bib/CSL file directly, no library needed"),
    fmt: str = typer.Option("auto", "--format", help="input format when --file is used: bibtex|csl|auto"),
    rules_file: str | None = typer.Option(None, "--rules", help="JSON rules overlay"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 on findings at/above this severity — the CI gate hook"
    ),
    db: str | None = typer.Option(None, "--db", help="library path"),
):
    """Measure fidelity: emit, parse back, diff. Nothing here is assumed."""
    _fail_on_or_fail(fail_on, "cite roundtrip")
    _egress_guard("cite roundtrip")
    rules = _rules_or_fail(rules_file, "cite roundtrip")
    if file is not None:
        parsed = _read_source(file, fmt, "cite roundtrip")
        reports = [cite.roundtrip_report(e) for e in parsed["entries"]]
        result = {
            "checked": len(reports),
            "identical": sum(1 for r in reports if r["identical"]),
            "store_faithful": None,  # no store was involved — measured nowhere, so not claimed
            "lost_fields": sorted({f for r in reports for f in r["lost_fields"]}),
            "reports": reports,
        }
        origin = parsed["source"]
    else:
        conn, path = _open_existing(db, "cite roundtrip")
        result = cite.store_roundtrip(conn, keys or None)
        origin = str(path)
    problems = [
        {
            "rule": "cite:roundtrip-lost",
            "line": 1,
            "path": origin,
            "message": (
                f"{r['key']}: "
                + (r["error"] or f"lost {', '.join(r['lost_fields']) or '-'}; changed {len(r['changed_fields'])} field(s)")
            ),
            "suggestion": "open the entry in the source .bib — a field value likely has unbalanced braces",
        }
        for r in result["reports"]
        if not r["identical"] or r.get("store_faithful") is False
    ]
    diags = cite.diagnostics_from(problems, path=origin, rules=rules)
    emit(
        ok(
            {"source": origin, **result, "diagnostics": diags, "summary": openswap.summarize(diags)},
            command="cite roundtrip",
            example="scout --json cite format --style apa",
            discover="scout cite list",
        ),
        command="cite roundtrip",
    )
    _gate(diags, fail_on)


@app.command(
    "forget",
    epilog=examples_epilog(
        ["scout --json cite forget --key doe2020 --yes", "scout --json cite forget --key a --key b --dry-run"]
    ),
)
def forget_cmd(
    keys: list[str] = typer.Option(..., "--key", help="citation key to remove (repeatable)"),
    yes: bool = typer.Option(False, "--yes", help="required to actually delete (no prompt, ever)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="report what would go, delete nothing"),
    db: str | None = typer.Option(None, "--db", help="library path"),
):
    """Remove keys from the library. Reports which were actually present."""
    _egress_guard("cite forget")
    conn, path = _open_existing(db, "cite forget")
    if dry_run or not yes:
        present = {e["key"] for e in cite.query(conn, limit=-1)}
        emit(
            ok(
                {
                    "db": str(path),
                    "dry_run": True,
                    "would_delete": sorted(k for k in keys if k in present),
                    "not_found": sorted(k for k in keys if k not in present),
                    "note": "nothing was deleted — pass --yes to commit",
                },
                command="cite forget",
                example="scout --json cite forget --key doe2020 --yes",
                discover="scout cite list",
            ),
            command="cite forget",
        )
        return
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    result = cite.delete_entries(conn, keys)
    emit(
        ok(
            {"db": str(path), "dry_run": False, **result},
            command="cite forget",
            example="scout --json cite list",
            discover="scout cite list",
        ),
        command="cite forget",
    )


def register(root):
    root.add_typer(app, name="cite")
