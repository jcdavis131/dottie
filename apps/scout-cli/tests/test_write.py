"""The write plugin's output path. 904 loc, no test file until 2026-08-02.

GOAT scored write 6.33 with D4 0. Reading the two D3 "HOME-layout" lines found a data-loss
bug sitting next to them.

BOTH SAVE SITES built the filename from `int(time.time())` — integer SECONDS — and then
called write_text on it. Two saves inside the same second produce the same name and the
second silently clobbers the first. Measured on the exact expression before changing it:

    5 saves in a tight loop -> 1 distinct filename
    files on disk           -> ['humanized-1785709805.md']
    surviving content       -> "document 4"          4 of 5 documents lost

`--save` is a promise the output is kept. Losing it silently is worse than refusing to
write. Higher resolution alone would only narrow the window; the existence check closes it,
and also covers a re-run landing in an already-populated directory.

SCOUT_WRITE_OUT was added in the same change, so these run against tmp_path instead of the
operator's ~/workspace/your_files/write-outputs.
"""

from __future__ import annotations

import pytest

from bigbang.plugins.write import cli as wc


@pytest.fixture(autouse=True)
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_WRITE_OUT", str(tmp_path))
    return tmp_path


def test_five_saves_in_one_second_keep_five_documents(out_dir):
    """The defect. This is the loop that lost 4 of 5."""
    for i in range(5):
        wc._next_output_path("humanized").write_text(f"document {i}\n", encoding="utf-8")

    files = sorted(p.name for p in out_dir.iterdir())
    assert len(files) == 5, files
    kept = sorted(p.read_text(encoding="utf-8").strip() for p in out_dir.iterdir())
    assert kept == sorted(f"document {i}" for i in range(5)), kept


def test_never_returns_a_path_that_already_exists(out_dir):
    """Covers the re-run case too: a directory already holding today's file."""
    first = wc._next_output_path("generated")
    first.write_text("x", encoding="utf-8")
    second = wc._next_output_path("generated")
    assert second != first
    assert not second.exists()


def test_the_first_save_keeps_the_plain_name(out_dir):
    """Non-vacuity for the suffixing: it must not suffix when there is no collision.

    A resolver that appended -1 unconditionally would pass the two tests above while
    changing every filename the operator already has.
    """
    p = wc._next_output_path("humanized")
    assert p.name.startswith("humanized-")
    assert not p.name.endswith("-1.md")


def test_output_dir_honours_scout_write_out(out_dir):
    assert wc._output_dir() == out_dir
    assert str(wc._next_output_path("humanized")).startswith(str(out_dir))


def test_output_dir_falls_back_to_the_home_layout(monkeypatch):
    """Non-vacuity for the override: the documented default must still be the default."""
    from pathlib import Path

    monkeypatch.delenv("SCOUT_WRITE_OUT", raising=False)
    assert wc._output_dir() == Path.home() / "workspace" / "your_files" / "write-outputs"


def test_output_dir_is_read_per_call_not_at_import(tmp_path, monkeypatch):
    """A module-level constant would bind before a harness could redirect it — the shape
    that bit ava-factory's telemetry _LOGS_DIR (53c5c60)."""
    monkeypatch.setenv("SCOUT_WRITE_OUT", str(tmp_path / "one"))
    first = wc._output_dir()
    monkeypatch.setenv("SCOUT_WRITE_OUT", str(tmp_path / "two"))
    assert wc._output_dir() != first


def test_the_directory_is_created_on_demand(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b" / "c"
    monkeypatch.setenv("SCOUT_WRITE_OUT", str(nested))
    assert not nested.exists()
    wc._next_output_path("humanized")
    assert nested.exists()
