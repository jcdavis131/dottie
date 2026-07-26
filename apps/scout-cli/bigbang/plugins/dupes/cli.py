# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout dupes` — Copyscape replacement, fully local (openswap #28).

Duplicate-content detection with the upload deleted. Copyscape's model is to
send the page you have not published yet to someone else's index, per query;
this surface never does, and cannot: the manifest disables the network axis
entirely (`detect` proves it by asking the policy gate for copyscape.com and
showing the denial), so "the unpublished draft never left the box" is
architectural rather than a promise.

The ONE real I/O lives here — reading local files as BYTES (Path.read_bytes,
never read_text: the encoding is sniffed, because a UTF-16 draft decoded as
UTF-8 becomes mojibake and mojibake matches nothing, i.e. a silent "no
duplicates"). Every judgment is deterministic and lives in
bigbang/core/dupes.py: k-shingling, blake2b fingerprints (never builtin hash(),
whose seed changes per process), Jaccard for "same page" plus containment for
"this draft is a slice of that page", and union-find clusters. Document ids are
posix-relative, so a report is byte-identical on Windows and Linux and diffs
clean in git when nothing moved.

Honesty is enforced, not documented: a file that is too large, binary or
unreadable, and a document too short to shingle, are each reported with a
LABELLED reason and surfaced as info-level diagnostics. A duplicate report that
quietly skipped half the corpus is worse than no report, so nothing is dropped
silently and no similarity number is ever invented to fill a field.

Policy: zero egress on every path, no filesystem writes at all (the manifest
denies both axes; the paths read are the ones named on the command line, never
a manifest allowlist widened to match them). fdupes/rdfind/jdupes are surfaced
by `detect` as local exact-byte duplicate finders and jscpd as a node code-clone
detector — none is a superset of near-duplicate PROSE detection, and none is
ever executed.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from bigbang.core import dupes, openswap, prose
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import check_permission, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib shingling detector is the complete product for this adapter: "
    "sniffed-encoding local file ingestion, markdown/HTML/plain-text "
    "tokenization reused from prose #1, k-shingle blake2b fingerprints, "
    "normalized-content sha256 for exact recycled copy, Jaccard similarity "
    "plus containment for partial lifts, a postings index so only pairs that "
    "share a shingle are compared, union-find near-duplicate clusters and "
    "labelled reasons for every unmeasured document; tier 'fallback' is the "
    "expected steady state — Copyscape is SaaS, and fdupes/rdfind/jdupes find "
    "BYTE-identical files only (they cannot see a reworded paragraph) while "
    "jscpd is a node code-clone detector, so no local binary supersedes this"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; fdupes/rdfind/jdupes on "
    "PATH are surfaced as exact-byte duplicate finders for manual use only and "
    "are never executed by scout"
)

# the SaaS this adapter replaces — used only to demonstrate the egress denial
SAAS_ORIGIN = "https://www.copyscape.com"

app = make_plugin_app(
    "dupes",
    "Find recycled and near-duplicate copy across local pages and drafts "
    "(Copyscape-class), fully local: k-shingling + Jaccard clusters, zero egress",
    examples=[
        "scout --json dupes scan docs",
        "scout --json dupes scan docs --threshold 0.4 --root docs",
        "scout --json dupes compare a.md b.md",
        "scout --json dupes config",
        "scout --json dupes detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only on probes
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _egress_gate() -> dict:
    """Ask the policy gate for the SaaS origin and report the denial verbatim.

    The privacy claim is falsifiable rather than asserted: this runs the same
    check_permission() every network call in this repo goes through, against the
    very host Copyscape would need, and shows the answer.
    """
    allowed, reason = check_permission(_manifest(), "network", SAAS_ORIGIN)
    return {"resource": SAAS_ORIGIN, "allowed": allowed, "reason": reason}


def _capability() -> dict:
    # Probes are truthful; execution stays stdlib regardless (module doc).
    native = openswap.probe_binary("jscpd", probe_args=("--version",))
    extras = {
        "fdupes": openswap.probe_binary("fdupes", probe_args=("--version",)),
        "rdfind": openswap.probe_binary("rdfind", probe_args=("--version",)),
        "jdupes": openswap.probe_binary("jdupes", probe_args=("--version",)),
    }
    report = openswap.capability_report(
        "dupes",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    report["egress_gate"] = _egress_gate()
    return report


def _config(
    config_file: str | None, overrides: dict, command: str, example: str
) -> dict:
    """Effective config: DEFAULT_CONFIG + optional JSON overlay + CLI flags."""
    overlay: dict = {}
    if config_file:
        try:
            overlay = json.loads(Path(config_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            fail_agent(
                f"bad config file {config_file}: {type(exc).__name__}: {exc}",
                command=command,
                example=example,
            )
        if not isinstance(overlay, dict):
            fail_agent(
                f"config file {config_file} must hold a JSON object",
                command=command,
                example=example,
            )
    overlay.update({k: v for k, v in overrides.items() if v is not None})
    try:
        return dupes.merge_config(overlay)
    except ValueError as exc:
        fail_agent(f"bad config: {exc}", command=command, example=example)
        raise  # unreachable: fail_agent exits (keeps the return type honest)


def _collect(paths: list[str], command: str, example: str) -> list[Path]:
    """Files named directly + every DOC_EXTS file under a named directory."""
    files: list[Path] = []
    for raw in paths:
        pth = Path(raw)
        if pth.is_file():
            files.append(pth)
        elif pth.is_dir():
            for ext in dupes.DOC_EXTS:
                files.extend(pth.rglob(f"*{ext}"))
        else:
            fail_agent(f"path not found: {raw}", command=command, example=example)
    return sorted(set(files))


def _doc_id(path: Path, root: Path | None) -> str:
    """Stable, diffable, platform-independent id: a posix relative path."""
    for base in (root, Path.cwd()):
        if base is None:
            continue
        try:
            return path.resolve().relative_to(base.resolve()).as_posix()
        except (OSError, ValueError):
            continue
    return path.as_posix()


def _read_doc(path: Path, root: Path | None, cfg: dict) -> tuple[dict, dict]:
    """The ONE real I/O: one file -> (document, provenance). Never raises.

    Every failure becomes a LABELLED reason on the document instead of an
    exception or a silent skip, because a corpus scan that dies on file 40 of
    200 (or quietly ignores it) reports "no duplicates" for the wrong reason.
    """
    doc_id = _doc_id(path, root)
    src = {"id": doc_id, "bytes": None, "encoding": None, "via": None}
    try:
        size = path.stat().st_size
        if size > cfg["max_bytes"]:
            reason = f"too-large: {size} bytes > max_bytes {cfg['max_bytes']}"
            return {"id": doc_id, "error": reason}, src
        data = path.read_bytes()
    except OSError as exc:
        return {"id": doc_id, "error": f"unreadable: {type(exc).__name__}: {exc}"}, src
    src["bytes"] = len(data)
    if dupes.looks_binary(data):
        return {"id": doc_id, "error": "binary: NUL bytes and no text encoding"}, src
    text, det = dupes.decode_document(data)
    src["encoding"], src["via"] = det["encoding"], det["via"]
    return {"id": doc_id, "text": text, "fmt": prose.detect_format(path.name)}, src


def _gate(diags: list[dict], fail_on: str | None, command: str, example: str) -> None:
    """`--fail-on <severity>`: the pre-publish gate hook, same as prose/seo."""
    if fail_on is None:
        return
    if fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=example,
        )
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json dupes hello"]))
def hello():
    """Smoke check — is the dupes surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "dupes"},
            command="dupes hello",
            example="scout --json dupes scan docs",
            discover="scout dupes detect",
        ),
        command="dupes hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json dupes detect"]))
def detect():
    """Report the capability tier + prove the egress denial (fallback IS the product)."""
    emit(
        ok(
            _capability(),
            command="dupes detect",
            example="scout --json dupes scan docs",
            discover="scout dupes config",
        ),
        command="dupes detect",
    )


@app.command(
    "config",
    epilog=examples_epilog(
        ["scout --json dupes config", "scout --json dupes config --config dupes.json"]
    ),
)
def config_cmd(
    config_file: str | None = typer.Option(
        None, "--config", help="JSON overlay on the default thresholds"
    ),
):
    """Show the effective detection config (defaults + optional JSON overlay)."""
    cfg = _config(config_file, {}, "dupes config", "scout --json dupes config")
    emit(
        ok(
            {"config": cfg, "overlay": config_file, "extensions": list(dupes.DOC_EXTS)},
            command="dupes config",
            example="scout --json dupes scan docs --config dupes.json",
            discover="scout dupes scan <path>",
        ),
        command="dupes config",
    )


@app.command(
    "scan",
    epilog=examples_epilog(
        [
            "scout --json dupes scan docs",
            "scout --json dupes scan docs drafts --root .",
            "scout --json dupes scan docs --threshold 0.4 --k 4",
            "scout --json dupes scan docs --fail-on warning",
        ]
    ),
)
def scan(
    paths: list[str] = typer.Argument(
        ...,
        help="files or directories (dirs walked for " + ", ".join(dupes.DOC_EXTS) + ")",
    ),
    root: str | None = typer.Option(
        None, "--root", help="relativize document ids to this dir (default: cwd)"
    ),
    config_file: str | None = typer.Option(
        None, "--config", help="JSON overlay on the default thresholds"
    ),
    k: int | None = typer.Option(None, "--k", help="shingle width in tokens"),
    threshold: float | None = typer.Option(
        None, "--threshold", help="Jaccard gate for a near-duplicate (0.0-1.0)"
    ),
    containment: float | None = typer.Option(
        None, "--containment", help="containment gate for a partial lift (0.0-1.0)"
    ),
    min_tokens: int | None = typer.Option(
        None, "--min-tokens", help="documents shorter than this are not shingled"
    ),
    show_shingles: bool = typer.Option(
        False, "--shingles", help="include every shingle digest (audit; very verbose)"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if any finding is at/above this severity "
        "(error|warning|suggestion|info) — the pre-publish gate hook",
    ),
):
    """Fingerprint a local corpus and report near-duplicate clusters. Reads files only."""
    example = "scout --json dupes scan docs --fail-on warning"
    cfg = _config(
        config_file,
        {
            "k": k,
            "threshold": threshold,
            "containment_threshold": containment,
            "min_tokens": min_tokens,
        },
        "dupes scan",
        example,
    )
    base = Path(root) if root else None
    if base is not None and not base.is_dir():
        fail_agent(
            f"--root is not a directory: {root}", command="dupes scan", example=example
        )
    files = _collect(paths, "dupes scan", example)
    if not files:
        fail_agent(
            f"no {'/'.join(dupes.DOC_EXTS)} files under {', '.join(paths)}",
            command="dupes scan",
            example=example,
        )
    documents, sources = [], []
    for path in files:
        doc, src = _read_doc(path, base, cfg)
        documents.append(doc)
        sources.append(src)
    report = dupes.analyze(documents, config=cfg, include_shingles=show_shingles)
    report["roots"] = list(paths)
    report["sources"] = sources
    emit(
        ok(
            report,
            command="dupes scan",
            example="scout --json dupes compare a.md b.md",
            discover="scout dupes config",
        ),
        command="dupes scan",
    )
    _gate(report["diagnostics"], fail_on, "dupes scan", example)


@app.command(
    "compare",
    epilog=examples_epilog(
        [
            "scout --json dupes compare a.md b.md",
            "scout --json dupes compare a.md b.md --k 3 --min-tokens 3",
        ]
    ),
)
def compare(
    left: str = typer.Argument(..., help="first file"),
    right: str = typer.Argument(..., help="second file"),
    config_file: str | None = typer.Option(
        None, "--config", help="JSON overlay on the default thresholds"
    ),
    k: int | None = typer.Option(None, "--k", help="shingle width in tokens"),
    min_tokens: int | None = typer.Option(
        None, "--min-tokens", help="documents shorter than this are not shingled"
    ),
):
    """Two documents, one similarity reading (or one labelled reason). Reads files only."""
    example = "scout --json dupes compare a.md b.md"
    cfg = _config(
        config_file, {"k": k, "min_tokens": min_tokens}, "dupes compare", example
    )
    files = _collect([left, right], "dupes compare", example)
    if len(files) != 2:
        fail_agent(
            f"compare needs two distinct files, got {[str(f) for f in files]}",
            command="dupes compare",
            example=example,
        )
    documents = [_read_doc(path, None, cfg)[0] for path in files]
    rows = dupes.fingerprint_documents(documents, config=cfg)
    pair = dupes.compare_rows(rows[0], rows[1], config=cfg)
    unmeasured = [r for r in rows if r["errors"]]
    reported = [pair] if pair.get("kind") in dupes.KINDS else []
    diags = dupes.to_diagnostics(reported, unmeasured, config=cfg)
    emit(
        ok(
            {
                "config": cfg,
                "documents": dupes.document_view(rows),
                "pair": pair,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="dupes compare",
            example="scout --json dupes scan docs",
            discover="scout dupes scan <path>",
        ),
        command="dupes compare",
    )


def register(root):
    root.add_typer(app, name="dupes")
