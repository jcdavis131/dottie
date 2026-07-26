"""Charts — openswap #16 (Grafana Cloud/Tableau -> deterministic static SVG from
sqlite ledgers or JSON/CSV). Pure-logic core tests + the read-only enforcement +
the determinism contract + the anti-fabrication contract + capability detection +
the subprocess envelope.

Offline and deterministic by construction: every fixture is a file under tmp_path
(a CSV, a JSON document, a sqlite ledger seeded through runtrack's OWN writers),
no test opens a socket, and nothing here reads the clock — because the renderer
must not either. Several tests exist purely to make that falsifiable: rendering
the same rows in a shuffled order must produce the SAME bytes, and rendering
twice must produce the same sha256.

The assertions this file refuses to make: that an empty source produced a chart
with numbers on it, or that a non-numeric metric is a zero.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bigbang.core import charts, openswap, runtrack

ROOT = Path(__file__).resolve().parents[1]
SVG_NS = "{http://www.w3.org/2000/svg}"

ROWS = [
    {"step": "0", "loss": "2.5", "key": "loss"},
    {"step": "1", "loss": "1.75", "key": "loss"},
    {"step": "2", "loss": "1.25", "key": "loss"},
]


def _csv(tmp_path, text, name="metrics.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _json(tmp_path, doc, name="metrics.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _seed_metrics(path, *, steps=(0, 1, 2)):
    """A real runtrack ledger written by runtrack's OWN writers (#10 substrate)."""
    conn = runtrack.open_store(path)
    run = runtrack.start_run(conn, "trainer", config={"lr": 3e-4}, ts=1000.0)
    for i in steps:
        runtrack.log_metrics(
            conn,
            run["id"],
            {"loss": 2.5 - 0.5 * i, "lr": 3e-4},
            step=i,
            ts=1000.0 + i,
        )
    conn.close()
    return run["id"]


def _tree(svg):
    """Parse the SVG — proof it is well-formed XML, not just a string that looks it."""
    # S314 waived: the input is markup this repo just generated, not untrusted
    # XML, and parsing it IS the assertion — a hostile series label that broke
    # out of its escaping would fail here rather than silently ship.
    return ET.fromstring(svg)  # noqa: S314


def _tags(svg, tag):
    return _tree(svg).findall(f".//{SVG_NS}{tag}")


# ---- readers: CSV ------------------------------------------------------------


def test_read_csv_rows_returns_dicts_and_provenance(tmp_path):
    p = _csv(tmp_path, "step,loss\n0,2.5\n1,1.75\n")
    rows, src = charts.read_csv_rows(p)
    assert rows == [{"step": "0", "loss": "2.5"}, {"step": "1", "loss": "1.75"}]
    assert src["kind"] == "csv" and src["table"] is None
    assert src["label"] == p.as_posix() and src["path"] == str(p)
    assert src["columns"] == ["step", "loss"]


def test_read_csv_strips_an_excel_bom_from_the_first_header(tmp_path):
    """utf-8-sig, not utf-8: a BOM would make --x step an unknown column."""
    p = tmp_path / "bom.csv"
    p.write_bytes(b"\xef\xbb\xbfstep,loss\n0,2.5\n")
    rows, _src = charts.read_csv_rows(p)
    assert list(rows[0]) == ["step", "loss"]
    assert "﻿step" not in rows[0]


def test_read_csv_honours_limit_and_reports_real_errors(tmp_path):
    p = _csv(tmp_path, "step,loss\n0,1\n1,2\n2,3\n")
    assert len(charts.read_csv_rows(p, limit=2)[0]) == 2
    with pytest.raises(charts.ChartError, match="no CSV file"):
        charts.read_csv_rows(tmp_path / "nope.csv")
    empty = _csv(tmp_path, "", name="empty.csv")
    with pytest.raises(charts.ChartError, match="no header row"):
        charts.read_csv_rows(empty)


# ---- readers: JSON ----------------------------------------------------------


def test_read_json_rows_accepts_a_top_level_array(tmp_path):
    p = _json(tmp_path, [{"step": 0, "loss": 2.5}, {"step": 1, "loss": 1.0}])
    rows, src = charts.read_json_rows(p)
    assert rows == [{"step": 0, "loss": 2.5}, {"step": 1, "loss": 1.0}]
    assert src["kind"] == "json" and src["records"] is None
    assert src["label"] == p.as_posix()


def test_read_json_rows_follows_a_dotted_records_path(tmp_path):
    """This CLI's own --json envelope nests payloads under data — chart it directly."""
    p = _json(tmp_path, {"ok": True, "data": {"history": [{"step": 0, "value": 9}]}})
    rows, src = charts.read_json_rows(p, records="data.history")
    assert rows == [{"step": 0, "value": 9}]
    assert src["records"] == "data.history"
    assert src["label"].endswith("#data.history")
    with pytest.raises(charts.ChartError, match="does not resolve at 'nope'"):
        charts.read_json_rows(p, records="data.nope")


def test_read_json_rows_refuses_shapes_it_cannot_chart(tmp_path):
    obj = _json(tmp_path, {"step": 0}, name="obj.json")
    with pytest.raises(charts.ChartError, match="array of objects"):
        charts.read_json_rows(obj)
    mixed = _json(tmp_path, [{"a": 1}, 7], name="mixed.json")
    with pytest.raises(charts.ChartError, match="non-object element"):
        charts.read_json_rows(mixed)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(charts.ChartError, match="not readable JSON"):
        charts.read_json_rows(bad)
    with pytest.raises(charts.ChartError, match="no JSON file"):
        charts.read_json_rows(tmp_path / "gone.json")


# ---- readers: sqlite, read-only is enforced not promised ---------------------


def test_open_readonly_physically_rejects_every_write(tmp_path):
    """Charting a ledger cannot disturb the daemon that owns it."""
    db = tmp_path / "runtrack.db"
    _seed_metrics(db)
    conn = charts.open_readonly(db)
    # reads work, so this is a real connection and not a stub
    assert conn.execute("SELECT COUNT(*) AS n FROM metrics").fetchone()["n"] == 6
    for sql in (
        "INSERT INTO metrics(run_id, step, key, value, ts) VALUES(1,9,'x',1.0,1.0)",
        "UPDATE metrics SET value = 0",
        "DELETE FROM metrics",
        "CREATE TABLE charts_notes(a)",
    ):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(sql)
    conn.close()


def test_open_readonly_reports_an_absent_ledger_and_survives_spaces(tmp_path):
    with pytest.raises(charts.ChartError, match="no sqlite ledger"):
        charts.open_readonly(tmp_path / "gone.db")
    d = tmp_path / "my chart dir"
    d.mkdir()
    db = d / "runtrack.db"
    _seed_metrics(db)
    conn = charts.open_readonly(db)
    assert conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"] == 1
    conn.close()


def test_table_and_column_names_are_validated_against_the_live_schema(tmp_path):
    db = tmp_path / "runtrack.db"
    _seed_metrics(db)
    conn = charts.open_readonly(db)
    assert "value" in charts.table_columns(conn, "metrics")
    with pytest.raises(charts.ChartError) as exc:
        charts.table_columns(conn, "nope")
    # the error carries the real table list instead of a sqlite stack
    assert "metrics" in str(exc.value) and "runs" in str(exc.value)
    conn.close()
    with pytest.raises(charts.ChartError) as exc2:
        charts.read_sqlite_rows(db, table="metrics", columns=["step", "ghost"])
    assert "no column(s) ['ghost']" in str(exc2.value)
    assert "value" in str(exc2.value)  # names what IS available


def test_read_sqlite_rows_supports_where_and_limit(tmp_path):
    db = tmp_path / "runtrack.db"
    _seed_metrics(db)
    rows, src = charts.read_sqlite_rows(
        db, table="metrics", columns=["step", "value"], where="key = 'loss'"
    )
    assert [r["value"] for r in rows] == [2.5, 2.0, 1.5]
    assert src["kind"] == "sqlite" and src["read_only"] is True
    assert src["table"] == "metrics" and src["where"] == "key = 'loss'"
    assert src["label"] == db.as_posix() + "#metrics"
    capped, _ = charts.read_sqlite_rows(db, table="metrics", columns=["step"], limit=2)
    assert len(capped) == 2


def test_read_sqlite_rows_turns_a_bad_predicate_into_an_actionable_error(tmp_path):
    db = tmp_path / "runtrack.db"
    _seed_metrics(db)
    with pytest.raises(charts.ChartError) as exc:
        charts.read_sqlite_rows(
            db, table="metrics", columns=["step"], where="ghost = 1"
        )
    assert "query failed" in str(exc.value) and "sql was: SELECT" in str(exc.value)


# ---- coercion: a gap is not a zero ------------------------------------------


def test_as_number_is_strict_about_what_counts_as_a_number():
    assert charts.as_number(3) == 3.0
    assert charts.as_number("1.5") == 1.5
    assert charts.as_number("1e3") == 1000.0
    assert charts.as_number(" -2 ") == -2.0
    for junk in (None, "", "   ", "null", "None", "NaN", "-", "na", "abc", "1,5"):
        assert charts.as_number(junk) is None, junk
    # bools are not measurements, and non-finite floats are not plottable
    assert charts.as_number(True) is None and charts.as_number(False) is None
    assert charts.as_number(float("inf")) is None
    assert charts.as_number(float("nan")) is None
    assert charts.as_number("inf") is None


def test_as_time_reuses_the_repo_iso_parser_and_never_reinterprets_numbers():
    # a step counter must stay a step counter, not become milliseconds
    assert charts.as_time(15000000) == 15000000.0
    assert charts.as_time("2026-07-19T00:00:00Z") == 1784419200.0
    assert charts.as_time("2026-07-19 00:00:00") == 1784419200.0
    assert charts.as_time("not a time") is None
    assert charts.as_time(None) is None


# ---- dataset: nothing invented, nothing silently dropped --------------------


def test_dataset_splits_series_and_counts_every_rejection():
    rows = [
        {"step": 0, "v": 1.0, "k": "a"},
        {"step": 1, "v": "2.0", "k": "a"},
        {"step": 2, "v": None, "k": "a"},  # a gap, not a zero
        {"step": "x", "v": 5.0, "k": "b"},  # unusable x
        {"step": 3, "v": 4.0, "k": "b"},
        {"nope": 1},  # missing both columns
    ]
    ds = charts.dataset(rows, kind="line", x="step", y="v", series="k")
    assert ds["rows_read"] == 6 and ds["points"] == 3
    assert ds["skipped"] == {"missing": 1, "bad_x": 1, "bad_y": 1}
    assert [s["label"] for s in ds["series"]] == ["a", "b"]
    assert ds["series"][0]["points"] == [[0.0, 1.0], [1.0, 2.0]]
    assert ds["series"][1]["points"] == [[3.0, 4.0]]
    assert ds["series"][0]["n"] == 2 and ds["series"][1]["n"] == 1
    # the dropped rows are absent, NOT present as zeros
    assert [2.0, 0.0] not in ds["series"][0]["points"]
    assert ds["bounds"] == {"y": [1.0, 4.0], "x": [0.0, 3.0]}
    assert ds["columns"] == {"x": "step", "y": "v", "series": "k"}


def test_dataset_without_a_series_column_labels_the_series_after_y():
    ds = charts.dataset(ROWS, kind="line", x="step", y="loss")
    assert [s["label"] for s in ds["series"]] == ["loss"]
    assert ds["series"][0]["points"] == [[0.0, 2.5], [1.0, 1.75], [2.0, 1.25]]
    assert ds["series"][0]["color"] == charts.PALETTE[0]


def test_dataset_assigns_colours_by_index_so_they_never_move():
    rows = [{"x": i, "y": i, "k": f"s{i}"} for i in range(len(charts.PALETTE) + 2)]
    ds = charts.dataset(rows, kind="scatter", x="x", y="y", series="k")
    colors = [s["color"] for s in ds["series"]]
    assert colors[: len(charts.PALETTE)] == list(charts.PALETTE)
    assert colors[len(charts.PALETTE)] == charts.PALETTE[0]  # cycles, never random


def test_dataset_is_indifferent_to_source_row_order():
    """A sqlite SELECT without ORDER BY is undefined; the dataset must not be."""
    rows = [{"x": 2, "y": 9}, {"x": 0, "y": 1}, {"x": 1, "y": 5}]
    a = charts.dataset(rows, kind="line", x="x", y="y")
    b = charts.dataset(list(reversed(rows)), kind="line", x="x", y="y")
    assert a["series"][0]["points"] == [[0.0, 1.0], [1.0, 5.0], [2.0, 9.0]]
    assert a["series"][0]["points"] == b["series"][0]["points"]
    assert charts.render_svg(a) == charts.render_svg(b)


def test_empty_and_unplottable_sources_produce_no_bounds():
    empty = charts.dataset([], kind="line", x="a", y="b")
    assert empty["rows_read"] == 0 and empty["points"] == 0
    assert empty["bounds"] is None and empty["series"] == []
    text = charts.dataset([{"a": 1, "b": "n/a"}], kind="line", x="a", y="b")
    assert text["rows_read"] == 1 and text["points"] == 0
    assert text["bounds"] is None
    assert text["skipped"]["bad_y"] == 1


def test_dataset_rejects_unknown_kinds_and_sorts():
    with pytest.raises(charts.ChartError, match="kind must be one of"):
        charts.dataset([], kind="pie", x="a", y="b")
    with pytest.raises(charts.ChartError, match="sort must be one of"):
        charts.dataset([], kind="bar", x="a", y="b", sort="random")


# ---- dataset: bar semantics -------------------------------------------------


def test_bar_sums_duplicate_categories_and_reports_the_fold():
    rows = [
        {"src": "trainer", "n": 3},
        {"src": "trainer", "n": 4},
        {"src": "loop", "n": 5},
    ]
    ds = charts.dataset(rows, kind="bar", x="src", y="n")
    assert ds["categories"] == ["loop", "trainer"]
    assert ds["series"][0]["values"] == [5.0, 7.0]
    assert ds["folded"] == 1  # the aggregation is never invisible
    assert "1 duplicate categories summed" in charts.provenance(ds)
    assert [d["rule"] for d in charts.to_diagnostics(ds)] == [
        "charts:folded-categories"
    ]


def test_bar_sort_modes_are_all_deterministic():
    rows = [{"c": "a", "v": 2}, {"c": "b", "v": 9}, {"c": "c", "v": 2}]
    by_label = charts.dataset(rows, kind="bar", x="c", y="v")
    assert by_label["categories"] == ["a", "b", "c"]
    asc = charts.dataset(rows, kind="bar", x="c", y="v", sort=charts.SORT_VALUE)
    assert asc["categories"] == ["a", "c", "b"]  # ties broken by label
    desc = charts.dataset(rows, kind="bar", x="c", y="v", sort=charts.SORT_VALUE_DESC)
    assert desc["categories"] == ["b", "a", "c"]
    assert desc["sort"] == charts.SORT_VALUE_DESC


def test_bar_y_axis_always_reaches_zero_but_line_does_not():
    """A truncated bar axis misstates every ratio on the chart."""
    rows = [{"c": "a", "v": 200}, {"c": "b", "v": 210}]
    bar = charts.dataset(rows, kind="bar", x="c", y="v")
    assert bar["bounds"]["y"] == [0.0, 210.0]
    assert bar["bounds"]["x"] is None  # a categorical axis has no numeric range
    line = charts.dataset(
        [{"c": 1, "v": 200}, {"c": 2, "v": 210}], kind="line", x="c", y="v"
    )
    assert line["bounds"]["y"] == [200.0, 210.0]
    neg = charts.dataset([{"c": "a", "v": -5}], kind="bar", x="c", y="v")
    assert neg["bounds"]["y"] == [-5.0, 0.0]


def test_grouped_bars_keep_one_shared_category_axis():
    rows = [
        {"c": "a", "v": 1, "k": "left"},
        {"c": "b", "v": 2, "k": "left"},
        {"c": "b", "v": 3, "k": "right"},
    ]
    ds = charts.dataset(rows, kind="bar", x="c", y="v", series="k")
    assert ds["categories"] == ["a", "b"]
    assert [s["label"] for s in ds["series"]] == ["left", "right"]
    assert ds["series"][0]["values"] == [1.0, 2.0]
    # "right" has no bar in category a — a hole, not a zero
    assert ds["series"][1]["values"] == [None, 3.0]
    assert ds["series"][1]["n"] == 1
    svg = charts.render_svg(ds)
    # background + frame + 3 bars + 2 legend swatches (two series)
    assert len(_tags(svg, "rect")) == 2 + 3 + 2


# ---- read_dataset: exactly one input ----------------------------------------


def test_read_dataset_requires_exactly_one_input(tmp_path):
    p = _csv(tmp_path, "a,b\n1,2\n")
    with pytest.raises(charts.ChartError, match="name exactly one input"):
        charts.read_dataset(kind="line", x="a", y="b")
    with pytest.raises(charts.ChartError, match="name exactly one input"):
        charts.read_dataset(kind="line", x="a", y="b", csv_path=p, db=p)
    with pytest.raises(charts.ChartError, match="--db needs --table"):
        charts.read_dataset(kind="line", x="a", y="b", db=p)
    ds = charts.read_dataset(kind="line", x="a", y="b", csv_path=p)
    assert ds["points"] == 1 and ds["source"]["kind"] == "csv"


def test_read_dataset_over_a_real_runtrack_ledger(tmp_path):
    """The documented integration: chart the local W&B replacement's own store."""
    db = tmp_path / "runtrack.db"
    _seed_metrics(db)
    ds = charts.read_dataset(
        kind="line", x="step", y="value", series="key", db=db, table="metrics"
    )
    assert ds["rows_read"] == 6 and ds["points"] == 6
    assert [s["label"] for s in ds["series"]] == ["loss", "lr"]
    assert ds["series"][0]["points"] == [[0.0, 2.5], [1.0, 2.0], [2.0, 1.5]]
    assert ds["source"]["label"].endswith("#metrics")
    assert ds["source"]["read_only"] is True
    assert f"{db.as_posix()}#metrics" in charts.provenance(ds)
    assert "6 rows read" in charts.provenance(ds)


def test_read_dataset_deduplicates_requested_columns(tmp_path):
    """--x and --y on the same column must not send SELECT a duplicate."""
    db = tmp_path / "runtrack.db"
    _seed_metrics(db)
    ds = charts.read_dataset(
        kind="scatter", x="value", y="value", db=db, table="metrics"
    )
    assert ds["points"] == 6


# ---- scales -----------------------------------------------------------------


def test_nice_axis_pads_to_round_ticks():
    ax = charts.nice_axis(0.0, 9.4)
    assert ax["lo"] == 0.0 and ax["hi"] >= 9.4
    assert ax["ticks"][0] == ax["lo"] and ax["ticks"][-1] == ax["hi"]
    assert len(ax["ticks"]) >= 3
    # tick values are clean, not 0.30000000000000004
    assert all(t == round(t, 12) for t in ax["ticks"])
    assert charts.nice_axis(1.0, 5.0)["step"] in (1.0, 2.0, 2.5)


def test_nice_axis_survives_flat_and_degenerate_ranges():
    flat = charts.nice_axis(5.0, 5.0)
    assert flat["lo"] < 5.0 < flat["hi"]
    zero = charts.nice_axis(0.0, 0.0)
    assert zero["lo"] < zero["hi"]
    swapped = charts.nice_axis(9.0, 1.0)
    assert swapped["lo"] <= 1.0 and swapped["hi"] >= 9.0
    nonfinite = charts.nice_axis(float("nan"), float("inf"))
    assert nonfinite["lo"] == 0.0 and nonfinite["hi"] >= 1.0
    # a pathological range must not emit thousands of gridlines
    assert len(charts.nice_axis(0.0, 1e12, count=5)["ticks"]) <= charts.MAX_TICKS + 1


def test_value_and_time_formatting_are_locale_free():
    assert charts.fmt_value(0) == "0"
    assert charts.fmt_value(1000) == "1000"
    assert charts.fmt_value(0.1 + 0.2) == "0.3"
    assert charts.fmt_value(2500000) == "2.50e+06"
    assert charts.fmt_value(0.00001) == "1.00e-05"
    assert charts.fmt_value(-1.5) == "-1.5"
    # assembled from gmtime fields, so no month name and no TZ can leak in
    assert charts.fmt_time(1784419200.0) == "2026-07-19 00:00"
    assert charts.fmt_time(0) == "1970-01-01 00:00"
    assert charts.fmt_time(1e30) == "1.00e+30"  # unrepresentable -> a number


# ---- rendering: self-contained, well-formed, escaped ------------------------


def test_render_svg_is_well_formed_and_self_contained():
    ds = charts.dataset(ROWS, kind="line", x="step", y="loss")
    svg = charts.render_svg(ds, title="Training loss")
    root = _tree(svg)
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("width") == str(charts.DEFAULT_WIDTH)
    assert root.get("viewBox") == f"0 0 {charts.DEFAULT_WIDTH} {charts.DEFAULT_HEIGHT}"
    assert root.get("role") == "img" and "Training loss" in root.get("aria-label")
    assert "<style>" in svg  # CSS is inline
    for forbidden in (
        "<script",
        "<image",
        "<link",
        "@import",
        "url(",
        "xlink:href",
        "font-face",
        "<use",
        "<foreignObject",
    ):
        assert forbidden not in svg, forbidden
    # the ONLY URL in the whole file is the SVG namespace declaration itself
    assert svg.count("http") == 1
    assert svg.count('xmlns="http://www.w3.org/2000/svg"') == 1
    assert "Training loss" in svg
    assert len(_tags(svg, "polyline")) == 1


def test_render_svg_escapes_hostile_labels_and_titles():
    rows = [
        {"c": "<script>alert(1)</script>", "v": 1},
        {
            "c": "b",
            "v": 2,
        },
    ]
    ds = charts.dataset(rows, kind="bar", x="c", y="v", series="c")
    svg = charts.render_svg(ds, title='"><script>x</script>')
    assert "<script" not in svg
    assert "&lt;script&gt;" in svg
    _tree(svg)  # still parses: escaping did not corrupt the document
    # a control character in a label must not produce an unloadable file
    ctrl = charts.dataset([{"c": "a\x00b", "v": 1}], kind="bar", x="c", y="v")
    _tree(charts.render_svg(ctrl))
    assert "\x00" not in charts.render_svg(ctrl)


def test_render_svg_carries_the_provenance_footer(tmp_path):
    db = tmp_path / "runtrack.db"
    _seed_metrics(db)
    ds = charts.read_dataset(
        kind="line",
        x="step",
        y="value",
        series="key",
        db=db,
        table="metrics",
        where="key = 'loss'",
    )
    svg = charts.render_svg(ds, title="loss")
    assert "runtrack.db#metrics" in svg  # the source table, named
    assert "3 rows read" in svg and "3 points" in svg  # the row count
    assert "x=step" in svg and "y=value" in svg and "series=key" in svg
    # the predicate is echoed, escaped: the footer states the filter behind the
    # numbers, so a chart of a SUBSET can never be mistaken for the whole table
    assert "where=key = &#x27;loss&#x27;" in svg
    assert "(sqlite)" in svg
    assert "no generation timestamp" in svg
    assert "openswap #16" in svg


def test_render_svg_states_skipped_rows_in_the_footer():
    rows = [{"x": 0, "y": 1}, {"x": 1, "y": "missing"}]
    ds = charts.dataset(rows, kind="line", x="x", y="y")
    svg = charts.render_svg(ds)
    assert "2 rows read" in svg and "1 points" in svg
    assert "1 rows skipped (not plottable)" in svg


# ---- rendering: determinism is the product ----------------------------------


def test_two_renders_are_byte_identical_and_share_a_fingerprint():
    ds = charts.dataset(ROWS, kind="line", x="step", y="loss")
    first = charts.render_svg(ds, title="loss")
    second = charts.render_svg(
        charts.dataset(ROWS, kind="line", x="step", y="loss"), title="loss"
    )
    assert first == second
    assert charts.fingerprint(first) == charts.fingerprint(second)
    assert len(charts.fingerprint(first)) == 64
    # a changed datapoint MUST change the digest, or the fingerprint is theatre
    moved = charts.dataset(
        [{"step": 0, "loss": 2.5}, {"step": 1, "loss": 1.75}, {"step": 2, "loss": 9}],
        kind="line",
        x="step",
        y="loss",
    )
    assert charts.fingerprint(
        charts.render_svg(moved, title="loss")
    ) != charts.fingerprint(first)


def test_no_generation_timestamp_leaks_into_a_non_time_chart():
    ds = charts.dataset(ROWS, kind="line", x="step", y="loss")
    svg = charts.render_svg(ds, title="loss")
    assert re.search(r"\d{4}-\d{2}-\d{2}", svg) is None
    assert "generated" not in svg.lower().replace("no generation timestamp", "")


def test_coordinates_never_carry_float_drift():
    rows = [{"x": i, "y": 0.1 * i} for i in range(7)]
    svg = charts.render_svg(charts.dataset(rows, kind="line", x="x", y="y"))
    assert "0000000000" not in svg  # no 0.30000000000000004 in the markup
    pts = _tags(svg, "polyline")[0].get("points").split()
    for pair in pts:
        for coord in pair.split(","):
            assert len(coord.split(".")[-1]) <= 2 or "." not in coord


def test_time_axis_labels_are_utc_and_only_appear_with_time_x():
    rows = [
        {"ts": "2026-07-19T00:00:00Z", "v": 1},
        {"ts": "2026-07-19T06:00:00Z", "v": 2},
    ]
    timed = charts.dataset(rows, kind="line", x="ts", y="v", time_x=True)
    assert timed["time_x"] is True and timed["points"] == 2
    assert timed["series"][0]["points"][0][0] == 1784419200.0
    svg = charts.render_svg(timed)
    assert re.search(r"2026-07-19 \d{2}:\d{2}", svg) is not None
    # without --time-x the same strings are simply not numbers, and are counted
    untimed = charts.dataset(rows, kind="line", x="ts", y="v")
    assert untimed["points"] == 0 and untimed["skipped"]["bad_x"] == 2
    assert untimed["time_x"] is False


# ---- rendering: the anti-fabrication contract -------------------------------


def test_an_empty_dataset_renders_no_axis_numbers_at_all():
    svg = charts.render_svg(charts.dataset([], kind="line", x="step", y="loss"))
    assert "no data to plot" in svg and "0 row(s) read" in svg
    assert _tags(svg, "polyline") == [] and _tags(svg, "circle") == []
    assert _tags(svg, "line") == []  # no gridlines implying a range
    texts = [t.text or "" for t in _tags(svg, "text")]
    assert not any(re.fullmatch(r"-?\d+(\.\d+)?", t) for t in texts)
    assert "0 rows read" in svg  # the footer still states provenance
    _tree(svg)


def test_rows_that_are_not_numbers_render_an_empty_panel_not_a_flat_line():
    ds = charts.dataset(
        [{"x": 0, "y": "n/a"}, {"x": 1, "y": ""}], kind="line", x="x", y="y"
    )
    svg = charts.render_svg(ds)
    assert "no data to plot" in svg and "2 row(s) read" in svg
    assert _tags(svg, "polyline") == []
    assert "2 rows skipped" in svg
    codes = [d["rule"] for d in charts.to_diagnostics(ds)]
    assert codes == ["charts:nothing-plottable"]


def test_a_single_point_series_renders_a_visible_dot():
    """A one-point polyline is invisible; silently drawing nothing is a lie."""
    ds = charts.dataset([{"x": 1, "y": 2}], kind="line", x="x", y="y")
    svg = charts.render_svg(ds)
    assert _tags(svg, "polyline") == []
    assert len(_tags(svg, "circle")) == 1


# ---- rendering: per-kind marks ----------------------------------------------


def test_each_kind_emits_its_own_marks_and_nothing_elses():
    rows = [{"x": 0, "y": 1}, {"x": 1, "y": 2}, {"x": 2, "y": 3}]
    line = charts.render_svg(charts.dataset(rows, kind="line", x="x", y="y"))
    assert len(_tags(line, "polyline")) == 1 and _tags(line, "circle") == []
    scatter = charts.render_svg(charts.dataset(rows, kind="scatter", x="x", y="y"))
    assert _tags(scatter, "polyline") == [] and len(_tags(scatter, "circle")) == 3
    bar = charts.render_svg(charts.dataset(rows, kind="bar", x="x", y="y"))
    assert _tags(bar, "polyline") == [] and _tags(bar, "circle") == []
    assert len(_tags(bar, "rect")) == 3 + 2  # background + frame + 3 bars
    # every bar names its category and value for a screen reader / tooltip
    titles = sorted((t.text or "") for t in _tags(bar, "title"))
    assert titles == ["0 = 1", "1 = 2", "2 = 3"]


def test_a_legend_appears_only_when_there_is_more_than_one_series():
    one = charts.render_svg(charts.dataset(ROWS, kind="line", x="step", y="loss"))
    assert "loss" in one
    rows = [{"x": 0, "y": 1, "k": "alpha"}, {"x": 1, "y": 2, "k": "omega"}]
    two = charts.render_svg(charts.dataset(rows, kind="line", x="x", y="y", series="k"))
    assert "alpha" in two and "omega" in two
    # the legend swatches are extra rects beyond background + frame
    assert len(_tags(two, "rect")) == 2 + 2
    assert len(_tags(one, "rect")) == 2


def test_render_svg_validates_its_canvas():
    ds = charts.dataset(ROWS, kind="line", x="step", y="loss")
    with pytest.raises(charts.ChartError, match="--width must be"):
        charts.render_svg(ds, width=10)
    with pytest.raises(charts.ChartError, match="--height must be"):
        charts.render_svg(ds, height=9999999)
    small = charts.render_svg(ds, width=charts.MIN_WIDTH, height=charts.MIN_HEIGHT)
    _tree(small)
    assert _tree(small).get("height") == str(charts.MIN_HEIGHT)


# ---- family diagnostics ------------------------------------------------------


def test_to_diagnostics_normalize_into_the_family_schema():
    empty = charts.to_diagnostics(charts.dataset([], kind="line", x="a", y="b"))
    assert [d["rule"] for d in empty] == ["charts:no-rows"]
    assert empty[0]["severity"] == "warning" and empty[0]["source"] == "charts"
    assert set(empty[0]) == {
        "path",
        "line",
        "col",
        "rule",
        "severity",
        "message",
        "suggestion",
        "source",
    }
    assert openswap.summarize(empty)["by_severity"]["warning"] == 1
    partial = charts.dataset(
        [{"x": 0, "y": 1}, {"x": 1, "y": "?"}], kind="line", x="x", y="y"
    )
    diags = charts.to_diagnostics(partial)
    assert [d["rule"] for d in diags] == ["charts:skipped-rows"]
    assert diags[0]["severity"] == "info"
    assert "never coerced to 0" in diags[0]["message"]
    clean = charts.to_diagnostics(charts.dataset(ROWS, kind="line", x="step", y="loss"))
    assert clean == []  # a healthy chart raises nothing


def test_diagnostics_name_the_source_they_are_about(tmp_path):
    p = _csv(tmp_path, "a,b\n", name="gone-quiet.csv")
    ds = charts.read_dataset(kind="line", x="a", y="b", csv_path=p)
    diags = charts.to_diagnostics(ds)
    assert diags[0]["path"] == p.as_posix()
    assert diags[0]["rule"] == "charts:no-rows"
    assert "empty, not flat" in diags[0]["message"]


# ---- detection ---------------------------------------------------------------


def test_detection_fallback_is_the_expected_steady_state(monkeypatch):
    from bigbang.plugins.charts import cli as charts_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = charts_cli._capability()
    assert cap["adapter"] == "charts"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "byte-identical" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "tableau"
    assert cap["extras"]["gnuplot"]["found"] is False
    assert cap["extras"]["grafana"]["found"] is False
    assert "install_hint" in cap


def test_manifest_denies_the_network_axis():
    from bigbang.core.policy import check_permission, load_manifest

    mf = load_manifest(ROOT / "bigbang" / "plugins" / "charts")
    assert mf["name"] == "charts"
    assert mf["capabilities"]["network"]["enabled"] is False
    assert mf["capabilities"]["network"]["domains"] == []
    assert mf["capabilities"]["secrets"]["allow"] == []
    allowed, reason = check_permission(mf, "network", "http://127.0.0.1:3000/api")
    assert allowed is False and "network disabled" in reason
    # the one capability it does need
    assert check_permission(mf, "fs_write", ".scout/chart.svg")[0] is True


def test_plugin_is_discoverable():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "charts" in list_plugin_names()


# ---- the real CLI in a subprocess -------------------------------------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        cwd=str(cwd or ROOT),
    )


def test_cli_hello_and_kinds_envelopes():
    r = _cli(["charts", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert data["data"]["kinds"] == ["line", "bar", "scatter"]
    r = _cli(["charts", "kinds"])
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)["data"]
    assert set(payload["kinds"]) == {"line", "bar", "scatter"}
    assert payload["sorts"] == ["label", "value", "-value"]
    assert "byte-identical" in payload["determinism"]
    assert "never read as 0" in payload["honesty"]


def test_cli_inspect_reports_provenance_without_writing_a_file(tmp_path):
    p = _csv(tmp_path, "step,loss\n0,2.5\n1,1.75\n2,skipped\n")
    r = _cli(["charts", "inspect", "--csv", str(p), "--x", "step", "--y", "loss"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["wrote_file"] is False
    assert data["rows_read"] == 3 and data["points"] == 2
    assert data["skipped"]["bad_y"] == 1
    assert data["series"][0]["head"] == [[0.0, 2.5], [1.0, 1.75]]
    assert data["source"]["kind"] == "csv"
    assert "2 points" in data["provenance"]
    assert [d["rule"] for d in data["diagnostics"]] == ["charts:skipped-rows"]
    assert list(tmp_path.glob("*.svg")) == []  # inspect writes nothing


def test_cli_line_writes_a_deterministic_svg(tmp_path):
    p = _csv(tmp_path, "step,loss\n0,2.5\n1,1.75\n2,1.25\n")
    out = tmp_path / "charts" / "loss.svg"
    args = [
        "charts",
        "line",
        "--csv",
        str(p),
        "--x",
        "step",
        "--y",
        "loss",
        "--out",
        str(out),
        "--title",
        "Training loss",
    ]
    r = _cli(args)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["out"] == str(out) and data["bytes"] > 0
    assert data["kind"] == "line" and data["points"] == 3
    assert data["deterministic"] is True
    raw = out.read_bytes()
    svg = raw.decode("utf-8")
    # the reported size is the FILE's size, not a character count
    assert len(raw) == data["bytes"] > len(svg)
    # LF on every platform: CRLF translation would make the same chart a
    # different file on Windows than on Linux, and the sha256 a lie
    assert b"\r\n" not in raw
    assert charts.fingerprint(svg) == data["sha256"]
    assert "<h1" not in svg and "<script" not in svg
    assert "Training loss" in svg and "3 rows read" in svg
    ET.fromstring(svg)  # noqa: S314 - our own output; parsing it is the assertion
    # a second process must produce the same bytes — this is the whole premise
    first = out.read_bytes()
    r2 = _cli(args)
    assert r2.returncode == 0, r2.stderr + r2.stdout
    assert out.read_bytes() == first
    assert json.loads(r2.stdout)["data"]["sha256"] == data["sha256"]


def test_cli_bar_and_scatter_over_the_same_source(tmp_path):
    p = _csv(tmp_path, "src,n\ntrainer,3\ntrainer,4\nloop,5\n")
    bar = tmp_path / "bar.svg"
    r = _cli(
        [
            "charts",
            "bar",
            "--csv",
            str(p),
            "--x",
            "src",
            "--y",
            "n",
            "--sort",
            "-value",
            "--out",
            str(bar),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["categories"] == ["trainer", "loop"]
    assert data["folded"] == 1
    assert "duplicate categories summed" in data["provenance"]
    assert "trainer" in bar.read_text(encoding="utf-8")

    sc = tmp_path / "scatter.svg"
    r = _cli(
        ["charts", "scatter", "--csv", str(p), "--x", "n", "--y", "n", "--out", str(sc)]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["data"]["points"] == 3
    svg = sc.read_text(encoding="utf-8")
    assert "<circle" in svg and "<polyline" not in svg


def test_cli_charts_a_real_ledger_read_only(tmp_path):
    db = tmp_path / "runtrack.db"
    _seed_metrics(db)
    before = db.read_bytes()
    out = tmp_path / "loss.svg"
    r = _cli(
        [
            "charts",
            "line",
            "--db",
            str(db),
            "--table",
            "metrics",
            "--x",
            "step",
            "--y",
            "value",
            "--series",
            "key",
            "--where",
            "key = 'loss'",
            "--out",
            str(out),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["source"]["read_only"] is True
    assert data["source"]["table"] == "metrics"
    assert data["rows_read"] == 3 and data["points"] == 3
    assert [s["label"] for s in data["series"]] == ["loss"]
    assert "#metrics" in data["provenance"]
    # charting a ledger must not touch it
    assert db.read_bytes() == before
    assert "3 rows read" in out.read_text(encoding="utf-8")


def test_cli_json_records_path_charts_this_cli_own_envelope(tmp_path):
    doc = {
        "ok": True,
        "data": {"history": [{"step": 0, "value": 1.0}, {"step": 1, "value": 0.5}]},
    }
    p = _json(tmp_path, doc, name="run.json")
    out = tmp_path / "run.svg"
    r = _cli(
        [
            "charts",
            "line",
            "--json-file",
            str(p),
            "--records",
            "data.history",
            "--x",
            "step",
            "--y",
            "value",
            "--out",
            str(out),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["points"] == 2
    assert data["source"]["label"].endswith("#data.history")
    assert out.exists()


def test_cli_gate_fires_when_a_panel_goes_empty(tmp_path):
    p = _csv(tmp_path, "step,loss\n", name="silent.csv")
    out = tmp_path / "empty.svg"
    r = _cli(
        [
            "charts",
            "line",
            "--csv",
            str(p),
            "--x",
            "step",
            "--y",
            "loss",
            "--out",
            str(out),
            "--fail-on",
            "warning",
        ]
    )
    # the file is still written (the empty state is the honest report) but the
    # gate fires, so cron notices the dashboard went blind
    assert r.returncode == 1
    data = json.loads(r.stdout)["data"]
    assert data["rows_read"] == 0 and data["points"] == 0
    assert data["summary"]["by_severity"]["warning"] == 1
    svg = out.read_text(encoding="utf-8")
    assert "no data to plot" in svg
    assert re.search(r"\d{4}-\d{2}-\d{2}", svg) is None
    # ...and the same chart without the gate exits 0
    r2 = _cli(
        [
            "charts",
            "line",
            "--csv",
            str(p),
            "--x",
            "step",
            "--y",
            "loss",
            "--out",
            str(out),
        ]
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout


def test_cli_gate_ignores_info_only_findings(tmp_path):
    p = _csv(tmp_path, "step,loss\n0,1\n1,skip\n")
    out = tmp_path / "part.svg"
    r = _cli(
        [
            "charts",
            "line",
            "--csv",
            str(p),
            "--x",
            "step",
            "--y",
            "loss",
            "--out",
            str(out),
            "--fail-on",
            "warning",
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["summary"]["by_severity"]["info"] == 1
    assert data["summary"]["by_severity"]["warning"] == 0
    r2 = _cli(
        [
            "charts",
            "line",
            "--csv",
            str(p),
            "--x",
            "step",
            "--y",
            "loss",
            "--out",
            str(out),
            "--fail-on",
            "info",
        ]
    )
    assert r2.returncode == 1


def test_cli_rejects_bad_inputs_with_actionable_errors(tmp_path):
    p = _csv(tmp_path, "step,loss\n0,1\n")
    r = _cli(["charts", "line", "--x", "step", "--y", "loss"])
    assert r.returncode == 1
    assert "name exactly one input" in json.loads(r.stdout)["error"]
    r = _cli(["charts", "line", "--csv", str(p), "--x", "ghost", "--y", "loss"])
    assert r.returncode == 0  # a CSV has no schema to validate against...
    assert json.loads(r.stdout)["data"]["skipped"]["missing"] == 1  # ...it is counted

    db = tmp_path / "runtrack.db"
    _seed_metrics(db)
    r = _cli(
        [
            "charts",
            "line",
            "--db",
            str(db),
            "--table",
            "metrics",
            "--x",
            "step",
            "--y",
            "ghost",
        ]
    )
    assert r.returncode == 1
    err = json.loads(r.stdout)["error"]
    assert "no column(s) ['ghost']" in err and "value" in err
    r = _cli(
        [
            "charts",
            "line",
            "--db",
            str(db),
            "--table",
            "nope",
            "--x",
            "step",
            "--y",
            "value",
        ]
    )
    assert r.returncode == 1
    assert "no table or view 'nope'" in json.loads(r.stdout)["error"]
    r = _cli(["charts", "line", "--db", str(db), "--x", "step", "--y", "value"])
    assert r.returncode == 1
    assert "--db needs --table" in json.loads(r.stdout)["error"]
    r = _cli(
        [
            "charts",
            "line",
            "--csv",
            str(p),
            "--x",
            "step",
            "--y",
            "loss",
            "--fail-on",
            "loud",
        ]
    )
    assert r.returncode == 1
    assert "--fail-on must be one of" in json.loads(r.stdout)["error"]
    r = _cli(
        [
            "charts",
            "line",
            "--csv",
            str(p),
            "--x",
            "step",
            "--y",
            "loss",
            "--width",
            "12",
        ]
    )
    assert r.returncode == 1
    assert "--width must be" in json.loads(r.stdout)["error"]
