# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout leaks` — GitGuardian / TruffleHog Enterprise replacement, fully
local (openswap #7).

Secrets scanning with zero install: the stdlib core (bigbang/core/leaks.py)
applies the regex signature pack + Shannon-entropy scoring to file trees
(`scan` — the security-audit sweep), the staged diff (`staged` — the
pre-commit hook), and repo history (`history`). Git runs HERE, read-only and
local only (`--no-pager diff --cached` / `log -p`); the core never spawns
anything, so every scan surface stays unit-testable offline.

There is no native binary tier to execute: gitleaks/trufflehog on PATH are
surfaced by `detect` for manual cross-checks but never run — a gate whose
verdict changes with PATH contents is flaky by construction, and at solo-repo
scale the signature pack + entropy IS the SaaS feature set. So the stdlib
core is 100% of the product and tier 'fallback' is the expected steady state.
Never a network call on any tier: the manifest denies the network axis, so
what gets scanned for secrets never leaves the machine — the SaaS's own
architecture (upload everything to find leaks) is the vulnerability this
replaces. No enforce_or_raise call sites exist because there are no outbound
calls and no writes to enforce.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from bigbang.core import leaks, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit

GITLEAKS_BIN = "gitleaks"
FALLBACK_SCOPE = (
    "pure-stdlib scanner is the complete product for this adapter: "
    "JSON-configurable regex signature pack + Shannon-entropy scoring over "
    "file trees, the staged diff, and read-only git history, with redacted "
    "findings, sha256 fingerprints, per-file-type entropy thresholds, and a "
    "false-positive allowlist; gitleaks/trufflehog on PATH are surfaced for "
    "manual cross-checks but never executed, so the gate's verdict never "
    "depends on PATH contents"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; gitleaks on PATH is "
    "surfaced for manual cross-checks only, never executed by scout"
)

app = make_plugin_app(
    "leaks",
    "Secrets scanning (GitGuardian-class), fully local: signature pack + entropy over trees and read-only git history",
    examples=[
        "scout --json leaks scan . --fail-on error",
        "scout --json leaks staged --fail-on warning",
        "scout --json leaks history --max-commits 100",
        "scout --json leaks scan src --config leaks.json",
        "scout --json leaks signatures",
        "scout --json leaks detect",
    ],
)


def _capability() -> dict:
    # Probes are truthful; execution stays stdlib regardless (module doc).
    native = openswap.probe_binary(GITLEAKS_BIN, probe_args=("version",))
    extras = {
        "trufflehog": openswap.probe_binary("trufflehog", probe_args=("--version",)),
        "detect-secrets": openswap.probe_binary(
            "detect-secrets", probe_args=("--version",)
        ),
    }
    return openswap.capability_report(
        "leaks",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _config_or_fail(config_file: str | None, command: str) -> dict:
    try:
        return leaks.load_config(config_file)
    except Exception as e:
        fail_agent(
            f"bad config file: {e}",
            command=command,
            example=f"scout --json {command} --config leaks.json",
        )


def _sigs_or_fail(cfg: dict, command: str) -> list[dict]:
    try:
        return leaks.build_signatures(cfg)
    except ValueError as e:
        fail_agent(
            str(e),
            command=command,
            example=f"scout --json {command} --config leaks.json",
        )


def _check_fail_on(fail_on: str | None, command: str, example: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, "
            f"got {fail_on!r}",
            command=command,
            example=example,
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    gate_rank = openswap.severity_rank(fail_on)
    blocking = sum(
        1 for d in diags if openswap.severity_rank(d["severity"]) <= gate_rank
    )
    if blocking:
        raise typer.Exit(code=1)


def _git_patch(repo: str, args: list[str], command: str, example: str) -> str:
    """Read-only git invocation; any failure becomes an actionable envelope."""
    if not Path(repo).is_dir():
        fail_agent(
            f"repo path not found: {repo}", command=command, example=example
        )
    try:
        r = subprocess.run(
            ["git", "--no-pager", "-C", repo, *args],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        fail_agent(
            "git not found on PATH (staged/history modes need it; "
            "`leaks scan` does not)",
            command=command,
            example="scout --json leaks scan .",
        )
    except subprocess.TimeoutExpired:
        fail_agent(
            "git timed out after 120s — narrow the sweep",
            command=command,
            example="scout --json leaks history --max-commits 20",
        )
    if r.returncode != 0:
        fail_agent(
            f"git failed: {(r.stderr or '').strip()[:200]}",
            command=command,
            example=example,
        )
    return r.stdout or ""


@app.command("hello", epilog=examples_epilog(["scout --json leaks hello"]))
def hello():
    """Smoke check — is the leaks surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "leaks"},
            command="leaks hello",
            example="scout --json leaks scan . --fail-on error",
            discover="scout leaks detect",
        ),
        command="leaks hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json leaks detect"]))
def detect():
    """Report the capability tier (gitleaks/trufflehog surfaced, never run)."""
    emit(
        ok(
            _capability(),
            command="leaks detect",
            example="scout --json leaks scan . --fail-on error",
            discover="scout leaks signatures",
        ),
        command="leaks detect",
    )


@app.command("signatures", epilog=examples_epilog([
    "scout --json leaks signatures",
    "scout --json leaks signatures --config leaks.json",
]))
def signatures_cmd(
    config_file: str | None = typer.Option(
        None, "--config",
        help="JSON config overlay (allowlist, extra signatures, thresholds)",
    ),
):
    """Show the effective signature pack (defaults + optional JSON overlay)."""
    cfg = _config_or_fail(config_file, "leaks signatures")
    sigs = _sigs_or_fail(cfg, "leaks signatures")
    listing = [
        {
            "id": s["id"],
            "severity": s["severity"],
            "entropy_gate": s["entropy"] if s["entropy"] is not None
            else s["entropy_key"],
            "description": s["description"],
        }
        for s in sigs
    ]
    emit(
        ok(
            {
                "signatures": listing,
                "count": len(listing),
                "disabled": cfg["disable"],
                "entropy": cfg["entropy"],
                "entropy_by_ext": cfg["entropy_by_ext"],
                "allow_counts": {k: len(v) for k, v in cfg["allow"].items()},
                # surfaced so a suppression is reviewable without opening the
                # JSON — an unexplained allowlist is the thing to catch
                "note": cfg["note"],
                "overlay": config_file,
            },
            command="leaks signatures",
            example="scout --json leaks scan . --config leaks.json",
            discover="scout leaks scan <path>",
        ),
        command="leaks signatures",
    )


@app.command("scan", epilog=examples_epilog([
    "scout --json leaks scan . --fail-on error",
    "scout --json leaks scan src tests --config leaks.json",
    "scout --json leaks scan deploy.env --fail-on warning",
]))
def scan(
    paths: list[str] = typer.Argument(
        ..., help="files or directories (dirs pruned of vendor/VCS noise)"
    ),
    config_file: str | None = typer.Option(
        None, "--config",
        help="JSON config overlay (allowlist, extra signatures, thresholds)",
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|suggestion|info) — the security-audit gate hook",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
):
    """Sweep files/trees for secrets; emit redacted normalized diagnostics."""
    example = "scout --json leaks scan . --fail-on error"
    _check_fail_on(fail_on, "leaks scan", example)
    cfg = _config_or_fail(config_file, "leaks scan")
    sigs = _sigs_or_fail(cfg, "leaks scan")
    diags: list[dict] = []
    stats: dict = {"files_scanned": 0, "skipped": {}}
    for p in paths:
        pth = Path(p)
        if pth.is_file():
            found, skip = leaks.scan_file(pth, config=cfg, signatures=sigs)
            if skip:
                stats["skipped"][skip] = stats["skipped"].get(skip, 0) + 1
            else:
                stats["files_scanned"] += 1
                diags.extend(found)
        elif pth.is_dir():
            found, tree_stats = leaks.scan_tree(pth, config=cfg, signatures=sigs)
            diags.extend(found)
            stats["files_scanned"] += tree_stats["files_scanned"]
            for reason, count in tree_stats["skipped"].items():
                stats["skipped"][reason] = stats["skipped"].get(reason, 0) + count
        else:
            fail_agent(
                f"path not found: {p}", command="leaks scan", example=example
            )
    diags = openswap.sort_diagnostics(diags)
    summary = openswap.summarize(diags)
    emit(
        ok(
            {
                "mode": "tree",
                "engine": "stdlib-core",
                "paths": paths,
                "diagnostics": diags[:max_findings],
                "truncated": len(diags) > max_findings,
                "summary": summary,
                "stats": stats,
            },
            command="leaks scan",
            example=example,
            discover="scout leaks staged --fail-on warning",
        ),
        command="leaks scan",
    )
    _gate(diags, fail_on)


@app.command("staged", epilog=examples_epilog([
    "scout --json leaks staged --fail-on warning",
    "scout --json leaks staged --repo ../sites --fail-on error",
]))
def staged(
    repo: str = typer.Option(".", "--repo", help="git repository to inspect"),
    config_file: str | None = typer.Option(
        None, "--config",
        help="JSON config overlay (allowlist, extra signatures, thresholds)",
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on",
        help="exit 1 if findings at/above this severity — the pre-commit hook",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
):
    """Scan the staged diff's added lines (read-only) before they commit."""
    example = "scout --json leaks staged --fail-on warning"
    _check_fail_on(fail_on, "leaks staged", example)
    cfg = _config_or_fail(config_file, "leaks staged")
    sigs = _sigs_or_fail(cfg, "leaks staged")
    patch = _git_patch(
        repo, ["diff", "--cached", "--no-color", "--unified=0"],
        "leaks staged", example,
    )
    diags, stats = leaks.scan_patch(patch, config=cfg, signatures=sigs)
    data = {
        "mode": "staged",
        "engine": "stdlib-core",
        "repo": repo,
        "diagnostics": diags[:max_findings],
        "truncated": len(diags) > max_findings,
        "summary": openswap.summarize(diags),
        "stats": stats,
    }
    if stats["added_lines"] == 0:
        data["note"] = "no staged additions — nothing to scan"
    emit(
        ok(
            data,
            command="leaks staged",
            example=example,
            discover="scout leaks history --max-commits 100",
        ),
        command="leaks staged",
    )
    _gate(diags, fail_on)


@app.command("history", epilog=examples_epilog([
    "scout --json leaks history --max-commits 100",
    "scout --json leaks history --repo ../sites --fail-on error",
]))
def history(
    repo: str = typer.Option(".", "--repo", help="git repository to inspect"),
    max_commits: int = typer.Option(
        50, "--max-commits", help="how far back to sweep (0 = full history)"
    ),
    config_file: str | None = typer.Option(
        None, "--config",
        help="JSON config overlay (allowlist, extra signatures, thresholds)",
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on",
        help="exit 1 if findings at/above this severity — the audit gate hook",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
):
    """Sweep read-only `git log -p --cc` for secrets already in history."""
    example = "scout --json leaks history --max-commits 100"
    _check_fail_on(fail_on, "leaks history", example)
    cfg = _config_or_fail(config_file, "leaks history")
    sigs = _sigs_or_fail(cfg, "leaks history")
    # --cc is load-bearing, not a flourish: plain `git log -p` emits NO diff for
    # a merge commit, so every line a merge introduced was silently unscanned
    # and this mode still reported a clean sweep. This repo had 38 such commits.
    # A conflict resolution is hand-written text, which is exactly where a
    # pasted credential lands. --cc shows only what differs from ALL parents,
    # so nothing already covered by a parent's own commit is rescanned.
    args = ["log", "-p", "--cc", "--no-color", "--unified=0"]
    if max_commits > 0:
        args += ["-n", str(max_commits)]
    patch = _git_patch(repo, args, "leaks history", example)
    diags, stats = leaks.scan_patch(patch, config=cfg, signatures=sigs)
    emit(
        ok(
            {
                "mode": "history",
                "engine": "stdlib-core",
                "repo": repo,
                "max_commits": max_commits,
                "diagnostics": diags[:max_findings],
                "truncated": len(diags) > max_findings,
                "summary": openswap.summarize(diags),
                "stats": stats,
            },
            command="leaks history",
            example=example,
            discover="scout leaks scan . --fail-on error",
        ),
        command="leaks history",
    )
    _gate(diags, fail_on)


def register(root):
    root.add_typer(app, name="leaks")
