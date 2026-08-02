"""`agent bus` must not overstate its own completeness.

It aggregates every record in audit.jsonl to suggest automation candidates. Corrupt lines
were dropped by a bare `continue`, while the payload reported `commands_seen` and
per-command totals with no hint that anything was skipped — so counts come back quietly
short and a `--threshold` can be missed for a reason the output never mentions.

Not hypothetical: the real log holds 3 unparsable lines out of 28,778 (2026-08-01), each an
orphaned tail of a record whose head is gone, because `audit.log_event` appends with no
lock. Same defect fixed in `audit.tail_events`; this is its sibling reader.

The whole-file read here is CORRECT and deliberately left alone — this aggregates rather
than tails, so there is nothing to bound.
"""

from __future__ import annotations

import json

import pytest

from bigbang.core import audit
from bigbang.plugins.agent import cli as agent_cli


@pytest.fixture
def audit_file(tmp_path, monkeypatch):
    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_FILE", p)
    return p


@pytest.fixture
def emitted(monkeypatch):
    box = {}
    monkeypatch.setattr(agent_cli, "emit", lambda payload, **kw: box.update(payload))
    return box


def _rec(cmd: str) -> str:
    return json.dumps({"ts": "2026-08-01T00:00:00", "command": cmd, "args": {},
                       "status": "ok", "duration_ms": 1})


def test_corrupt_records_are_reported_not_silently_skipped(audit_file, emitted):
    audit_file.write_text(
        "\n".join([_rec("scout ls"), 'rue}, "orphaned": "tail"}', _rec("scout ls"),
                   "not json at all", _rec("scout ls")]) + "\n",
        encoding="utf-8",
    )
    agent_cli.bus(threshold=3)
    assert emitted["records_skipped"] == 2
    assert emitted["commands_seen"] == 1
    assert emitted["suggestions"][0]["times_run"] == 3


def test_reports_zero_when_the_log_is_intact(audit_file, emitted):
    """Non-vacuity: `records_skipped` must be able to be 0, or the check above is hollow."""
    audit_file.write_text("\n".join(_rec("scout ls") for _ in range(3)) + "\n",
                          encoding="utf-8")
    agent_cli.bus(threshold=3)
    assert emitted["records_skipped"] == 0
    assert emitted["suggestions"][0]["times_run"] == 3


def test_key_is_present_even_when_the_log_does_not_exist(audit_file, emitted):
    """Both exit paths carry the key, so a consumer never has to test for it."""
    assert not audit_file.exists()
    agent_cli.bus(threshold=3)
    assert emitted["records_skipped"] == 0
    assert emitted["suggestions"] == []


def test_skipped_records_do_not_inflate_command_counts(audit_file, emitted):
    """A corrupt line must not be counted as a command under any name."""
    audit_file.write_text(
        "\n".join([_rec("scout ls"), "{ broken", _rec("scout ls")]) + "\n",
        encoding="utf-8",
    )
    agent_cli.bus(threshold=2)
    assert emitted["records_skipped"] == 1
    assert emitted["commands_seen"] == 1
    assert emitted["suggestions"][0]["times_run"] == 2
