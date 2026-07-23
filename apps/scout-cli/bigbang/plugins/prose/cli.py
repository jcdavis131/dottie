# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout prose` — Grammarly Premium replacement, fully local (openswap #1).

Best-available-tier execution per the openswap contract:
- native: harper-cli on PATH (Automattic's Rust grammar engine) — shelled out
  per file, findings merged under the family diagnostic schema.
- fallback: the pure-stdlib heuristic core in bigbang/core/prose.py — carries
  launch (harper-cli verified ABSENT on this box 2026-07-23) and always runs,
  so native findings only ever ADD to the report.
Never a network call on any tier: the privacy guarantee is architectural
(manifest denies the network axis), not a policy promise. No enforce_or_raise
call sites exist because there are no outbound calls to enforce.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from bigbang.core import openswap, prose
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit

HARPER_BIN = "harper-cli"
INSTALL_HINT = (
    "install harper-cli from github.com/automattic/harper releases "
    "(single static binary), then re-run: scout prose detect"
)
FALLBACK_SCOPE = (
    "pure-stdlib heuristic linter: doubled words, a/an agreement, passive "
    "voice, sentence length, wordiness/cliches, quote+space hygiene, wordlist "
    "spellcheck; no full grammar parse until harper-cli is on PATH"
)

app = make_plugin_app(
    "prose",
    "Lint prose (Grammarly-class), fully local: harper-cli when present, stdlib heuristics always",
    examples=[
        "scout --json prose lint README.md",
        "scout --json prose lint docs --fail-on warning",
        "scout --json prose lint README.md --rules org-style.json",
        "scout --json prose detect",
        "scout --json prose rules",
    ],
)


def _capability() -> dict:
    # cheap read-only health probe (harper-cli core-version, per the harper docs)
    native = openswap.probe_binary(HARPER_BIN, probe_args=("core-version",))
    extras = {"harper-ls": openswap.probe_binary("harper-ls", probe_args=("--version",))}
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


def register(root):
    root.add_typer(app, name="prose")
