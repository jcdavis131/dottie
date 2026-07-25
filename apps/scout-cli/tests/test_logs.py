"""Logs — openswap #14 (Papertrail/Splunk/Loggly -> stdlib tailing log pipeline).

Encoding detection (incl. the repo's real UTF-16-LE research logs), unit-aligned
byte-offset tailing, per-source parsers, locale-independent timestamp parsing,
the indexed sqlite store, query/rollup, capability detection, and the subprocess
CLI envelope. Offline and deterministic by construction: this adapter has NO
network surface at all, every fixture is a real file written into tmp_path (no
mocked filesystem), and `now`/`ts` are explicit so nothing depends on wall clock.
"""

from __future__ import annotations

import calendar
import codecs
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import logs, openswap

ROOT = Path(__file__).resolve().parents[1]

# 2026-07-19T13:45:01Z, verified independently with calendar.timegm
TS_1345 = 1784468701.0


def _mem():
    return logs.open_store(":memory:")


def _write(path: Path, text: str, *, encoding: str = "utf-8", bom: bytes = b"") -> Path:
    path.write_bytes(bom + text.encode(encoding))
    return path


# ---- encoding detection -----------------------------------------------------


def test_detect_encoding_bom_table_orders_utf32_before_utf16():
    """UTF-32-LE's BOM starts with UTF-16-LE's, so order is load-bearing."""
    assert logs.detect_encoding(codecs.BOM_UTF32_LE + b"a\0\0\0") == {
        "encoding": "utf-32-le",
        "bom_len": 4,
        "unit": 4,
        "via": "bom",
    }
    assert logs.detect_encoding(codecs.BOM_UTF32_BE + b"\0\0\0a")["encoding"] == (
        "utf-32-be"
    )
    le = logs.detect_encoding(codecs.BOM_UTF16_LE + "hi\n".encode("utf-16-le"))
    assert le == {"encoding": "utf-16-le", "bom_len": 2, "unit": 2, "via": "bom"}
    be = logs.detect_encoding(codecs.BOM_UTF16_BE + "hi\n".encode("utf-16-be"))
    assert be["encoding"] == "utf-16-be" and be["unit"] == 2
    # a UTF-8 BOM is stripped by offset, so the codec name stays plain utf-8
    u8 = logs.detect_encoding(codecs.BOM_UTF8 + b"hi\n")
    assert u8 == {"encoding": "utf-8", "bom_len": 3, "unit": 1, "via": "bom"}


def test_detect_encoding_bomless_utf16_and_fallbacks():
    bomless = ("2026-07-19 INFO up\n" * 4).encode("utf-16-le")
    got = logs.detect_encoding(bomless)
    assert got["encoding"] == "utf-16-le" and got["bom_len"] == 0
    assert got["via"] == "nul-pattern"  # no BOM to go on — the NULs gave it away
    assert logs.detect_encoding(("2026-07-19 INFO up\n" * 4).encode("utf-16-be"))[
        "encoding"
    ] == "utf-16-be"
    plain = logs.detect_encoding(b"plain ascii line\n")
    assert plain["encoding"] == "utf-8" and plain["via"] == "utf-8"
    # invalid UTF-8 that is not UTF-16 either: latin-1 never raises, so ingest
    # degrades instead of dying, and `via` says so out loud
    junk = logs.detect_encoding(b"\xff\xfd\xfe caf\xe9 latin\n" * 4)
    assert junk["encoding"] == "latin-1" and junk["via"] == "fallback"


def test_detect_encoding_tolerates_a_char_cut_by_the_sample_boundary():
    # "é" is 2 bytes in UTF-8; cutting it in half must not demote to latin-1
    sample = ("x" * 20 + "é").encode("utf-8")[:-1]
    assert logs.detect_encoding(sample)["encoding"] == "utf-8"


# ---- line splitting + byte accounting ---------------------------------------


def test_split_complete_lines_leaves_a_partial_tail_unconsumed():
    raw = b"one\ntwo\nthr"
    lines, consumed = logs.split_complete_lines(raw, encoding="utf-8", unit=1)
    assert lines == ["one", "two"] and consumed == 8  # "thr" waits for its newline
    lines, consumed = logs.split_complete_lines(
        raw, encoding="utf-8", unit=1, include_partial=True
    )
    assert lines == ["one", "two", "thr"] and consumed == len(raw)
    # a chunk with no newline at all consumes nothing unless asked
    assert logs.split_complete_lines(b"nope", encoding="utf-8", unit=1) == ([], 0)


def test_split_complete_lines_strips_crlf_but_not_inner_unicode_breaks():
    raw = "a\r\nb still-b\r\n".encode()
    lines, consumed = logs.split_complete_lines(raw, encoding="utf-8", unit=1)
    # str.splitlines() would break on U+2028 and invent a third line
    assert lines == ["a", "b still-b"] and consumed == len(raw)


def test_split_complete_lines_utf16_consumes_whole_code_units():
    raw = "ok\nnext\npart".encode("utf-16-le")
    lines, consumed = logs.split_complete_lines(raw, encoding="utf-16-le", unit=2)
    assert lines == ["ok", "next"]
    assert consumed == len("ok\nnext\n") * 2 and consumed % 2 == 0


def test_split_complete_lines_skips_a_misaligned_newline_byte_pair():
    """In UTF-16-LE b"\\n\\x00" can straddle two unrelated code units."""
    # U+0A41 then U+4100 encode LE as 41 0a | 00 41 — a b"\n\x00" at an ODD index
    raw = "ok\nੁ䄀".encode("utf-16-le")
    assert raw.rfind(b"\n\x00") % 2 == 1  # the trap this test exists for
    lines, consumed = logs.split_complete_lines(raw, encoding="utf-16-le", unit=2)
    assert lines == ["ok"]  # the real newline, not the straddling byte pair
    assert consumed == 6  # "ok\n" in UTF-16-LE; the 2 decorative chars stay


# ---- levels -----------------------------------------------------------------


def test_normalize_level_aliases_and_syslog_priorities():
    assert logs.normalize_level("WARN") == "warning"
    assert logs.normalize_level("[Error]") == "error"
    assert logs.normalize_level("fatal") == "critical"
    assert logs.normalize_level("notice") == "info"
    assert logs.normalize_level(3) == "error"  # syslog priority 3 = err
    assert logs.normalize_level(7) == "debug"
    assert logs.normalize_level("nonsense") is None
    assert logs.normalize_level(True) is None  # bool is an int subclass — reject
    assert logs.level_rank("critical") < logs.level_rank("info")
    assert logs.level_rank("bogus") == len(logs.LEVELS)  # unknown sorts LAST


def test_sniff_level_picks_most_severe_and_respects_word_boundaries():
    assert logs.sniff_level("started ok") is None  # nothing invented
    assert logs.sniff_level("WARN slow disk, then ERROR losing writes") == "error"
    assert logs.sniff_level("connection error: timed out") == "error"
    # "UserWarning" has no word boundary before "Warning" — pytorch spam must
    # not silently promote thousands of trainer lines to warning
    assert logs.sniff_level("UserWarning: .grad on a non-leaf Tensor") is None


# ---- timestamps -------------------------------------------------------------


def test_parse_timestamp_iso_variants_and_zones():
    assert logs.parse_timestamp("2026-07-19T13:45:01Z") == TS_1345
    assert logs.parse_timestamp("2026-07-19 13:45:01") == TS_1345  # naive = UTC
    assert logs.parse_timestamp("2026-07-19 13:45:01,250") == TS_1345 + 0.25
    assert logs.parse_timestamp("2026-07-19T13:45:01.5") == TS_1345 + 0.5
    assert logs.parse_timestamp("2026-07-19T13:45") == TS_1345 - 1.0  # no seconds
    # explicit zones win over the source's tz_offset
    assert logs.parse_timestamp("2026-07-19T13:45:01+05:30") == TS_1345 - 19800.0
    assert logs.parse_timestamp("2026-07-19T13:45:01-0500") == TS_1345 + 18000.0
    assert (
        logs.parse_timestamp("2026-07-19T13:45:01+05:30", tz_offset=-18000.0)
        == TS_1345 - 19800.0
    )
    # a naive stamp from a UTC-5 writer shifts by the declared offset
    assert logs.parse_timestamp("2026-07-19 13:45:01", tz_offset=-18000.0) == (
        TS_1345 + 18000.0
    )


def test_parse_timestamp_epochs_seconds_and_milliseconds():
    assert logs.parse_timestamp(1784468701.5) == 1784468701.5
    assert logs.parse_timestamp("1784468701.5") == 1784468701.5
    assert logs.parse_timestamp(1784468701000) == 1784468701.0  # ms epoch
    assert logs.parse_timestamp("1784468701000") == 1784468701.0


def test_parse_timestamp_syslog_needs_the_year_from_the_caller():
    assert logs.parse_timestamp("Jul 19 13:45:01") is None  # no year in the line
    assert logs.parse_timestamp("Jul 19 13:45:01", year=2026) == TS_1345
    assert logs.parse_timestamp("Jul 19 13:45:01", year=2026, tz_offset=3600.0) == (
        TS_1345 - 3600.0
    )
    # hardcoded English months + calendar.timegm: a locale month name is not one
    assert logs.parse_timestamp("Jui 19 13:45:01", year=2026) is None


def test_parse_timestamp_rejects_non_timestamps():
    for bad in (None, True, False, "", "   ", "not a time", "123", "2026-13-45 99:99"):
        assert logs.parse_timestamp(bad) is None


def test_parse_timestamp_is_independent_of_the_host_timezone(monkeypatch):
    """timegm, never strptime/mktime — a TZ change cannot move an event."""
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    assert logs.parse_timestamp("2026-07-19T13:45:01Z") == TS_1345
    monkeypatch.setenv("TZ", "America/Chicago")
    assert logs.parse_timestamp("2026-07-19T13:45:01Z") == TS_1345
    assert logs.parse_timestamp("Jul 19 13:45:01", year=2026) == TS_1345


# ---- parsers ----------------------------------------------------------------


def test_parse_line_iso_shape():
    got = logs.parse_line(
        "2026-07-19 13:45:01,123 ERROR trainer: step 15 diverged", parser="iso"
    )
    assert got["parsed"] is True
    assert got["ts"] == TS_1345 + 0.123
    assert got["level"] == "error" and got["level_from"] == "field"
    assert got["message"] == "trainer: step 15 diverged"


def test_parse_line_bracket_shape():
    got = logs.parse_line(
        "[2026-07-19T13:45:01Z] [WARN] gpu clocks pinned at 780MHz", parser="bracket"
    )
    assert got["parsed"] is True and got["ts"] == TS_1345
    assert got["level"] == "warning" and got["message"] == "gpu clocks pinned at 780MHz"


def test_parse_line_syslog_shape_takes_the_year_and_sniffs_the_level():
    got = logs.parse_line(
        "Jul 19 13:45:01 dottie trainer[8123]: ERROR checkpoint lost",
        parser="syslog",
        year=2026,
    )
    assert got["parsed"] is True and got["ts"] == TS_1345
    assert got["level"] == "error" and got["level_from"] == "sniff"
    assert got["message"] == "ERROR checkpoint lost"
    # without a year the shape still matches; only the timestamp is unknown
    assert logs.parse_line("Jul 19 13:45:01 h p: hi", parser="syslog")["ts"] is None


def test_parse_line_jsonl_reads_the_usual_key_spellings():
    got = logs.parse_line(
        json.dumps({"timestamp": "2026-07-19T13:45:01Z", "severity": "warn",
                    "msg": "grad clip hit"}),
        parser="jsonl",
    )
    assert got["parsed"] is True and got["ts"] == TS_1345
    assert got["level"] == "warning" and got["message"] == "grad clip hit"
    # the research loop's real shape: epoch ts, no level, `action` as the message
    got = logs.parse_line(
        '{"ts": 1784468701.0, "action": "implement", "result": {"state": "ok"}}',
        parser="jsonl",
    )
    assert got["ts"] == TS_1345 and got["message"] == "implement"
    assert got["level"] == "info" and got["level_from"] == "default"
    # no message-ish key at all: the object itself is the event, not an empty line
    got = logs.parse_line('{"ts": 1784468701.0, "phase": 3}', parser="jsonl")
    assert got["message"] == '{"phase": 3, "ts": 1784468701.0}'


def test_parse_line_declared_parser_that_misses_reports_unparsed():
    got = logs.parse_line("Traceback (most recent call last):", parser="jsonl")
    assert got["parsed"] is False  # the honesty signal: wrong parser for this line
    assert got["ts"] is None and got["message"] == "Traceback (most recent call last):"
    assert got["parser"] == "jsonl"  # the DECLARED parser, not a silent swap
    # a JSON array is valid JSON but not a log record
    assert logs.parse_line("[1, 2, 3]", parser="jsonl")["parsed"] is False
    # plain matches everything by construction
    assert logs.parse_line("anything at all", parser="plain")["parsed"] is True


def test_parse_line_custom_regex_beats_the_builtin_parsers():
    pattern = (
        r"^(?P<level>[A-Z]+)\|(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
        r"\|(?P<message>.*)$"
    )
    got = logs.parse_line(
        "CRIT|2026-07-19T13:45:01Z|psu fan stalled", parser="iso", regex=pattern
    )
    assert got["parsed"] is True and got["ts"] == TS_1345
    assert got["level"] == "critical" and got["message"] == "psu fan stalled"


def test_parse_line_default_level_comes_from_the_source():
    got = logs.parse_line("no level anywhere", parser="plain", default_level="debug")
    assert got["level"] == "debug" and got["level_from"] == "default"


def test_parser_catalog_is_discoverable():
    names = {p["name"] for p in logs.parser_catalog()}
    assert {"iso", "bracket", "syslog", "jsonl", "plain"} <= names
    for spec in logs.parser_catalog():
        assert spec["description"] and spec["example"]


# ---- sources as config ------------------------------------------------------


def test_load_sources_defaults_are_repo_relative():
    srcs = logs.load_sources()
    assert srcs  # the box's own logs ship as defaults
    for name, cfg in srcs.items():
        assert not Path(cfg["path"]).is_absolute(), f"{name} hardcodes an absolute path"
        assert cfg["parser"] in logs.PARSERS


def test_load_sources_overlay_merges_and_drops(tmp_path):
    overlay = tmp_path / "srcs.json"
    overlay.write_text(
        json.dumps(
            {
                "research-loop": False,  # drop a default
                "trainer": {"parser": "plain"},  # merge into a default
                "mine": {"path": "logs/*.log", "parser": "iso", "level": "debug"},
            }
        ),
        encoding="utf-8",
    )
    srcs = logs.load_sources(str(overlay))
    assert "research-loop" not in srcs
    assert srcs["trainer"]["parser"] == "plain"
    assert srcs["trainer"]["path"] == logs.DEFAULT_SOURCES["trainer"]["path"]
    assert srcs["mine"] == {"path": "logs/*.log", "parser": "iso", "level": "debug"}


def test_load_sources_rejects_bad_config(tmp_path):
    def _load(payload):
        f = tmp_path / "bad.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        return logs.load_sources(str(f))

    for payload in (
        {"x": {"path": ""}},  # empty path
        {"x": {"parser": "iso"}},  # no path at all
        {"x": {"path": "a.log", "parser": "logstash"}},  # unknown parser
        {"x": {"path": "a.log", "regex": "(?P<oops>.*)"}},  # no message group
        {"x": {"path": "a.log", "regex": "([unclosed"}},  # uncompilable
        {"x": {"path": "a.log", "level": "loud"}},  # unknown level
        {"x": {"path": "a.log", "tz_offset": "late"}},  # not a number
        {"x": {"path": "a.log", "tz_offset": True}},  # bool is not a number
        {"x": ["a.log"]},  # not an object or false
        [1, 2],  # not an object at all
    ):
        with pytest.raises(ValueError):
            _load(payload)


def test_resolve_files_expands_globs_and_drops_misses(tmp_path):
    (tmp_path / "logs").mkdir()
    a = _write(tmp_path / "logs" / "a.log", "x\n")
    b = _write(tmp_path / "logs" / "b.log", "y\n")
    (tmp_path / "logs" / "c.txt").write_text("z\n", encoding="utf-8")
    got = logs.resolve_files({"path": "logs/*.log"}, root=tmp_path)
    assert got == sorted([a, b])  # sorted -> a pass over a glob is deterministic
    assert logs.resolve_files({"path": "logs/a.log"}, root=tmp_path) == [a]
    assert logs.resolve_files({"path": "logs/gone.log"}, root=tmp_path) == []
    assert logs.resolve_files({"path": "logs"}, root=tmp_path) == []  # a dir is not
    # an absolute path works too (the CLI accepts one), and so does an absolute glob
    assert logs.resolve_files({"path": str(a)}, root=tmp_path) == [a]
    assert logs.resolve_files({"path": str(tmp_path / "logs" / "*.log")}) == sorted(
        [a, b]
    )


def test_display_path_is_root_relative_and_posix(tmp_path):
    (tmp_path / "d").mkdir()
    f = _write(tmp_path / "d" / "a.log", "x\n")
    assert logs.display_path(f, tmp_path) == "d/a.log"  # forward slashes on Windows too


# ---- collection: offsets, rotation, Windows handles -------------------------


def test_collect_file_is_incremental_across_appends(tmp_path):
    conn = _mem()
    cfg = {"path": "app.log", "parser": "iso"}
    f = _write(
        tmp_path / "app.log",
        "2026-07-19 13:45:01 INFO boot\n2026-07-19 13:45:02 ERROR boom\n",
    )
    first = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=1000.0)
    assert first["ingested"] == 2 and first["lines"] == 2
    assert first["start"] == 0 and first["offset"] == f.stat().st_size
    assert first["by_level"] == {"info": 1, "error": 1}

    # re-running an unchanged file ingests NOTHING (this is the whole point)
    second = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=1001.0)
    assert second["ingested"] == 0 and second["lines"] == 0
    assert second["start"] == second["offset"] == first["offset"]
    assert len(logs.query(conn, limit=50)) == 2

    with f.open("a", encoding="utf-8") as fh:
        fh.write("2026-07-19 13:45:03 WARN slow\n")
    third = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=1002.0)
    assert third["ingested"] == 1 and third["start"] == first["offset"]
    assert third["by_level"] == {"warning": 1}
    # line numbers continue across passes rather than restarting at 1
    assert [e["line_no"] for e in logs.query(conn, limit=50, newest_first=False)] == (
        [1, 2, 3]
    )


def test_collect_file_waits_for_a_partial_line_to_finish(tmp_path):
    conn = _mem()
    cfg = {"path": "app.log", "parser": "plain"}
    f = _write(tmp_path / "app.log", "complete line\n")
    assert logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=1.0)["ingested"] == 1
    with f.open("a", encoding="utf-8") as fh:
        fh.write("half a li")  # the writer is mid-flush
    mid = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=2.0)
    assert mid["ingested"] == 0 and mid["offset"] == len("complete line\n")
    with f.open("a", encoding="utf-8") as fh:
        fh.write("ne now\n")
    done = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=3.0)
    assert done["ingested"] == 1
    assert logs.query(conn, limit=5)[0]["message"] == "half a line now"  # never split


def test_collect_file_include_partial_consumes_a_file_with_no_final_newline(tmp_path):
    conn = _mem()
    cfg = {"path": "app.log", "parser": "plain"}
    f = _write(tmp_path / "app.log", "a\nb\nlast line no newline")
    tail = logs.collect_file(
        conn, "app", f, cfg, root=tmp_path, now=1.0, include_partial=True
    )
    assert tail["ingested"] == 3 and tail["offset"] == f.stat().st_size
    assert logs.query(conn, limit=1)[0]["message"] == "last line no newline"


def test_collect_file_resets_when_the_file_shrinks(tmp_path):
    conn = _mem()
    cfg = {"path": "app.log", "parser": "plain"}
    f = _write(tmp_path / "app.log", "one\ntwo\nthree\n")
    logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=1.0)
    # rotation: the writer truncated and started over at the same path
    _write(f, "fresh\n")
    after = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=2.0)
    assert after["rotated"] is True
    assert after["start"] == 0 and after["ingested"] == 1
    assert logs.query(conn, limit=1)[0]["line_no"] == 1  # numbering restarts
    off = logs.get_offset(conn, "app", "app.log")
    assert off["rotations"] == 1 and off["lines"] == 1


def test_collect_file_holds_no_handle_so_the_writer_can_rotate(tmp_path):
    """On Windows an open handle blocks unlink/rename — the tailer must not hold one."""
    conn = _mem()
    cfg = {"path": "app.log", "parser": "plain"}
    f = _write(tmp_path / "app.log", "line\n")
    logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=1.0)
    rotated = tmp_path / "app.log.1"
    f.rename(rotated)  # PermissionError here if we kept the file open
    assert rotated.exists() and not f.exists()
    rotated.unlink()


def test_collect_file_survives_an_unreadable_file(tmp_path):
    conn = _mem()
    missing = tmp_path / "gone.log"
    res = logs.collect_file(conn, "app", missing, {"path": "gone.log"}, root=tmp_path)
    assert res["error"] and "Error" in res["error"]  # FileNotFoundError, reported
    assert res["ingested"] == 0


def test_collect_file_max_bytes_caps_a_pass_and_says_so(tmp_path):
    conn = _mem()
    cfg = {"path": "big.log", "parser": "plain"}
    f = _write(tmp_path / "big.log", "".join(f"line {i}\n" for i in range(200)))
    first = logs.collect_file(
        conn, "app", f, cfg, root=tmp_path, now=1.0, max_bytes=100
    )
    assert first["capped"] is True and 0 < first["ingested"] < 200
    total = first["ingested"]
    for i in range(60):  # drain it with repeated passes
        got = logs.collect_file(
            conn, "app", f, cfg, root=tmp_path, now=2.0 + i, max_bytes=100
        )
        total += got["ingested"]
        if got["ingested"] == 0:
            break
    assert total == 200  # every line arrives exactly once, no gaps, no dupes


def test_collect_file_utf16_lines_decode_to_real_text(tmp_path):
    """The repo's own research logs are UTF-16-LE with a BOM."""
    conn = _mem()
    cfg = {"path": "u16.log", "parser": "iso"}
    f = _write(
        tmp_path / "u16.log",
        "2026-07-19 13:45:01 INFO ünïcode ✓ start\r\n"
        "2026-07-19 13:45:02 ERROR bööm\r\n",
        encoding="utf-16-le",
        bom=codecs.BOM_UTF16_LE,
    )
    res = logs.collect_file(conn, "res", f, cfg, root=tmp_path, now=1.0)
    assert res["encoding"] == "utf-16-le" and res["detected_via"] == "bom"
    assert res["start"] == 2  # the BOM is never handed to the parser
    assert res["ingested"] == 2 and res["offset"] == f.stat().st_size
    rows = logs.query(conn, limit=5, newest_first=False)
    assert rows[0]["message"] == "ünïcode ✓ start" and rows[0]["ts"] == TS_1345
    assert rows[1]["level"] == "error" and rows[1]["message"] == "bööm"
    # and it stays incremental in a 2-byte-per-unit encoding
    with f.open("ab") as fh:
        fh.write("2026-07-19 13:45:03 WARN late\r\n".encode("utf-16-le"))
    again = logs.collect_file(conn, "res", f, cfg, root=tmp_path, now=2.0)
    assert again["ingested"] == 1 and again["offset"] == f.stat().st_size


def test_collect_no_record_leaves_the_store_untouched(tmp_path):
    conn = _mem()
    cfg = {"path": "app.log", "parser": "plain"}
    f = _write(tmp_path / "app.log", "a\nb\n")
    dry = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=1.0, record=False)
    assert dry["ingested"] == 2  # it reports what it WOULD ingest
    assert logs.query(conn, limit=5) == []  # ...and wrote nothing
    assert logs.get_offset(conn, "app", "app.log") is None  # tail did not advance
    wet = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=2.0)
    assert wet["ingested"] == 2  # so a real pass still gets both lines


def test_collect_pass_covers_every_source_and_reports_empty_ones(tmp_path):
    conn = _mem()
    (tmp_path / "svc").mkdir()
    _write(tmp_path / "svc" / "a.log", "2026-07-19 13:45:01 INFO a\n")
    _write(tmp_path / "svc" / "b.log", "2026-07-19 13:45:02 ERROR b\n")
    _write(tmp_path / "flat.jsonl", '{"ts": 1784468701.0, "level": "warn", "msg": "w"}\n')
    sources = {
        "svc": {"path": "svc/*.log", "parser": "iso"},
        "flat": {"path": "flat.jsonl", "parser": "jsonl"},
        "absent": {"path": "nothing/*.log", "parser": "plain"},
    }
    res = logs.collect(conn, sources, root=tmp_path, now=500.0)
    assert res["ingested"] == 3 and res["parsed"] == 3 and res["unparsed"] == 0
    assert res["by_level"] == {"info": 1, "error": 1, "warning": 1}
    assert res["sources"]["svc"]["files"] == 2
    # a source whose glob matches nothing is REPORTED, not silently dropped
    assert res["sources"]["absent"] == {
        "pattern": "nothing/*.log",
        "parser": "plain",
        "files": 0,
        "ingested": 0,
        "capped": False,
    }
    assert res["errors"] == []
    assert {e["source"] for e in logs.query(conn, limit=10)} == {"svc", "flat"}


def test_collect_undated_lines_fall_back_to_ingest_time_and_say_so(tmp_path):
    conn = _mem()
    _write(tmp_path / "app.log", "no timestamp here\n")
    logs.collect(
        conn, {"a": {"path": "app.log", "parser": "plain"}}, root=tmp_path, now=777.0
    )
    row = logs.query(conn, limit=1)[0]
    assert row["ts"] == 777.0 and row["dated"] == 0  # honest about the fallback
    # which means a time filter still finds it instead of silently dropping it
    assert len(logs.query(conn, since=700.0, until=800.0)) == 1


# ---- query + rollup ---------------------------------------------------------


def _seed(conn, entries):
    rows = [
        {
            "source": src,
            "path": f"{src}.log",
            "line_no": i + 1,
            "ts": ts,
            "dated": True,
            "ingest_ts": 0.0,
            "level": level,
            "message": msg,
            "raw": raw or msg,
            "parser": "iso",
            "parsed": True,
        }
        for i, (src, ts, level, msg, raw) in enumerate(entries)
    ]
    logs.record_entries(conn, rows)


def test_query_level_is_a_floor_not_an_equality_test():
    conn = _mem()
    _seed(
        conn,
        [
            ("a", 100.0, "debug", "d", None),
            ("a", 200.0, "info", "i", None),
            ("a", 300.0, "warning", "w", None),
            ("b", 400.0, "error", "e", None),
            ("b", 500.0, "critical", "c", None),
        ],
    )
    assert [e["level"] for e in logs.query(conn, level="warning")] == [
        "critical",
        "error",
        "warning",
    ]
    assert [e["level"] for e in logs.query(conn, level="error")] == ["critical", "error"]
    assert len(logs.query(conn, level="trace")) == 5  # the floor of the floor
    assert [e["source"] for e in logs.query(conn, source="b")] == ["b", "b"]


def test_query_time_bounds_are_inclusive_and_ordering_is_selectable():
    conn = _mem()
    _seed(
        conn,
        [
            ("a", 100.0, "info", "first", None),
            ("a", 200.0, "info", "second", None),
            ("a", 300.0, "info", "third", None),
        ],
    )
    assert [e["message"] for e in logs.query(conn, since=200.0)] == ["third", "second"]
    assert [e["message"] for e in logs.query(conn, until=200.0)] == ["second", "first"]
    assert [e["message"] for e in logs.query(conn, since=200.0, until=200.0)] == (
        ["second"]
    )
    assert [e["message"] for e in logs.query(conn, newest_first=False)] == [
        "first",
        "second",
        "third",
    ]
    assert len(logs.query(conn, limit=2)) == 2


def test_query_contains_matches_message_or_raw_case_insensitively():
    conn = _mem()
    _seed(
        conn,
        [
            ("a", 100.0, "info", "phase_enter", '{"event":"phase_enter","seq":256}'),
            ("a", 200.0, "info", "Checkpoint Banked", None),
        ],
    )
    # a jsonl source's message is just an event name — the payload lives in raw
    assert [e["message"] for e in logs.query(conn, contains="seq")] == ["phase_enter"]
    assert [e["message"] for e in logs.query(conn, contains="checkpoint")] == (
        ["Checkpoint Banked"]
    )
    assert logs.query(conn, contains="%") == []  # a LIKE wildcard is a literal here


def test_rollup_buckets_by_time_level_and_source():
    conn = _mem()
    _seed(
        conn,
        [
            ("a", 0.0, "info", "i1", None),
            ("a", 100.0, "error", "e1", None),
            ("b", 3700.0, "warning", "w1", None),
            ("b", 7300.0, "error", "e2", None),
        ],
    )
    res = logs.rollup(conn, bucket_seconds=3600.0)
    assert res["total"] == 4 and res["dated"] == 4 and res["parsed"] == 4
    assert res["first_ts"] == 0.0 and res["last_ts"] == 7300.0
    assert res["by_level"] == {"error": 2, "warning": 1, "info": 1}
    assert res["by_source"] == {"a": 2, "b": 2}
    assert [b["start"] for b in res["buckets"]] == [0.0, 3600.0, 7200.0]
    assert res["buckets"][0] == {
        "start": 0.0,
        "count": 2,
        "by_level": {"info": 1, "error": 1},
    }
    # filters narrow the rollup the same way they narrow a query
    narrowed = logs.rollup(conn, level="error", bucket_seconds=3600.0)
    assert narrowed["total"] == 2 and narrowed["by_level"] == {"error": 2}
    assert logs.rollup(conn, source="b", bucket_seconds=3600.0)["total"] == 2
    assert logs.rollup(conn, since=3700.0, bucket_seconds=3600.0)["total"] == 2


def test_rollup_rejects_a_zero_width_bucket():
    conn = _mem()
    for bad in (0.0, -60.0):
        with pytest.raises(ValueError):
            logs.rollup(conn, bucket_seconds=bad)


def test_list_offsets_and_source_status_expose_how_far_behind_we_are(tmp_path):
    conn = _mem()
    cfg = {"path": "app.log", "parser": "plain"}
    f = _write(tmp_path / "app.log", "one\n")
    sources = {"app": cfg}
    logs.collect(conn, sources, root=tmp_path, now=10.0)
    with f.open("a", encoding="utf-8") as fh:
        fh.write("two\nthree\n")  # written but not yet collected
    board = logs.source_status(conn, sources, root=tmp_path)
    assert len(board) == 1 and board[0]["source"] == "app"
    row = board[0]["files"][0]
    assert row["offset"] == 4 and row["size"] == f.stat().st_size
    assert row["behind_bytes"] == row["size"] - 4  # visible WITHOUT ingesting
    assert row["encoding"] == "utf-8" and row["ingested"] == 1
    assert [o["path"] for o in logs.list_offsets(conn)] == ["app.log"]
    assert logs.list_offsets(conn, source="nope") == []


# ---- family schema + detection ----------------------------------------------


def test_to_diagnostics_maps_only_findings_and_sorts_them():
    entries = [
        {"source": "a", "path": "a.log", "line_no": 9, "level": "info",
         "message": "fine", "parser": "iso"},
        {"source": "a", "path": "a.log", "line_no": 4, "level": "warning",
         "message": "slow", "parser": "iso"},
        {"source": "a", "path": "a.log", "line_no": 7, "level": "error",
         "message": "boom", "parser": "iso"},
        {"source": "a", "path": "a.log", "line_no": 1, "level": "critical",
         "message": "dead", "parser": "iso"},
        {"source": "a", "path": "a.log", "line_no": 2, "level": "debug",
         "message": "noise", "parser": "iso"},
    ]
    diags = logs.to_diagnostics(entries)
    assert len(diags) == 3  # info/debug emit nothing
    assert [d["line"] for d in diags] == [1, 4, 7]  # sorted by position
    assert [d["severity"] for d in diags] == ["error", "warning", "error"]
    assert diags[0]["rule"] == "logs:critical" and diags[0]["path"] == "a:a.log"
    summary = openswap.summarize(diags)
    assert summary["by_severity"]["error"] == 2
    assert summary["by_severity"]["warning"] == 1


def test_severity_for_level_is_the_single_gate_mapping():
    assert logs.severity_for_level("critical") == "error"
    assert logs.severity_for_level("error") == "error"
    assert logs.severity_for_level("warning") == "warning"
    for quiet in ("info", "debug", "trace", "bogus"):
        assert logs.severity_for_level(quiet) is None


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.logs import cli as logs_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = logs_cli._capability()
    assert cap["adapter"] == "logs"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "lnav"
    # SaaS clients: surfaced for awareness, never executed
    assert cap["extras"]["papertrail"]["found"] is False
    assert cap["extras"]["splunk"]["found"] is False


def test_manifest_denies_network_entirely():
    from bigbang.core.policy import check_permission, load_manifest

    # bigbang/core/logs.py -> parents[1] is the bigbang package
    manifest = load_manifest(Path(logs.__file__).parents[1] / "plugins" / "logs")
    assert manifest["name"] == "logs"
    allowed, reason = check_permission(manifest, "network", "https://papertrailapp.com")
    assert allowed is False and "network disabled" in reason
    assert check_permission(manifest, "fs_write", ".scout/logs.db")[0] is True
    assert check_permission(manifest, "secret", "SPLUNK_TOKEN")[0] is False


# ---- adversarial ------------------------------------------------------------


def test_blank_lines_are_counted_but_never_stored(tmp_path):
    conn = _mem()
    f = _write(tmp_path / "app.log", "a\n\n   \nb\n")
    res = logs.collect_file(
        conn, "app", f, {"path": "app.log", "parser": "plain"}, root=tmp_path, now=1.0
    )
    assert res["lines"] == 4 and res["blank"] == 2 and res["ingested"] == 2
    # blank lines still occupy line numbers, so a reported line_no matches the file
    assert [e["line_no"] for e in logs.query(conn, newest_first=False)] == [1, 4]


def test_a_half_written_file_is_read_without_crashing(tmp_path):
    conn = _mem()
    f = tmp_path / "trunc.log"
    f.write_bytes(codecs.BOM_UTF16_LE[:1])  # one byte: not even a whole BOM
    cfg = {"path": "trunc.log", "parser": "plain"}
    first = logs.collect_file(conn, "t", f, cfg, root=tmp_path, now=1.0)
    assert first["error"] is None and first["ingested"] == 0
    second = logs.collect_file(conn, "t", f, cfg, root=tmp_path, now=2.0)
    assert second["rotated"] is False and second["ingested"] == 0


def test_a_misaligned_stored_offset_self_heals_instead_of_flapping(tmp_path):
    """Realigning a bad offset must never push it PAST end-of-file.

    A stored offset > size reads as a rotation on the next pass, which would
    re-ingest the whole file — so the realignment is clamped to the real size.
    """
    conn = _mem()
    # 4-byte UTF-32-LE BOM + 10 payload bytes: the size itself is not a whole
    # number of code units, so rounding an offset UP can overshoot EOF
    f = tmp_path / "u32.log"
    f.write_bytes(codecs.BOM_UTF32_LE + b"0123456789")
    assert f.stat().st_size == 14
    cfg = {"path": "u32.log", "parser": "plain"}
    logs.save_offset(
        conn,
        "u32",
        "u32.log",
        offset=13,  # mid-code-unit: realignment wants byte 16, past the 14-byte EOF
        size=13,
        mtime=1.0,
        encoding="utf-32-le",
        lines=0,
        ingested=0,
        rotations=0,
        now=1.0,
    )
    first = logs.collect_file(conn, "u32", f, cfg, root=tmp_path, now=2.0)
    assert first["start"] == 16  # realigned up to the next code-unit boundary
    assert first["offset"] <= first["size"]  # ...but never STORED past EOF
    second = logs.collect_file(conn, "u32", f, cfg, root=tmp_path, now=3.0)
    assert second["rotated"] is False  # no phantom rotation, no re-ingest loop
    assert logs.get_offset(conn, "u32", "u32.log")["rotations"] == 0


def test_crlf_and_unicode_survive_the_round_trip(tmp_path):
    conn = _mem()
    f = _write(tmp_path / "app.log", "2026-07-19 13:45:01 INFO 実験-α ✓\r\n")
    logs.collect_file(
        conn, "app", f, {"path": "app.log", "parser": "iso"}, root=tmp_path, now=1.0
    )
    row = logs.query(conn, limit=1)[0]
    assert row["message"] == "実験-α ✓" and "\r" not in row["raw"]


def test_syslog_year_comes_from_the_file_mtime_not_from_now(tmp_path):
    import os as _os

    conn = _mem()
    f = _write(tmp_path / "sys.log", "Jul 19 13:45:01 dottie trainer[1]: hello\n")
    # backdate the file to 2019; the parsed year must follow the FILE, not today
    stamp = calendar.timegm((2019, 7, 19, 13, 45, 1, 0, 0, 0))
    _os.utime(f, (stamp, stamp))
    logs.collect_file(
        conn, "sys", f, {"path": "sys.log", "parser": "syslog"}, root=tmp_path, now=1.0
    )
    row = logs.query(conn, limit=1)[0]
    assert row["ts"] == float(calendar.timegm((2019, 7, 19, 13, 45, 1, 0, 0, 0)))
    assert row["dated"] == 1


def test_source_tz_offset_shifts_naive_timestamps(tmp_path):
    conn = _mem()
    f = _write(tmp_path / "app.log", "2026-07-19 13:45:01 INFO local clock\n")
    logs.collect_file(
        conn,
        "app",
        f,
        {"path": "app.log", "parser": "iso", "tz_offset": -18000},
        root=tmp_path,
        now=1.0,
    )
    assert logs.query(conn, limit=1)[0]["ts"] == TS_1345 + 18000.0


# ---- the real CLI in a subprocess (fully offline — no network surface) -------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(cwd or ROOT),
    )


def _data(res):
    assert res.returncode == 0, res.stderr + res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    return payload["data"]


def test_cli_logs_hello_envelope():
    data = _data(_cli(["logs", "hello"]))
    assert data["ready"] is True and data["plugin"] == "logs"


def test_cli_logs_parsers_lists_the_catalog():
    data = _data(_cli(["logs", "parsers"]))
    assert {p["name"] for p in data["parsers"]} >= {"iso", "jsonl", "syslog", "plain"}
    assert data["default_level"] == "info"


def test_cli_logs_collect_query_rollup_loop(tmp_path):
    db = str(tmp_path / "logs.db")
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "api.log").write_text(
        "2026-07-19 13:45:01 INFO boot ok\n"
        "2026-07-19 13:45:02 ERROR upstream refused\n"
        "2026-07-19 14:45:03 WARN retry budget low\n",
        encoding="utf-8",
    )
    (tmp_path / "events.jsonl").write_text(
        '{"ts": 1784468704.0, "level": "critical", "msg": "disk full"}\n',
        encoding="utf-8",
    )
    srcs = tmp_path / "srcs.json"
    srcs.write_text(
        json.dumps(
            {
                "research-loop": False,
                "trainer": False,
                "telemetry": False,
                "api": {"path": "svc/*.log", "parser": "iso"},
                "events": {"path": "events.jsonl", "parser": "jsonl"},
            }
        ),
        encoding="utf-8",
    )
    common = ["--db", db, "--sources", str(srcs), "--root", str(tmp_path)]

    data = _data(_cli(["logs", "collect", *common]))
    assert data["ingested"] == 4 and data["unparsed"] == 0
    assert data["by_level"] == {"info": 1, "error": 1, "warning": 1, "critical": 1}
    assert data["errors"] == []

    # a second pass is a no-op: the offsets did their job
    assert _data(_cli(["logs", "collect", *common]))["ingested"] == 0

    # query: the level filter is a floor, and time bounds work
    data = _data(_cli(["logs", "query", "--db", db, "--level", "warning"]))
    assert data["count"] == 3
    assert data["summary"]["by_severity"] == {
        "error": 2,
        "warning": 1,
        "suggestion": 0,
        "info": 0,
    }
    data = _data(
        _cli(
            ["logs", "query", "--db", db, "--since", "2026-07-19T14:00:00Z",
             "--oldest-first"]
        )
    )
    assert [e["message"] for e in data["entries"]] == ["retry budget low"]
    data = _data(_cli(["logs", "query", "--db", db, "--contains", "upstream"]))
    assert data["count"] == 1 and data["entries"][0]["level"] == "error"
    data = _data(_cli(["logs", "query", "--db", db, "--source", "events"]))
    assert data["count"] == 1 and data["entries"][0]["level"] == "critical"

    # rollup: hourly buckets over the same store
    data = _data(_cli(["logs", "rollup", "--db", db, "--bucket", "3600"]))
    assert data["total"] == 4 and data["by_source"] == {"api": 3, "events": 1}
    assert len(data["buckets"]) == 2

    # sources board shows the tails are caught up
    data = _data(
        _cli(["logs", "sources", "--db", db, "--sources", str(srcs),
              "--root", str(tmp_path)])
    )
    assert data["count"] == 2 and data["tracked_files"] == 2
    assert all(f["behind_bytes"] == 0 for s in data["sources"] for f in s["files"])


def test_cli_logs_collect_reads_utf16_end_to_end(tmp_path):
    db = str(tmp_path / "logs.db")
    (tmp_path / "run.log").write_bytes(
        codecs.BOM_UTF16_LE
        + (
            '{"ts": 1784468701.0, "action": "implement", "state": "ok"}\r\n'
            '{"ts": 1784468702.0, "level": "error", "msg": "candidate crashed"}\r\n'
        ).encode("utf-16-le")
    )
    srcs = tmp_path / "srcs.json"
    srcs.write_text(
        json.dumps(
            {
                "research-loop": False,
                "trainer": False,
                "telemetry": False,
                "run": {"path": "run.log", "parser": "jsonl"},
            }
        ),
        encoding="utf-8",
    )
    data = _data(
        _cli(["logs", "collect", "--db", db, "--sources", str(srcs),
              "--root", str(tmp_path)])
    )
    assert data["ingested"] == 2 and data["unparsed"] == 0
    assert data["files"][0]["encoding"] == "utf-16-le"
    assert data["files"][0]["detected_via"] == "bom"
    # decoded as real text, not NUL-riddled mojibake
    data = _data(_cli(["logs", "query", "--db", db, "--oldest-first"]))
    assert [e["message"] for e in data["entries"]] == [
        "implement",
        "candidate crashed",
    ]
    assert data["entries"][0]["ts"] == TS_1345


def test_cli_logs_collect_fail_on_gates_on_this_pass_only(tmp_path):
    db = str(tmp_path / "logs.db")
    (tmp_path / "app.log").write_text(
        "2026-07-19 13:45:01 ERROR disk offline\n", encoding="utf-8"
    )
    srcs = tmp_path / "srcs.json"
    srcs.write_text(
        json.dumps(
            {
                "research-loop": False,
                "trainer": False,
                "telemetry": False,
                "app": {"path": "app.log", "parser": "iso"},
            }
        ),
        encoding="utf-8",
    )
    common = ["--db", db, "--sources", str(srcs), "--root", str(tmp_path)]
    res = _cli(["logs", "collect", *common, "--fail-on", "error"])
    assert res.returncode == 1  # the error line fires the gate
    body = json.loads(res.stdout)["data"]
    assert body["gate"] == {
        "fail_on": "error",
        "triggered": True,
        "counts": {"error": 1},
    }
    # the SAME error is already stored, but a second pass collected nothing new,
    # so today's cron run is green — a stale error must not fail it forever
    res = _cli(["logs", "collect", *common, "--fail-on", "error"])
    assert res.returncode == 0
    assert json.loads(res.stdout)["data"]["gate"]["triggered"] is False
    # ...while a query over the store still finds it and can gate explicitly
    assert _cli(["logs", "query", "--db", db, "--fail-on", "error"]).returncode == 1


def test_cli_logs_query_without_store_fails_actionably(tmp_path):
    res = _cli(["logs", "query", "--db", str(tmp_path / "none.db")])
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    assert "no log store" in payload["error"]
    assert "example" in payload


def test_cli_logs_rejects_bad_arguments(tmp_path):
    db = str(tmp_path / "logs.db")
    (tmp_path / "a.log").write_text("hi\n", encoding="utf-8")
    srcs = tmp_path / "srcs.json"
    srcs.write_text(
        json.dumps(
            {"research-loop": False, "trainer": False, "telemetry": False,
             "a": {"path": "a.log", "parser": "plain"}}
        ),
        encoding="utf-8",
    )
    assert _cli(
        ["logs", "collect", "--db", db, "--sources", str(srcs),
         "--root", str(tmp_path)]
    ).returncode == 0
    for args, needle in (
        (["logs", "query", "--db", db, "--level", "loud"], "--level must be one of"),
        (["logs", "query", "--db", db, "--since", "yesterday"], "--since must be"),
        (["logs", "query", "--db", db, "--fail-on", "nope"], "--fail-on must be"),
        (["logs", "rollup", "--db", db, "--bucket", "0"], "bucket_seconds"),
    ):
        res = _cli(args)
        assert res.returncode == 1, res.stdout
        assert needle in json.loads(res.stdout)["error"], res.stdout


def test_cli_logs_bad_sources_file_fails_actionably(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"x": {"path": "a.log", "parser": "logstash"}}),
                   encoding="utf-8")
    res = _cli(["logs", "collect", "--db", str(tmp_path / "l.db"),
                "--sources", str(bad), "--root", str(tmp_path)])
    assert res.returncode == 1
    assert "unknown parser" in json.loads(res.stdout)["error"]


# ---- gap closers: verified to kill mutants that the suite currently survives --


def test_collect_file_counts_unparseable_lines_as_unparsed(tmp_path):
    """A declared parser that MISSES must split the counters, not inflate `parsed`.

    The suite asserts `unparsed == 0` on all-clean fixtures, which a collector
    that never increments `unparsed` also satisfies. This pins the positive case:
    malformed lines are ingested, kept verbatim, and counted as misses.
    """
    conn = _mem()
    cfg = {"path": "app.log", "parser": "iso"}  # iso is DECLARED...
    f = _write(
        tmp_path / "app.log",
        "2026-07-19 13:45:01 INFO real iso line\n"
        "this line has no iso timestamp at all\n"
        "neither does this one\n",
    )
    res = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=900.0)
    assert res["ingested"] == 3  # nothing is dropped for failing to parse
    assert res["parsed"] == 1  # ...exactly one line actually MATCHED iso
    assert res["unparsed"] == 2  # ...and the misses are counted as misses
    assert res["parsed"] + res["unparsed"] == res["ingested"]
    assert res["dated"] == 1  # only the matching line carried a timestamp
    rows = sorted(logs.query(conn, limit=5), key=lambda r: r["line_no"])
    assert [r["parsed"] for r in rows] == [1, 0, 0]
    assert [r["parser"] for r in rows] == ["iso"] * 3  # declared, never swapped
    # an unparsed line still lands, verbatim, at ingest time and says so
    assert rows[1]["raw"] == "this line has no iso timestamp at all"
    assert rows[1]["message"] == "this line has no iso timestamp at all"
    assert rows[1]["ts"] == 900.0 and rows[1]["dated"] == 0


def test_collect_file_applies_the_sources_declared_default_level(tmp_path):
    """`level` on a source is the floor for lines that carry none (policy-as-config)."""
    conn = _mem()
    f = _write(tmp_path / "d.log", "no level word here\n")
    cfg = {"path": "d.log", "parser": "plain", "level": "debug"}
    res = logs.collect_file(conn, "d", f, cfg, root=tmp_path, now=5.0)
    assert res["by_level"] == {"debug": 1}  # NOT the global 'info' default
    assert res["level_from"] == {"default": 1}
    assert logs.query(conn, limit=1)[0]["level"] == "debug"
    assert logs.DEFAULT_LEVEL == "info"  # so the assertion above is a real contrast
    # ...and a declared default never overrides a level the line does carry
    f2 = _write(tmp_path / "e.log", "ERROR exploded\n")
    res2 = logs.collect_file(
        conn, "e", f2, {"path": "e.log", "parser": "plain", "level": "debug"},
        root=tmp_path, now=6.0,
    )
    assert res2["by_level"] == {"error": 1} and res2["level_from"] == {"sniff": 1}


def test_normalize_level_maps_the_whole_syslog_priority_table():
    """All 8 priorities, not just a spot check.

    3->error / 4->warning is the boundary an off-by-one hides in, and it is the
    one that decides whether `--fail-on error` fires.
    """
    assert [logs.normalize_level(p) for p in range(8)] == [
        "critical", "critical", "critical", "error",
        "warning", "info", "info", "debug",
    ]
    # outside 0..7 is not a syslog priority and must not be invented into one
    assert logs.normalize_level(8) is None and logs.normalize_level(-1) is None


def test_offsets_ingested_counter_is_cumulative_across_passes(tmp_path):
    """`lines`/`ingested` on the offset row are LIFETIME totals, not per-pass.

    A single-pass fixture cannot tell the two apart (both read 2), so this takes
    a second pass — which is where a per-pass overwrite becomes visible.
    """
    conn = _mem()
    cfg = {"path": "app.log", "parser": "plain"}
    f = _write(tmp_path / "app.log", "one\ntwo\n")
    logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=1.0)
    first = logs.get_offset(conn, "app", "app.log")
    assert first["ingested"] == 2 and first["lines"] == 2
    with f.open("a", encoding="utf-8") as fh:
        fh.write("three\n")
    second = logs.collect_file(conn, "app", f, cfg, root=tmp_path, now=2.0)
    assert second["ingested"] == 1  # the PASS ingested one new line...
    row = logs.get_offset(conn, "app", "app.log")
    assert row["ingested"] == 3  # ...while the STORE tracks all three
    assert row["lines"] == 3 and row["rotations"] == 0
    # and the lifetime figure is what the operator board surfaces
    board = logs.source_status(conn, {"app": cfg}, root=tmp_path)
    assert board[0]["files"][0]["ingested"] == 3


def test_split_complete_lines_include_partial_stays_unit_aligned():
    """--include-partial must still consume WHOLE code units.

    A UTF-16 file whose final character is half-written would otherwise leave the
    stored offset on an odd byte and desync every later pass.
    """
    raw = "a\r\nbc".encode("utf-16-le")[:-1]  # 10 bytes, last char cut in half
    assert len(raw) == 9
    lines, consumed = logs.split_complete_lines(
        raw, encoding="utf-16-le", unit=2, include_partial=True
    )
    assert consumed == 8 and consumed % 2 == 0  # never lands mid code unit
    assert lines == ["a", "b"]  # the half character is left for the next pass
    # the aligned tail is still consumed when it IS complete
    whole = "a\r\nbc".encode("utf-16-le")
    lines2, consumed2 = logs.split_complete_lines(
        whole, encoding="utf-16-le", unit=2, include_partial=True
    )
    assert consumed2 == 10 and lines2 == ["a", "bc"]
