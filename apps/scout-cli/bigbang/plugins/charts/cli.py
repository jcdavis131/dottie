# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout charts` — Grafana Cloud / Tableau replacement, fully local (openswap #16).

The dashboard server is deleted. `line`, `bar` and `scatter` each read one source
that is ALREADY on this box — a sqlite ledger (`--db X --table T`, opened
`mode=ro`), a CSV, or a JSON array — and write one self-contained SVG: no chart
library, no JavaScript, no webfont, no external asset, so the file renders from
`file://`, inside a README, or pasted into an email. The manifest disables the
network axis entirely, so "no datapoint left the box" is architectural.

The property that makes this worth having instead of a hosted panel is that the
output is BYTE-IDENTICAL for identical input, which is what lets a chart live in
git next to the numbers and show up in a diff when they move. Every command
returns the SVG's `sha256` so that claim is checkable from the shell rather than
taken on faith. No generation timestamp is written anywhere for the same reason.

All deterministic logic (readers, coercion, the dataset contract, nice-tick
scales, the string-template SVG) lives in bigbang/core/charts.py; this surface
adds argument parsing, path resolution and the fs_write policy gate. Two habits
it keeps that a plotting one-liner does not: a row whose y is not a number is
SKIPPED and counted rather than coerced to zero (a gap in a metric is not a
zero), and every chart carries a footer naming the source table/file and the row
count it read — `inspect` shows the same numbers without writing a file, so
provenance can be checked before publication.

There is no native binary tier to prefer. Tableau ships no CLI at all and
Grafana ships a SERVER, so `detect` reports tier=fallback as the expected steady
state (scope honesty, not degradation). gnuplot and grafana are surfaced as
optional local tools and NEVER executed: spawning a plotter would put the SVG
bytes at the mercy of PATH contents and someone else's version string, which
would destroy the diffability that is this adapter's entire reason to exist.
"""

from __future__ import annotations

from pathlib import Path

import typer

from bigbang.core import charts, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib static SVG rendering is the complete product for this adapter: "
    "line/bar/scatter from sqlite (mode=ro), CSV or JSON, per-series grouping, "
    "nice-tick numeric and UTC time axes, zero-anchored bar baselines, an "
    "explicit empty state, a provenance footer naming the source table/file and "
    "row count, and byte-identical output for identical input (sha256 reported); "
    "tier 'fallback' is the expected steady state (Tableau ships no CLI and "
    "Grafana ships a server — no native binary is a superset of a deterministic "
    "file, and spawning one would make the bytes depend on PATH)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib renderer is complete; gnuplot is worth "
    "having separately for interactive exploration, but it is not used here"
)

app = make_plugin_app(
    "charts",
    "Charts (Grafana Cloud/Tableau-class), fully local: deterministic static "
    "SVG from sqlite ledgers or JSON/CSV, zero egress, diffable output",
    examples=[
        "scout --json charts inspect --db .scout/runtrack.db --table metrics --x step --y value --series key",
        "scout charts line --db .scout/runtrack.db --table metrics --x step --y value --series key --out .scout/loss.svg",
        "scout charts bar --csv counts.csv --x source --y n --sort -value",
        "scout charts scatter --json-file run.json --records data.history --x step --y value",
        "scout --json charts line --csv metrics.csv --x ts --y loss --time-x --fail-on warning",
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
    # No native binary is a superset of this core: Tableau ships no CLI and
    # Grafana ships a server, so `native` stays a truthful probe that reports
    # absent. gnuplot and grafana are surfaced as optional local tools and NEVER
    # executed — a spawned plotter would make the SVG bytes depend on PATH
    # contents and its own version string, destroying the diffability contract
    # (the links #4 doctrine: output that changes with PATH is flaky by design).
    native = openswap.probe_binary("tableau", probe_args=("--version",))
    extras = {
        "gnuplot": openswap.probe_binary("gnuplot", probe_args=("--version",)),
        "grafana": openswap.probe_binary("grafana", probe_args=("--version",)),
    }
    return openswap.capability_report(
        "charts",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _fail_on_or_fail(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json charts line --csv m.csv --x t --y v --fail-on warning",
        )


def _dataset_or_fail(kind: str, command: str, **spec) -> dict:
    """Read the one named source. Every input problem is actionable, not a stack."""
    try:
        return charts.read_dataset(kind=kind, **spec)
    except charts.ChartError as exc:
        fail_agent(
            str(exc),
            command=command,
            example=(
                "scout --json charts inspect --db .scout/runtrack.db "
                "--table metrics --x step --y value"
            ),
            discover="scout charts kinds",
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    if fail_on is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


def _chart(
    kind: str,
    *,
    out: str | None,
    title: str | None,
    width: int,
    height: int,
    fail_on: str | None,
    **spec,
) -> None:
    """Read -> render -> write -> report. Shared by line, bar and scatter."""
    command = f"charts {kind}"
    _fail_on_or_fail(fail_on, command)
    ds = _dataset_or_fail(kind, command, **spec)
    out_path = Path(out or charts.OUT_REL)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(out_path))
    try:
        svg = charts.render_svg(ds, title=title, width=width, height=height)
    except charts.ChartError as exc:
        fail_agent(
            str(exc),
            command=command,
            example=f"scout charts {kind} --csv m.csv --x t --y v --width 820",
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" is load-bearing, not tidiness: the default translates \n to
    # \r\n on Windows, which would make the same chart a DIFFERENT file on
    # Windows than on Linux and break the byte-identical claim (and the reported
    # sha256, which is taken over the string) the moment the repo is shared.
    out_path.write_text(svg, encoding="utf-8", newline="\n")
    diags = charts.to_diagnostics(ds)
    emit(
        ok(
            {
                "out": str(out_path),
                # the file's real size, not len(str): the footer's separators are
                # multi-byte, so character count would overstate nothing and
                # understate the file by ~60 bytes
                "bytes": len(svg.encode("utf-8")),
                "sha256": charts.fingerprint(svg),
                "kind": ds["kind"],
                "source": ds["source"],
                "columns": ds["columns"],
                "rows_read": ds["rows_read"],
                "points": ds["points"],
                "skipped": ds["skipped"],
                "folded": ds["folded"],
                "series": [
                    {"label": s["label"], "color": s["color"], "n": s["n"]}
                    for s in ds["series"]
                ],
                "categories": ds["categories"],
                "bounds": ds["bounds"],
                "provenance": charts.provenance(ds),
                "deterministic": True,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command=command,
            example="scout --json charts inspect --csv m.csv --x t --y v",
            discover="scout charts kinds",
        ),
        command=command,
    )
    _gate(diags, fail_on)


@app.command("hello", epilog=examples_epilog(["scout --json charts hello"]))
def hello():
    """Smoke check — is the charts surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "charts", "kinds": list(charts.KINDS)},
            command="charts hello",
            example="scout --json charts kinds",
            discover="scout charts kinds",
        ),
        command="charts hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json charts detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="charts detect",
            example="scout --json charts kinds",
            discover="scout charts kinds",
        ),
        command="charts detect",
    )


@app.command("kinds", epilog=examples_epilog(["scout --json charts kinds"]))
def kinds_cmd():
    """The chart kinds, the accepted inputs, and the determinism contract."""
    emit(
        ok(
            {
                "kinds": {
                    charts.KIND_LINE: "ordered x/y polyline per series; a "
                    "single-point series renders as a dot so it is never invisible",
                    charts.KIND_BAR: "categorical x, summed duplicates, y axis "
                    "always includes zero (a truncated bar axis misstates ratios)",
                    charts.KIND_SCATTER: "one dot per x/y row, no connecting line",
                },
                "inputs": {
                    "--csv FILE": "header row + rows; utf-8-sig so an Excel BOM "
                    "does not corrupt the first column name",
                    "--json-file FILE": "JSON array of objects, or --records "
                    "data.history to point at a nested array (this CLI's own "
                    "--json envelope is chartable that way)",
                    "--db LEDGER --table T": "sqlite table or view opened mode=ro; "
                    "names are validated against the live schema before use",
                },
                "sorts": list(charts.SORTS),
                "palette": list(charts.PALETTE),
                "determinism": (
                    "no generation timestamp, no reliance on source row order "
                    "(sqlite without ORDER BY is undefined, so points sort by "
                    "(x, y), bar categories by --sort, series by label), no "
                    "locale/TZ (UTC labels assembled from gmtime fields), "
                    "coordinates rounded to 2dp — identical input renders "
                    "byte-identical output, reported as sha256"
                ),
                "honesty": (
                    "non-numeric y is skipped and counted, never read as 0; "
                    "zero plottable rows renders an explicit empty panel with no "
                    "axis numbers instead of an invented range"
                ),
            },
            command="charts kinds",
            example="scout --json charts inspect --csv m.csv --x t --y v",
            discover="scout charts detect",
        ),
        command="charts kinds",
    )


@app.command(
    "inspect",
    epilog=examples_epilog(
        [
            "scout --json charts inspect --csv metrics.csv --x step --y loss",
            "scout --json charts inspect --db .scout/uptime.db --table checks --x ts --y latency_ms --series target",
            "scout --json charts inspect --json-file run.json --records data.history --x step --y value",
        ]
    ),
)
def inspect_cmd(
    csv_path: str | None = typer.Option(None, "--csv", help="CSV input (header row)"),
    json_file: str | None = typer.Option(
        None,
        "--json-file",
        help="JSON array input (named so it cannot clash with the global --json output flag)",
    ),
    records: str | None = typer.Option(
        None, "--records", help="dotted path to the array inside a JSON document"
    ),
    db: str | None = typer.Option(None, "--db", help="sqlite ledger (opened mode=ro)"),
    table: str | None = typer.Option(None, "--table", help="table or view to read"),
    where: str | None = typer.Option(
        None, "--where", help="SQL predicate (read-only connection)"
    ),
    limit: int | None = typer.Option(None, "--limit", help="max rows read"),
    x: str = typer.Option(..., "--x", help="x column (category column for bar)"),
    y: str = typer.Option(..., "--y", help="y column (must hold numbers)"),
    series: str | None = typer.Option(
        None, "--series", help="column to split series by"
    ),
    kind: str = typer.Option(
        charts.KIND_LINE,
        "--kind",
        help=f"shape to validate for ({'|'.join(charts.KINDS)})",
    ),
    time_x: bool = typer.Option(
        False, "--time-x", help="read x as timestamps (epoch or ISO-8601)"
    ),
    sort: str = typer.Option(
        charts.SORT_LABEL,
        "--sort",
        help=f"bar category order ({'|'.join(charts.SORTS)})",
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 at/above this severity — the cron/CI gate hook"
    ),
):
    """Provenance before publication: what the source holds, writing no file."""
    _fail_on_or_fail(fail_on, "charts inspect")
    ds = _dataset_or_fail(
        kind,
        "charts inspect",
        x=x,
        y=y,
        series=series,
        csv_path=csv_path,
        json_path=json_file,
        records=records,
        db=db,
        table=table,
        where=where,
        limit=limit,
        time_x=time_x,
        sort=sort,
    )
    diags = charts.to_diagnostics(ds)
    emit(
        ok(
            {
                "kind": ds["kind"],
                "source": ds["source"],
                "columns": ds["columns"],
                "rows_read": ds["rows_read"],
                "points": ds["points"],
                "skipped": ds["skipped"],
                "folded": ds["folded"],
                "bounds": ds["bounds"],
                "categories": ds["categories"],
                "series": [
                    {
                        "label": s["label"],
                        "n": s["n"],
                        "color": s["color"],
                        "head": s["points"][:3],
                        "tail": s["points"][-3:],
                    }
                    for s in ds["series"]
                ],
                "provenance": charts.provenance(ds),
                "wrote_file": False,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="charts inspect",
            example=f"scout charts {kind} --x {x} --y {y} --out .scout/chart.svg",
            discover="scout charts kinds",
        ),
        command="charts inspect",
    )
    _gate(diags, fail_on)


@app.command(
    "line",
    epilog=examples_epilog(
        [
            "scout charts line --csv metrics.csv --x step --y loss --out .scout/loss.svg",
            "scout charts line --db .scout/runtrack.db --table metrics --x step --y value --series key",
            "scout --json charts line --csv m.csv --x ts --y latency_ms --time-x --fail-on warning",
        ]
    ),
)
def line_cmd(
    csv_path: str | None = typer.Option(None, "--csv", help="CSV input (header row)"),
    json_file: str | None = typer.Option(None, "--json-file", help="JSON array input"),
    records: str | None = typer.Option(
        None, "--records", help="dotted path to the array inside a JSON document"
    ),
    db: str | None = typer.Option(None, "--db", help="sqlite ledger (opened mode=ro)"),
    table: str | None = typer.Option(None, "--table", help="table or view to read"),
    where: str | None = typer.Option(
        None, "--where", help="SQL predicate (read-only connection)"
    ),
    limit: int | None = typer.Option(None, "--limit", help="max rows read"),
    x: str = typer.Option(
        ..., "--x", help="x column (numeric, or timestamps with --time-x)"
    ),
    y: str = typer.Option(..., "--y", help="y column (must hold numbers)"),
    series: str | None = typer.Option(
        None, "--series", help="column to split series by"
    ),
    time_x: bool = typer.Option(
        False, "--time-x", help="read x as timestamps (epoch or ISO-8601)"
    ),
    out: str | None = typer.Option(
        None, "--out", help=f"SVG output path (default {charts.OUT_REL})"
    ),
    title: str | None = typer.Option(None, "--title", help="chart heading"),
    width: int = typer.Option(charts.DEFAULT_WIDTH, "--width", help="SVG width in px"),
    height: int = typer.Option(
        charts.DEFAULT_HEIGHT, "--height", help="SVG height in px"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 at/above this severity — fires when a panel goes empty",
    ),
):
    """Line chart — points sorted by x, so an unordered SELECT still renders once."""
    _chart(
        charts.KIND_LINE,
        out=out,
        title=title,
        width=width,
        height=height,
        fail_on=fail_on,
        x=x,
        y=y,
        series=series,
        csv_path=csv_path,
        json_path=json_file,
        records=records,
        db=db,
        table=table,
        where=where,
        limit=limit,
        time_x=time_x,
    )


@app.command(
    "bar",
    epilog=examples_epilog(
        [
            "scout charts bar --csv counts.csv --x source --y n --sort -value",
            "scout charts bar --db .scout/logs.db --table entries --x level --y line_no --title 'lines by level'",
            "scout --json charts bar --csv counts.csv --x source --y n --fail-on warning",
        ]
    ),
)
def bar_cmd(
    csv_path: str | None = typer.Option(None, "--csv", help="CSV input (header row)"),
    json_file: str | None = typer.Option(None, "--json-file", help="JSON array input"),
    records: str | None = typer.Option(
        None, "--records", help="dotted path to the array inside a JSON document"
    ),
    db: str | None = typer.Option(None, "--db", help="sqlite ledger (opened mode=ro)"),
    table: str | None = typer.Option(None, "--table", help="table or view to read"),
    where: str | None = typer.Option(
        None, "--where", help="SQL predicate (read-only connection)"
    ),
    limit: int | None = typer.Option(None, "--limit", help="max rows read"),
    x: str = typer.Option(..., "--x", help="category column (duplicates are summed)"),
    y: str = typer.Option(..., "--y", help="value column (must hold numbers)"),
    series: str | None = typer.Option(
        None, "--series", help="column to split grouped bars by"
    ),
    sort: str = typer.Option(
        charts.SORT_LABEL, "--sort", help=f"category order ({'|'.join(charts.SORTS)})"
    ),
    out: str | None = typer.Option(
        None, "--out", help=f"SVG output path (default {charts.OUT_REL})"
    ),
    title: str | None = typer.Option(None, "--title", help="chart heading"),
    width: int = typer.Option(charts.DEFAULT_WIDTH, "--width", help="SVG width in px"),
    height: int = typer.Option(
        charts.DEFAULT_HEIGHT, "--height", help="SVG height in px"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 at/above this severity — fires when a panel goes empty",
    ),
):
    """Bar chart — duplicate categories summed (and the fold is stated in the footer)."""
    _chart(
        charts.KIND_BAR,
        out=out,
        title=title,
        width=width,
        height=height,
        fail_on=fail_on,
        x=x,
        y=y,
        series=series,
        csv_path=csv_path,
        json_path=json_file,
        records=records,
        db=db,
        table=table,
        where=where,
        limit=limit,
        sort=sort,
    )


@app.command(
    "scatter",
    epilog=examples_epilog(
        [
            "scout charts scatter --csv runs.csv --x lr --y final_loss",
            "scout charts scatter --db .scout/uptime.db --table checks --x ts --y latency_ms --series target --time-x",
            "scout --json charts scatter --csv runs.csv --x lr --y final_loss --fail-on warning",
        ]
    ),
)
def scatter_cmd(
    csv_path: str | None = typer.Option(None, "--csv", help="CSV input (header row)"),
    json_file: str | None = typer.Option(None, "--json-file", help="JSON array input"),
    records: str | None = typer.Option(
        None, "--records", help="dotted path to the array inside a JSON document"
    ),
    db: str | None = typer.Option(None, "--db", help="sqlite ledger (opened mode=ro)"),
    table: str | None = typer.Option(None, "--table", help="table or view to read"),
    where: str | None = typer.Option(
        None, "--where", help="SQL predicate (read-only connection)"
    ),
    limit: int | None = typer.Option(None, "--limit", help="max rows read"),
    x: str = typer.Option(
        ..., "--x", help="x column (numeric, or timestamps with --time-x)"
    ),
    y: str = typer.Option(..., "--y", help="y column (must hold numbers)"),
    series: str | None = typer.Option(
        None, "--series", help="column to split series by"
    ),
    time_x: bool = typer.Option(
        False, "--time-x", help="read x as timestamps (epoch or ISO-8601)"
    ),
    out: str | None = typer.Option(
        None, "--out", help=f"SVG output path (default {charts.OUT_REL})"
    ),
    title: str | None = typer.Option(None, "--title", help="chart heading"),
    width: int = typer.Option(charts.DEFAULT_WIDTH, "--width", help="SVG width in px"),
    height: int = typer.Option(
        charts.DEFAULT_HEIGHT, "--height", help="SVG height in px"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 at/above this severity — fires when a panel goes empty",
    ),
):
    """Scatter chart — one dot per row, no line implying an order that is not there."""
    _chart(
        charts.KIND_SCATTER,
        out=out,
        title=title,
        width=width,
        height=height,
        fail_on=fail_on,
        x=x,
        y=y,
        series=series,
        csv_path=csv_path,
        json_path=json_file,
        records=records,
        db=db,
        table=table,
        where=where,
        limit=limit,
        time_x=time_x,
    )


def register(root):
    root.add_typer(app, name="charts")
