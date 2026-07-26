# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout contentgap` — Clearscope replacement, fully local (openswap #24).

Content optimization with the crawler deleted. Clearscope, Surfer and
MarketMuse all sell the same loop — upload a draft, they fetch the pages already
ranking for the topic, weight the vocabulary those pages share, and return the
terms you are missing — and the part you pay for is also the part that ships
your unpublished draft off the box. Here the comparison corpus is FILES ALREADY
ON DISK (pages you saved, exported, or pulled earlier with `scout extract`), the
term weighting is `collections.Counter` + `math.log`, and the manifest disables
the network axis entirely: nothing is fetched, at any tier, ever. That makes
"the draft never left the machine" architectural rather than a ToS promise.

All deterministic logic (tokenizer, sublinear tf, smoothed idf, density-
normalized expectations, missing/thin/overused classification, coverage score,
the markdown brief) lives in bigbang/core/contentgap.py. This surface owns the
one real I/O — reading the draft and the corpus files — plus argument parsing,
the fs_write gate for `brief`, and the --fail-on exit code.

Three things it gets right that a naive keyword counter does not: markup is
stripped by reusing the prose extractors (code fences and <script> never become
"terms"), a term used by every comparison page keeps weight 1.0 instead of being
zeroed by textbook idf (the consensus vocabulary is the point), and expectations
are density-normalized, so a 300-word draft is never told to match a 3,000-word
page's raw counts. Over-optimization is reported too: `overused` is a finding,
because "add more keywords" is how these tools get you penalized.

Policy: no network axis at all (see manifest — enabled:false, empty domain
list). Corpus and draft files are READ ONLY; the single write is the optional
brief artifact, gated by enforce_or_raise(fs_write) at the call site and written
with write_bytes so the markdown stays byte-identical across platforms. There is
no native binary tier to prefer: every competitor in this category is a hosted
web app, so `detect` reports tier=fallback as the expected steady state (scope
honesty, not degradation). yake and pandoc are surfaced as optional LOCAL
helpers and are never executed.
"""

from __future__ import annotations

from pathlib import Path

import typer

from bigbang.core import contentgap, openswap, prose
from bigbang.core.cli_ux import examples_epilog, fail_agent, read_stdin_text
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib TF-IDF content optimizer is the complete product for this "
    "adapter: markup-aware tokenizer, sublinear tf with smoothed idf over a "
    "local corpus of comparison pages, unigrams + adjacent phrases, density-"
    "normalized per-term expectations, missing/thin/overused classification, a "
    "weighted coverage score and the markdown content brief; tier 'fallback' is "
    "the expected steady state (Clearscope, Surfer and MarketMuse are hosted "
    "web apps — no local native binary does draft-vs-corpus coverage)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; yake (local keyword "
    "extraction) and pandoc (convert odd corpus formats to .txt/.md before "
    "indexing) are optional local helpers, never required and never called"
)
STDIN_DRAFT = "-"

app = make_plugin_app(
    "contentgap",
    "TF-IDF content optimizer (Clearscope-class), fully local: weight a cached "
    "corpus of comparison pages and report the terms your draft is missing",
    examples=[
        "scout --json contentgap terms --corpus .scout/contentgap/corpus",
        "scout --json contentgap audit draft.md --corpus corpus/",
        "scout --json contentgap audit draft.md --corpus corpus/ --fail-on warning",
        "scout contentgap brief draft.md --corpus corpus/ --out .scout/brief.md",
        "scout --json contentgap detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only on writes
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # There is no local native CLI that does draft-vs-corpus coverage — the
    # whole category (Clearscope/Surfer/MarketMuse) ships browser apps over
    # hosted APIs — so `native` stays a truthful probe that reports absent
    # rather than a fake binary name that could accidentally exist. yake and
    # pandoc are benign optional local helpers; neither is ever executed here.
    native = openswap.probe_binary("clearscope", probe_args=("--version",))
    extras = {
        "yake": openswap.probe_binary("yake", probe_args=("--help",)),
        "pandoc": openswap.probe_binary("pandoc", probe_args=("--version",)),
    }
    return openswap.capability_report(
        "contentgap",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _read_doc(path: Path, *, max_kb: int) -> dict:
    """Read one corpus file — the ONE real I/O, with labelled failures.

    An unreadable or oversized file returns text=None plus the reason, and
    build_corpus() puts it in `skipped` instead of dropping it silently: a
    corpus that quietly lost a page reports different weights for no visible
    cause. errors="replace" keeps a mixed-encoding page countable.
    """
    name = path.as_posix()
    try:
        size = path.stat().st_size
        if size > max_kb * 1024:
            return {
                "name": name,
                "text": None,
                "error": f"too-large: {size // 1024} KB > --max-kb {max_kb}",
            }
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"name": name, "text": None, "error": f"{type(exc).__name__}: {exc}"}
    return {"name": name, "text": text, "format": prose.detect_format(name)}


def _corpus_files(paths: list[str], command: str) -> list[Path]:
    """Expand corpus arguments (files or directories) — pathlib only, sorted."""
    found: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            found.add(p)
        elif p.is_dir():
            for ext in contentgap.CORPUS_EXTS:
                found.update(f for f in p.rglob(f"*{ext}") if f.is_file())
        else:
            fail_agent(
                f"corpus path not found: {raw}",
                command=command,
                example="scout --json contentgap terms --corpus corpus/",
            )
    return sorted(found)


def _model(
    corpus: list[str], *, phrases: bool, min_length: int, max_kb: int, command: str
) -> dict:
    """Build the weighted corpus model from disk. No network on any path."""
    files = _corpus_files(corpus or [str(contentgap.CORPUS_REL)], command)
    if not files:
        fail_agent(
            f"no corpus documents found in {', '.join(corpus) or contentgap.CORPUS_REL}"
            f" (looking for {', '.join(contentgap.CORPUS_EXTS)}) — save the pages you"
            " want to be measured against there first; contentgap never fetches",
            command=command,
            example="scout --json contentgap terms --corpus corpus/",
        )
    docs = [_read_doc(f, max_kb=max_kb) for f in files]
    return contentgap.build_corpus(docs, phrases=phrases, min_length=min_length)


def _draft(draft: str, command: str) -> tuple[str, str, str]:
    """(text, display path, format) for the draft — a file, or '-' for stdin."""
    if draft == STDIN_DRAFT:
        try:
            return read_stdin_text(strip=False), "(stdin)", contentgap.FORMAT_TEXT
        except ValueError:
            fail_agent(
                "no draft on stdin",
                command=command,
                example="scout --json contentgap audit draft.md --corpus corpus/",
            )
    path = Path(draft)
    if not path.is_file():
        fail_agent(
            f"draft not found: {draft}",
            command=command,
            example="scout --json contentgap audit draft.md --corpus corpus/",
        )
    name = path.as_posix()
    return (
        path.read_text(encoding="utf-8", errors="replace"),
        name,
        prose.detect_format(name),
    )


def _audit(
    draft: str,
    *,
    corpus: list[str],
    top: int,
    phrases: bool,
    min_length: int,
    max_kb: int,
    thin_ratio: float,
    over_ratio: float,
    target_score: float,
    fail_on: str | None,
    command: str,
) -> tuple[dict, list[dict]]:
    """The shared audit pipeline behind `audit` and `brief`.

    --fail-on is validated BEFORE any file is read, so a typo'd gate fails on
    the argument rather than after a full pass.
    """
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json contentgap audit draft.md --fail-on warning",
        )
    model = _model(
        corpus,
        phrases=phrases,
        min_length=min_length,
        max_kb=max_kb,
        command=command,
    )
    text, name, fmt = _draft(draft, command)
    report = contentgap.analyze(
        text,
        model,
        path=name,
        fmt=fmt,
        top=top,
        thin_ratio=thin_ratio,
        over_ratio=over_ratio,
        target_score=target_score,
    )
    return report, contentgap.to_diagnostics(report)


def _gate(diags: list[dict], fail_on: str | None) -> None:
    """Exit 1 when any finding lands at or above the requested severity."""
    if fail_on is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json contentgap hello"]))
def hello():
    """Smoke check — is the contentgap surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "contentgap"},
            command="contentgap hello",
            example="scout --json contentgap audit draft.md --corpus corpus/",
            discover="scout contentgap detect",
        ),
        command="contentgap hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json contentgap detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="contentgap detect",
            example="scout --json contentgap audit draft.md --corpus corpus/",
            discover="scout contentgap terms --corpus corpus/",
        ),
        command="contentgap detect",
    )


@app.command(
    "terms",
    epilog=examples_epilog(
        [
            "scout --json contentgap terms --corpus corpus/",
            "scout --json contentgap terms --corpus corpus/ --top 20 --no-phrases",
        ]
    ),
)
def terms(
    corpus: list[str] = typer.Option(
        None,
        "--corpus",
        help=f"corpus file or directory, repeatable (default {contentgap.CORPUS_REL})",
    ),
    top: int = typer.Option(
        contentgap.DEFAULT_TOP, "--top", help="how many ranked terms to emit"
    ),
    phrases: bool = typer.Option(
        True, "--phrases/--no-phrases", help="include adjacent two-word phrases"
    ),
    min_length: int = typer.Option(
        contentgap.MIN_TERM_LENGTH,
        "--min-length",
        help="shortest token that can be a term",
    ),
    max_kb: int = typer.Option(
        contentgap.DEFAULT_MAX_KB, "--max-kb", help="skip corpus files larger than this"
    ),
):
    """Rank what the local comparison corpus emphasises. Reads files only."""
    model = _model(
        list(corpus or []),
        phrases=phrases,
        min_length=min_length,
        max_kb=max_kb,
        command="contentgap terms",
    )
    emit(
        ok(
            {
                "tier": _capability()["tier"],
                "scope_note": FALLBACK_SCOPE,
                "corpus": {
                    "n_docs": model["n_docs"],
                    "tokens": model["tokens"],
                    "unique_terms": len(model["terms"]),
                    "phrases": model["phrases"],
                    "min_length": model["min_length"],
                    "documents": model["documents"],
                    "skipped": model["skipped"],
                },
                "terms": contentgap.corpus_terms(model, limit=top),
            },
            command="contentgap terms",
            example="scout --json contentgap audit draft.md --corpus corpus/",
            discover="scout contentgap audit <draft>",
        ),
        command="contentgap terms",
    )


@app.command(
    "audit",
    epilog=examples_epilog(
        [
            "scout --json contentgap audit draft.md --corpus corpus/",
            "scout --json contentgap audit draft.md --corpus corpus/ --top 60 --target-score 80",
            "cat draft.md | scout --json contentgap audit - --corpus corpus/ --fail-on warning",
        ]
    ),
)
def audit(
    draft: str = typer.Argument(
        ..., help=f"draft file, or {STDIN_DRAFT} to read stdin"
    ),
    corpus: list[str] = typer.Option(
        None,
        "--corpus",
        help=f"corpus file or directory, repeatable (default {contentgap.CORPUS_REL})",
    ),
    top: int = typer.Option(
        contentgap.DEFAULT_TOP, "--top", help="how many top corpus terms to require"
    ),
    phrases: bool = typer.Option(
        True, "--phrases/--no-phrases", help="include adjacent two-word phrases"
    ),
    min_length: int = typer.Option(
        contentgap.MIN_TERM_LENGTH,
        "--min-length",
        help="shortest token that can be a term",
    ),
    max_kb: int = typer.Option(
        contentgap.DEFAULT_MAX_KB, "--max-kb", help="skip corpus files larger than this"
    ),
    thin_ratio: float = typer.Option(
        contentgap.DEFAULT_THIN_RATIO,
        "--thin-ratio",
        help="fraction of the expected count that still counts as covered",
    ),
    over_ratio: float = typer.Option(
        contentgap.DEFAULT_OVER_RATIO,
        "--over-ratio",
        help="multiple of expected that reads as over-optimization",
    ),
    target_score: float = typer.Option(
        contentgap.DEFAULT_TARGET_SCORE,
        "--target-score",
        help="coverage score below this is a finding",
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|suggestion|info) — the pre-publish gate",
    ),
):
    """Score a draft against the corpus and report its coverage gaps."""
    report, diags = _audit(
        draft,
        corpus=list(corpus or []),
        top=top,
        phrases=phrases,
        min_length=min_length,
        max_kb=max_kb,
        thin_ratio=thin_ratio,
        over_ratio=over_ratio,
        target_score=target_score,
        fail_on=fail_on,
        command="contentgap audit",
    )
    emit(
        ok(
            {
                "tier": _capability()["tier"],
                "scope_note": FALLBACK_SCOPE,
                "report": report,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="contentgap audit",
            example="scout contentgap brief draft.md --corpus corpus/",
            discover="scout contentgap terms --corpus corpus/",
        ),
        command="contentgap audit",
    )
    _gate(diags, fail_on)


@app.command(
    "brief",
    epilog=examples_epilog(
        [
            "scout contentgap brief draft.md --corpus corpus/",
            "scout --json contentgap brief draft.md --corpus corpus/ --out .scout/brief.md",
        ]
    ),
)
def brief(
    draft: str = typer.Argument(
        ..., help=f"draft file, or {STDIN_DRAFT} to read stdin"
    ),
    corpus: list[str] = typer.Option(
        None,
        "--corpus",
        help=f"corpus file or directory, repeatable (default {contentgap.CORPUS_REL})",
    ),
    out: str | None = typer.Option(
        None, "--out", help=f"markdown output path (default {contentgap.BRIEF_REL})"
    ),
    title: str = typer.Option("Content brief", "--title", help="brief heading"),
    top: int = typer.Option(
        contentgap.DEFAULT_TOP, "--top", help="how many top corpus terms to require"
    ),
    phrases: bool = typer.Option(
        True, "--phrases/--no-phrases", help="include adjacent two-word phrases"
    ),
    min_length: int = typer.Option(
        contentgap.MIN_TERM_LENGTH,
        "--min-length",
        help="shortest token that can be a term",
    ),
    max_kb: int = typer.Option(
        contentgap.DEFAULT_MAX_KB, "--max-kb", help="skip corpus files larger than this"
    ),
    thin_ratio: float = typer.Option(
        contentgap.DEFAULT_THIN_RATIO,
        "--thin-ratio",
        help="fraction of the expected count that still counts as covered",
    ),
    over_ratio: float = typer.Option(
        contentgap.DEFAULT_OVER_RATIO,
        "--over-ratio",
        help="multiple of expected that reads as over-optimization",
    ),
    target_score: float = typer.Option(
        contentgap.DEFAULT_TARGET_SCORE,
        "--target-score",
        help="coverage score below this is a finding",
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 AFTER writing if findings at/above this severity",
    ),
):
    """Write the content brief — Clearscope's deliverable, as a committable file."""
    report, diags = _audit(
        draft,
        corpus=list(corpus or []),
        top=top,
        phrases=phrases,
        min_length=min_length,
        max_kb=max_kb,
        thin_ratio=thin_ratio,
        over_ratio=over_ratio,
        target_score=target_score,
        fail_on=fail_on,
        command="contentgap brief",
    )
    out_path = Path(out or contentgap.BRIEF_REL)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(out_path))
    page = contentgap.render_brief(report, title=title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # write_bytes, not write_text: write_text would translate every \n to \r\n on
    # Windows and a committed brief would diff against itself on the next run
    out_path.write_bytes(page.encode("utf-8"))
    emit(
        ok(
            {
                "out": out_path.as_posix(),
                "bytes": out_path.stat().st_size,
                "coverage_score": report["coverage_score"],
                "counts": report["counts"],
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="contentgap brief",
            example="scout --json contentgap audit draft.md --corpus corpus/",
            discover="scout contentgap terms --corpus corpus/",
        ),
        command="contentgap brief",
    )
    _gate(diags, fail_on)


def register(root):
    root.add_typer(app, name="contentgap")
