# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout quality` — SonarQube / CodeClimate replacement, fully local (openswap #30).

Per-function code metrics from the stdlib `ast` — cyclomatic complexity with the
branch breakdown that produced it, function size and nesting depth, imports bound
but never referenced, and TODO-marker density normalized per 100 SLOC — plus the
part the SaaS actually charges for: a HISTORY, so run 12 can be compared with run
11. The history is a sqlite file on this box. There is no scanner token, no
project key and no intake host, so "no source ever left the machine" is
architectural rather than a retention setting.

The ONE real file-read in this plugin is `Path.read_text` in _read_source; the
only write is the sqlite trend store, opened through bigbang.core.quality and
skipped entirely under --no-record. Every judgment is deterministic and lives in
bigbang/core/quality.py, so the whole analyzer is unit testable with strings.

Zero egress is the product, not a setting: SonarCloud and CodeClimate are hosted
services that need your source, and sonar-scanner is a client that requires a
SonarQube SERVER to talk to. The manifest disables the network axis with an EMPTY
domain list, and `detect` and `scan` both call _egress_guard first, which re-reads
the manifest and REFUSES to run if that section was ever widened. There is no
enforce_or_raise call site because there is no outbound call to gate — the guard
is the inverse assertion, and it is what makes the claim falsifiable.

There is no native tier and there will not be one. radon, mccabe, flake8 and
pylint are the open tools in this category and every one is a third-party
dependency the openswap premise forbids; sonar-scanner needs a server. They are
PROBED and surfaced for awareness, never executed, and `detect` says so in
`native_used` on every tier rather than letting tier=native imply a binary
produced these numbers.

NOT a duplicate, and the reasoning is in the core module docstring in full:
scripts/goat_audit.py scores a PLUGIN on a six-dimension rubric from its cli.py
alone and uses a function's line span as an explicit proxy — no branch counting,
no per-function table, one mean per plugin as its only history. `reviewgraph`
stores ast RELATIONSHIPS (imports/calls/fan-in) for review blast radius and
measures nothing about a function's body. `todos` lists markers, which is why
this plugin emits ONE density finding per file and points at `scout todos` for
the listing instead of re-reporting every marker.
"""

from __future__ import annotations

import time
from pathlib import Path

import typer

from bigbang.core import openswap, quality
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import load_manifest

# Relative on purpose: resolved against the caller's cwd by pathlib, so nothing
# here assumes a home directory or a drive letter.
DEFAULT_DB = Path(".scout") / "quality.db"

FALLBACK_SCOPE = (
    "pure-stdlib `ast` + `tokenize` is the complete product for this adapter: "
    "cyclomatic complexity per function with a published, overlayable weight "
    "table and a per-node-type breakdown on every score; function lines, "
    "statement count, nesting depth and parameter count; module-level complexity "
    "so an import-time script cannot score clean by defining no functions; "
    "imports bound but never referenced (with __all__, quoted annotations and "
    "`# noqa: F401` honoured); marker density from real COMMENT tokens; and a "
    "sqlite run history with per-unit regression comparison. Tier 'fallback' is "
    "the expected steady state — SonarQube is a server and every open analyzer "
    "in this category is a third-party dependency. What it does NOT do: any "
    "language but Python, cross-file duplication (see scout dupes), coverage, or "
    "runtime dispatch a static read cannot see"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; radon/flake8/pylint are "
    "third-party analyzers to run by hand if you want a second opinion (this "
    "plugin never executes them and adds no dependency)"
)
NEVER_EXECUTED = (
    "sonar-scanner/radon/flake8/pylint are probed for awareness and NEVER "
    "executed: sonar-scanner requires a SonarQube server, which is the egress "
    "this adapter exists to delete, and the others are third-party dependencies "
    "whose verdict would vary with PATH contents and version"
)

app = make_plugin_app(
    "quality",
    "Per-function code metrics with history (SonarQube/CodeClimate-class), fully "
    "local: cyclomatic complexity, function size, unused imports, marker density",
    examples=[
        "scout --json quality scan bigbang/core",
        "scout --json quality scan . --fail-on error --no-record",
        "scout --json quality trend --metric complexity_total",
        "scout --json quality compare --fail-on-regression",
        "scout --json quality rules",
        "scout --json quality detect",
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
    one. A privacy guarantee that is only in a docstring is a promise; one that
    fails the command is a contract.
    """
    net = (_manifest().get("capabilities") or {}).get("network") or {}
    if net.get("enabled") or (net.get("domains") or []):
        fail_agent(
            "manifest declares network access for a plugin whose whole premise is "
            "zero egress — refusing to run until capabilities.network is disabled "
            "with an empty domain list",
            command=command,
            example="scout --json quality detect",
        )
    return {"network_enabled": False, "domains": [], "reads": "local source files only"}


def _capability() -> dict:
    # SonarQube/CodeClimate are hosted; sonar-scanner is only a client for the
    # server this adapter deletes, and radon/flake8/pylint are third-party deps.
    # So `native` stays a truthful probe and `native_used` is False on EVERY
    # tier — tier=native must never imply a binary produced these numbers.
    native = openswap.probe_binary("sonar-scanner", probe_args=("--version",))
    extras = {
        "radon": openswap.probe_binary("radon", probe_args=("--version",)),
        "flake8": openswap.probe_binary("flake8", probe_args=("--version",)),
        "pylint": openswap.probe_binary("pylint", probe_args=("--version",)),
    }
    report = openswap.capability_report(
        "quality",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    report["native_used"] = False
    report["native_never_executed"] = NEVER_EXECUTED
    report["scope_limits"] = quality.SCOPE_LIMITS
    return report


def _config_or_fail(config_file: str | None, command: str) -> dict:
    try:
        return quality.load_config(config_file)
    except Exception as e:
        fail_agent(
            f"bad config overlay: {type(e).__name__}: {e}",
            command=command,
            example="scout --json quality scan . --config org-quality.json",
            discover="scout --json quality rules",
        )
        raise  # unreachable: fail_agent exits


def _collect_files(paths: list[str], command: str) -> list[Path]:
    """Named files as given; directories walked for quality.PY_EXTS."""
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            for ext in quality.PY_EXTS:
                files.extend(p.rglob(f"*{ext}"))
        else:
            fail_agent(
                f"path not found: {raw}",
                command=command,
                example="scout --json quality scan bigbang/core",
            )
    return sorted(set(files))


def _read_source(path: Path) -> tuple[str, str | None]:
    """The ONE real file-read in this plugin: one local file as utf-8.

    A failure to open returns the exception text so the caller records WHY the
    file was not measured instead of reporting it clean. `errors="replace"` keeps
    one bad byte from aborting the measurement of otherwise valid code — a
    replacement character is a token like any other to `ast`.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as e:
        return "", f"{type(e).__name__}: {e}"


def _fail_on_or_fail(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json quality scan . --fail-on error",
        )


def _store_or_fail(db: str | None, command: str):
    try:
        return quality.open_store(db or DEFAULT_DB)
    except Exception as e:
        fail_agent(
            f"could not open the trend store: {type(e).__name__}: {e}",
            command=command,
            example="scout --json quality trend --db .scout/quality.db",
        )
        raise  # unreachable: fail_agent exits


@app.command("hello", epilog=examples_epilog(["scout --json quality hello"]))
def hello():
    """Smoke check — is the quality surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "quality"},
            command="quality hello",
            example="scout --json quality scan bigbang/core",
            discover="scout quality detect",
        ),
        command="quality hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json quality detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    data = _capability()
    data["egress"] = _egress_guard("quality detect")
    emit(
        ok(
            data,
            command="quality detect",
            example="scout --json quality scan bigbang/core",
            discover="scout quality rules",
        ),
        command="quality detect",
    )


@app.command(
    "rules",
    epilog=examples_epilog(
        [
            "scout --json quality rules",
            "scout --json quality rules --config org-quality.json",
        ]
    ),
)
def rules_cmd(
    config_file: str | None = typer.Option(
        None,
        "--config",
        help="JSON overlay of weights/thresholds/rules (policy-as-config)",
    ),
):
    """Publish the effective policy: decision-point weights, thresholds, rules."""
    cfg = _config_or_fail(config_file, "quality rules")
    emit(
        ok(
            {
                **cfg,
                "overlay": config_file,
                "weights_fingerprint": quality.weights_fingerprint(cfg["weights"]),
                "severities": list(openswap.SEVERITIES),
                "trend_metrics": list(quality.TREND_METRICS),
                "markers": list(quality.MARKERS),
                "scope_limits": quality.SCOPE_LIMITS,
                "weights_note": (
                    "radon, mccabe and lizard disagree about assert, boolean operators "
                    "and comprehensions, so the table is data and every score ships its "
                    "own per-node-type breakdown"
                ),
            },
            command="quality rules",
            example="scout --json quality scan . --config org-quality.json",
            discover="scout quality scan <path>",
        ),
        command="quality rules",
    )


@app.command(
    "scan",
    epilog=examples_epilog(
        [
            "scout --json quality scan bigbang/core",
            "scout --json quality scan . --fail-on error",
            "scout --json quality scan . --no-record --top 20",
            "scout --json quality scan . --label pre-refactor --config org-quality.json",
        ]
    ),
)
def scan(
    paths: list[str] = typer.Argument(
        ...,
        help="files or directories (dirs walked for "
        + ", ".join(quality.PY_EXTS)
        + ")",
    ),
    config_file: str | None = typer.Option(
        None, "--config", help="JSON overlay of weights/thresholds/rules"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|suggestion|info) "
        "— the CI quality gate hook",
    ),
    record: bool = typer.Option(
        True, "--record/--no-record", help="append this run to the sqlite trend store"
    ),
    db: str | None = typer.Option(
        None, "--db", help=f"trend store path (default {DEFAULT_DB})"
    ),
    label: str | None = typer.Option(
        None, "--label", help="name this run in the history"
    ),
    top: int = typer.Option(10, "--top", help="how many hottest functions to include"),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
    units: bool = typer.Option(
        False,
        "--units/--no-units",
        help="include the full per-function measurement table",
    ),
):
    """Measure Python files. Reads source and the local store; opens no socket."""
    _fail_on_or_fail(fail_on, "quality scan")
    _egress_guard("quality scan")
    cfg = _config_or_fail(config_file, "quality scan")
    files = _collect_files(paths, "quality scan")
    if not files:
        fail_agent(
            f"no Python files found (looking for {', '.join(quality.PY_EXTS)})",
            command="quality scan",
            example="scout --json quality scan bigbang/core",
        )
    started = time.perf_counter()
    reports = [_measure(f, cfg) for f in files]
    result = quality.scan_report(reports, top=top)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
    diags = openswap.sort_diagnostics([d for r in reports for d in r["diagnostics"]])
    run_id = _record(reports, result, cfg, db=db, label=label) if record else None
    emit(
        ok(
            {
                "tier": _capability()["tier"],
                "native_used": False,
                "scope_limits": quality.SCOPE_LIMITS,
                "scope_note": FALLBACK_SCOPE,
                "elapsed_ms": elapsed_ms,
                "run_id": run_id,
                "recorded": run_id is not None,
                "db": None if run_id is None else str(db or DEFAULT_DB),
                "weights_fingerprint": quality.weights_fingerprint(cfg["weights"]),
                "aggregate": {k: v for k, v in result.items() if k != "summary"},
                "files": [_thin(r, units) for r in reports],
                "diagnostics": diags[:max_findings],
                "truncated": len(diags) > max_findings,
                "summary": result["summary"],
            },
            command="quality scan",
            example="scout --json quality compare --fail-on-regression",
            discover="scout quality trend",
        ),
        command="quality scan",
    )
    if fail_on is not None:
        gate = openswap.severity_rank(fail_on)
        if any(openswap.severity_rank(d["severity"]) <= gate for d in diags):
            raise typer.Exit(code=1)


def _measure(path: Path, cfg: dict) -> dict:
    """Read one file and measure it, or record WHY it could not be measured."""
    text, error = _read_source(path)
    if error:
        return quality.unreadable_report(str(path), error, config=cfg)
    return quality.file_report(text, path=str(path), config=cfg)


def _thin(report: dict, units: bool) -> dict:
    """One file's row for the payload; the per-unit table is opt-in (it is big)."""
    keep = ("path", "error", "counts", "unmeasured")
    row = {k: report[k] for k in keep}
    row["unused_imports"] = [
        {"name": b["name"], "line": b["line"], "statement": b["statement"]}
        for b in report["unused"]
    ]
    if units:
        row["units"] = report["units"]
        row["markers"] = report["markers"]
    return row


def _record(
    reports: list[dict], result: dict, cfg: dict, *, db: str | None, label: str | None
) -> int:
    """Append this run to the trend store. Failures are loud, never silent."""
    conn = _store_or_fail(db, "quality scan")
    try:
        return quality.record_run(
            conn,
            scan=result,
            reports=reports,
            root=str(Path.cwd().name),
            ts=time.time(),
            weights=cfg["weights"],
            label=label,
        )
    except Exception as e:
        fail_agent(
            f"measured the tree but could not record the run: {type(e).__name__}: {e}",
            command="quality scan",
            example="scout --json quality scan . --no-record",
        )
        raise  # unreachable: fail_agent exits
    finally:
        conn.close()


@app.command(
    "trend",
    epilog=examples_epilog(
        [
            "scout --json quality trend",
            "scout --json quality trend --metric complexity_max --limit 50",
            "scout --json quality trend --metric todo_density",
        ]
    ),
)
def trend_cmd(
    metric: str = typer.Option(
        "complexity_total",
        "--metric",
        help="one of: " + ", ".join(quality.TREND_METRICS),
    ),
    limit: int = typer.Option(20, "--limit", help="how many recent runs to include"),
    db: str | None = typer.Option(
        None, "--db", help=f"trend store path (default {DEFAULT_DB})"
    ),
):
    """One metric across recorded runs, oldest first. Reads the local store only."""
    conn = _store_or_fail(db, "quality trend")
    try:
        try:
            series = quality.trend(conn, metric, limit=limit)
        except ValueError as e:
            fail_agent(
                str(e),
                command="quality trend",
                example="scout --json quality trend --metric complexity_max",
                discover="scout --json quality rules",
            )
        runs = quality.list_runs(conn, limit=limit)
    finally:
        conn.close()
    emit(
        ok(
            {**series, "runs": runs, "db": str(db or DEFAULT_DB)},
            command="quality trend",
            example="scout --json quality compare",
            discover="scout quality rules",
        ),
        command="quality trend",
    )


@app.command(
    "compare",
    epilog=examples_epilog(
        [
            "scout --json quality compare",
            "scout --json quality compare --base 1 --head 4",
            "scout --json quality compare --fail-on-regression",
        ]
    ),
)
def compare_cmd(
    base: int | None = typer.Option(
        None, "--base", help="baseline run id (default: previous run)"
    ),
    head: int | None = typer.Option(
        None, "--head", help="run id to judge (default: latest run)"
    ),
    db: str | None = typer.Option(
        None, "--db", help=f"trend store path (default {DEFAULT_DB})"
    ),
    fail_on_regression: bool = typer.Option(
        False,
        "--fail-on-regression/--no-fail-on-regression",
        help="exit 1 if any function got more complex — or if the two runs cannot be compared",
    ),
):
    """Per-function deltas between two runs. A retune is never called a regression."""
    conn = _store_or_fail(db, "quality compare")
    try:
        recent = quality.list_runs(conn, limit=2)
        if base is None or head is None:
            if len(recent) < 2:
                fail_agent(
                    f"need two recorded runs to compare, found {len(recent)}",
                    command="quality compare",
                    example="scout --json quality scan bigbang/core",
                    discover="scout --json quality trend",
                )
            head = head if head is not None else recent[0]["id"]
            base = base if base is not None else recent[1]["id"]
        try:
            result = quality.compare_runs(conn, base, head)
        except ValueError as e:
            fail_agent(
                str(e),
                command="quality compare",
                example="scout --json quality compare --base 1 --head 2",
                discover="scout --json quality trend",
            )
    finally:
        conn.close()
    emit(
        ok(
            {**result, "db": str(db or DEFAULT_DB)},
            command="quality compare",
            example="scout --json quality compare --fail-on-regression",
            discover="scout quality trend",
        ),
        command="quality compare",
    )
    if fail_on_regression and (result["regressions"] or not result["comparable"]):
        # "cannot determine" must not pass a gate: with two weight tables in play
        # there is no honest per-unit delta to clear it with.
        raise typer.Exit(code=1)


def register(root):
    root.add_typer(app, name="quality")
