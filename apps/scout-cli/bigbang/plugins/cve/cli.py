# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout cve` — Snyk / Dependabot replacement, fully offline (openswap #29).

Dependency vulnerability auditing with the SaaS call deleted: your dependency
graph never leaves the box, and the vulnerability database is a CACHED FILE you
placed on disk out of band. `audit` parses requirements.txt / pyproject.toml /
package.json / package-lock.json / uv.lock / poetry.lock, matches every PINNED
version against the OSV records in that snapshot, and gates on the findings.
The ONE real I/O call in this plugin is `Path.read_text` in _read_text; every
judgment is deterministic and lives in bigbang/core/cve.py, so the whole audit is
unit testable with strings and needs no fixture on disk.

Zero egress is the product, not a setting. Snyk and Dependabot are
architecturally "upload the manifest and we will tell you", so the manifest
disables the network axis with an EMPTY domain list and every command calls
_egress_guard first, which re-reads the manifest and REFUSES to run if that
section was ever widened. There is no enforce_or_raise call site for the network
axis because there is no outbound call to gate — the guard is the inverse
assertion, and it is what makes the claim falsifiable.

NO SNAPSHOT IS AN ERROR, NEVER A CLEAN AUDIT. That is the one failure mode this
whole plugin is shaped around: a scanner whose database is missing reports
nothing wrong, and "nothing wrong" is indistinguishable from "no findings".
_snapshot_or_fail exits non-zero with the resolved path and how to point at
another file, and `audit` never reaches the report path without an index. The
softer version of the same hazard — a snapshot that IS present but old, or that
declares no generation date at all — rides the diagnostics as
cve:snapshot-stale / cve:snapshot-undated, so `--fail-on error` catches a stale
cache and a clean tree cannot hide behind a year-old file.

There is no native tier and there will not be one. osv-scanner, pip-audit and
safety are the open scanners in this category and all three FETCH the advisory
database (osv.dev, PyPI's advisory feed, the safety-db endpoint) as part of a
normal run; executing one would reintroduce the exact egress this adapter
deletes, and the verdict would then vary with PATH contents and network reach.
They are PROBED and surfaced for awareness, never executed, and `native_used` is
False on every tier so tier=native can never imply a binary produced a finding.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import typer

from bigbang.core import cve, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import load_manifest

# Repo-relative by design: no home-directory lookup, no absolute literal, no
# machine layout assumption. Override per call with --snapshot or the env var.
SNAPSHOT_REL = Path(".scout") / "osv-snapshot.json"
SNAPSHOT_ENV = "SCOUT_CVE_SNAPSHOT"
# Directories a dependency audit must never descend into: installed trees hold
# thousands of vendored manifests that are not what this project declares.
SKIP_DIRS = frozenset(
    {
        "node_modules", ".venv", "venv", "env", ".git", "__pycache__",
        "site-packages", "dist", "build", ".tox", ".mypy_cache", ".ruff_cache",
        ".pytest_cache", "vendor", ".next",
    }
)
DEFAULT_MAX_AGE_DAYS = 30.0

FALLBACK_SCOPE = (
    "pure-stdlib offline auditing is the complete product for this adapter: "
    "requirements.txt / pyproject.toml / package.json / package-lock.json / "
    "uv.lock / poetry.lock readers, PEP 440 and SemVer 2.0.0 ordering, the OSV "
    "affected.ranges.events interval walk (introduced / fixed / last_affected, "
    "withdrawn advisories excluded) and CVSS v3.0/v3.1 base-score arithmetic, "
    "all against a snapshot file; tier 'fallback' is the expected steady state "
    "(Snyk and Dependabot are hosted services, and every open scanner in this "
    "category fetches the advisory database at scan time, so no local native "
    "binary is a superset of this offline core). What it does NOT do is resolve "
    "a dependency tree: transitive dependencies are audited only when a "
    "lockfile names them, and an unpinned range gets no verdict at all"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; what you DO need is the "
    "snapshot file, produced out of band (an OSV bulk export per ecosystem, or "
    "an advisory-database clone flattened into one JSON list) and copied onto "
    "this box. This plugin never downloads it"
)
NEVER_EXECUTED = (
    "osv-scanner / pip-audit / safety are probed for awareness and NEVER "
    "executed: all three fetch the advisory database during a normal scan, "
    "which is the egress this adapter exists to delete, and their verdict would "
    "then vary with PATH contents and network reach"
)
SNAPSHOT_SHAPE = (
    'either {"generated": "<RFC3339>", "advisories": [<OSV record>, ...]} or a '
    "bare JSON list of OSV records; 'generated' is optional but a snapshot "
    "without it is reported as cve:snapshot-undated, because an unknown age is "
    "not a fresh one"
)

app = make_plugin_app(
    "cve",
    "Audit dependencies against a cached OSV snapshot (Snyk/Dependabot-class), "
    "fully offline: requirements/pyproject/package.json/lockfiles, PEP 440 + "
    "SemVer ranges, CVSS v3 scoring, zero egress",
    examples=[
        "scout --json cve audit .",
        "scout --json cve audit requirements.txt --fail-on error",
        "scout --json cve snapshot",
        "scout --json cve match --package requests --version 2.30.0",
        "scout --json cve rules",
        "scout --json cve detect",
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
    call, so the thing worth checking is that nobody widened the axis to allow
    one. A vulnerability database that could be fetched at audit time is a
    different product with a different privacy story.
    """
    net = (_manifest().get("capabilities") or {}).get("network") or {}
    if net.get("enabled") or (net.get("domains") or []):
        fail_agent(
            "manifest declares network access for a plugin whose whole premise is "
            "an offline snapshot — refusing to run until capabilities.network is "
            "disabled with an empty domain list",
            command=command,
            example="scout --json cve detect",
        )
    return {
        "network_enabled": False,
        "domains": [],
        "reads": "local files only (manifests + the snapshot)",
        "snapshot_fetched": False,
    }


def _capability() -> dict:
    # Snyk/Dependabot are SaaS with no offline local CLI, and every open scanner
    # in this category fetches the advisory database at scan time, so `native`
    # stays a truthful probe and `native_used` is False on EVERY tier —
    # tier=native must never imply a binary produced these findings.
    native = openswap.probe_binary("osv-scanner", probe_args=("--version",))
    extras = {
        "pip-audit": openswap.probe_binary("pip-audit", probe_args=("--version",)),
        "safety": openswap.probe_binary("safety", probe_args=("--version",)),
    }
    report = openswap.capability_report(
        "cve",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    report["native_used"] = False
    report["native_never_executed"] = NEVER_EXECUTED
    report["scope_limits"] = cve.SCOPE_LIMITS
    return report


def _read_text(path: Path) -> tuple[str, str | None]:
    """The ONE real I/O call in this plugin: read one local file as utf-8.

    errors="replace" keeps a mojibake byte from aborting an otherwise valid
    manifest; a failure to open returns the exception text so the caller can
    record WHY the file was not audited instead of reporting it clean.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as e:
        return "", f"{type(e).__name__}: {e}"


def _snapshot_path(override: str | None) -> Path:
    return Path(override or os.environ.get(SNAPSHOT_ENV) or SNAPSHOT_REL)


def _snapshot_or_fail(override: str | None, command: str) -> tuple[dict, Path]:
    """Load the cached OSV snapshot, or EXIT NON-ZERO. Never a false clean.

    Every failure mode here — missing file, unreadable file, bad JSON, wrong
    shape — is an error with the resolved path in it. The one thing this must
    never do is fall through to an empty index, because an empty index makes
    every dependency look clean.
    """
    path = _snapshot_path(override)
    hint = (
        f"place the snapshot at {SNAPSHOT_REL} (or set {SNAPSHOT_ENV}, or pass "
        f"--snapshot PATH). Expected shape: {SNAPSHOT_SHAPE}"
    )
    if not path.exists():
        fail_agent(
            f"no OSV snapshot at {path} — refusing to report an audit without a "
            f"vulnerability database, because 'no findings' and 'no data' are not "
            f"the same answer. {hint}",
            command=command,
            example="scout --json cve audit . --snapshot osv-snapshot.json",
            discover="scout --json cve snapshot --snapshot osv-snapshot.json",
        )
    text, error = _read_text(path)
    if error is not None:
        fail_agent(
            f"OSV snapshot at {path} could not be read, so nothing was audited: {error}",
            command=command,
            example="scout --json cve snapshot --snapshot osv-snapshot.json",
        )
    try:
        snapshot = cve.load_snapshot(json.loads(text))
    except ValueError as e:  # JSONDecodeError and SnapshotError are both ValueError
        fail_agent(
            f"OSV snapshot at {path} is not usable, so nothing was audited: "
            f"{type(e).__name__}: {e}. {hint}",
            command=command,
            example="scout --json cve snapshot --snapshot osv-snapshot.json",
        )
        raise  # unreachable: fail_agent exits
    return snapshot, path


def _rules_or_fail(rules_file: str | None, command: str) -> dict:
    try:
        return cve.load_rules(rules_file)
    except Exception as e:
        fail_agent(
            f"bad rules overlay: {type(e).__name__}: {e}",
            command=command,
            example="scout --json cve rules --rules org-cve.json",
            discover="scout --json cve rules",
        )
        raise  # unreachable: fail_agent exits


def _fail_on_or_fail(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json cve audit . --fail-on error",
        )


def _walk(root: Path) -> list[Path]:
    """Manifests under a directory, skipping installed/vendored trees."""
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir():
            if child.name not in SKIP_DIRS and not child.is_symlink():
                found.extend(_walk(child))
        elif cve.manifest_kind(child.name) is not None:
            found.append(child)
    return found


def _collect_manifests(paths: list[str], command: str) -> list[Path]:
    """Named files as given (whatever their name); directories walked."""
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(_walk(p))
        else:
            fail_agent(
                f"path not found: {raw}",
                command=command,
                example="scout --json cve audit requirements.txt",
            )
    return sorted(set(files))


def _audit_files(
    files: list[Path],
    snapshot: dict,
    rules: dict,
    diags: list[dict],
    *,
    show_deps: bool,
) -> list[dict]:
    """One report per manifest; `diags` accumulates every finding in file order.

    A file that could not be read becomes an unreadable_report rather than being
    skipped, so an unreadable manifest can never quietly shrink the audit.
    """
    reports: list[dict] = []
    for f in files:
        text, error = _read_text(f)
        report = (
            cve.unreadable_report(str(f), error, rules=rules)
            if error
            else cve.audit_manifest(
                cve.parse_manifest(text, f.name), snapshot, path=str(f), rules=rules
            )
        )
        diags.extend(report["diagnostics"])
        if not show_deps:
            report = {k: v for k, v in report.items() if k != "dependencies"}
        reports.append(report)
    return reports


def _now_ts() -> float:
    """Wall-clock UTC seconds — a snapshot's AGE is a date difference, not an
    interval, so perf_counter (which has no epoch) cannot express it."""
    return datetime.now(UTC).timestamp()


def _age_of(snapshot: dict) -> dict:
    return cve.snapshot_age(snapshot.get("meta") or {}, _now_ts())


@app.command("hello", epilog=examples_epilog(["scout --json cve hello"]))
def hello():
    """Smoke check — is the cve surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "cve"},
            command="cve hello",
            example="scout --json cve audit .",
            discover="scout cve detect",
        ),
        command="cve hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json cve detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    data = _capability()
    data["egress"] = _egress_guard("cve detect")
    data["snapshot_default"] = str(SNAPSHOT_REL)
    data["snapshot_env"] = SNAPSHOT_ENV
    data["snapshot_shape"] = SNAPSHOT_SHAPE
    emit(
        ok(
            data,
            command="cve detect",
            example="scout --json cve audit .",
            discover="scout cve rules",
        ),
        command="cve detect",
    )


@app.command(
    "rules",
    epilog=examples_epilog(
        ["scout --json cve rules", "scout --json cve rules --rules org-cve.json"]
    ),
)
def rules_cmd(
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (org policy, policy-as-config)"
    ),
):
    """Publish the effective rule table: id, severity, enabled, rating mapping."""
    merged = _rules_or_fail(rules_file, "cve rules")
    emit(
        ok(
            {
                "rules": merged,
                "overlay": rules_file,
                "severities": list(openswap.SEVERITIES),
                "rating_severity": cve.RATING_SEVERITY,
                "ecosystems": {e: cve.VERSION_SCHEMES[e] for e in cve.ECOSYSTEMS},
                "manifests": ["requirements*.txt", *cve.MANIFEST_NAMES],
                "scope_limits": cve.SCOPE_LIMITS,
            },
            command="cve rules",
            example="scout --json cve audit . --rules org-cve.json",
            discover="scout cve audit <path>",
        ),
        command="cve rules",
    )


@app.command(
    "snapshot",
    epilog=examples_epilog(
        [
            "scout --json cve snapshot",
            "scout --json cve snapshot --snapshot osv-pypi.json --max-age-days 7",
        ]
    ),
)
def snapshot_cmd(
    snapshot_file: str | None = typer.Option(
        None, "--snapshot", help=f"cached OSV JSON (default {SNAPSHOT_REL}, env {SNAPSHOT_ENV})"
    ),
    max_age_days: float | None = typer.Option(
        DEFAULT_MAX_AGE_DAYS, "--max-age-days", help="report staleness past this age"
    ),
    limit: int = typer.Option(20, "--limit", help="how many indexed packages to list"),
    rules_file: str | None = typer.Option(None, "--rules", help="JSON rules overlay"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 if snapshot findings reach this severity"
    ),
):
    """Inspect the cached snapshot: record counts, age, indexed packages."""
    _fail_on_or_fail(fail_on, "cve snapshot")
    _egress_guard("cve snapshot")
    rules = _rules_or_fail(rules_file, "cve snapshot")
    snapshot, path = _snapshot_or_fail(snapshot_file, "cve snapshot")
    age = _age_of(snapshot)
    diags = cve.snapshot_diagnostics(
        age, snapshot_path=str(path), max_age_days=max_age_days, rules=rules
    )
    packages = sorted(f"{eco}:{name}" for eco, name in (snapshot.get("index") or {}))
    emit(
        ok(
            {
                "path": str(path),
                "meta": snapshot["meta"],
                "counts": snapshot["counts"],
                "age": age,
                "max_age_days": max_age_days,
                "packages_sample": packages[:limit],
                "packages_listed": min(limit, len(packages)),
                "fetched": False,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="cve snapshot",
            example="scout --json cve audit .",
            discover="scout cve rules",
        ),
        command="cve snapshot",
    )
    _gate(fail_on, diags)


@app.command(
    "match",
    epilog=examples_epilog(
        [
            "scout --json cve match --package requests --version 2.30.0",
            "scout --json cve match --package lodash --version 4.17.20 --ecosystem npm",
        ]
    ),
)
def match_cmd(
    package: str = typer.Option(..., "--package", help="package name as published"),
    version: str = typer.Option(..., "--version", help="the exact installed version"),
    ecosystem: str = typer.Option(
        cve.ECO_PYPI, "--ecosystem", help=f"one of {'|'.join(cve.ECOSYSTEMS)}"
    ),
    snapshot_file: str | None = typer.Option(None, "--snapshot", help="cached OSV JSON"),
    rules_file: str | None = typer.Option(None, "--rules", help="JSON rules overlay"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 if findings reach this severity"
    ),
):
    """One package at one version against the snapshot. No files walked."""
    _fail_on_or_fail(fail_on, "cve match")
    _egress_guard("cve match")
    eco = next((e for e in cve.ECOSYSTEMS if e.lower() == ecosystem.lower()), None)
    if eco is None:
        fail_agent(
            f"--ecosystem must be one of {'|'.join(cve.ECOSYSTEMS)}, got {ecosystem!r}",
            command="cve match",
            example="scout --json cve match --package lodash --version 4.17.20 --ecosystem npm",
        )
    rules = _rules_or_fail(rules_file, "cve match")
    snapshot, path = _snapshot_or_fail(snapshot_file, "cve match")
    pinned, reason = cve.exact_pin(version, eco)
    dep = cve.dependency(
        name=package,
        ecosystem=eco,
        specifier=version,
        version=pinned,
        pin_reason=reason,
        field="--package",
    )
    parsed = {"kind": "cli", "ecosystem": eco, "dependencies": [dep], "notes": [], "error": None}
    report = cve.audit_manifest(parsed, snapshot, path=f"{eco}:{package}", rules=rules)
    age = _age_of(snapshot)
    diags = report["diagnostics"] + cve.snapshot_diagnostics(
        age, snapshot_path=str(path), max_age_days=None, rules=rules
    )
    emit(
        ok(
            {
                "snapshot": {"path": str(path), "age": age, "counts": snapshot["counts"]},
                "dependency": report["dependencies"][0],
                "counts": report["counts"],
                "diagnostics": openswap.sort_diagnostics(diags),
                "summary": openswap.summarize(diags),
                "scope_limits": cve.SCOPE_LIMITS,
            },
            command="cve match",
            example="scout --json cve audit .",
            discover="scout cve snapshot",
        ),
        command="cve match",
    )
    _gate(fail_on, diags)


@app.command(
    "audit",
    epilog=examples_epilog(
        [
            "scout --json cve audit .",
            "scout --json cve audit requirements.txt --fail-on error",
            "scout --json cve audit . --snapshot osv.json --max-age-days 7 --rules org-cve.json",
        ]
    ),
)
def audit(
    paths: list[str] = typer.Argument(
        ..., help="files or directories (dirs walked for requirements*.txt, "
        + ", ".join(cve.MANIFEST_NAMES) + ")"
    ),
    snapshot_file: str | None = typer.Option(
        None, "--snapshot", help=f"cached OSV JSON (default {SNAPSHOT_REL}, env {SNAPSHOT_ENV})"
    ),
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (org policy, policy-as-config)"
    ),
    max_age_days: float | None = typer.Option(
        DEFAULT_MAX_AGE_DAYS,
        "--max-age-days",
        help="a snapshot older than this raises cve:snapshot-stale",
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|suggestion|info) "
        "— the CI gate hook",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
    show_deps: bool = typer.Option(
        False, "--deps/--no-deps", help="include every per-dependency row"
    ),
):
    """Audit local manifests against the cached snapshot. Opens no socket."""
    _fail_on_or_fail(fail_on, "cve audit")
    _egress_guard("cve audit")
    rules = _rules_or_fail(rules_file, "cve audit")
    snapshot, snap_path = _snapshot_or_fail(snapshot_file, "cve audit")
    files = _collect_manifests(paths, "cve audit")
    if not files:
        fail_agent(
            "no dependency manifests found (looking for requirements*.txt, "
            + ", ".join(cve.MANIFEST_NAMES)
            + ")",
            command="cve audit",
            example="scout --json cve audit requirements.txt",
        )
    started = time.perf_counter()
    age = _age_of(snapshot)
    diags = cve.snapshot_diagnostics(
        age, snapshot_path=str(snap_path), max_age_days=max_age_days, rules=rules
    )
    reports = _audit_files(files, snapshot, rules, diags, show_deps=show_deps)
    diags = openswap.sort_diagnostics(diags)
    emit(
        ok(
            {
                "tier": _capability()["tier"],
                "native_used": False,
                "scope_limits": cve.SCOPE_LIMITS,
                "snapshot": {
                    "path": str(snap_path),
                    "fetched": False,
                    "age": age,
                    "max_age_days": max_age_days,
                    "counts": snapshot["counts"],
                },
                "aggregate": cve.aggregate(reports),
                "manifests": reports,
                "diagnostics": diags[:max_findings],
                "truncated": len(diags) > max_findings,
                "summary": openswap.summarize(diags),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            },
            command="cve audit",
            example="scout --json cve audit . --fail-on error",
            discover="scout cve rules",
        ),
        command="cve audit",
    )
    _gate(fail_on, diags)


def _gate(fail_on: str | None, diags: list[dict]) -> None:
    """Exit 1 when any finding is at or above the requested severity."""
    if fail_on is None:
        return
    gate = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= gate for d in diags):
        raise typer.Exit(code=1)


def register(root):
    root.add_typer(app, name="cve")
