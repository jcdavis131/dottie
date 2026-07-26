"""Coverage — openswap #31 (Codecov -> stdlib Cobertura/sqlite parsing + a static
HTML report with per-module deltas). Pure-logic core tests: path normalization,
the pct-XOR-reason honesty invariant on every construction path, numbits/arc
decoding against hand-built coverage.py data files, the Cobertura parser
(including every refusal), set-arithmetic merging, sum-based rollups, deltas
with an absent or unknown baseline, the store's CHECK constraint, the rendered
page's refusal to draw a zero bar for an unknown module, and the real CLI in a
subprocess. Offline and deterministic by construction: every fixture is built
here, no network is opened on any path, and no clock is read by the core."""

from __future__ import annotations

import ast
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import coverage, openswap

ROOT = Path(__file__).resolve().parents[1]

# A real coverage.py 7.x export, trimmed: one empty file (<lines/>), one file with
# a missed branch, one partially covered branch. The numbers here are the ones
# coverage.py itself printed for this tree (calc 62.5%, helpers 80%, total 69.23%).
COBERTURA = """<?xml version="1.0" ?>
<coverage version="7.15.2" timestamp="1784960460652" lines-valid="13" lines-covered="9"
 line-rate="0.6923" branches-valid="4" branches-covered="1" branch-rate="0.25">
  <sources><source>/repo/root</source></sources>
  <packages>
    <package name="pkg" line-rate="0.625">
      <classes>
        <class name="__init__.py" filename="pkg/__init__.py" line-rate="1"><lines/></class>
        <class name="calc.py" filename="pkg/calc.py" line-rate="0.625">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
            <line number="5" hits="1"/>
            <line number="6" hits="1"/>
            <line number="9" hits="1"/>
            <line number="10" hits="0" branch="true" condition-coverage="0% (0/2)"/>
            <line number="11" hits="0"/>
            <line number="12" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
    <package name="util" line-rate="0.8">
      <classes>
        <class name="helpers.py" filename="util/helpers.py" line-rate="0.8">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
            <line number="3" hits="1" branch="true" condition-coverage="50% (1/2)"/>
            <line number="4" hits="0"/>
            <line number="5" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


def _xml(classes: str, *, attrs: str = "") -> str:
    return (
        f'<?xml version="1.0" ?>\n<coverage {attrs}>'
        f'<packages><package name="p"><classes>{classes}</classes></package></packages>'
        "</coverage>"
    )


def _cls(filename: str, lines: str) -> str:
    return f'<class name="c" filename="{filename}"><lines>{lines}</lines></class>'


def _line(number: int, hits: int, *, branch: str = "") -> str:
    return f'<line number="{number}" hits="{hits}"{branch}/>'


def _data_file(
    path: Path,
    *,
    files: tuple[str, ...],
    line_bits: tuple[tuple[int, int, tuple[int, ...]], ...] = (),
    arcs: tuple[tuple[int, int, int, int], ...] = (),
    contexts: tuple[str, ...] = ("",),
    schema: int | None = 7,
    has_arcs: bool = False,
    drop_tables: tuple[str, ...] = (),
) -> Path:
    """Build a coverage.py data file by hand — no coverage.py import anywhere.

    Indices in `line_bits`/`arcs` are 1-based into `files` / `contexts`, exactly
    as the real schema's foreign keys are.
    """
    conn = sqlite3.connect(str(path))
    ddl = {
        "coverage_schema": "CREATE TABLE coverage_schema (version integer)",
        "meta": "CREATE TABLE meta (key text, value text, unique (key))",
        "file": "CREATE TABLE file (id integer primary key, path text, unique(path))",
        "context": "CREATE TABLE context (id integer primary key, context text, unique(context))",
        "line_bits": "CREATE TABLE line_bits (file_id integer, context_id integer, numbits blob)",
        "arc": "CREATE TABLE arc (file_id integer, context_id integer, fromno integer, tono integer)",
    }
    for name, statement in ddl.items():
        if name not in drop_tables:
            conn.execute(statement)
    if schema is not None and "coverage_schema" not in drop_tables:
        conn.execute("INSERT INTO coverage_schema(version) VALUES(?)", (schema,))
    if "meta" not in drop_tables:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('has_arcs', ?)",
            ("1" if has_arcs else "0"),
        )
    for i, f in enumerate(files, start=1):
        conn.execute("INSERT INTO file(id, path) VALUES(?, ?)", (i, f))
    if "context" not in drop_tables:
        for i, c in enumerate(contexts, start=1):
            conn.execute("INSERT INTO context(id, context) VALUES(?, ?)", (i, c))
    for file_id, ctx_id, nums in line_bits:
        conn.execute(
            "INSERT INTO line_bits(file_id, context_id, numbits) VALUES(?, ?, ?)",
            (file_id, ctx_id, coverage.lines_to_numbits(list(nums))),
        )
    for file_id, ctx_id, fromno, tono in arcs:
        conn.execute(
            "INSERT INTO arc(file_id, context_id, fromno, tono) VALUES(?, ?, ?, ?)",
            (file_id, ctx_id, fromno, tono),
        )
    conn.commit()
    conn.close()
    return path


# ---- paths ------------------------------------------------------------------


def test_normalize_path_folds_windows_separators_and_noise():
    assert coverage.normalize_path("pkg\\core\\logs.py") == "pkg/core/logs.py"
    assert coverage.normalize_path("./pkg//core/logs.py") == "pkg/core/logs.py"
    assert coverage.normalize_path("  ././a.py  ") == "a.py"
    assert coverage.normalize_path("pkg/") == "pkg"
    assert coverage.normalize_path("") == ""
    assert coverage.normalize_path(None) == ""


def test_strip_prefix_takes_the_longest_match_and_ignores_case():
    prefixes = ("/repo", "/repo/src")
    assert coverage.strip_prefix("/repo/src/a.py", prefixes) == "a.py"
    assert coverage.strip_prefix("/repo/other/a.py", prefixes) == "other/a.py"
    # drive-letter case is the real-world Windows mismatch this exists for
    assert coverage.strip_prefix("c:\\Repo\\A.py", ("C:/repo",)) == "A.py"
    assert coverage.strip_prefix("/elsewhere/a.py", prefixes) == "/elsewhere/a.py"
    assert coverage.strip_prefix("/repo/a.py", ("",)) == "/repo/a.py"
    # a prefix must end at a separator: /repository is not inside /repo
    assert coverage.strip_prefix("/repository/a.py", ("/repo",)) == "/repository/a.py"


def test_module_of_keeps_depth_directories_only():
    assert coverage.module_of("bigbang/core/logs.py", 1) == "bigbang"
    assert coverage.module_of("bigbang/core/logs.py", 2) == "bigbang/core"
    assert coverage.module_of("bigbang/core/logs.py", 9) == "bigbang/core"
    assert coverage.module_of("setup.py", 2) == coverage.ROOT_MODULE
    assert coverage.module_of("a\\b\\c\\d.py", 2) == "a/b"
    with pytest.raises(ValueError, match="depth"):
        coverage.module_of("a/b.py", 0)


# ---- the pct-XOR-reason invariant -------------------------------------------


def test_percentage_is_a_number_or_a_named_reason_never_both():
    pct, reason = coverage.percentage(9, 13)
    assert pct == 69.23 and reason is None
    pct, reason = coverage.percentage(0, None)
    assert pct is None and reason == coverage.NO_INVENTORY_REASON
    pct, reason = coverage.percentage(0, 0)
    assert pct is None and reason == coverage.NO_STATEMENTS_REASON
    assert coverage.percentage(1, 3)[0] == 33.33  # 2dp, not 33.333333
    assert coverage.percentage(13, 13)[0] == 100.0


def test_measurement_carries_exactly_one_of_pct_or_reason():
    m = coverage.measurement(path="a/b.py", statements=8, covered=5)
    assert m["pct"] == 62.5 and m["unknown_reason"] is None and m["missing"] == 3
    empty = coverage.measurement(path="a/__init__.py", statements=0, covered=0)
    assert empty["pct"] is None and "divide by zero" in empty["unknown_reason"]
    blind = coverage.measurement(path="a/c.py", statements=None, covered=7)
    assert blind["pct"] is None and blind["covered"] == 7 and blind["missing"] is None
    assert coverage.NO_INVENTORY_REASON == blind["unknown_reason"]


def test_check_measurement_rejects_both_neither_and_impossible_readings():
    with pytest.raises(ValueError, match="EITHER a pct"):
        coverage.check_measurement({"path": "a", "pct": 50.0, "unknown_reason": "hmm"})
    with pytest.raises(ValueError, match="EITHER a pct"):
        coverage.check_measurement({"path": "a", "pct": None, "unknown_reason": None})
    with pytest.raises(ValueError, match="must say why"):
        coverage.check_measurement({"path": "a", "pct": None, "unknown_reason": "  "})
    with pytest.raises(ValueError, match=r"outside 0\.\.100"):
        coverage.check_measurement({"path": "a", "pct": 101.0, "unknown_reason": None})
    with pytest.raises(ValueError, match="exceeds statements"):
        coverage.check_measurement(
            {
                "path": "a",
                "pct": 50.0,
                "unknown_reason": None,
                "statements": 3,
                "covered": 4,
            }
        )
    good = {
        "path": "a",
        "pct": 50.0,
        "unknown_reason": None,
        "statements": 4,
        "covered": 2,
    }
    assert coverage.check_measurement(good) is good


def test_branch_reading_is_unknown_when_the_report_has_no_branch_data():
    plain = coverage.measurement(path="a.py", statements=4, covered=4)
    assert plain["branch_pct"] is None and plain["branch_unknown_reason"]
    branched = coverage.measurement(
        path="a.py", statements=4, covered=4, branches=2, branches_covered=1
    )
    assert branched["branch_pct"] == 50.0 and branched["branch_unknown_reason"] is None


# ---- numbits ----------------------------------------------------------------


def test_numbits_decodes_coverage_pys_own_bitmap():
    # byte 0 bits 1 and 2 -> lines 1 and 2; byte 1 bit 0 -> line 8
    assert coverage.numbits_to_lines(bytes([0b00000110, 0b00000001])) == [1, 2, 8]
    assert coverage.numbits_to_lines(bytes([0b00000001])) == []  # bit 0 is line 0
    assert coverage.numbits_to_lines(b"") == []
    assert coverage.numbits_to_lines(None) == []
    assert coverage.numbits_to_lines(memoryview(bytes([0b00001000]))) == [3]


def test_numbits_round_trips_through_the_encoder():
    nums = [1, 2, 3, 7, 8, 9, 64, 65, 300]
    assert coverage.numbits_to_lines(coverage.lines_to_numbits(nums)) == nums
    assert coverage.lines_to_numbits([]) == b""
    assert coverage.lines_to_numbits([0, -4]) == b""  # line 0 is not a line
    assert len(coverage.lines_to_numbits([300])) == 38  # 300 // 8 + 1


# ---- Cobertura --------------------------------------------------------------


def test_parse_cobertura_reads_lines_branches_and_sources():
    p = coverage.parse_cobertura(COBERTURA, label="coverage.xml")
    assert p["format"] == coverage.FORMAT_COBERTURA and p["classes"] == 3
    assert p["sources"] == ["/repo/root"]
    assert p["declared"]["lines_valid"] == 13 and p["declared"]["version"] == "7.15.2"
    calc = p["files"]["pkg/calc.py"]
    assert len(calc["statements"]) == 8 and len(calc["hits"]) == 5
    assert 10 not in calc["hits"] and 9 in calc["hits"]
    assert calc["branches"] == 2 and calc["branches_covered"] == 0
    assert p["files"]["util/helpers.py"]["branches_covered"] == 1
    assert p["files"]["pkg/__init__.py"]["statements"] == set()


def test_parse_cobertura_refuses_a_doctype_before_parsing():
    bomb = '<!DOCTYPE coverage [<!ENTITY a "aa">]>' + _xml(_cls("a.py", _line(1, 1)))
    with pytest.raises(coverage.CoverageError, match="DOCTYPE"):
        coverage.parse_cobertura(bomb)


def test_parse_cobertura_refuses_jacoco_and_other_roots_by_name():
    with pytest.raises(coverage.CoverageError, match="JaCoCo"):
        coverage.parse_cobertura('<report name="x"><counter covered="1"/></report>')
    with pytest.raises(coverage.CoverageError, match="expected <coverage>"):
        coverage.parse_cobertura("<testsuites><testsuite/></testsuites>")


def test_parse_cobertura_refuses_junk_instead_of_measuring_nothing():
    with pytest.raises(coverage.CoverageError, match="empty document"):
        coverage.parse_cobertura("   ")
    with pytest.raises(coverage.CoverageError, match="not well-formed"):
        coverage.parse_cobertura("<coverage><packages>")
    with pytest.raises(coverage.CoverageError, match="not well-formed"):
        coverage.parse_cobertura(b"\x00\x01binary")


def test_parse_cobertura_merges_a_file_listed_twice_without_double_counting():
    doc = _xml(
        _cls("a.py", _line(1, 1) + _line(2, 0))
        + _cls("a.py", _line(2, 3) + _line(3, 0))
    )
    p = coverage.parse_cobertura(doc)
    rec = p["files"]["a.py"]
    assert rec["statements"] == {1, 2, 3}  # not 4 entries, and not summed
    assert rec["hits"] == {1, 2}  # line 2 was hit in the second copy
    assert p["classes"] == 2  # both classes were read


def test_parse_cobertura_notes_what_it_could_not_attribute():
    doc = _xml('<class name="c"><lines>' + _line(1, 1) + "</lines></class>")
    p = coverage.parse_cobertura(doc)
    assert p["files"] == {} and any("no filename" in n for n in p["notes"])
    assert any("measures nothing" in n for n in p["notes"])


def test_parse_cobertura_leaves_undeclared_branches_out_and_says_so():
    doc = _xml(_cls("a.py", _line(1, 1, branch=' branch="true"')))
    p = coverage.parse_cobertura(doc)
    assert p["files"]["a.py"]["branches"] == 0
    assert any("no condition-coverage" in n for n in p["notes"])
    m = coverage.combine([p])["files"][0]
    assert m["branch_pct"] is None and m["branch_unknown_reason"]


def test_parse_cobertura_ignores_bad_line_numbers_and_hits():
    doc = _xml(
        _cls(
            "a.py",
            '<line number="0" hits="1"/><line number="x" hits="1"/>'
            '<line number="4" hits="nope"/><line number="5" hits="2"/>',
        )
    )
    rec = coverage.parse_cobertura(doc)["files"]["a.py"]
    assert rec["statements"] == {4, 5}  # 0 and "x" are not line numbers
    assert rec["hits"] == {5}  # an unparsable hit count is not a hit


def test_parse_cobertura_survives_a_namespaced_document():
    doc = (
        '<c:coverage xmlns:c="urn:x" lines-valid="1" lines-covered="1"><c:packages>'
        '<c:package name="p"><c:classes><c:class filename="a.py"><c:lines>'
        '<c:line number="1" hits="1"/></c:lines></c:class></c:classes></c:package>'
        "</c:packages></c:coverage>"
    )
    p = coverage.parse_cobertura(doc)
    assert p["files"]["a.py"]["hits"] == {1}


def test_declared_totals_are_reported_not_trusted():
    agree = coverage.declared_vs_counted(coverage.parse_cobertura(COBERTURA))
    assert agree["counted_statements"] == 13 and agree["counted_covered"] == 9
    assert agree["agrees"] is True and agree["note"] is None
    lying = coverage.parse_cobertura(
        _xml(_cls("a.py", _line(1, 1)), attrs='lines-valid="99" lines-covered="98"')
    )
    check = coverage.declared_vs_counted(lying)
    assert check["agrees"] is False and "disagree" in check["note"]
    # the measurement uses the counted lines, never the declared ones
    assert coverage.combine([lying])["totals"]["statements"] == 1
    silent = coverage.declared_vs_counted(
        coverage.parse_cobertura(_xml(_cls("a.py", "")))
    )
    assert silent["agrees"] is None and "declares no" in silent["note"]


# ---- coverage.py data files -------------------------------------------------


def test_read_coverage_sqlite_reads_line_bits_and_keeps_silent_files(tmp_path):
    db = _data_file(
        tmp_path / ".coverage",
        files=("/repo/a.py", "/repo/quiet.py"),
        line_bits=((1, 1, (1, 2, 5)),),
    )
    got = coverage.read_coverage_sqlite(db)
    assert got["format"] == coverage.FORMAT_COVERAGEPY and got["schema_version"] == 7
    assert got["files"]["/repo/a.py"]["executed"] == {1, 2, 5}
    # a measured file with nothing executed still gets a row: with an inventory it
    # is genuinely 0%, and dropping it would hide the least-tested module
    assert got["files"]["/repo/quiet.py"]["executed"] == set()
    assert got["has_arcs"] is False


def test_read_coverage_sqlite_derives_lines_from_arcs_on_a_branch_run(tmp_path):
    db = _data_file(
        tmp_path / ".coverage",
        files=("/repo/a.py",),
        arcs=((1, 1, -1, 1), (1, 1, 1, 2), (1, 1, 2, -1)),
        has_arcs=True,
    )
    got = coverage.read_coverage_sqlite(db)
    assert got["files"]["/repo/a.py"]["executed"] == {1, 2}  # -1 is a block marker
    assert any("--branch run" in n for n in got["notes"])
    assert any("NOT converted into branch percentages" in n for n in got["notes"])


def test_read_coverage_sqlite_filters_by_context_and_refuses_a_typo(tmp_path):
    db = _data_file(
        tmp_path / ".coverage",
        files=("/repo/a.py",),
        contexts=("", "test_login"),
        line_bits=((1, 1, (1, 2)), (1, 2, (7,))),
    )
    assert coverage.read_coverage_sqlite(db)["files"]["/repo/a.py"]["executed"] == {
        1,
        2,
        7,
    }
    only = coverage.read_coverage_sqlite(db, context="test_login")
    assert (
        only["files"]["/repo/a.py"]["executed"] == {7}
        and only["context"] == "test_login"
    )
    with pytest.raises(coverage.CoverageError, match="no measurement context named"):
        coverage.read_coverage_sqlite(db, context="test_logn")
    with pytest.raises(coverage.CoverageError, match="refusing to report zero"):
        coverage.read_coverage_sqlite(db, context="nope")


def test_read_coverage_sqlite_names_what_is_missing(tmp_path):
    nocontext = _data_file(
        tmp_path / "nc.coverage",
        files=("/repo/a.py",),
        line_bits=((1, 1, (1,)),),
        drop_tables=("context",),
    )
    assert coverage.read_coverage_sqlite(nocontext)["contexts"] == []
    with pytest.raises(coverage.CoverageError, match="no context table"):
        coverage.read_coverage_sqlite(nocontext, context="x")
    nobits = _data_file(
        tmp_path / "nb.coverage", files=("/repo/a.py",), drop_tables=("line_bits",)
    )
    with pytest.raises(coverage.CoverageError, match="line_bits"):
        coverage.read_coverage_sqlite(nobits)


def test_read_coverage_sqlite_reports_an_unknown_schema_and_an_empty_file(tmp_path):
    future = _data_file(tmp_path / "f.coverage", files=("/repo/a.py",), schema=99)
    got = coverage.read_coverage_sqlite(future)
    assert got["schema_version"] == 99
    assert any("version 99 is not one this parser" in n for n in got["notes"])
    assert any("records no executed lines at all" in n for n in got["notes"])
    unversioned = _data_file(
        tmp_path / "u.coverage", files=("/repo/a.py",), drop_tables=("coverage_schema",)
    )
    got = coverage.read_coverage_sqlite(unversioned)
    assert got["schema_version"] is None
    assert any("no coverage_schema version" in n for n in got["notes"])


def test_read_coverage_sqlite_refuses_the_wrong_kind_of_file(tmp_path):
    legacy = tmp_path / "old.coverage"
    legacy.write_bytes(b'!coverage.py: This is a private format\n{"lines": {}}')
    with pytest.raises(coverage.CoverageError, match=r"4\.x"):
        coverage.read_coverage_sqlite(legacy)
    junk = tmp_path / "junk.coverage"
    junk.write_bytes(b"not a database at all")
    with pytest.raises(coverage.CoverageError, match="not a sqlite database"):
        coverage.read_coverage_sqlite(junk)
    with pytest.raises(coverage.CoverageError, match="no such coverage data file"):
        coverage.read_coverage_sqlite(tmp_path / "absent.coverage")


def test_open_readonly_physically_refuses_to_write_the_artifact(tmp_path):
    db = _data_file(tmp_path / ".coverage", files=("/repo/a.py",))
    conn = coverage.open_readonly(db)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO file(id, path) VALUES(9, '/x.py')")
    finally:
        conn.close()


# ---- combining --------------------------------------------------------------


def test_combine_unions_executed_lines_into_the_numerator(tmp_path):
    xml = coverage.parse_cobertura(
        _xml(_cls("a.py", _line(1, 1) + _line(2, 0) + _line(3, 0)))
    )
    db = _data_file(tmp_path / ".coverage", files=("a.py",), line_bits=((1, 1, (2,)),))
    merged = coverage.combine([xml, coverage.read_coverage_sqlite(db)])
    only_xml = coverage.combine([xml])["files"][0]
    assert only_xml["covered"] == 1 and only_xml["pct"] == 33.33
    both = merged["files"][0]
    assert both["covered"] == 2 and both["pct"] == 66.67  # line 2 ran under the tracer
    assert both["formats"] == [coverage.FORMAT_COBERTURA, coverage.FORMAT_COVERAGEPY]


def test_combine_never_counts_an_executed_line_outside_the_inventory(tmp_path):
    xml = coverage.parse_cobertura(_xml(_cls("a.py", _line(1, 1) + _line(2, 0))))
    db = _data_file(
        tmp_path / ".coverage", files=("a.py",), line_bits=((1, 1, (1, 2, 40, 41)),)
    )
    merged = coverage.combine([xml, coverage.read_coverage_sqlite(db)])
    row = merged["files"][0]
    assert row["covered"] == 2 and row["statements"] == 2 and row["pct"] == 100.0
    assert row["executed_outside_inventory"] == 2
    assert merged["executed_outside_inventory"] == 2
    assert any("not in the statement inventory" in n for n in merged["notes"])


def test_combine_matches_absolute_data_paths_via_the_xml_source_root(tmp_path):
    xml = coverage.parse_cobertura(
        "<coverage><sources><source>/repo/root</source></sources><packages><package "
        'name="p"><classes>' + _cls("pkg/a.py", _line(1, 0)) + "</classes></package>"
        "</packages></coverage>"
    )
    db = _data_file(
        tmp_path / ".coverage",
        files=("/repo/root/pkg/a.py",),
        line_bits=((1, 1, (1,)),),
    )
    merged = coverage.combine([xml, coverage.read_coverage_sqlite(db)])
    assert len(merged["files"]) == 1, "the source root should have made the paths match"
    assert (
        merged["files"][0]["path"] == "pkg/a.py" and merged["files"][0]["pct"] == 100.0
    )
    # without the root the two paths are two different files, and the extra one is
    # honestly UNKNOWN rather than silently folded in
    split = coverage.combine(
        [
            coverage.parse_cobertura(_xml(_cls("pkg/a.py", _line(1, 0)))),
            coverage.read_coverage_sqlite(db),
        ]
    )
    assert len(split["files"]) == 2
    assert any("pass --strip-prefix" in n for n in split["notes"])
    assert any("absolute" in n for n in split["notes"])


def test_combine_honours_an_explicit_strip_prefix(tmp_path):
    db = _data_file(
        tmp_path / ".coverage",
        files=("/build/tmp/pkg/a.py",),
        line_bits=((1, 1, (1,)),),
    )
    parsed = [coverage.read_coverage_sqlite(db)]
    assert coverage.combine(parsed)["files"][0]["path"] == "/build/tmp/pkg/a.py"
    stripped = coverage.combine(parsed, strip_prefixes=("/build/tmp",))
    assert stripped["files"][0]["path"] == "pkg/a.py"
    assert stripped["strip_prefixes"] == ["/build/tmp"]


def test_a_data_file_alone_gives_counts_and_an_unknown_percentage(tmp_path):
    db = _data_file(
        tmp_path / ".coverage",
        files=("pkg/a.py", "pkg/b.py"),
        line_bits=((1, 1, (1, 2, 3)),),
    )
    combined = coverage.combine([coverage.read_coverage_sqlite(db)], depth=1)
    a, b = combined["files"]
    assert a["covered"] == 3 and a["pct"] is None
    assert coverage.NO_INVENTORY_REASON == a["unknown_reason"]
    assert b["covered"] == 0 and b["pct"] is None
    module = combined["modules"][0]
    assert module["pct"] is None and module["files_unknown"] == 2
    assert module["executed_unmeasured"] == 3  # the lines seen, kept out of a ratio
    assert combined["totals"]["pct"] is None and combined["totals"]["covered"] == 0


# ---- rollups ----------------------------------------------------------------


def test_module_percentage_sums_counts_instead_of_averaging_percentages():
    files = [
        coverage.measurement(path="m/tiny.py", statements=1, covered=1),
        coverage.measurement(path="m/big.py", statements=100, covered=1),
    ]
    module = coverage.rollup_modules(files, depth=1)[0]
    # the mean of 100% and 1% is 50.5; the honest answer is 2/101
    assert (
        module["pct"] == 1.98 and module["statements"] == 101 and module["covered"] == 2
    )
    assert module["files"] == 2 and module["files_measured"] == 2
    assert coverage.totals_of(files)["pct"] == 1.98


def test_rollup_keeps_an_empty_file_from_dragging_a_module_to_unknown():
    files = [
        coverage.measurement(path="m/__init__.py", statements=0, covered=0),
        coverage.measurement(path="m/a.py", statements=4, covered=3),
    ]
    module = coverage.rollup_modules(files, depth=1)[0]
    assert module["pct"] == 75.0 and module["partial"] is True
    assert module["files_unknown"] == 1 and module["unknown_paths"] == ["m/__init__.py"]
    assert module["files_measured"] == 1


def test_rollup_module_is_unknown_only_when_no_file_has_an_inventory():
    files = [
        coverage.measurement(path="m/a.py", statements=None, covered=9),
        coverage.measurement(path="m/b.py", statements=None, covered=0),
    ]
    module = coverage.rollup_modules(files, depth=1)[0]
    assert module["pct"] is None and module["statements"] is None
    assert "none of the 2 file(s)" in module["unknown_reason"]
    assert module["executed_unmeasured"] == 9


def test_rollup_groups_by_depth_and_fills_in_the_module_on_each_file():
    files = [
        coverage.measurement(path="a/x/one.py", statements=2, covered=1),
        coverage.measurement(path="a/y/two.py", statements=2, covered=2),
        coverage.measurement(path="top.py", statements=1, covered=0),
    ]
    shallow = coverage.rollup_modules(files, depth=1)
    assert [m["module"] for m in shallow] == [coverage.ROOT_MODULE, "a"]
    assert [m["pct"] for m in shallow] == [0.0, 75.0]
    assert files[0]["module"] == "a"
    deep = coverage.rollup_modules(files, depth=2)
    assert [m["module"] for m in deep] == [coverage.ROOT_MODULE, "a/x", "a/y"]
    assert files[0]["module"] == "a/x"


def test_totals_match_the_real_report_coverage_py_produced():
    combined = coverage.combine([coverage.parse_cobertura(COBERTURA)], depth=1)
    assert combined["totals"]["pct"] == 69.23  # coverage.py's own line-rate 0.6923
    assert combined["totals"]["statements"] == 13 and combined["totals"]["covered"] == 9
    assert combined["totals"]["branch_pct"] == 25.0  # its branch-rate 0.25
    by_name = {m["module"]: m for m in combined["modules"]}
    assert by_name["pkg"]["pct"] == 62.5 and by_name["util"]["pct"] == 80.0
    assert by_name["pkg"]["files_unknown"] == 1  # the empty __init__.py


# ---- deltas -----------------------------------------------------------------


def _mod(name: str, pct: float | None, *, statements=10, covered=5, reason=None):
    return {
        "module": name,
        "pct": pct,
        "statements": statements,
        "covered": covered,
        "unknown_reason": reason if pct is None else None,
    }


def test_delta_classifies_movement_around_the_display_epsilon():
    assert coverage.delta_of(_mod("m", 80.0), _mod("m", 70.0))["status"] == "improved"
    assert coverage.delta_of(_mod("m", 70.0), _mod("m", 80.0))["status"] == "regressed"
    assert coverage.delta_of(_mod("m", 70.0), _mod("m", 70.0))["status"] == "unchanged"
    drop = coverage.delta_of(_mod("m", 62.5), _mod("m", 75.0))
    assert drop["delta"] == -12.5 and drop["delta_reason"] is None
    tiny = coverage.delta_of(_mod("m", 70.001), _mod("m", 70.0))
    assert tiny["status"] == "unchanged" and tiny["delta"] == 0.0


def test_delta_is_none_with_a_reason_whenever_it_cannot_be_a_number():
    new = coverage.delta_of(_mod("m", 80.0), None)
    assert new["delta"] is None and new["status"] == "new"
    assert "not in the baseline run" in new["delta_reason"]
    gone = coverage.delta_of(None, _mod("m", 80.0))
    assert gone["delta"] is None and gone["status"] == "removed"
    assert gone["baseline_pct"] == 80.0 and gone["pct"] is None
    blind = coverage.delta_of(_mod("m", None, reason="no inventory"), _mod("m", 80.0))
    assert blind["delta"] is None and blind["status"] == "unknown"
    assert "this run has no percentage" in blind["delta_reason"]
    was_blind = coverage.delta_of(_mod("m", 80.0), _mod("m", None, reason="was empty"))
    assert (
        was_blind["delta"] is None
        and "baseline has no percentage" in was_blind["delta_reason"]
    )
    assert "was empty" in was_blind["delta_reason"]


def test_delta_reports_statement_movement_even_when_both_sides_are_known():
    row = coverage.delta_of(
        _mod("m", 50.0, statements=20, covered=10),
        _mod("m", 60.0, statements=10, covered=6),
    )
    assert row["statements_delta"] == 10 and row["covered_delta"] == 4
    assert row["status"] == "regressed"  # more code, proportionally less covered


def test_compare_modules_counts_every_status_and_finds_the_worst_drop():
    current = [_mod("a", 90.0), _mod("b", 50.0), _mod("c", 70.0)]
    baseline = [_mod("a", 80.0), _mod("b", 75.0), _mod("d", 60.0)]
    cmp = coverage.compare_modules(current, baseline)
    assert cmp["have_baseline"] is True
    status = {r["module"]: r["status"] for r in cmp["modules"]}
    assert status == {"a": "improved", "b": "regressed", "c": "new", "d": "removed"}
    assert cmp["counts"]["regressed"] == 1 and cmp["counts"]["removed"] == 1
    assert cmp["worst"]["module"] == "b" and cmp["worst"]["delta"] == -25.0
    assert [r["module"] for r in cmp["modules"]] == ["a", "b", "c", "d"]


def test_compare_modules_with_no_baseline_is_all_new_and_no_zero_deltas():
    cmp = coverage.compare_modules([_mod("a", 90.0), _mod("b", 10.0)], None)
    assert cmp["have_baseline"] is False and cmp["counts"]["new"] == 2
    assert all(r["delta"] is None and r["delta_reason"] for r in cmp["modules"])
    assert cmp["worst"] is None


# ---- rules and diagnostics --------------------------------------------------


def _report(xml_doc: str, *, baseline=None, depth=1, generated_ts=1700000000.0, **kw):
    combined = coverage.combine([coverage.parse_cobertura(xml_doc)], depth=depth)
    return coverage.build_report(
        combined, baseline=baseline, generated_ts=generated_ts, **kw
    )


def test_load_rules_overlay_is_policy_as_config_and_typos_are_fatal(tmp_path):
    assert coverage.load_rules()["coverage:regressed"]["severity"] == "error"
    overlay = tmp_path / "org.json"
    overlay.write_text(
        json.dumps({"coverage:regressed": {"severity": "warning", "enabled": False}}),
        encoding="utf-8",
    )
    merged = coverage.load_rules(overlay)
    assert merged["coverage:regressed"] == {
        "enabled": False,
        "severity": "warning",
        "why": coverage.RULES["coverage:regressed"]["why"],
    }
    assert coverage.RULES["coverage:regressed"]["enabled"] is True  # not mutated
    for bad, match in (
        ({"coverage:nope": {}}, "unknown rule id"),
        ({"coverage:regressed": "warning"}, "must be a JSON object"),
        (
            {"coverage:regressed": {"severity": "catastrophe"}},
            "severity must be one of",
        ),
        ([], "must be a JSON object"),
    ):
        overlay.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match=match):
            coverage.load_rules(overlay)


def test_thresholds_fire_on_the_total_and_on_each_module():
    report = _report(
        _xml(_cls("a/x.py", _line(1, 1) + _line(2, 0)) + _cls("b/y.py", _line(1, 1)))
    )
    diags = coverage.to_diagnostics(report, min_pct=80)
    fired = {d["rule"]: d for d in diags}
    assert "coverage:total-below-threshold" in fired  # 2/3 = 66.67%
    assert "coverage:below-threshold" in fired
    assert fired["coverage:below-threshold"]["path"] == "a"  # b is 100%
    assert "50.00%" in fired["coverage:below-threshold"]["message"]
    assert not [d for d in diags if d["path"] == "b"]
    # with no threshold asked for, neither rule may fire on its own
    assert {d["rule"] for d in coverage.to_diagnostics(report)} == {
        "coverage:no-baseline"
    }


def test_an_unmeasurable_report_can_never_satisfy_a_threshold(tmp_path):
    db = _data_file(
        tmp_path / ".coverage", files=("a/x.py",), line_bits=((1, 1, (1, 2)),)
    )
    combined = coverage.combine([coverage.read_coverage_sqlite(db)], depth=1)
    report = coverage.build_report(combined, generated_ts=0.0)
    rules = {d["rule"] for d in coverage.to_diagnostics(report, min_pct=1)}
    assert "coverage:total-unmeasured" in rules and "coverage:no-data" in rules
    assert (
        "coverage:total-below-threshold" not in rules
    )  # there is no number to compare
    severities = {
        d["severity"]
        for d in coverage.to_diagnostics(report, min_pct=1)
        if d["rule"] == "coverage:total-unmeasured"
    }
    assert severities == {"error"}  # an unknown must fail a gate, not pass it


def test_regression_rule_respects_max_drop_and_needs_a_baseline():
    baseline = {"id": 1, "ts": 1.0, "modules": [_mod("a", 90.0), _mod("b", 90.0)]}
    report = _report(
        _xml(_cls("a/x.py", _line(1, 1) + _line(2, 0)) + _cls("b/y.py", _line(1, 1))),
        baseline=baseline,
    )
    lenient = {d["rule"] for d in coverage.to_diagnostics(report, max_drop=50)}
    assert "coverage:regressed" not in lenient  # a dropped 40 points, allowance is 50
    strict = [
        d
        for d in coverage.to_diagnostics(report, max_drop=0)
        if d["rule"] == "coverage:regressed"
    ]
    assert len(strict) == 1 and strict[0]["path"] == "a"
    assert "90.00% -> 50.00%" in strict[0]["message"]
    assert "coverage:no-baseline" not in {
        d["rule"] for d in coverage.to_diagnostics(report, max_drop=0)
    }


def test_missing_baseline_and_partial_modules_are_reported_not_hidden():
    report = _report(
        _xml(_cls("a/x.py", _line(1, 1)) + _cls("a/e.py", "")), db="cov.db"
    )
    diags = {d["rule"]: d for d in coverage.to_diagnostics(report)}
    assert diags["coverage:no-baseline"]["path"] == "cov.db"
    assert diags["coverage:no-baseline"]["severity"] == "info"
    partial = diags["coverage:module-partial"]
    assert "1 of 2 file(s)" in partial["message"] and "a/e.py" in partial["suggestion"]


def test_unparsable_sources_ride_the_diagnostic_schema():
    report = _report(
        _xml(_cls("a/x.py", _line(1, 1))),
        unparsable=[
            {"path": "broken.xml", "error": "CoverageError: not well-formed XML"}
        ],
    )
    hit = [
        d
        for d in coverage.to_diagnostics(report)
        if d["rule"] == "coverage:source-unparsable"
    ]
    assert len(hit) == 1 and hit[0]["severity"] == "error"
    assert hit[0]["path"] == "broken.xml" and "not well-formed" in hit[0]["message"]


def test_a_disabled_rule_stays_quiet_and_a_clean_report_has_no_errors():
    report = _report(_xml(_cls("a/x.py", _line(1, 1))))
    quiet = coverage.load_rules()
    quiet["coverage:no-baseline"]["enabled"] = False
    assert coverage.to_diagnostics(report, rules=quiet) == []
    loud = coverage.to_diagnostics(report)
    assert [d["rule"] for d in loud] == ["coverage:no-baseline"]
    assert not [d for d in loud if d["severity"] == "error"]


def test_outside_inventory_findings_come_from_the_count_not_a_string_match(tmp_path):
    xml = coverage.parse_cobertura(_xml(_cls("a/x.py", _line(1, 1))))
    db = _data_file(
        tmp_path / ".coverage", files=("a/x.py",), line_bits=((1, 1, (1, 99)),)
    )
    combined = coverage.combine([xml, coverage.read_coverage_sqlite(db)], depth=1)
    report = coverage.build_report(combined, generated_ts=0.0)
    hit = [
        d
        for d in coverage.to_diagnostics(report)
        if d["rule"] == "coverage:executed-outside-inventory"
    ]
    assert len(hit) == 1 and "1 line(s)" in hit[0]["message"]


# ---- the store --------------------------------------------------------------


def test_store_round_trips_a_run_including_its_unknown_modules(tmp_path):
    conn = coverage.open_store(tmp_path / "hist.db")
    report = _report(
        _xml(_cls("a/x.py", _line(1, 1) + _line(2, 0)) + _cls("b/e.py", ""))
    )
    run_id = coverage.record_run(conn, report, ts=1700000000.5, label="ci #7")
    assert run_id == 1
    stored = coverage.get_run(conn, run_id)
    assert stored["label"] == "ci #7" and stored["ts"] == 1700000000.5
    assert stored["totals"]["pct"] == 50.0 and stored["depth"] == 1
    rows = {m["module"]: m for m in stored["modules"]}
    assert rows["a"]["pct"] == 50.0 and rows["a"]["unknown_reason"] is None
    assert rows["b"]["pct"] is None and "divide by zero" in rows["b"]["unknown_reason"]
    assert rows["b"]["statements"] == 0 and rows["b"]["files"] == 1
    assert coverage.get_run(conn, 99) is None


def test_store_check_constraint_enforces_the_invariant_in_sql(tmp_path):
    conn = coverage.open_store(tmp_path / "hist.db")
    conn.execute(
        "INSERT INTO runs(ts, label, depth, sources, totals) VALUES(1, 'x', 1, '[]', '{}')"
    )
    insert = (
        "INSERT INTO modules(run_id, module, statements, covered, pct, unknown_reason,"
        " files, files_unknown) VALUES(1, ?, 1, 1, ?, ?, 1, 0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("both", 50.0, "and a reason"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("neither", None, None))
    conn.execute(insert, ("pct only", 50.0, None))
    conn.execute(insert, ("reason only", None, "nothing measurable"))
    assert conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0] == 2


def test_store_json_columns_are_key_sorted_so_two_runs_can_be_diffed(tmp_path):
    # a third mutation survivor: dropping sort_keys left the store working but no
    # longer byte-comparable, so a `sqlite3 .dump | diff` of two identical runs
    # could show phantom changes from Python's key insertion order
    conn = coverage.open_store(tmp_path / "hist.db")
    report = _report(_xml(_cls("a/x.py", _line(1, 1) + _line(2, 0))))
    coverage.record_run(conn, report, ts=1.0, label="one")
    totals, sources = conn.execute("SELECT totals, sources FROM runs").fetchone()
    assert list(json.loads(totals)) == sorted(json.loads(totals)), totals
    assert json.loads(totals)["pct"] == 50.0  # and it is the real measurement
    assert list(json.loads(sources)[0]) == sorted(json.loads(sources)[0])


def test_runs_list_is_newest_first_and_latest_is_the_baseline(tmp_path):
    conn = coverage.open_store(tmp_path / "hist.db")
    assert coverage.latest_run(conn) is None and coverage.list_runs(conn) == []
    first = coverage.record_run(
        conn, _report(_xml(_cls("a/x.py", _line(1, 1)))), ts=10.0, label="one"
    )
    second = coverage.record_run(
        conn, _report(_xml(_cls("a/x.py", _line(1, 0)))), ts=20.0, label="two"
    )
    listed = coverage.list_runs(conn)
    assert [r["id"] for r in listed] == [second, first]
    assert listed[0]["totals"]["pct"] == 0.0 and listed[1]["totals"]["pct"] == 100.0
    assert coverage.latest_run(conn)["id"] == second
    assert len(coverage.list_runs(conn, limit=1)) == 1


def test_the_store_is_its_own_file_and_can_hold_a_missing_measurement():
    # runtrack #10 already deltas runs against a baseline; its metric column is
    # NOT NULL, so an unmeasured module could only be logged as a fabricated 0.0.
    # That constraint is the citable reason this is a separate store.
    from bigbang.core import runtrack

    assert "value REAL NOT NULL" in runtrack._SCHEMA
    assert (
        "pct REAL" in coverage._SCHEMA and "pct REAL NOT NULL" not in coverage._SCHEMA
    )
    assert coverage.DB_REL != runtrack.DB_REL
    assert coverage.DB_REL.parent == Path(".scout")


# ---- the rendered page ------------------------------------------------------


def _rows(page: str) -> list[str]:
    table = page.split("<h2>Modules</h2>", 1)[1].split("</table>", 1)[0]
    return table.split("<tr>")[2:]  # [0] is the pre-table text, [1] the header


# Every real figure this page prints is formatted "%.2f%%" (in a cell or in a bar
# width), so this pattern finds a percentage and nothing else — prose like
# "not 0% covered" in a reason string does not match it.
_FIGURE = r"\d+\.\d\d%"


def test_a_missing_timestamp_renders_as_unrecorded_not_as_1970():
    # found by mutation: replacing the guard with `ts = ts or 0.0` passed the whole
    # suite while printing "1970-01-01T00:00:00Z" for a time nobody recorded. A
    # fabricated date is the same defect class as a fabricated zero.
    assert coverage._iso(1700000000.0) == "2023-11-14T22:13:20Z"
    assert coverage._iso(0) == "unrecorded" and coverage._iso(None) == "unrecorded"
    page = coverage.render_html(
        _report(_xml(_cls("a/x.py", _line(1, 1))), generated_ts=0.0)
    )
    assert "unrecorded" in page and "1970" not in page


def test_render_names_how_many_files_the_headline_excludes():
    # also a mutation survivor: deleting this note left a 75% headline with no
    # statement anywhere on the page that it covers only half the files.
    report = _report(
        _xml(_cls("m/a.py", _line(1, 1) + _line(2, 0)) + _cls("m/e.py", ""))
    )
    page = coverage.render_html(report)
    assert "1 of 2 file(s) have no percentage of their own" in page
    assert "never as 0%" in page
    clean = coverage.render_html(_report(_xml(_cls("m/a.py", _line(1, 1)))))
    assert "have no percentage of their own" not in clean  # nothing to disclose


def test_render_draws_no_bar_and_no_percentage_for_an_unknown_module():
    import re

    report = _report(_xml(_cls("good/x.py", _line(1, 1)) + _cls("blind/e.py", "")))
    page = coverage.render_html(report)
    rows = {r.split("</td>", 1)[0]: r for r in _rows(page)}
    blind = next(r for k, r in rows.items() if "blind" in k)
    good = next(r for k, r in rows.items() if "good" in k)
    assert "UNKNOWN" in blind and "bar unknown" in blind
    assert "width:" not in blind, "an unknown module must not get a zero-width bar"
    assert re.search(_FIGURE, blind) is None, "no percentage may be printed for it"
    assert "100.00%" in good and "width:100.00%" in good
    assert "divide by zero" in page  # the reason travels with the row


def test_render_says_unknown_in_the_banner_instead_of_zero(tmp_path):
    import re

    db = _data_file(
        tmp_path / ".coverage", files=("a/x.py",), line_bits=((1, 1, (1,)),)
    )
    combined = coverage.combine([coverage.read_coverage_sqlite(db)], depth=1)
    page = coverage.render_html(coverage.build_report(combined, generated_ts=0.0))
    figures = page.split("<h1>", 1)[1].split("</table>", 1)[0]
    assert "banner unk" in page and "UNKNOWN" in figures
    assert re.search(_FIGURE, figures) is None, f"invented a figure: {figures}"
    assert "no denominator" in page


def test_render_shows_deltas_and_keeps_a_removed_module_visible():
    baseline = {
        "id": 4,
        "ts": 1699999999.0,
        "modules": [_mod("a", 90.0), _mod("gone", 70.0)],
    }
    report = _report(_xml(_cls("a/x.py", _line(1, 1) + _line(2, 0))), baseline=baseline)
    page = coverage.render_html(report, title="Repo coverage")
    assert "<title>Repo coverage</title>" in page and "run 4 recorded" in page
    rows = _rows(page)
    assert len(rows) == 2
    live = next(r for r in rows if ">a<" in r)
    assert "-40.00" in live and "s-regressed" in live and "90.00%" in live
    dead = next(r for r in rows if "gone" in r)
    assert "s-removed" in dead and "70.00%" in dead and "n/a" in dead


def test_render_escapes_everything_and_stays_self_contained():
    # the attribute is XML-escaped, so the PARSED filename really does contain
    # markup — exactly what an attacker-controlled path would look like
    hostile = "&lt;script&gt;alert(1)&lt;/script&gt;/a.py"
    parsed = coverage.parse_cobertura(_xml(_cls(hostile, _line(1, 1))))
    assert "<script>alert(1)</script>/a.py" in parsed["files"]
    page = coverage.render_html(_report(_xml(_cls(hostile, _line(1, 1)))))
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "http://" not in page and "https://" not in page
    assert "<script" not in page.lower().replace("&lt;script", "")
    assert page.startswith("<!DOCTYPE html>") and page.rstrip().endswith("</html>")


def test_render_reads_no_clock_so_the_page_is_reproducible(monkeypatch):
    report = _report(_xml(_cls("a/x.py", _line(1, 1))))
    first = coverage.render_html(report)
    monkeypatch.setattr(coverage.time, "time", lambda: 4102444800.0)
    monkeypatch.setattr(coverage.time, "monotonic", lambda: 99.0)
    assert coverage.render_html(report) == first
    assert "2023-11-14T22:13:20Z" in first  # the INJECTED generated_ts, formatted UTC
    moved = dict(report, generated_ts=1700000001.0)
    assert coverage.render_html(moved) != first  # so the equality above means something


def test_render_reports_an_unreadable_source_on_the_page():
    report = _report(
        _xml(_cls("a/x.py", _line(1, 1))),
        unparsable=[
            {"path": "broken.xml", "error": "CoverageError: refusing a DOCTYPE"}
        ],
    )
    page = coverage.render_html(report)
    assert (
        "Not parsed" in page and "broken.xml" in page and "refusing a DOCTYPE" in page
    )


# ---- stdlib-only invariant (the whole point of the openswap family) ----------


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_imports_are_stdlib_only():
    roots = _import_roots(ROOT / "bigbang" / "core" / "coverage.py")
    allowed = set(sys.stdlib_module_names) | {"bigbang"}
    assert roots <= allowed, f"non-stdlib imports: {sorted(roots - allowed)}"
    assert "coverage" not in roots  # never the third-party package it replaces


def test_plugin_cli_adds_no_dependency_beyond_typer():
    roots = _import_roots(ROOT / "bigbang" / "plugins" / "coverage" / "cli.py")
    allowed = set(sys.stdlib_module_names) | {"bigbang", "typer"}
    assert roots <= allowed, f"new dependency: {sorted(roots - allowed)}"


def test_namespace_folding_is_reused_from_feeds_not_retyped():
    from bigbang.core import feeds

    assert coverage.local is feeds.local  # identity: drift is impossible


# ---- capability, manifest, egress guard -------------------------------------


def test_detection_falls_back_when_no_binary_is_on_path(monkeypatch):
    from bigbang.plugins.coverage import cli as cov_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = cov_cli._capability()
    assert cap["adapter"] == "coverage" and cap["tier"] == openswap.TIER_FALLBACK
    assert cap["native"]["binary"] == "coverage" and cap["native"]["found"] is False
    assert cap["extras"]["codecov"]["found"] is False
    assert cap["native_used"] is False  # true on EVERY tier, by contract
    assert "NEVER executed" in cap["native_never_executed"]
    assert "complete product" in cap["fallback_scope"]


def test_manifest_is_zero_egress_with_writes_confined_to_the_store():
    import yaml

    mf = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "coverage" / "manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    caps = mf["capabilities"]
    assert mf["name"] == "coverage"
    assert caps["network"]["enabled"] is False and caps["network"]["domains"] == []
    assert caps["filesystem"]["write"] is True and caps["filesystem"]["paths"] == [
        ".scout"
    ]
    assert caps["secrets"]["allow"] == []  # no CODECOV_TOKEN to hold


def test_egress_guard_refuses_a_widened_manifest(monkeypatch):
    import typer

    from bigbang.plugins.coverage import cli as cov_cli

    assert cov_cli._egress_guard("test")["network_enabled"] is False
    for widened in (
        {"capabilities": {"network": {"enabled": True, "domains": []}}},
        {"capabilities": {"network": {"enabled": False, "domains": ["codecov.io"]}}},
    ):
        monkeypatch.setattr(cov_cli, "_MANIFEST", widened)
        with pytest.raises(typer.Exit):
            cov_cli._egress_guard("test")


def test_db_path_prefers_the_flag_then_the_env_then_the_default(monkeypatch):
    from bigbang.plugins.coverage import cli as cov_cli

    monkeypatch.delenv("SCOUT_COVERAGE_DB", raising=False)
    assert cov_cli._db_path(None) == coverage.DB_REL
    monkeypatch.setenv("SCOUT_COVERAGE_DB", "env.db")
    assert cov_cli._db_path(None) == Path("env.db")
    assert cov_cli._db_path("flag.db") == Path("flag.db")


# ---- the real CLI in a subprocess (offline on every path) --------------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(cwd or ROOT),
    )


@pytest.fixture
def repo(tmp_path):
    """A coverage.xml plus a matching .coverage, as a real run would leave them."""
    xml = tmp_path / "coverage.xml"
    xml.write_text(COBERTURA, encoding="utf-8")
    _data_file(
        tmp_path / ".coverage",
        files=("/repo/root/pkg/calc.py", "/repo/root/util/helpers.py"),
        line_bits=((1, 1, (1, 2, 5, 6, 9)), (2, 1, (1, 2, 3, 5))),
    )
    return tmp_path


def test_cli_hello_envelope():
    r = _cli(["coverage", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"] == {"ready": True, "plugin": "coverage"}
    assert "example" in data


def test_cli_detect_reports_zero_egress_and_never_uses_the_binary():
    r = _cli(["coverage", "detect"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["native_used"] is False
    assert data["egress"] == {
        "network_enabled": False,
        "domains": [],
        "uploads": "none, on any path",
    }
    # the tier must agree with THIS box's PATH, not with a hardcoded expectation
    expected = "native" if shutil.which("coverage") else "fallback"
    assert data["tier"] == expected
    assert data["native"]["found"] is (expected == "native")
    # the tier says nothing about what was USED, so the scope has to be stated
    assert (
        "UNKNOWN percentage" in data["scope_limits"] and "LCOV" in data["scope_limits"]
    )
    assert "NEVER executed" in data["native_never_executed"]


def test_cli_parse_measures_a_real_report(repo):
    r = _cli(["coverage", "parse", "--xml", str(repo / "coverage.xml"), "--depth", "1"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["totals"]["pct"] == 69.23 and data["totals"]["files_unknown"] == 1
    assert [(m["module"], m["pct"]) for m in data["modules"]] == [
        ("pkg", 62.5),
        ("util", 80.0),
    ]
    assert data["declared_vs_counted"][0]["agrees"] is True
    assert data["unparsable"] == [] and "files" not in data
    assert data["native_used"] is False


def test_cli_parse_merges_the_data_file_through_the_source_root(repo):
    r = _cli(
        [
            "coverage",
            "parse",
            "--xml",
            str(repo / "coverage.xml"),
            "--data",
            str(repo / ".coverage"),
            "--depth",
            "1",
            "--files",
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    paths = {f["path"] for f in data["files"]}
    assert paths == {"pkg/__init__.py", "pkg/calc.py", "util/helpers.py"}
    assert data["totals"]["pct"] == 69.23  # the .coverage agreed with the XML
    assert data["executed_outside_inventory"] == 0
    assert len(data["sources"]) == 2


def test_cli_parse_needs_something_to_parse():
    r = _cli(["coverage", "parse"])
    assert r.returncode == 1
    assert "nothing to parse" in json.loads(r.stdout)["error"]


def test_cli_refuses_to_report_when_nothing_parsed(tmp_path):
    bad = tmp_path / "broken.xml"
    bad.write_text("<report><counter/></report>", encoding="utf-8")
    r = _cli(["coverage", "parse", "--xml", str(bad)])
    assert r.returncode == 1
    error = json.loads(r.stdout)["error"]
    assert "no coverage report could be parsed" in error and "JaCoCo" in error
    missing = _cli(["coverage", "parse", "--xml", str(tmp_path / "nope.xml")])
    assert missing.returncode == 1
    assert "no coverage report could be parsed" in json.loads(missing.stdout)["error"]


def test_cli_parse_rejects_a_depth_that_cannot_name_a_module(repo):
    r = _cli(["coverage", "parse", "--xml", str(repo / "coverage.xml"), "--depth", "0"])
    assert r.returncode == 1
    assert "depth must be >= 1" in json.loads(r.stdout)["error"]


def test_cli_report_records_a_baseline_then_finds_the_regression(repo, tmp_path):
    db = tmp_path / "hist.db"
    first = _cli(
        [
            "coverage",
            "report",
            "--xml",
            str(repo / "coverage.xml"),
            "--depth",
            "1",
            "--db",
            str(db),
            "--record",
            "--label",
            "run one",
        ]
    )
    assert first.returncode == 0, first.stderr + first.stdout
    one = json.loads(first.stdout)["data"]
    assert one["recorded_run_id"] == 1 and one["baseline"] is None
    assert one["comparison"]["counts"]["new"] == 2
    assert {d["rule"] for d in one["diagnostics"]} >= {"coverage:no-baseline"}

    # the same repo with pkg/calc.py losing one covered line
    worse = COBERTURA.replace(
        '<line number="9" hits="1"/>', '<line number="9" hits="0"/>'
    )
    (repo / "coverage.xml").write_text(worse, encoding="utf-8")
    second = _cli(
        [
            "coverage",
            "report",
            "--xml",
            str(repo / "coverage.xml"),
            "--depth",
            "1",
            "--db",
            str(db),
            "--record",
            "--max-drop",
            "0",
            "--fail-on",
            "error",
        ]
    )
    assert second.returncode == 1  # the gate fired on the regression
    two = json.loads(second.stdout)["data"]
    assert two["baseline"]["run_id"] == 1 and two["recorded_run_id"] == 2
    rows = {m["module"]: m for m in two["comparison"]["modules"]}
    assert rows["pkg"]["status"] == "regressed" and rows["pkg"]["delta"] == -12.5
    assert rows["util"]["status"] == "unchanged" and rows["util"]["delta"] == 0.0
    assert two["comparison"]["worst"]["module"] == "pkg"
    regressions = [d for d in two["diagnostics"] if d["rule"] == "coverage:regressed"]
    assert len(regressions) == 1 and regressions[0]["path"] == "pkg"
    assert two["summary"]["by_severity"]["error"] == 1


def test_cli_report_writes_a_self_contained_page(repo, tmp_path):
    out = tmp_path / "pages" / "cov.html"
    r = _cli(
        [
            "coverage",
            "report",
            "--xml",
            str(repo / "coverage.xml"),
            "--depth",
            "1",
            "--db",
            str(tmp_path / "h.db"),
            "--html",
            str(out),
            "--title",
            "My Repo",
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    info = json.loads(r.stdout)["data"]["html"]
    page = out.read_bytes()
    assert info["bytes"] == len(page)  # what was reported is what landed on disk
    text = page.decode("utf-8")
    assert "<title>My Repo</title>" in text and "69.23%" in text
    assert "UNKNOWN" in text  # the empty pkg/__init__.py
    assert "<script" not in text.lower() and "http" not in text.replace(
        "http-equiv", ""
    )
    assert b"\r\n" not in page  # write_bytes: no newline translation


def test_cli_report_gate_fails_on_a_threshold_and_passes_when_met(repo, tmp_path):
    args = [
        "coverage",
        "report",
        "--xml",
        str(repo / "coverage.xml"),
        "--depth",
        "1",
        "--db",
        str(tmp_path / "h.db"),
    ]
    strict = _cli([*args, "--min-pct", "80", "--fail-on", "error"])
    assert strict.returncode == 1
    fired = {d["rule"] for d in json.loads(strict.stdout)["data"]["diagnostics"]}
    assert "coverage:total-below-threshold" in fired
    lenient = _cli([*args, "--min-pct", "60", "--fail-on", "error"])
    assert lenient.returncode == 0, lenient.stdout
    data = json.loads(lenient.stdout)["data"]
    assert data["thresholds"] == {"min_pct": 60.0, "max_drop": None}
    assert not [d for d in data["diagnostics"] if d["severity"] == "error"]


def test_cli_report_data_only_cannot_pass_a_threshold(repo, tmp_path):
    r = _cli(
        [
            "coverage",
            "report",
            "--data",
            str(repo / ".coverage"),
            "--depth",
            "1",
            "--db",
            str(tmp_path / "h.db"),
            "--min-pct",
            "1",
            "--fail-on",
            "error",
        ]
    )
    assert r.returncode == 1  # UNKNOWN never passes a gate
    data = json.loads(r.stdout)["data"]
    assert data["totals"]["pct"] is None
    assert "coverage:total-unmeasured" in {d["rule"] for d in data["diagnostics"]}


def test_cli_report_rejects_a_bad_gate_and_a_missing_baseline(repo, tmp_path):
    bad = _cli(
        [
            "coverage",
            "report",
            "--xml",
            str(repo / "coverage.xml"),
            "--fail-on",
            "whenever",
        ]
    )
    assert bad.returncode == 1
    assert "--fail-on must be one of" in json.loads(bad.stdout)["error"]
    db = tmp_path / "h.db"
    _cli(
        [
            "coverage",
            "report",
            "--xml",
            str(repo / "coverage.xml"),
            "--db",
            str(db),
            "--record",
        ]
    )
    ghost = _cli(
        [
            "coverage",
            "report",
            "--xml",
            str(repo / "coverage.xml"),
            "--db",
            str(db),
            "--baseline",
            "77",
        ]
    )
    assert ghost.returncode == 1
    assert "no recorded run with id 77" in json.loads(ghost.stdout)["error"]


def test_cli_report_without_record_leaves_no_store(repo, tmp_path):
    db = tmp_path / "absent.db"
    r = _cli(
        [
            "coverage",
            "report",
            "--xml",
            str(repo / "coverage.xml"),
            "--db",
            str(db),
            "--no-record",
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert not db.exists()  # a read-only report creates nothing
    assert json.loads(r.stdout)["data"]["db"] is None


def test_cli_runs_lists_history_and_one_run(repo, tmp_path):
    db = tmp_path / "hist.db"
    empty = _cli(["coverage", "runs", "--db", str(db)])
    assert (
        empty.returncode == 1
        and "no coverage history" in json.loads(empty.stdout)["error"]
    )
    _cli(
        [
            "coverage",
            "report",
            "--xml",
            str(repo / "coverage.xml"),
            "--depth",
            "1",
            "--db",
            str(db),
            "--record",
            "--label",
            "ci",
        ]
    )
    listed = _cli(["coverage", "runs", "--db", str(db)])
    assert listed.returncode == 0, listed.stderr + listed.stdout
    data = json.loads(listed.stdout)["data"]
    assert data["count"] == 1 and data["runs"][0]["label"] == "ci"
    assert data["runs"][0]["totals"]["pct"] == 69.23
    one = _cli(["coverage", "runs", "--db", str(db), "--run", "1"])
    assert one.returncode == 0
    modules = json.loads(one.stdout)["data"]["run"]["modules"]
    assert {m["module"] for m in modules} == {"pkg", "util"}
    ghost = _cli(["coverage", "runs", "--db", str(db), "--run", "5"])
    assert ghost.returncode == 1 and "recent ids" in json.loads(ghost.stdout)["error"]


def test_cli_rules_publishes_the_table_and_rejects_a_bad_overlay(tmp_path):
    r = _cli(["coverage", "rules"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert set(data["rules"]) == set(coverage.RULES)
    assert data["rules"]["coverage:no-data"]["severity"] == "warning"
    assert all(cfg["why"] for cfg in data["rules"].values())
    assert data["overlay"] is None and data["statuses"] == list(coverage.STATUSES)
    bad = tmp_path / "bad.json"
    bad.write_text('{"coverage:not-a-rule": {}}', encoding="utf-8")
    broken = _cli(["coverage", "rules", "--rules", str(bad)])
    assert broken.returncode == 1
    assert "bad rules overlay" in json.loads(broken.stdout)["error"]


def test_cli_rules_overlay_changes_a_real_gate(repo, tmp_path):
    overlay = tmp_path / "org.json"
    overlay.write_text(
        json.dumps({"coverage:total-below-threshold": {"enabled": False}}),
        encoding="utf-8",
    )
    args = [
        "coverage",
        "report",
        "--xml",
        str(repo / "coverage.xml"),
        "--depth",
        "1",
        "--db",
        str(tmp_path / "h.db"),
        "--min-pct",
        "80",
        "--fail-on",
        "error",
    ]
    assert _cli(args).returncode == 1
    relaxed = _cli([*args, "--rules", str(overlay)])
    assert relaxed.returncode == 1  # the per-MODULE rule still fires
    fired = {d["rule"] for d in json.loads(relaxed.stdout)["data"]["diagnostics"]}
    assert "coverage:total-below-threshold" not in fired
    assert "coverage:below-threshold" in fired


def test_cli_context_typo_is_refused_instead_of_reporting_zero(repo, tmp_path):
    r = _cli(
        ["coverage", "parse", "--data", str(repo / ".coverage"), "--context", "nope"]
    )
    assert r.returncode == 1
    error = json.loads(r.stdout)["error"]
    assert (
        "no measurement context named" in error and "refusing to report zero" in error
    )


def test_unknown_cells_carry_their_reason_as_a_title():
    """The reason must reach the PAGE, not merely exist in the data.

    plugins/coverage/cli.py promises "a module with no data renders as UNKNOWN with
    the reason, never as 0%". Deleting the title= from these two cells left the page
    saying UNKNOWN with no explanation, and survived the entire 86-test suite
    (mutations X1 and X4 in the batch-5 verify pass) because nothing asserted the
    reason was rendered. An unexplained UNKNOWN is the same failure as a fabricated
    zero: the operator cannot tell why the number is missing.
    """
    cell = coverage._pct_cell(None, "no coverage data for this module")
    assert "UNKNOWN" in cell
    assert 'title="no coverage data for this module"' in cell
    assert "0.00%" not in cell  # never a fabricated zero
    # a missing reason still renders a real title rather than an empty attribute
    assert 'title="no data"' in coverage._pct_cell(None, None)
    # and a measured percentage is not decorated as unknown
    assert coverage._pct_cell(12.5, None) == "12.50%"
    # the delta cell carries the same contract (X4)
    d = coverage._delta_cell({"delta": None, "delta_reason": "no baseline run"})
    assert "n/a" in d and 'title="no baseline run"' in d
    assert coverage._delta_cell({"delta": 1.25, "delta_reason": None}) == "+1.25"


def test_the_unchanged_dead_zone_is_narrow_and_its_boundary_is_pinned():
    """DELTA_EPSILON must stay a rounding tolerance, not a shock absorber.

    Widening it from 0.005 to 0.4 survived the whole 86-test suite (mutation X3 in
    the batch-5 verify pass) — nothing asserted where the boundary sits. That matters
    because the dead zone decides whether a real coverage DROP is reported as
    `regressed` or silently as `unchanged`, and delta_of's own docstring says
    "unchanged" and "we have nothing to compare" are different facts.
    """

    def status(cur_pct, base_pct):
        return coverage.delta_of(
            {"module": "m", "pct": cur_pct, "unknown_reason": None},
            {"module": "m", "pct": base_pct, "unknown_reason": None},
        )["status"]

    # the epsilon is a rounding tolerance, so it must stay TIGHT — this is the
    # assertion an 0.005 -> 0.4 widening has to fail
    # pinned EXACTLY, not bounded: `<= 0.01` admitted eps=0.01, and at that value a
    # delta the page PRINTS as -0.01 is labelled `unchanged` — the inverse of the
    # documented rationale ("below display resolution", percentages shown to 2dp).
    assert coverage.DELTA_EPSILON == 0.005

    # just outside the dead zone in both directions: a real verdict, not "unchanged"
    assert status(90.0 - 0.02, 90.0) == coverage.STATUS_REGRESSED
    assert status(90.0 + 0.02, 90.0) == coverage.STATUS_IMPROVED
    # a drop far smaller than any widened epsilon would still be caught
    assert status(90.0 - 0.3, 90.0) == coverage.STATUS_REGRESSED
    # BEHAVIOUR in the band just above the epsilon, not just the constant's value.
    # `== 0.005` above pins the CONSTANT; it does not pin the COMPARISON, so widening
    # the threshold at the call site (`raw < -DELTA_EPSILON` -> `raw < -0.015`) left the
    # constant intact and passed the whole suite. 0.01 is the smallest delta the page
    # actually PRINTS (2dp), so it must never read as unchanged.
    assert status(90.0 - 0.01, 90.0) == coverage.STATUS_REGRESSED
    assert status(90.0 + 0.01, 90.0) == coverage.STATUS_IMPROVED
    # strictly inside the dead zone: rounding noise reads as unchanged
    assert status(90.0 + 0.001, 90.0) == coverage.STATUS_UNCHANGED
    assert status(90.0, 90.0) == coverage.STATUS_UNCHANGED


def test_the_page_carries_its_notes_and_its_scope_limits():
    """Disclosures must reach the PAGE, not merely sit in the report dict.

    Deleting the whole Notes section (X2) and dropping SCOPE_LIMITS from the footer
    (X5) each survived the entire 86-test suite. A report that silently omits its own
    caveats reads as MORE complete than it is, which is the one thing a coverage page
    must never do — the caveats are how the reader knows what the number excludes.
    """
    report = _report(_xml(_cls("a/x.py", _line(1, 1))))
    report["notes"] = ["baseline was produced by a different python version"]
    page = coverage.render_html(report)
    # X2: the section AND its content, not just the heading
    assert "<h2>Notes</h2>" in page
    assert "baseline was produced by a different python version" in page
    # X5: the footer states the scope. Asserted via an escape-free fragment because
    # the footer HTML-escapes SCOPE_LIMITS (it contains an apostrophe).
    # Assert a LATE fragment, not a prefix: truncating SCOPE_LIMITS to its first 13
    # characters ("Cobertura XML") passed the whole suite while dropping ~700 chars
    # of scope. Both fragments are pinned against the constant so the indirection
    # cannot rot, and the page must carry the tail as well as the head.
    tail = "never per line"
    assert "Cobertura XML" in coverage.SCOPE_LIMITS
    assert tail in coverage.SCOPE_LIMITS, "late fragment must stay in SCOPE_LIMITS"
    assert "Scope:" in page and "Cobertura XML" in page and tail in page
    # and a report with no notes must not grow an empty Notes section
    bare = coverage.render_html(_report(_xml(_cls("a/x.py", _line(1, 1)))))
    assert "<h2>Notes</h2>" not in bare


def test_the_page_discloses_why_no_per_file_delta_and_lists_unmeasured_files():
    """The two remaining disclosure mutations (X6, X7), each survived 86 tests.

    X6 deleted the sentence explaining that per-FILE deltas are not stored, and X7
    dropped the Unmeasured per-file list. Both leave a page that looks complete: a
    missing per-file delta column with no explanation invites the reader to assume
    zero, and a file with no statement inventory that is never listed simply does not
    exist as far as the page is concerned. `render_html`'s own prose promises such
    files are "listed as UNKNOWN below, never as 0%".
    """
    report = _report(_xml(_cls("a/x.py", _line(1, 1))))
    page = coverage.render_html(report)
    # X6: the reason no per-file delta is shown, and that it is not an implied zero
    assert "Per-FILE deltas are not stored" in page
    assert "implying zero" in page
    # X7: the section exists even when empty, and says so positively rather than
    # rendering nothing (a silent absence is indistinguishable from "not checked")
    assert "<h2>Unmeasured</h2>" in page
    assert "carried a statement inventory" in page

    # and when a file IS unmeasured it is named, with its reason, not just counted
    unk = _report(_xml(_cls("a/x.py", _line(1, 1))))
    for f in unk["files"]:
        f["pct"] = None
        f["unknown_reason"] = "no statement inventory in the XML"
    page2 = coverage.render_html(unk)
    assert "a/x.py" in page2
    assert "no statement inventory in the XML" in page2


def test_the_module_ROW_carries_the_unknown_reason_not_only_the_unmeasured_list():
    """Pins the CALL SITES, which a unit test on _pct_cell cannot reach.

    test_unknown_cells_carry_their_reason_as_a_title exercises `_pct_cell` directly, so
    it proves the primitive renders a title — and proves nothing about render_html
    PASSING the reason in. Mutating `_pct_cell(mod["pct"], mod["unknown_reason"])` to
    `_pct_cell(mod["pct"], None)` at the call site left the page saying UNKNOWN with
    title="no data" and passed the whole suite: X1's exact defect, restored, green.

    The pre-existing `assert "divide by zero" in page` does not catch it either, and
    that is instructive — it passes off the Unmeasured <li>, not off the module row. So
    this test counts OCCURRENCES: an unmeasured module's reason must appear at least
    twice (once in its row, once in the list). A caller-side mutation drops it to one.
    """
    report = _report(_xml(_cls("a/x.py", _line(1, 1))))
    for f in report["files"]:
        f["pct"] = None
        f["unknown_reason"] = "no measurable statements were recorded"
    for m in report["modules"]:
        m["pct"] = None
        m["unknown_reason"] = "no measurable statements were recorded"
    page = coverage.render_html(report)
    reason = "no measurable statements were recorded"
    # the row AND the list, so a call site passing None is visible as a drop to 1
    # EXACTLY 2, not >=2: the pristine page mentions the reason twice (row + list), so a
    # `>=` bound sits on the boundary — a future third mention (a totals banner reusing
    # the string) would create slack and let a row-drop pass at 2. == is strictly tighter
    # and fails loudly if the page starts repeating itself, which is the moment to
    # re-scope this assertion rather than widen it.
    assert page.count(reason) == 2, (
        "the reason must reach the module ROW and the Unmeasured list, exactly once each"
    )
    # NOT asserting `title="no data"` is absent: that fallback legitimately appears in
    # the BASELINE column of a report with no baseline run, so the absence check failed
    # on the pristine module. Counting the real reason is the assertion that isolates a
    # caller passing None.


def test_the_baseline_column_carries_its_own_reason_too():
    """The OTHER _pct_cell call site — the one round 3 found still unpinned.

    coverage.py:1444 (the module's own percentage) is pinned by
    test_the_module_ROW_carries_the_unknown_reason_not_only_the_unmeasured_list. Line
    1447 renders the BASELINE column through the same primitive, and mutating it to
    `_pct_cell(d.get("baseline_pct"), None)` passed the whole suite: the baseline cell's
    tooltip silently degraded to "no data" while a real delta_reason existed. Same class
    as X1, one column over — which is exactly why a per-call-site assertion is needed
    rather than trusting the primitive's unit test.
    """
    # baseline record shape is {"id", "ts", "modules"} — a full report dict has no
    # run_id and render_html would raise on int(None), which my first fixture did.
    baseline = {"id": 9, "ts": 1699999999.0, "modules": [_mod("a", 90.0)]}
    cur = _report(
        _xml(_cls("a/x.py", _line(1, 1)) + _cls("b/new.py", _line(1, 1))),
        baseline=baseline,
    )
    rows = cur["comparison"]["modules"]
    unknown = [
        r for r in rows if r.get("baseline_pct") is None and r.get("delta_reason")
    ]
    assert unknown, "fixture must produce a row whose BASELINE percentage is unknown"
    page = coverage.render_html(cur)
    reason = unknown[0]["delta_reason"]
    # COUNT, do not use `in`: the same delta_reason is also rendered by _delta_cell in
    # the delta column, so `reason in page` still passes with the baseline column's copy
    # removed — verified: that mutation survived an `in` assertion. A substring assertion
    # against a whole page cannot say WHERE the substring came from.
    assert page.count(reason) == 2, (
        "the reason must appear in BOTH the baseline column and the delta column"
    )
