# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout prose` — Grammarly Premium replacement, fully local (openswap #1),
now also Hemingway Editor Plus (openswap #21) via `score` and `report`.

Best-available-tier execution per the openswap contract:
- native: harper-cli on PATH (Automattic's Rust grammar engine) — shelled out
  per file, findings merged under the family diagnostic schema.
- fallback: the pure-stdlib heuristic core in bigbang/core/prose.py — carries
  launch (harper-cli verified ABSENT on this box 2026-07-23) and always runs,
  so native findings only ever ADD to the report.
Never a network call on any tier: the privacy guarantee is architectural
(manifest denies the network axis), not a policy promise. No enforce_or_raise
call site exists for the network axis because there are no outbound calls.

#21 (readability: Flesch-Kincaid, sentence histogram, adverb/passive budgets,
per-paragraph difficulty) lives HERE rather than in a plugin of its own, and
that was the deliberate call: the openswap table itself files #21 as "prose gate
companion to #1", and every input it needs — markdown/HTML extraction, paragraph
boundaries, the passive-voice matcher, the rules overlay, the --fail-on gate —
already exists in this plugin. A separate `readability` plugin would have had to
import bigbang.core.prose anyway and would have shipped a second copy of the
same argparse surface, capability probe and manifest for zero new capability.
The arithmetic is in bigbang/core/readability.py (pure logic, no I/O) and also
registers as a `readability` rule inside `lint`, so one --fail-on gates grammar
and grade together.

`report` is the one command in this plugin that writes a file (the Hemingway
artifact: per-paragraph difficulty as one self-contained HTML page), so the
manifest now declares filesystem.write for `.scout` and the write goes through
enforce_or_raise at the call site. Nothing else here touches the disk for
writing, and the network axis stays disabled.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from bigbang.core import openswap, prose, readability
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

HARPER_BIN = "harper-cli"
INSTALL_HINT = (
    "install harper-cli from github.com/automattic/harper releases "
    "(single static binary), then re-run: scout prose detect"
)
FALLBACK_SCOPE = (
    "pure-stdlib heuristic linter: doubled words, a/an agreement, passive "
    "voice, sentence length, wordiness/cliches, quote+space hygiene, wordlist "
    "spellcheck, plus the complete readability scorer (#21: flesch, "
    "flesch-kincaid, gunning fog, coleman-liau, sentence histogram, "
    "adverb/passive budgets, per-paragraph difficulty); no full grammar parse "
    "until harper-cli is on PATH"
)

app = make_plugin_app(
    "prose",
    "Lint and score prose (Grammarly + Hemingway class), fully local: "
    "harper-cli when present, stdlib heuristics always",
    examples=[
        "scout --json prose lint README.md",
        "scout --json prose lint docs --fail-on warning",
        "scout --json prose score README.md --target-grade 10",
        "scout prose report docs --out .scout/readability.html",
        "scout --json prose detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only when used
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # cheap read-only health probe (harper-cli core-version, per the harper docs)
    native = openswap.probe_binary(HARPER_BIN, probe_args=("core-version",))
    extras = {
        "harper-ls": openswap.probe_binary("harper-ls", probe_args=("--version",)),
        # GNU diction's `style` computes readability indices too. Surfaced for
        # awareness ONLY — never executed beyond --version — because the stdlib
        # scorer is a superset here (it reports per-paragraph bands and rides the
        # shared diagnostic schema) and `style` has no Windows build.
        "style": openswap.probe_binary("style", probe_args=("--version",)),
    }
    return openswap.capability_report(
        "prose", native=native, extras=extras,
        fallback_scope=FALLBACK_SCOPE, install_hint=INSTALL_HINT,
    )


def _collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        pth = Path(p)
        if pth.is_file():
            files.append(pth)
        elif pth.is_dir():
            for ext in prose.PROSE_EXTS:
                files.extend(pth.rglob(f"*{ext}"))
        else:
            fail_agent(
                f"path not found: {p}",
                command="prose lint",
                example="scout --json prose lint README.md",
            )
    return sorted(set(files))


def _run_harper(harper_path: str, file: Path, timeout: float = 20.0):
    """Native-tier lint of one file. Returns (diagnostics, note|None).

    harper's machine-output flags are not pinned (binary absent on the dev
    box), so the contract is: tolerant parse, and any failure degrades to
    core-only findings with a visible note — never a crash, never a no-op
    masquerading as a clean report.
    """
    try:
        r = subprocess.run(
            [harper_path, "lint", "--format", "json", str(file)],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        diags = prose.parse_harper_output(r.stdout or "", path=str(file))
        if diags:
            return diags, None
        if r.returncode != 0:
            return [], f"harper exit {r.returncode}: {(r.stderr or '').strip()[:200]}"
        return [], None
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


@app.command("hello", epilog=examples_epilog(["scout --json prose hello"]))
def hello():
    """Smoke check — is the prose surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "prose"},
            command="prose hello",
            example="scout --json prose lint README.md",
            discover="scout prose detect",
        ),
        command="prose hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json prose detect"]))
def detect():
    """Report the local capability tier (native harper-cli vs stdlib fallback)."""
    emit(
        ok(
            _capability(),
            command="prose detect",
            example="scout --json prose lint README.md",
            discover="scout prose rules",
        ),
        command="prose detect",
    )


@app.command("rules", epilog=examples_epilog([
    "scout --json prose rules",
    "scout --json prose rules --rules org-style.json",
]))
def rules_cmd(
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (org style, policy-as-config)"
    ),
):
    """Show the effective rule set (defaults + optional JSON overlay)."""
    try:
        merged = prose.load_rules(rules_file)
    except Exception as e:
        fail_agent(
            f"bad rules file: {e}",
            command="prose rules",
            example='scout --json prose rules --rules org-style.json',
        )
    summary = {}
    for rid, cfg in merged.items():
        entry = {
            "enabled": bool(cfg.get("enabled")),
            "severity": cfg.get("severity", "warning"),
        }
        for key in ("phrases", "map", "wordlist", "use_a", "use_an"):
            if key in cfg:
                entry[f"{key}_count"] = len(cfg[key])
        summary[rid] = entry
    emit(
        ok(
            {"rules": summary, "overlay": rules_file},
            command="prose rules",
            example="scout --json prose lint README.md --rules org-style.json",
            discover="scout prose lint <file>",
        ),
        command="prose rules",
    )


@app.command("lint", epilog=examples_epilog([
    "scout --json prose lint README.md",
    "scout --json prose lint docs --fail-on warning",
    "scout --json prose lint README.md --rules org-style.json --no-native",
]))
def lint(
    paths: list[str] = typer.Argument(
        ..., help="files or directories (dirs walked for " + ", ".join(prose.PROSE_EXTS) + ")"
    ),
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (org style, policy-as-config)"
    ),
    native: bool = typer.Option(
        True, "--native/--no-native",
        help="use harper-cli when on PATH (merged under the same schema)",
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|suggestion|info) — the pre-publish gate hook",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
):
    """Lint prose in markdown/HTML/text files; emit normalized diagnostics."""
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command="prose lint",
            example="scout --json prose lint README.md --fail-on warning",
        )
    try:
        rules = prose.load_rules(rules_file)
    except Exception as e:
        fail_agent(
            f"bad rules file: {e}",
            command="prose lint",
            example="scout --json prose lint README.md --rules org-style.json",
        )
    files = _collect_files(paths)
    if not files:
        fail_agent(
            "no lintable files found "
            f"(looking for {', '.join(prose.PROSE_EXTS)})",
            command="prose lint",
            example="scout --json prose lint README.md",
        )
    cap = _capability()
    use_native = native and cap["tier"] == openswap.TIER_NATIVE
    diags: list[dict] = []
    notes: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        diags.extend(
            prose.lint_text(text, path=str(f), fmt=prose.detect_format(str(f)), rules=rules)
        )
        if use_native:
            harper_diags, note = _run_harper(cap["native"]["path"], f)
            diags.extend(harper_diags)
            if note:
                notes.append(f"{f}: {note}")
    diags = openswap.sort_diagnostics(diags)
    summary = openswap.summarize(diags)
    data = {
        "tier": cap["tier"],
        "native_used": use_native,
        "files": [str(f) for f in files],
        "diagnostics": diags[:max_findings],
        "truncated": len(diags) > max_findings,
        "summary": summary,
    }
    if cap["tier"] != openswap.TIER_NATIVE:
        data["scope_note"] = FALLBACK_SCOPE
    if notes:
        data["native_notes"] = notes
    emit(
        ok(
            data,
            command="prose lint",
            example="scout --json prose lint docs --fail-on warning",
            discover="scout prose detect",
        ),
        command="prose lint",
    )
    if fail_on is not None:
        gate_rank = openswap.severity_rank(fail_on)
        blocking = sum(
            1 for d in diags if openswap.severity_rank(d["severity"]) <= gate_rank
        )
        if blocking:
            raise typer.Exit(code=1)


def _readability_rules(
    rules_file: str | None, target_grade: float | None, command: str
) -> dict:
    """Rules for a scoring run: the overlay, plus --target-grade as an override.

    --target-grade edits ONLY readability.max_grade (the document target). The
    per-sentence hard/very-hard bands stay where the rules file put them, so
    tightening the gate never silently reclassifies every sentence.
    """
    try:
        rules = prose.load_rules(rules_file)
    except Exception as e:
        fail_agent(
            f"bad rules file: {e}",
            command=command,
            example="scout --json prose score README.md --rules org-style.json",
        )
    if target_grade is not None:
        if target_grade <= 0:
            fail_agent(
                f"--target-grade must be > 0, got {target_grade}",
                command=command,
                example="scout --json prose score README.md --target-grade 10",
            )
        rules["readability"]["max_grade"] = float(target_grade)
    return rules


def _check_fail_on(fail_on: str | None, command: str, example: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=example,
        )


def _score_files(files: list[Path], rules: dict) -> tuple[list[dict], list[dict]]:
    """Score every file; return (reports, sorted diagnostics)."""
    reports: list[dict] = []
    diags: list[dict] = []
    for f in files:
        report = readability.score_text(
            f.read_text(encoding="utf-8", errors="replace"),
            path=str(f),
            fmt=prose.detect_format(str(f)),
            rules=rules,
        )
        reports.append(report)
        diags.extend(readability.to_diagnostics(report, rules=rules))
    return reports, openswap.sort_diagnostics(diags)


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    gate_rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= gate_rank for d in diags):
        raise typer.Exit(code=1)


@app.command("score", epilog=examples_epilog([
    "scout --json prose score README.md",
    "scout --json prose score docs --target-grade 10 --fail-on suggestion",
    "scout --json prose score README.md --max-paragraphs 5",
]))
def score(
    paths: list[str] = typer.Argument(
        ..., help="files or directories (dirs walked for " + ", ".join(prose.PROSE_EXTS) + ")"
    ),
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (readability thresholds included)"
    ),
    target_grade: float | None = typer.Option(
        None, "--target-grade",
        help="override readability.max_grade — grade above this is a finding",
    ),
    max_paragraphs: int = typer.Option(
        30, "--max-paragraphs", help="cap per-paragraph rows per file (counts stay complete)"
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|suggestion|info) — the pre-publish gate",
    ),
):
    """Score readability (Hemingway-class): grade level, histogram, difficulty.

    Reports four formulas, not one: Flesch-Kincaid and Gunning fog use the
    syllable heuristic, Coleman-Liau uses letters only, and `consensus_grade` is
    their median — a wide spread is the signal that the syllable counter, not
    the prose, is being measured.
    """
    _check_fail_on(fail_on, "prose score", "scout --json prose score README.md --fail-on suggestion")
    rules = _readability_rules(rules_file, target_grade, "prose score")
    files = _collect_files(paths)
    if not files:
        fail_agent(
            f"no scorable files found (looking for {', '.join(prose.PROSE_EXTS)})",
            command="prose score",
            example="scout --json prose score README.md",
        )
    reports, diags = _score_files(files, rules)
    for report in reports:
        report["paragraphs_truncated"] = len(report["paragraphs"]) > max_paragraphs
        report["paragraphs"] = report["paragraphs"][:max_paragraphs]
    hardest = max(
        (r for r in reports if r["scores"]["consensus_grade"] is not None),
        key=lambda r: r["scores"]["consensus_grade"],
        default=None,
    )
    emit(
        ok(
            {
                "scorer": "stdlib-readability",
                "tier": _capability()["tier"],
                "files": [str(f) for f in files],
                "target_grade": rules["readability"]["max_grade"],
                "hardest": None if hardest is None else {
                    "path": hardest["path"],
                    "consensus_grade": hardest["scores"]["consensus_grade"],
                    "ease_label": hardest["ease_label"],
                },
                "reports": reports,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="prose score",
            example="scout prose report README.md --out .scout/readability.html",
            discover="scout prose rules",
        ),
        command="prose score",
    )
    _gate(diags, fail_on)


@app.command("report", epilog=examples_epilog([
    "scout prose report README.md",
    "scout prose report docs --out .scout/readability.html --title 'digest draft'",
    "scout --json prose report README.md --target-grade 10 --fail-on suggestion",
]))
def report(
    paths: list[str] = typer.Argument(..., help="files or directories to score"),
    out: str | None = typer.Option(
        None, "--out", help=f"HTML output path (default {readability.PAGE_REL})"
    ),
    title: str = typer.Option("Readability", "--title", help="page heading"),
    rules_file: str | None = typer.Option(None, "--rules", help="JSON rules overlay"),
    target_grade: float | None = typer.Option(
        None, "--target-grade", help="override readability.max_grade"
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 after writing if findings at/above this severity"
    ),
):
    """Write the per-paragraph difficulty page — Hemingway's highlighting, as a file.

    One self-contained HTML file: inline CSS, zero JavaScript, zero external
    assets, so it opens from file:// and can be published with any of the sites.
    """
    _check_fail_on(fail_on, "prose report", "scout prose report README.md --fail-on suggestion")
    rules = _readability_rules(rules_file, target_grade, "prose report")
    files = _collect_files(paths)
    if not files:
        fail_agent(
            f"no scorable files found (looking for {', '.join(prose.PROSE_EXTS)})",
            command="prose report",
            example="scout prose report README.md",
        )
    reports, diags = _score_files(files, rules)
    out_path = Path(out or readability.PAGE_REL)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write", str(out_path))
    page = readability.render_html(reports, title=title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    emit(
        ok(
            {
                "out": str(out_path),
                # on-disk size, not len(page): Windows newline translation makes
                # those differ, and a field called "bytes" should be checkable
                # against the file the user actually got
                "bytes": out_path.stat().st_size,
                "chars": len(page),
                "files": [str(f) for f in files],
                "target_grade": rules["readability"]["max_grade"],
                "grades": {
                    r["path"]: r["scores"]["consensus_grade"] for r in reports
                },
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="prose report",
            example="scout --json prose score docs --fail-on suggestion",
            discover="scout --json prose score README.md",
        ),
        command="prose report",
    )
    _gate(diags, fail_on)


def register(root):
    root.add_typer(app, name="prose")
