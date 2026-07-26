# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout coverage` — Codecov replacement, fully local (openswap #31).

Codecov is an uploader plus a web app. This deletes both halves: the coverage
report you already produced (`coverage xml`, `pytest --cov`, or the raw
`.coverage` sqlite) is parsed on THIS box, rolled up per module, compared
against the previous run in a local sqlite history, and rendered into ONE
self-contained HTML file. No token, no `CODECOV_TOKEN`, no upload, no service,
and no account — the manifest disables the network axis with an EMPTY domain
list and `report`/`parse`/`detect` all call `_egress_guard` first, which
re-reads the manifest and REFUSES to run if that section was ever widened. A
coverage report names every file in your repository and how much of it is
untested; not shipping that anywhere is the product.

The real I/O lives here and nothing else does: reading the report files
(`Path.read_bytes` for the XML so its encoding declaration is honoured, sqlite
`mode=ro` for the .coverage), the history store under .scout, and
`Path.write_bytes` for the HTML (bytes, never write_text, so no newline
translation can change the file between platforms). Every judgment —
parsing, merging, the per-module rollup, deltas, the pct-XOR-reason invariant,
the page itself — is deterministic and lives in bigbang/core/coverage.py.

The one thing this refuses to do is invent a zero. A module with no data
renders as UNKNOWN with the reason, never as 0%: an unmeasured module and a
completely untested module look identical on a dashboard, and only one of them
is a crisis. That is why a `.coverage` file ALONE yields covered-line counts
with an UNKNOWN percentage (it stores executed lines, not a statement
inventory), why a missing baseline yields no delta instead of 0.0, and why a
`--context` typo is a hard error listing the real contexts instead of a report
where everything is suddenly uncovered.

Deliberately NOT `runtrack` (#10), whose compare_runs() already deltas metrics
against a baseline run: its store column is `value REAL NOT NULL`, so an
unmeasured module could only be logged as a fabricated 0.0. This store keeps
(statements, covered, pct-or-reason) per module and enforces the XOR with a
sqlite CHECK constraint. See the core module docstring for the full reasoning.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import typer

from bigbang.core import coverage, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib parsing and rendering is the complete product for this "
    "adapter: Cobertura XML (xml.etree, with a DOCTYPE refused before parsing) "
    "and coverage.py's .coverage sqlite (schema 7, numbits bitmaps decoded by "
    "hand, opened mode=ro), merged by set arithmetic on line numbers so a file "
    "listed twice cannot double-count and an executed line outside the "
    "statement inventory can never push coverage past 100%; per-module rollups "
    "summed (never a mean of percentages), deltas against the previous run in a "
    "local sqlite history, family diagnostics with --min-pct/--max-drop gates, "
    "and one self-contained zero-JavaScript HTML page. What it does NOT do is "
    "derive a denominator that is not in the report: a .coverage file alone "
    "gives covered-line counts and an UNKNOWN percentage"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; `coverage html` (from "
    "coverage.py, which produced the data in the first place) is the richer "
    "single-run line-by-line viewer, and this plugin never executes it"
)
NEVER_EXECUTED = (
    "the codecov uploader is probed for awareness and NEVER executed: its whole "
    "job is shipping your coverage report to the paid platform, which is the "
    "egress this adapter exists to delete. coverage.py's own CLI is not executed "
    "either — it re-reads your source to compute a denominator, so the answer "
    "would move with the venv on PATH and with which source tree happens to be "
    "checked out (the links #4 doctrine: a gate whose answer moves with PATH is "
    "flaky by construction). Reports are read as artifacts, never regenerated"
)

app = make_plugin_app(
    "coverage",
    "Coverage report renderer (Codecov-class), fully local: parse coverage.xml "
    "and/or .coverage, per-module deltas vs the last run, static HTML, zero upload",
    examples=[
        "scout --json coverage parse --xml coverage.xml",
        "scout --json coverage report --xml coverage.xml --record",
        "scout --json coverage report --xml coverage.xml --html cov.html --min-pct 80",
        "scout --json coverage report --xml coverage.xml --max-drop 0 --fail-on error",
        "scout --json coverage runs",
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
    one. A privacy guarantee that lives only in a docstring is a promise; one
    that fails the command is a contract.
    """
    net = (_manifest().get("capabilities") or {}).get("network") or {}
    if net.get("enabled") or (net.get("domains") or []):
        fail_agent(
            "manifest declares network access for a plugin whose whole premise is "
            "replacing an uploader — refusing to run until capabilities.network is "
            "disabled with an empty domain list",
            command=command,
            example="scout --json coverage detect",
        )
    return {"network_enabled": False, "domains": [], "uploads": "none, on any path"}


def _capability() -> dict:
    # coverage.py's CLI is the honest `native` probe: it is local, it produced
    # the data being read, and `coverage html` is a real alternative for the
    # single-run view. It is still never EXECUTED (see NEVER_EXECUTED), so
    # `native_used` is False on every tier — tier=native must never be able to
    # imply a binary produced these numbers. The codecov uploader is surfaced
    # for awareness only; running it is the egress this adapter deletes.
    native = openswap.probe_binary("coverage", probe_args=("--version",))
    extras = {
        "codecov": openswap.probe_binary("codecov", probe_args=("--version",)),
        "gcovr": openswap.probe_binary("gcovr", probe_args=("--version",)),
        "diff-cover": openswap.probe_binary("diff-cover", probe_args=("--version",)),
    }
    report = openswap.capability_report(
        "coverage",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    report["native_used"] = False
    report["native_never_executed"] = NEVER_EXECUTED
    report["scope_limits"] = coverage.SCOPE_LIMITS
    return report


def _rules_or_fail(rules_file: str | None, command: str) -> dict:
    try:
        return coverage.load_rules(rules_file)
    except Exception as e:
        fail_agent(
            f"bad rules overlay: {type(e).__name__}: {e}",
            command=command,
            example="scout --json coverage rules --rules org-coverage.json",
            discover="scout --json coverage rules",
        )
        raise  # unreachable: fail_agent exits


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_COVERAGE_DB") or coverage.DB_REL)


def _read_sources(
    xml_paths: list[str], data_path: str | None, context: str | None, command: str
) -> tuple[list[dict], list[dict]]:
    """The real read: every named report -> parsed facts, or a labelled failure.

    A file that could not be read or parsed lands in `unparsable` with the
    reason and rides the family diagnostic schema, so it shows up in the report
    and in --fail-on. It is never dropped: a report that silently measured
    nothing renders as 0% covered, which is the lie this plugin exists to avoid.
    """
    parsed: list[dict] = []
    bad: list[dict] = []
    for raw in xml_paths:
        p = Path(raw)
        try:
            # bytes, not text: an XML encoding declaration is authoritative and
            # decoding to str first would throw it away
            parsed.append(coverage.parse_cobertura(p.read_bytes(), label=p.as_posix()))
        except (OSError, coverage.CoverageError) as e:
            bad.append({"path": p.as_posix(), "error": f"{type(e).__name__}: {e}"})
    if data_path is not None:
        p = Path(data_path)
        try:
            parsed.append(coverage.read_coverage_sqlite(p, context=context))
        except Exception as e:
            # broad on purpose: sqlite3.DatabaseError escapes from a truncated or
            # encrypted file, and a corrupt artifact must be REPORTED as unread,
            # never allowed to look like a repository with no covered lines
            bad.append({"path": p.as_posix(), "error": f"{type(e).__name__}: {e}"})
    if not parsed:
        reasons = "; ".join(f"{b['path']}: {b['error']}" for b in bad) or "none given"
        fail_agent(
            f"no coverage report could be parsed, so nothing was measured ({reasons})",
            command=command,
            example="scout --json coverage report --xml coverage.xml",
            discover="scout --json coverage detect",
        )
    return parsed, bad


def _combine(parsed: list[dict], depth: int, strip: list[str], command: str) -> dict:
    try:
        return coverage.combine(parsed, depth=depth, strip_prefixes=tuple(strip))
    except ValueError as e:
        fail_agent(
            f"{type(e).__name__}: {e}",
            command=command,
            example="scout --json coverage parse --xml coverage.xml --depth 2",
        )
        raise  # unreachable: fail_agent exits


def _open_history(db: str | None, *, record: bool) -> tuple[object | None, Path]:
    """Open the run history, or return None when there is nothing to open.

    Recording is the only write, and it is gated by enforce_or_raise at this call
    site because the plugin loader does not check fs_write for us. Without
    --record an ABSENT store is not an error: the first run of a repository has
    no history, and it reports every module as new instead of failing.
    """
    path = _db_path(db)
    if record:
        enforce_or_raise(_manifest(), "fs_write_arg", str(path))
        return coverage.open_store(path), path
    if path.exists():
        return coverage.open_store(path), path  # baseline read; nothing is inserted
    return None, path


def _baseline_for(conn: object | None, run_id: int | None):
    """The run this report is compared against: an explicit id, or the latest.

    An explicitly requested id that does not exist is a hard failure listing the
    ids that do — silently falling back to the latest run would compare against
    something the caller did not ask for and label the deltas as if it had.
    """
    if conn is None:
        return None
    base = (
        coverage.latest_run(conn) if run_id is None else coverage.get_run(conn, run_id)
    )
    if run_id is not None and base is None:
        ids = [r["id"] for r in coverage.list_runs(conn, limit=10)]
        fail_agent(
            f"no recorded run with id {run_id} (recent ids: {ids or 'none'})",
            command="coverage report",
            example="scout --json coverage runs",
            discover="scout --json coverage runs",
        )
    return base


def _fail_on_or_fail(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json coverage report --xml coverage.xml --fail-on error",
        )


def _require_sources(xml: list[str], data: str | None, command: str) -> None:
    """No report named means no measurement — never an empty one worth 0%."""
    if not xml and data is None:
        fail_agent(
            f"nothing to {command.split()[-1]}: pass --xml coverage.xml and/or "
            "--data .coverage",
            command=command,
            example="scout --json coverage parse --xml coverage.xml",
            discover="scout --json coverage detect",
        )


def _gate_or_exit(diags: list[dict], fail_on: str | None) -> None:
    """Exit 1 when anything at or above `fail_on` was found (the CI hook)."""
    if fail_on is None:
        return
    gate = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= gate for d in diags):
        raise typer.Exit(code=1)


def _write_html(target: str, report: dict, title: str | None, command: str) -> dict:
    """Write the page as BYTES so the file is identical on every platform."""
    path = Path(target)
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    payload = coverage.render_html(report, title=title).encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    except OSError as e:
        fail_agent(
            f"could not write the report to {path.as_posix()}: {type(e).__name__}: {e}",
            command=command,
            example="scout --json coverage report --xml coverage.xml --html cov.html",
        )
    return {"path": path.as_posix(), "bytes": len(payload)}


@app.command("hello", epilog=examples_epilog(["scout --json coverage hello"]))
def hello():
    """Smoke check — is the coverage surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "coverage"},
            command="coverage hello",
            example="scout --json coverage parse --xml coverage.xml",
            discover="scout coverage detect",
        ),
        command="coverage hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json coverage detect"]))
def detect():
    """Report the capability tier. `native_used` is False on EVERY tier — see module doc."""
    data = _capability()
    data["egress"] = _egress_guard("coverage detect")
    emit(
        ok(
            data,
            command="coverage detect",
            example="scout --json coverage report --xml coverage.xml",
            discover="scout coverage rules",
        ),
        command="coverage detect",
    )


@app.command(
    "rules",
    epilog=examples_epilog(
        ["scout --json coverage rules", "scout --json coverage rules --rules org.json"]
    ),
)
def rules_cmd(
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (org policy, policy-as-config)"
    ),
):
    """Publish the effective rule table: id, severity, why it exists, enabled."""
    merged = _rules_or_fail(rules_file, "coverage rules")
    emit(
        ok(
            {
                "rules": merged,
                "overlay": rules_file,
                "severities": list(openswap.SEVERITIES),
                "scope_limits": coverage.SCOPE_LIMITS,
                "statuses": list(coverage.STATUSES),
            },
            command="coverage rules",
            example="scout --json coverage report --xml coverage.xml --rules org.json",
            discover="scout coverage report --xml coverage.xml",
        ),
        command="coverage rules",
    )


@app.command(
    "parse",
    epilog=examples_epilog(
        [
            "scout --json coverage parse --xml coverage.xml",
            "scout --json coverage parse --data .coverage",
            "scout --json coverage parse --xml coverage.xml --data .coverage --files",
            "scout --json coverage parse --data .coverage --context test_login",
        ]
    ),
)
def parse_cmd(
    xml: list[str] = typer.Option(
        [], "--xml", help="Cobertura coverage.xml (repeatable; reports are merged)"
    ),
    data: str | None = typer.Option(
        None,
        "--data",
        help="coverage.py .coverage sqlite (executed lines, no denominator)",
    ),
    context: str | None = typer.Option(
        None, "--context", help="only this measurement context from --data"
    ),
    depth: int = typer.Option(
        coverage.DEFAULT_DEPTH,
        "--depth",
        help="directory components a module name keeps",
    ),
    strip: list[str] = typer.Option(
        [],
        "--strip-prefix",
        help="path root to remove so .coverage and XML paths match (repeatable; the "
        "XML's own <sources> roots are stripped automatically)",
    ),
    show_files: bool = typer.Option(
        False, "--files/--no-files", help="include every per-file reading"
    ),
):
    """Parse report(s) and print the measurement. Touches no store, writes nothing."""
    _egress_guard("coverage parse")
    _require_sources(list(xml), data, "coverage parse")
    parsed, bad = _read_sources(list(xml), data, context, "coverage parse")
    combined = _combine(parsed, depth, list(strip), "coverage parse")
    payload = {
        "tier": _capability()["tier"],
        "native_used": False,
        "scope_limits": coverage.SCOPE_LIMITS,
        **{k: v for k, v in combined.items() if k != "files" or show_files},
        "declared_vs_counted": [
            coverage.declared_vs_counted(p)
            for p in parsed
            if p["format"] == coverage.FORMAT_COBERTURA
        ],
        "unparsable": bad,
    }
    emit(
        ok(
            payload,
            command="coverage parse",
            example="scout --json coverage report --xml coverage.xml --record",
            discover="scout coverage rules",
        ),
        command="coverage parse",
    )


@app.command(
    "report",
    epilog=examples_epilog(
        [
            "scout --json coverage report --xml coverage.xml --record",
            "scout --json coverage report --xml coverage.xml --html cov.html",
            "scout --json coverage report --xml coverage.xml --min-pct 80 --fail-on error",
            "scout --json coverage report --xml coverage.xml --max-drop 0.5 --baseline 3",
        ]
    ),
)
def report_cmd(
    xml: list[str] = typer.Option(
        [], "--xml", help="Cobertura coverage.xml (repeatable; reports are merged)"
    ),
    data: str | None = typer.Option(
        None,
        "--data",
        help="coverage.py .coverage sqlite (executed lines, no denominator)",
    ),
    context: str | None = typer.Option(
        None, "--context", help="only this measurement context from --data"
    ),
    depth: int = typer.Option(
        coverage.DEFAULT_DEPTH,
        "--depth",
        help="directory components a module name keeps",
    ),
    strip: list[str] = typer.Option(
        [],
        "--strip-prefix",
        help="path root to remove so .coverage and XML paths match",
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=f"history store (default {coverage.DB_REL} or $SCOUT_COVERAGE_DB)",
    ),
    baseline: int | None = typer.Option(
        None,
        "--baseline",
        help="compare against this recorded run id (default: the latest)",
    ),
    record: bool = typer.Option(
        False, "--record/--no-record", help="store this run as the next baseline"
    ),
    label: str | None = typer.Option(
        None, "--label", help="label for the recorded run"
    ),
    html_out: str | None = typer.Option(
        None, "--html", help="write the static self-contained HTML report here"
    ),
    title: str | None = typer.Option(None, "--title", help="heading for the HTML page"),
    min_pct: float | None = typer.Option(
        None, "--min-pct", help="coverage floor for the total AND each module"
    ),
    max_drop: float | None = typer.Option(
        None,
        "--max-drop",
        help="points a module may lose vs the baseline before it is a finding "
        "(0 = any drop)",
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|suggestion|info)"
        " — the CI gate hook",
    ),
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (org policy, policy-as-config)"
    ),
    show_files: bool = typer.Option(
        False, "--files/--no-files", help="include every per-file reading"
    ),
    max_findings: int = typer.Option(
        200,
        "--max-findings",
        help="cap emitted diagnostics (the summary stays complete)",
    ),
):
    """Parse, delta against the last run, render, gate. Opens no socket on any path."""
    _egress_guard("coverage report")
    _fail_on_or_fail(fail_on, "coverage report")
    rules = _rules_or_fail(rules_file, "coverage report")
    _require_sources(list(xml), data, "coverage report")
    parsed, bad = _read_sources(list(xml), data, context, "coverage report")
    combined = _combine(parsed, depth, list(strip), "coverage report")
    conn, path = _open_history(db, record=record)
    base = _baseline_for(conn, baseline)
    report = coverage.build_report(
        combined,
        baseline=base,
        generated_ts=time.time(),
        title=title,
        db=str(path) if conn is not None else None,
        unparsable=bad,
    )
    diags = coverage.to_diagnostics(
        report, min_pct=min_pct, max_drop=max_drop, rules=rules
    )
    html_info = (
        _write_html(html_out, report, title, "coverage report") if html_out else None
    )
    # recorded LAST, after the comparison above read the previous run: recording
    # first would make every run its own baseline and every delta 0.0
    run_id = (
        coverage.record_run(conn, report, ts=report["generated_ts"], label=label)
        if (conn is not None and record)
        else None
    )
    emit(
        ok(
            {
                "tier": _capability()["tier"],
                "native_used": False,
                **{k: v for k, v in report.items() if k != "files" or show_files},
                "recorded_run_id": run_id,
                "html": html_info,
                "thresholds": {"min_pct": min_pct, "max_drop": max_drop},
                "diagnostics": diags[:max_findings],
                "truncated": len(diags) > max_findings,
                "summary": openswap.summarize(diags),
            },
            command="coverage report",
            example="scout --json coverage runs",
            discover="scout --json coverage rules",
        ),
        command="coverage report",
    )
    _gate_or_exit(diags, fail_on)


@app.command(
    "runs",
    epilog=examples_epilog(
        [
            "scout --json coverage runs",
            "scout --json coverage runs --limit 5",
            "scout --json coverage runs --run 2",
        ]
    ),
)
def runs_cmd(
    db: str | None = typer.Option(None, "--db", help="history store path"),
    limit: int = typer.Option(20, "--limit", help="max runs listed (newest first)"),
    run: int | None = typer.Option(
        None, "--run", help="show this run's module rows instead of the list"
    ),
):
    """List recorded runs, or one run's per-module rows. Read-only."""
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no coverage history at {path} — record a run first",
            command="coverage runs",
            example="scout --json coverage report --xml coverage.xml --record",
        )
    conn = coverage.open_store(path)
    if run is not None:
        one = coverage.get_run(conn, run)
        if one is None:
            ids = [r["id"] for r in coverage.list_runs(conn, limit=limit)]
            fail_agent(
                f"no recorded run with id {run} (recent ids: {ids or 'none'})",
                command="coverage runs",
                example="scout --json coverage runs",
            )
        emit(
            ok(
                {"db": str(path), "run": one},
                command="coverage runs",
                example="scout --json coverage report --xml coverage.xml --baseline 1",
                discover="scout --json coverage runs",
            ),
            command="coverage runs",
        )
        return
    runs = coverage.list_runs(conn, limit=limit)
    emit(
        ok(
            {"db": str(path), "count": len(runs), "runs": runs},
            command="coverage runs",
            example="scout --json coverage runs --run 1",
            discover="scout --json coverage report --xml coverage.xml",
        ),
        command="coverage runs",
    )


def register(root):
    root.add_typer(app, name="coverage")
