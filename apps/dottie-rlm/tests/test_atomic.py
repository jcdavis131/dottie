"""atomic.py: missing is empty, unreadable is NOT — the fail-silent lesson."""

from __future__ import annotations

import json
import os
import threading

import pytest
from dottie_rlm import atomic


def test_missing_file_returns_the_default(tmp_path) -> None:
    assert atomic.read_json(tmp_path / "absent.json", {"d": 1}) == {"d": 1}


def test_corrupt_file_raises_and_preserves_the_bytes(tmp_path) -> None:
    p = tmp_path / "state.json"
    p.write_text('{"vault": ["HF_TOKEN"', encoding="utf-8")  # truncated
    with pytest.raises(atomic.CorruptStateFileError) as ei:
        atomic.read_json(p, {})
    assert "read-modify-write" in str(ei.value)
    preserved = list(tmp_path.glob("state.json.corrupt-*"))
    assert len(preserved) == 1
    assert preserved[0].read_text(encoding="utf-8") == '{"vault": ["HF_TOKEN"'


def test_write_json_round_trips_and_leaves_no_temp(tmp_path) -> None:
    p = tmp_path / "sub" / "s.json"
    atomic.write_json(p, {"a": [1, 2]})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": [1, 2]}
    assert list(p.parent.glob("*.tmp")) == []


def test_temp_name_is_per_process_and_per_thread(tmp_path) -> None:
    """A FIXED temp name is shared by every writer — the herd-ledger race."""
    p = tmp_path / "x.json"
    names = {atomic._temp_for(p).name}

    def other() -> None:
        names.add(atomic._temp_for(p).name)

    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert len(names) == 2, names
    assert all(str(os.getpid()) in n for n in names)


def test_concurrent_writers_all_succeed(tmp_path) -> None:
    p = tmp_path / "hot.json"
    errors: list[BaseException] = []

    def writer(i: int) -> None:
        try:
            for _ in range(20):
                atomic.write_json(p, {"w": i})
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [], errors
    assert isinstance(json.loads(p.read_text(encoding="utf-8")), dict)
    assert list(tmp_path.glob("*.tmp")) == []


def test_append_jsonl_is_append_only_under_concurrency(tmp_path) -> None:
    """Read-rewrite-replace appends LOSE lines when two writers interleave;
    open-append does not. 4 writers x 25 lines must yield exactly 100."""
    p = tmp_path / "ledger.jsonl"

    def writer(i: int) -> None:
        for j in range(25):
            atomic.append_jsonl(p, {"w": i, "j": j})

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    records = atomic.read_jsonl(p)
    assert len(records) == 100, len(records)
    assert len({(r["w"], r["j"]) for r in records}) == 100  # nothing clobbered


def test_read_jsonl_missing_is_empty_and_full_is_non_vacuous(tmp_path) -> None:
    assert atomic.read_jsonl(tmp_path / "none.jsonl") == []
    p = tmp_path / "l.jsonl"
    atomic.append_jsonl(p, {"a": 1})
    assert atomic.read_jsonl(p) == [{"a": 1}]  # anti-vacuity: really reads back


def test_a_truncated_last_line_is_dropped_loudly_not_silently(tmp_path, capsys) -> None:
    p = tmp_path / "l.jsonl"
    atomic.append_jsonl(p, {"good": 1})
    with p.open("a", encoding="utf-8") as fh:
        fh.write('{"partial": ')  # crash mid-append, no trailing newline
    assert atomic.read_jsonl(p) == [{"good": 1}]
    assert "truncated" in capsys.readouterr().err


def test_a_corrupt_middle_line_raises_rather_than_returning_partial(tmp_path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"a": 1}\nNOT JSON\n{"b": 2}\n', encoding="utf-8")
    with pytest.raises(atomic.CorruptStateFileError) as ei:
        atomic.read_jsonl(p)
    assert "partial history" in str(ei.value)
