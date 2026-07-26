# Solo personal project, no connection to employer, built with public/free-tier only
"""Charts — deterministic static SVG core (openswap #16: Grafana Cloud / Tableau).

The paid enemy is a dashboard *server*: you ship your numbers to it, it renders
them, and the picture only exists while you are logged in. This adapter deletes
the server. A chart here is a pure function of data that is ALREADY on this box,
and the output is one self-contained SVG file — no chart library, no JavaScript,
no webfont, no external asset — rendered by string templating so the whole
pipeline is auditable end to end.

The one property that makes this worth writing instead of installing something:
**the output is byte-identical for identical input.** That is what lets a chart
live in git next to the data that produced it and show up in a diff when the
numbers move. Everything that would break it is therefore banned by design:

- No generation timestamp anywhere in the SVG. A "generated at" stamp would make
  every re-render a diff, which is exactly the failure mode this avoids.
- No reliance on source row order. A sqlite SELECT without ORDER BY returns rows
  in an UNDEFINED order, so a renderer that "preserved input order" would emit
  different bytes on different runs over the same file. Ordering comes from the
  data: line/scatter points sort by (x, y), bar categories sort by `--sort`
  (label, or value with label as the tie-break), series sort by label.
- No locale, no timezone, no strftime. Tick labels are assembled from
  time.gmtime fields with explicit %02d formatting, so a chart rendered in
  Denver and in UTC are the same file.
- No float drift in coordinates. Every number in the markup goes through
  `_svg_num`, which rounds to 2 decimals and normalizes -0.0 to 0.

Provenance honesty is the second invariant, and it is why `dataset()` counts
things it could have silently dropped:
- Every chart carries a footer naming the source (file path, or `db#table` for a
  ledger) and the ROW COUNT it read, so a picture can never outlive its data
  without saying so.
- Rows whose y is not a number are SKIPPED and counted (`skipped.bad_y`), never
  coerced to zero — a gap in a metric is not a zero, and a chart that invents
  zeros is worse than no chart.
- Bar duplicates are summed, and the number of folded rows is reported in the
  footer, so an aggregation is never invisible.
- Zero plottable rows renders an explicit empty chart with NO axes numbers: no
  invented range, no line through nothing.

Reading is read-only and non-negotiable for ledgers: `open_readonly` opens with
sqlite `mode=ro`, so charting the shared uptime/runtrack ledgers physically
cannot write to them or take a write lock away from the daemon that owns them.
Table and column names ARE interpolated into the SELECT (they cannot be bound as
parameters), so they are validated against sqlite_master / PRAGMA table_info
first and quoted — an unknown name fails with the real column list instead of
reaching the SQL layer.

Extension points:
- `dataset()` takes rows (a list of dicts) plus a source descriptor, so any
  producer — csv, json, sqlite, a fixture, a future reader — renders identically.
- `render_svg()` takes the dataset dict, never a connection.
- `to_diagnostics()` maps a chart onto the family schema (no rows / nothing
  plottable = warning, skipped rows = info) so `--fail-on` gates a chart exactly
  like prose findings: a dashboard panel that quietly went empty is an incident.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

from bigbang.core import logs, openswap

KIND_LINE = "line"
KIND_BAR = "bar"
KIND_SCATTER = "scatter"
KINDS = (KIND_LINE, KIND_BAR, KIND_SCATTER)

SORT_LABEL = "label"
SORT_VALUE = "value"
SORT_VALUE_DESC = "-value"
SORTS = (SORT_LABEL, SORT_VALUE, SORT_VALUE_DESC)

OUT_REL = Path(".scout") / "chart.svg"

DEFAULT_WIDTH = 820
DEFAULT_HEIGHT = 440
# below this the plot area stops being a chart and starts being a rounding error
MIN_WIDTH = 240
MIN_HEIGHT = 160
MAX_WIDTH = 4000
MAX_HEIGHT = 4000

DEFAULT_TICKS = 5
# a hard stop on tick generation: a pathological range must not emit 10k lines
MAX_TICKS = 24
# bar category labels are truncated to fit their slot (px per character at 11px)
_CHAR_PX = 6.2

# Fixed, index-assigned series palette. Chosen for contrast on both light and
# dark backgrounds because the SVG honours prefers-color-scheme for its chrome
# while the series colours stay constant (a series must not change colour
# between two viewers looking at the same file).
PALETTE = (
    "#2f6fb3",
    "#b3261e",
    "#1b6b3a",
    "#a86500",
    "#6b3fa0",
    "#0e7c86",
    "#b0446b",
    "#55606e",
)


class ChartError(ValueError):
    """An actionable input problem: bad column, missing table, unusable data.

    Raised (never returned) by the readers and by `dataset()`, so the CLI can
    turn one exception type into a `fail_agent` message with an example
    invocation instead of leaking a traceback or a sqlite error string.
    """


# ---- reading ----------------------------------------------------------------


def open_readonly(path: str | Path) -> sqlite3.Connection:
    """Open a sqlite ledger READ-ONLY (`mode=ro`). Absent file is a ChartError.

    Read-only is the enforcement half of "charting cannot disturb the thing it
    charts": the returned connection rejects every write at the sqlite layer, so
    plotting `.scout/uptime.db` can neither modify it nor contend for the write
    lock uptime's probe loop holds. as_uri() gives the absolute percent-encoded
    form sqlite's URI parser wants on Windows too, so paths with spaces open.
    """
    p = Path(path)
    if not p.exists():
        raise ChartError(f"no sqlite ledger at {p}")
    try:
        conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - platform URI failures
        raise ChartError(f"{p} could not be opened read-only: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def _ident(name: str) -> str:
    """Quote a schema-validated identifier; doubling `"` closes the last hatch.

    Validation already proved the name exists, so this is belt-and-braces: a
    table someone literally named `x" --` still cannot terminate the quote.
    """
    return '"' + str(name).replace('"', '""') + '"'


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Column names of `table`, or a ChartError naming the tables that exist.

    This is the validation gate in front of the only interpolated SQL in this
    module: a name that reaches the SELECT has been confirmed to exist here.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    if row is None:
        have = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                " ORDER BY name"
            )
        ]
        raise ChartError(f"no table or view {table!r} — this ledger has {have}")
    return [r[1] for r in conn.execute(f"PRAGMA table_info({_ident(table)})")]


def read_sqlite_rows(
    path: str | Path,
    *,
    table: str,
    columns: list[str],
    where: str | None = None,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the named columns of one table/view, read-only.

    `where` is interpolated verbatim because a predicate cannot be bound as a
    parameter. That is bounded, not blind: the connection is `mode=ro` and
    sqlite3.execute refuses more than one statement, so the worst a hostile
    `--where` achieves is a different read of a file the caller already named.
    Identifiers are a different story and are validated against the live schema
    by `table_columns` before they are quoted into the statement.
    """
    conn = open_readonly(path)
    try:
        have = table_columns(conn, table)
        missing = [c for c in columns if c not in have]
        if missing:
            raise ChartError(f"{table} has no column(s) {missing} — available: {have}")
        cols = ", ".join(_ident(c) for c in columns)
        sql = f"SELECT {cols} FROM {_ident(table)}"  # noqa: S608 - idents validated
        if where:
            sql += f" WHERE {where}"
        if limit is not None:
            sql += " LIMIT ?"
        try:
            cur = conn.execute(sql, (limit,) if limit is not None else ())
            rows = [{c: r[c] for c in columns} for r in cur]
        except sqlite3.Error as exc:
            raise ChartError(f"query failed ({exc}) — sql was: {sql}") from exc
    finally:
        conn.close()
    return rows, {
        "kind": "sqlite",
        "path": str(Path(path)),
        "table": table,
        "label": f"{Path(path).as_posix()}#{table}",
        "read_only": True,
        "where": where,
    }


def read_csv_rows(
    path: str | Path, *, limit: int | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a header-row CSV into dicts. Every value is text at this stage.

    newline="" is required by the csv module (it does its own line ending
    handling); utf-8-sig strips the BOM Excel writes, which would otherwise
    turn the first header into "﻿step" and make --x step "unknown".
    """
    p = Path(path)
    if not p.exists():
        raise ChartError(f"no CSV file at {p}")
    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ChartError(f"{p} has no header row — CSV needs column names")
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(dict(row))
            if limit is not None and len(rows) >= limit:
                break
    return rows, {
        "kind": "csv",
        "path": str(p),
        "table": None,
        "label": p.as_posix(),
        "columns": list(reader.fieldnames),
    }


def _dig(doc: Any, pointer: str) -> Any:
    """Walk a dotted path through nested dicts (JSON pointer, poor man's)."""
    cur = doc
    for part in pointer.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise ChartError(f"--records {pointer!r} does not resolve at {part!r}")
        cur = cur[part]
    return cur


def read_json_rows(
    path: str | Path, *, records: str | None = None, limit: int | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a JSON array of objects, optionally at a dotted `records` path.

    The dotted path is what makes `scout --json <anything> > x.json` chartable:
    this CLI's own envelope puts payloads under `data`, so
    `--records data.history` plots a runtrack run without a reshaping step.
    """
    p = Path(path)
    if not p.exists():
        raise ChartError(f"no JSON file at {p}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ChartError(f"{p} is not readable JSON: {exc}") from exc
    if records:
        doc = _dig(doc, records)
    if not isinstance(doc, list):
        raise ChartError(
            f"{p} does not hold a JSON array of objects at "
            f"{records or 'the top level'} — pass --records to point at one"
        )
    rows = [r for r in doc if isinstance(r, dict)]
    if len(rows) != len(doc):
        raise ChartError(
            f"{p} array holds {len(doc) - len(rows)} non-object element(s); "
            "every element must be an object with the --x/--y keys"
        )
    if limit is not None:
        rows = rows[:limit]
    return rows, {
        "kind": "json",
        "path": str(p),
        "table": None,
        "label": p.as_posix() + ("" if not records else f"#{records}"),
        "records": records,
    }


# ---- coercion ---------------------------------------------------------------


def as_number(value: Any) -> float | None:
    """Anything -> a finite float, or None when it genuinely is not a number.

    Deliberately strict: None, "", "null", bools and NaN/inf are NOT numbers.
    A chart that reads a missing metric as 0 draws a cliff that never happened,
    so every rejection here is counted and reported instead of substituted.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    text = str(value).strip()
    if not text or text.lower() in ("null", "none", "nan", "-", "na"):
        return None
    try:
        v = float(text)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def as_time(value: Any) -> float | None:
    """A timestamp-ish x value -> epoch seconds, for `--time-x`.

    Numbers pass through untouched (an epoch is already an epoch, and a step
    counter must never be reinterpreted as milliseconds), non-numeric strings go
    through logs.parse_timestamp — the locale-independent ISO-8601 parser this
    repo already owns, reused rather than re-implemented.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return as_number(value)
    direct = as_number(value)
    if direct is not None:
        return direct
    if value is None:
        return None
    return logs.parse_timestamp(str(value))


# ---- the dataset (the render contract) --------------------------------------


def _series_label(row: dict[str, Any], column: str | None, default: str) -> str:
    if column is None:
        return default
    raw = row.get(column)
    return default if raw is None or str(raw) == "" else str(raw)


def _sorted_categories(totals: dict[str, float], sort: str) -> list[str]:
    """Bar category order — deterministic under every sort, ties broken by label."""
    if sort == SORT_VALUE:
        return sorted(totals, key=lambda c: (totals[c], c))
    if sort == SORT_VALUE_DESC:
        return sorted(totals, key=lambda c: (-totals[c], c))
    return sorted(totals)


def _bar_series(
    rows: list[dict[str, Any]],
    *,
    x: str,
    y: str,
    series: str | None,
    sort: str,
    skipped: dict[str, int],
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Fold rows into {series: {category: sum}} plus the shared category axis."""
    grouped: dict[str, dict[str, float]] = {}
    totals: dict[str, float] = {}
    folded = 0
    for row in rows:
        if x not in row or y not in row:
            skipped["missing"] += 1
            continue
        value = as_number(row.get(y))
        if value is None:
            skipped["bad_y"] += 1
            continue
        cat = str(row.get(x))
        label = _series_label(row, series, y)
        bucket = grouped.setdefault(label, {})
        if cat in bucket:
            folded += 1
        bucket[cat] = bucket.get(cat, 0.0) + value
        totals[cat] = totals.get(cat, 0.0) + value
    categories = _sorted_categories(totals, sort)
    out = [
        {
            "label": label,
            "points": [[c, bucket[c]] for c in categories if c in bucket],
            "values": [bucket.get(c) for c in categories],
        }
        for label, bucket in sorted(grouped.items())
    ]
    return out, categories, folded


def _xy_series(
    rows: list[dict[str, Any]],
    *,
    x: str,
    y: str,
    series: str | None,
    time_x: bool,
    skipped: dict[str, int],
) -> list[dict[str, Any]]:
    """Fold rows into sorted (x, y) point lists per series."""
    grouped: dict[str, list[list[float]]] = {}
    coerce = as_time if time_x else as_number
    for row in rows:
        if x not in row or y not in row:
            skipped["missing"] += 1
            continue
        xv = coerce(row.get(x))
        yv = as_number(row.get(y))
        if xv is None:
            skipped["bad_x"] += 1
            continue
        if yv is None:
            skipped["bad_y"] += 1
            continue
        grouped.setdefault(_series_label(row, series, y), []).append([xv, yv])
    return [
        {"label": label, "points": sorted(points)}
        for label, points in sorted(grouped.items())
    ]


def dataset(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    x: str,
    y: str,
    series: str | None = None,
    source: dict[str, Any] | None = None,
    time_x: bool = False,
    sort: str = SORT_LABEL,
) -> dict[str, Any]:
    """Rows -> the JSON-able dataset every renderer and every test agrees on.

    Nothing is invented and nothing is silently dropped: unusable rows land in
    `skipped` by reason, bar duplicates land in `folded`, and `bounds` is None
    (not a made-up 0..1) when there is nothing to bound.
    """
    if kind not in KINDS:
        raise ChartError(f"kind must be one of {'|'.join(KINDS)}, got {kind!r}")
    if sort not in SORTS:
        raise ChartError(f"sort must be one of {'|'.join(SORTS)}, got {sort!r}")
    skipped = {"missing": 0, "bad_x": 0, "bad_y": 0}
    categories: list[str] = []
    folded = 0
    if kind == KIND_BAR:
        built, categories, folded = _bar_series(
            rows, x=x, y=y, series=series, sort=sort, skipped=skipped
        )
    else:
        built = _xy_series(
            rows, x=x, y=y, series=series, time_x=time_x, skipped=skipped
        )
    for idx, s in enumerate(built):
        s["color"] = PALETTE[idx % len(PALETTE)]
        s["n"] = len(s["points"])
    ys = [p[1] for s in built for p in s["points"]]
    bounds: dict[str, Any] | None = None
    if ys:
        bounds = {"y": [min(ys), max(ys)]}
        if kind == KIND_BAR:
            # A bar chart is read as a length comparison, so an axis that does
            # not reach zero misstates every ratio on it (the classic truncated-
            # axis lie). Bars always get zero in range; line/scatter do not,
            # because a time series pinned to zero hides the variation.
            bounds["y"] = [min(0.0, min(ys)), max(0.0, max(ys))]
            bounds["x"] = None  # categorical axis: there is no numeric x range
        else:
            xs = [p[0] for s in built for p in s["points"]]
            bounds["x"] = [min(xs), max(xs)]
    return {
        "kind": kind,
        "columns": {"x": x, "y": y, "series": series},
        "time_x": bool(time_x and kind != KIND_BAR),
        "sort": sort if kind == KIND_BAR else None,
        "series": built,
        "categories": categories,
        "rows_read": len(rows),
        "points": len(ys),
        "skipped": skipped,
        "folded": folded,
        "bounds": bounds,
        "source": source
        or {"kind": "rows", "path": None, "table": None, "label": "in-memory rows"},
    }


def read_dataset(
    *,
    kind: str,
    x: str,
    y: str,
    series: str | None = None,
    csv_path: str | Path | None = None,
    json_path: str | Path | None = None,
    records: str | None = None,
    db: str | Path | None = None,
    table: str | None = None,
    where: str | None = None,
    limit: int | None = None,
    time_x: bool = False,
    sort: str = SORT_LABEL,
) -> dict[str, Any]:
    """Resolve exactly one input source, read it, and build the dataset."""
    chosen = [
        n
        for n, v in (("--csv", csv_path), ("--json-file", json_path), ("--db", db))
        if v
    ]
    if len(chosen) != 1:
        raise ChartError(
            "name exactly one input: --csv FILE, --json-file FILE, or "
            f"--db LEDGER --table NAME (got {chosen or 'none'})"
        )
    if db:
        if not table:
            raise ChartError("--db needs --table (the table or view to read)")
        cols = [c for c in (x, y, series) if c]
        rows, source = read_sqlite_rows(
            db,
            table=table,
            columns=list(dict.fromkeys(cols)),
            where=where,
            limit=limit,
        )
    elif csv_path:
        rows, source = read_csv_rows(csv_path, limit=limit)
    else:
        rows, source = read_json_rows(json_path, records=records, limit=limit)
    return dataset(
        rows,
        kind=kind,
        x=x,
        y=y,
        series=series,
        source=source,
        time_x=time_x,
        sort=sort,
    )


# ---- diagnostics ------------------------------------------------------------


def to_diagnostics(ds: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a chart onto the family diagnostic schema.

    A panel that quietly went empty is the classic dashboard failure — the graph
    still renders, nobody notices the feed died — so `charts:no-rows` and
    `charts:nothing-plottable` are warnings a cron job can gate on. Skipped rows
    are info: they are usually a legitimately sparse metric, but the count has to
    be visible or the picture is lying by omission.
    """
    where = str(ds.get("source", {}).get("label") or "input")
    cols = ds.get("columns", {})
    diags: list[dict[str, Any]] = []
    if not ds.get("rows_read"):
        diags.append(
            openswap.diagnostic(
                path=where,
                line=0,
                col=0,
                rule="charts:no-rows",
                severity="warning",
                source="charts",
                message="source returned no rows — the chart is empty, not flat",
            )
        )
    elif not ds.get("points"):
        diags.append(
            openswap.diagnostic(
                path=where,
                line=0,
                col=0,
                rule="charts:nothing-plottable",
                severity="warning",
                source="charts",
                message=(
                    f"{ds['rows_read']} row(s) read but none plottable with "
                    f"x={cols.get('x')!r} y={cols.get('y')!r} — check the column "
                    "names and whether y holds numbers"
                ),
            )
        )
    skipped = ds.get("skipped") or {}
    total_skipped = sum(int(v) for v in skipped.values())
    if total_skipped and ds.get("points"):
        diags.append(
            openswap.diagnostic(
                path=where,
                line=0,
                col=0,
                rule="charts:skipped-rows",
                severity="info",
                source="charts",
                message=(
                    f"{total_skipped} of {ds['rows_read']} row(s) skipped "
                    f"({skipped}) — omitted from the chart, never coerced to 0"
                ),
            )
        )
    if ds.get("folded"):
        diags.append(
            openswap.diagnostic(
                path=where,
                line=0,
                col=0,
                rule="charts:folded-categories",
                severity="info",
                source="charts",
                message=(
                    f"{ds['folded']} row(s) summed into an existing bar "
                    "category — the footer states the fold"
                ),
            )
        )
    return openswap.sort_diagnostics(diags)


# ---- scales -----------------------------------------------------------------


def _nice_step(raw: float) -> float:
    """Round a raw tick spacing up to the next 1/2/2.5/5 x 10^n."""
    if not math.isfinite(raw) or raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    base = raw / (10.0**exp)
    for mult in (1.0, 2.0, 2.5, 5.0):
        if base <= mult:
            return mult * (10.0**exp)
    return 10.0 ** (exp + 1)


def nice_axis(lo: float, hi: float, *, count: int = DEFAULT_TICKS) -> dict[str, Any]:
    """A padded axis range plus its tick values — deterministic and finite.

    A flat series (lo == hi) is padded rather than divided by zero, and tick
    values are rounded to 12 places so 0.1 + 0.2 never prints as
    0.30000000000000004 in the markup.
    """
    lo, hi = float(lo), float(hi)
    if not (math.isfinite(lo) and math.isfinite(hi)):
        lo, hi = 0.0, 1.0
    if hi < lo:
        lo, hi = hi, lo
    if hi == lo:
        pad = abs(hi) * 0.1 or 1.0
        lo, hi = lo - pad, hi + pad
    count = max(2, min(int(count), MAX_TICKS))
    step = _nice_step((hi - lo) / count)
    nlo = math.floor(lo / step) * step
    nhi = math.ceil(hi / step) * step
    n = round((nhi - nlo) / step)
    n = max(1, min(n, MAX_TICKS))
    ticks = [round(nlo + i * step, 12) for i in range(n + 1)]
    return {
        "lo": round(nlo, 12),
        "hi": round(ticks[-1], 12),
        "step": step,
        "ticks": ticks,
    }


# ---- formatting -------------------------------------------------------------

# control characters are not legal XML text; map them to a space rather than
# emitting a file no parser will load
_CTRL = {c: " " for c in list(range(0x20)) + [0x7F] if c not in (0x09,)}


def esc(value: Any) -> str:
    """XML-safe text for both element bodies and attribute values."""
    return html.escape(str(value).translate(_CTRL), quote=True)


def _svg_num(value: float) -> str:
    """Coordinate formatting — 2dp, and -0.00 normalized to 0."""
    v = round(float(value), 2)
    if v == 0:
        return "0"
    return f"{v:g}" if abs(v) >= 0.01 else "0"


def fmt_value(value: float) -> str:
    """Tick/label formatting: compact, deterministic, never locale-dependent."""
    v = float(value)
    if v == 0:
        return "0"
    if abs(v) >= 1e6 or abs(v) < 1e-3:
        return f"{v:.2e}"
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def fmt_time(epoch: float) -> str:
    """UTC label assembled from gmtime fields — no strftime, no locale, no TZ."""
    try:
        tm = time.gmtime(float(epoch))
    except (OSError, OverflowError, ValueError):
        return fmt_value(epoch)
    return (
        f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d} "
        f"{tm.tm_hour:02d}:{tm.tm_min:02d}"
    )


def _truncate(text: str, chars: int) -> str:
    chars = max(1, int(chars))
    return text if len(text) <= chars else text[: max(1, chars - 2)] + ".."


def provenance(ds: dict[str, Any]) -> str:
    """The footer line: what was read, how much of it, and what was dropped.

    Deliberately not a caption. It names the source and the row count so a chart
    checked into a repo can be traced back to the table that produced it, and it
    states every omission (skips, folds) so the picture cannot lie by silence.
    """
    src = ds.get("source", {})
    cols = ds.get("columns", {})
    bits = [
        f"source: {src.get('label')} ({src.get('kind')})",
        f"{ds.get('rows_read', 0)} rows read",
        f"{ds.get('points', 0)} points",
        f"x={cols.get('x')}",
        f"y={cols.get('y')}",
    ]
    if cols.get("series"):
        bits.append(f"series={cols['series']}")
    if src.get("where"):
        bits.append(f"where={src['where']}")
    skipped = sum(int(v) for v in (ds.get("skipped") or {}).values())
    if skipped:
        bits.append(f"{skipped} rows skipped (not plottable)")
    if ds.get("folded"):
        bits.append(f"{ds['folded']} duplicate categories summed")
    return " · ".join(bits)


# ---- rendering --------------------------------------------------------------

_CSS = """
.bg { fill: #ffffff; }
text { font-family: system-ui, sans-serif; fill: #1c2430; }
.title { font-size: 16px; font-weight: 600; }
.axis { font-size: 11px; fill: #55606e; }
.axis-name { font-size: 11px; fill: #55606e; font-weight: 600; }
.foot { font-family: ui-monospace, monospace; font-size: 9px; fill: #55606e; }
.grid { stroke: #d8dee6; stroke-width: 1; }
.frame { stroke: #a9b3c0; stroke-width: 1; fill: none; }
.zero { stroke: #8b96a5; stroke-width: 1; }
.empty { font-size: 13px; fill: #a86500; }
@media (prefers-color-scheme: dark) {
  .bg { fill: #12161c; }
  text { fill: #e7ecf2; }
  .axis, .axis-name, .foot { fill: #9aa7b6; }
  .grid { stroke: #2b3440; }
  .frame { stroke: #3b4653; }
}
"""

_FOOT_H = 30
_LEGEND_H = 20
_TITLE_H = 26
_AXIS_H = 34
_PAD_L = 68
_PAD_R = 16
_PAD_T = 12


def _plot_box(
    ds: dict[str, Any], width: int, height: int, has_title: bool
) -> dict[str, float]:
    legend = _LEGEND_H if len(ds.get("series") or []) > 1 else 0
    top = _PAD_T + (_TITLE_H if has_title else 0) + legend
    bottom = height - _FOOT_H - _AXIS_H
    return {
        "left": float(_PAD_L),
        "right": float(width - _PAD_R),
        "top": float(top),
        "bottom": float(bottom),
        "w": float(width - _PAD_R - _PAD_L),
        "h": float(bottom - top),
        "legend_y": float(_PAD_T + (_TITLE_H if has_title else 0) + 13),
    }


def _y_axis(box: dict[str, float], axis: dict[str, Any]) -> list[str]:
    span = axis["hi"] - axis["lo"] or 1.0
    out = []
    for tick in axis["ticks"]:
        y = box["bottom"] - (tick - axis["lo"]) / span * box["h"]
        cls = "zero" if tick == 0 else "grid"
        out.append(
            f'<line class="{cls}" x1="{_svg_num(box["left"])}" '
            f'y1="{_svg_num(y)}" x2="{_svg_num(box["right"])}" '
            f'y2="{_svg_num(y)}"/>'
        )
        out.append(
            f'<text class="axis" x="{_svg_num(box["left"] - 6)}" '
            f'y="{_svg_num(y + 3.5)}" text-anchor="end">'
            f"{esc(fmt_value(tick))}</text>"
        )
    return out


def _x_axis_numeric(
    box: dict[str, float], axis: dict[str, Any], *, time_x: bool
) -> list[str]:
    span = axis["hi"] - axis["lo"] or 1.0
    fmt = fmt_time if time_x else fmt_value
    out = []
    for tick in axis["ticks"]:
        x = box["left"] + (tick - axis["lo"]) / span * box["w"]
        out.append(
            f'<line class="grid" x1="{_svg_num(x)}" y1="{_svg_num(box["bottom"])}" '
            f'x2="{_svg_num(x)}" y2="{_svg_num(box["bottom"] + 4)}"/>'
        )
        out.append(
            f'<text class="axis" x="{_svg_num(x)}" '
            f'y="{_svg_num(box["bottom"] + 16)}" text-anchor="middle">'
            f"{esc(fmt(tick))}</text>"
        )
    return out


def _x_axis_categories(box: dict[str, float], categories: list[str]) -> list[str]:
    slot = box["w"] / max(1, len(categories))
    chars = int(slot / _CHAR_PX)
    out = []
    for idx, cat in enumerate(categories):
        x = box["left"] + slot * (idx + 0.5)
        out.append(
            f'<text class="axis" x="{_svg_num(x)}" '
            f'y="{_svg_num(box["bottom"] + 16)}" text-anchor="middle">'
            f"{esc(_truncate(cat, chars))}</text>"
        )
    return out


def _marks_xy(
    ds: dict[str, Any],
    box: dict[str, float],
    xa: dict[str, Any],
    ya: dict[str, Any],
) -> list[str]:
    xspan = xa["hi"] - xa["lo"] or 1.0
    yspan = ya["hi"] - ya["lo"] or 1.0

    def place(point: list[float]) -> tuple[float, float]:
        px = box["left"] + (point[0] - xa["lo"]) / xspan * box["w"]
        py = box["bottom"] - (point[1] - ya["lo"]) / yspan * box["h"]
        return px, py

    out = []
    for s in ds["series"]:
        placed = [place(p) for p in s["points"]]
        if ds["kind"] == KIND_LINE and len(placed) > 1:
            pts = " ".join(f"{_svg_num(px)},{_svg_num(py)}" for px, py in placed)
            out.append(
                f'<polyline fill="none" stroke="{esc(s["color"])}" '
                f'stroke-width="2" stroke-linejoin="round" points="{pts}"/>'
            )
        # a one-point line is invisible, and scatter is dots by definition
        if ds["kind"] == KIND_SCATTER or len(placed) == 1:
            for px, py in placed:
                out.append(
                    f'<circle cx="{_svg_num(px)}" cy="{_svg_num(py)}" r="3" '
                    f'fill="{esc(s["color"])}"/>'
                )
    return out


def _marks_bar(
    ds: dict[str, Any], box: dict[str, float], ya: dict[str, Any]
) -> list[str]:
    cats = ds["categories"]
    slot = box["w"] / max(1, len(cats))
    n = max(1, len(ds["series"]))
    bar_w = slot * 0.8 / n
    yspan = ya["hi"] - ya["lo"] or 1.0
    base = box["bottom"] - (0.0 - ya["lo"]) / yspan * box["h"]
    base = min(max(base, box["top"]), box["bottom"])
    out = []
    for si, s in enumerate(ds["series"]):
        for ci, cat in enumerate(cats):
            value = s["values"][ci]
            if value is None:
                continue  # this series has no bar for that category; draw nothing
            y = box["bottom"] - (value - ya["lo"]) / yspan * box["h"]
            top, bot = min(y, base), max(y, base)
            x = box["left"] + slot * ci + slot * 0.1 + bar_w * si
            out.append(
                f'<rect x="{_svg_num(x)}" y="{_svg_num(top)}" '
                f'width="{_svg_num(bar_w)}" height="{_svg_num(max(0.5, bot - top))}" '
                f'fill="{esc(s["color"])}"><title>{esc(cat)} = '
                f"{esc(fmt_value(value))}</title></rect>"
            )
    return out


def _legend(ds: dict[str, Any], box: dict[str, float]) -> list[str]:
    if len(ds["series"]) <= 1:
        return []
    out = []
    x = box["left"]
    for s in ds["series"]:
        label = _truncate(str(s["label"]), 22)
        out.append(
            f'<rect x="{_svg_num(x)}" y="{_svg_num(box["legend_y"] - 8)}" '
            f'width="9" height="9" fill="{esc(s["color"])}"/>'
        )
        out.append(
            f'<text class="axis" x="{_svg_num(x + 13)}" '
            f'y="{_svg_num(box["legend_y"])}">{esc(label)}</text>'
        )
        x += 13 + len(label) * _CHAR_PX + 16
    return out


def render_svg(
    ds: dict[str, Any],
    *,
    title: str | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> str:
    """The dashboard panel, deleted: one self-contained deterministic SVG.

    Inline CSS, zero JavaScript, zero external assets, and — the point of the
    whole module — NO generation timestamp, so re-rendering unchanged data
    produces a byte-identical file. Every dynamic string (series labels, category
    names, the source path, the title) goes through `esc`, because all of them
    come from data or from an operator's shell.

    An empty dataset renders an explicit "no data" panel with no axes and no tick
    numbers: an invented 0..1 range around nothing is the dashboard lie this
    adapter exists to avoid.
    """
    width = int(width)
    height = int(height)
    if not (MIN_WIDTH <= width <= MAX_WIDTH):
        raise ChartError(f"--width must be {MIN_WIDTH}..{MAX_WIDTH}, got {width}")
    if not (MIN_HEIGHT <= height <= MAX_HEIGHT):
        raise ChartError(f"--height must be {MIN_HEIGHT}..{MAX_HEIGHT}, got {height}")
    cols = ds.get("columns", {})
    box = _plot_box(ds, width, height, bool(title))
    parts: list[str] = [
        f'<rect class="bg" x="0" y="0" width="{width}" height="{height}"/>'
    ]
    if title:
        parts.append(
            f'<text class="title" x="{_PAD_L}" y="{_PAD_T + 15}">{esc(title)}</text>'
        )
    if not ds.get("points"):
        parts.append(
            f'<text class="empty" x="{_svg_num(width / 2)}" '
            f'y="{_svg_num(box["top"] + box["h"] / 2)}" text-anchor="middle">'
            f"no data to plot — {esc(ds.get('rows_read', 0))} row(s) read, "
            "nothing plottable</text>"
        )
    else:
        ya = nice_axis(*ds["bounds"]["y"])
        parts.extend(_legend(ds, box))
        parts.extend(_y_axis(box, ya))
        if ds["kind"] == KIND_BAR:
            parts.extend(_x_axis_categories(box, ds["categories"]))
            parts.extend(_marks_bar(ds, box, ya))
        else:
            # UTC stamps are ~16 chars wide; 5 of them collide, so a time axis
            # asks for fewer ticks rather than overlapping labels
            time_x = bool(ds.get("time_x"))
            xa = nice_axis(*ds["bounds"]["x"], count=3 if time_x else DEFAULT_TICKS)
            parts.extend(_x_axis_numeric(box, xa, time_x=time_x))
            parts.extend(_marks_xy(ds, box, xa, ya))
        parts.append(
            f'<rect class="frame" x="{_svg_num(box["left"])}" '
            f'y="{_svg_num(box["top"])}" width="{_svg_num(box["w"])}" '
            f'height="{_svg_num(box["h"])}"/>'
        )
        parts.append(
            f'<text class="axis-name" x="{_svg_num((box["left"] + box["right"]) / 2)}"'
            f' y="{_svg_num(box["bottom"] + 30)}" text-anchor="middle">'
            f"{esc(cols.get('x'))}</text>"
        )
        parts.append(
            f'<text class="axis-name" x="14" y="{_svg_num(box["top"] + box["h"] / 2)}"'
            f' text-anchor="middle" transform="rotate(-90 14 '
            f'{_svg_num(box["top"] + box["h"] / 2)})">{esc(cols.get("y"))}</text>'
        )
    parts.append(
        f'<text class="foot" x="{_svg_num(_PAD_L)}" '
        f'y="{_svg_num(height - 16)}">{esc(provenance(ds))}</text>'
    )
    parts.append(
        f'<text class="foot" x="{_svg_num(_PAD_L)}" y="{_svg_num(height - 6)}">'
        f"scout charts {esc(ds.get('kind'))} (openswap #16) — static SVG, no "
        "script, no external assets, no generation timestamp: identical input "
        "renders byte-identical output</text>"
    )
    body = "\n".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{esc(title or cols.get("y") or "chart")}">\n'
        f"<style>{_CSS}</style>\n{body}\n</svg>\n"
    )


def fingerprint(svg: str) -> str:
    """sha256 of the rendered SVG — the falsifiable half of "deterministic".

    Callers (and this repo's tests) compare two renders of the same dataset by
    this digest instead of trusting the docstring.
    """
    return hashlib.sha256(svg.encode("utf-8")).hexdigest()
