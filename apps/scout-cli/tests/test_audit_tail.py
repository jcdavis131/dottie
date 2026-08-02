"""Audit tail: bounded reads, no silent loss.

Two defects, both measured on the real log (41.4 MB, 28,778 entries, 2026-08-01):

  1. `tail_events` did `read_text().split("\\n")[-n:]` — the WHOLE file into memory to
     return a handful of records. 154 ms to show 5 events in a status command, growing
     linearly in a file that only ever appends.
  2. Unparsable lines were dropped by `except Exception: pass`. The real log holds three
     (lines 6200, 8344, 13516), each an orphaned TAIL of a record whose head is gone while
     the line before it parses fine — the signature of concurrent appends, since
     `log_event` opens with "a" and writes with no lock. An audit trail that silently
     discards what it cannot parse reports a clean history whether or not it has one.

The write-side race is NOT fixed here: locking touches every CLI invocation and is a
separate call. These tests pin that the loss is at least counted.
"""

from __future__ import annotations

import json

import pytest

from bigbang.core import audit


@pytest.fixture
def audit_file(tmp_path, monkeypatch):
    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_FILE", p)
    return p


def _rec(i: int) -> str:
    return json.dumps({"ts": f"2026-08-01T00:00:{i:02d}", "command": f"c{i}",
                       "args": {}, "status": "ok", "duration_ms": i})


def test_returns_the_last_n_newest_last(audit_file):
    audit_file.write_text("\n".join(_rec(i) for i in range(10)) + "\n", encoding="utf-8")
    got = audit.tail_events(3)
    assert [e["command"] for e in got] == ["c7", "c8", "c9"]


def test_default_contract_is_still_a_plain_list(audit_file):
    """cockpit.py and system/cli.py index into the result; it must stay a list of dicts."""
    audit_file.write_text(_rec(1) + "\n", encoding="utf-8")
    got = audit.tail_events(5)
    assert isinstance(got, list) and isinstance(got[0], dict)


def test_crlf_records_parse_identically_to_lf(audit_file):
    """The tail reads BYTES; read_text() used to strip \\r for free on Windows.

    The real log has MIXED endings, so a byte-level reader that forgets this disagrees with
    the old implementation on every CRLF record. That regression was caught by diffing the
    two, not by a test — this is the test.
    """
    audit_file.write_bytes(
        (_rec(1) + "\r\n" + _rec(2) + "\n" + _rec(3) + "\r\n").encode("utf-8")
    )
    got = audit.tail_events(5)
    assert [e["command"] for e in got] == ["c1", "c2", "c3"]

    # Assert the RAW lines, not the parsed records. Checking only the parsed output lets
    # this pass with the \r still attached, because json.loads treats a trailing \r as
    # whitespace — verified by mutation: deleting the rstrip left all nine tests green.
    # A test that survives the removal of the code it exists to pin is not a test.
    raw = audit._read_last_lines(audit_file, 5)
    assert all(not ln.endswith("\r") for ln in raw), raw
    assert raw == [_rec(1), _rec(2), _rec(3)]


def test_corrupt_lines_are_counted_not_silently_dropped(audit_file):
    audit_file.write_text(
        _rec(1) + "\n" + 'rue}, "orphaned": "tail"}' + "\n" + _rec(2) + "\n",
        encoding="utf-8",
    )
    events, stats = audit.tail_events(10, return_stats=True)
    assert [e["command"] for e in events] == ["c1", "c2"]
    assert stats["skipped"] == 1, "a record was lost and the caller could not tell"
    assert stats["read"] == 3


def test_stats_report_zero_when_the_log_is_intact(audit_file):
    """Non-vacuity: `skipped` must be able to be 0, or the assertion above proves nothing."""
    audit_file.write_text("\n".join(_rec(i) for i in range(4)) + "\n", encoding="utf-8")
    _, stats = audit.tail_events(10, return_stats=True)
    assert stats == {"read": 4, "skipped": 0}


def test_reads_only_the_tail_not_the_whole_file(audit_file):
    """The point of the change. Asserted by BYTES READ, not by wall-clock.

    A timing assertion would be flaky on a loaded box and would pass for the wrong reason
    on a fast disk. Counting what the file object is asked for measures the property
    directly: a bounded tail must not read a file far larger than what it returns.
    """
    big = "\n".join(_rec(i) for i in range(20_000)) + "\n"
    audit_file.write_bytes(big.encode("utf-8"))
    total = len(big.encode("utf-8"))

    read_bytes = 0
    real_open = type(audit_file).open

    def counting_open(self, *a, **kw):
        fh = real_open(self, *a, **kw)
        real_read = fh.read

        def read(*ra, **rkw):
            nonlocal read_bytes
            data = real_read(*ra, **rkw)
            read_bytes += len(data)
            return data

        fh.read = read
        return fh

    import pathlib

    original = pathlib.Path.open
    pathlib.Path.open = counting_open
    try:
        got = audit.tail_events(5)
    finally:
        pathlib.Path.open = original

    assert len(got) == 5
    assert total > 1_000_000, "fixture too small to distinguish bounded from whole-file"
    assert read_bytes < total / 10, (
        f"read {read_bytes} of {total} bytes — the tail is not bounded"
    )


def test_missing_file_is_empty_not_an_error(audit_file):
    assert audit.tail_events(5) == []
    assert audit.tail_events(5, return_stats=True) == ([], {"read": 0, "skipped": 0})


def test_empty_file_is_empty(audit_file):
    audit_file.write_text("", encoding="utf-8")
    assert audit.tail_events(5) == []


def test_n_larger_than_the_log_returns_everything(audit_file):
    audit_file.write_text("\n".join(_rec(i) for i in range(3)) + "\n", encoding="utf-8")
    assert len(audit.tail_events(500)) == 3
