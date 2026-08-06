"""The live-status document must not lose accumulated state silently.

`_load_live_status` is deliberately NON-RAISING -- telemetry must never take down
a training run -- but it used to swallow a corrupt file and return {}. Callers do

    live = _load_live_status()
    if not live:
        live = {...fresh...}          # telemetry.py:255, :521

and then write it back, so one unreadable file reset uptime_sec and every
accumulated counter, and the next write made that permanent with no trace.

This is the same read-modify-write trap that destroyed the secrets vault in
scout-cli (fixed 3e301cb), but the answer differs: there the fix is to RAISE, here
raising would stop the trainer. So the reset stays, and is announced with the
previous bytes preserved.

    AVA_FACTORY_ROOT="$PWD" python -m pytest tests/test_telemetry_state.py -q
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dottie import telemetry


@pytest.fixture()
def live(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "LIVE_STATUS_PATH", tmp_path / "live_status.json")
    monkeypatch.setattr(telemetry, "LEGACY_LIVE", tmp_path / "legacy_live.json")
    return telemetry


class TestCorruptLiveStatus:
    def test_missing_file_is_empty_and_silent(self, live, capsys):
        """Missing IS genuinely empty. It must not warn, or the warning stops
        meaning anything on a first run."""
        assert live._load_live_status() == {}
        assert capsys.readouterr().err == ""

    def test_a_corrupt_file_still_returns_empty_rather_than_raising(self, live):
        """The constraint that makes this different from the vault: telemetry may
        not take down training."""
        live.LIVE_STATUS_PATH.write_text('{"uptime_sec": 91234, "step": 5')
        assert live._load_live_status() == {}

    def test_the_reset_is_announced(self, live, capsys):
        live.LIVE_STATUS_PATH.write_text('{"uptime_sec": 91234, "step": 5')
        live._load_live_status()
        err = capsys.readouterr().err
        assert "unreadable" in err, f"the reset was silent: {err!r}"
        assert "RESETS" in err, "the message does not say state is being discarded"

    def test_the_previous_bytes_are_preserved(self, live, tmp_path):
        """A reset is survivable; a reset that also destroys the only copy is not."""
        live.LIVE_STATUS_PATH.write_text('{"uptime_sec": 91234, "step": 5')
        live._load_live_status()
        backups = list(tmp_path.glob("live_status.json.corrupt-*"))
        assert len(backups) == 1, f"bytes not preserved: {list(tmp_path.iterdir())}"
        assert "91234" in backups[0].read_text(), "the preserved copy is not the data"

    def test_the_same_damage_is_not_reported_twice(self, live, capsys):
        """LEGACY_LIVE is a symlink to LIVE_STATUS_PATH, so retrying it would
        re-read the same bytes and double-report one fault."""
        live.LIVE_STATUS_PATH.write_text("{oops")
        live.LEGACY_LIVE.write_text("{oops")
        live._load_live_status()
        assert capsys.readouterr().err.count("unreadable") == 1

    def test_a_healthy_document_round_trips(self, live):
        """Anti-vacuity: if loading returned {} for everything the tests above
        would pass while the module was completely broken."""
        live._write_live_status({"uptime_sec": 7, "run_id": "abc"})
        assert live._load_live_status() == {"uptime_sec": 7, "run_id": "abc"}


class TestLiveStatusWriteIsProcessSafe:
    def test_the_temp_name_carries_the_pid(self, live, monkeypatch):
        """The trainer, the collector and the console all write this file. A fixed
        temp name is shared by every one of them -- measured on the same shape in
        scout-cli's herd ledger as 3334 errors in 6 seconds."""
        seen = []
        real = Path.replace

        def spy(self, target):
            seen.append(Path(self).name)
            return real(self, target)

        monkeypatch.setattr(Path, "replace", spy)
        live._write_live_status({"a": 1})
        assert seen, "nothing was replaced -- the write is not atomic"
        assert seen[0] != "live_status.tmp.json", (
            "the temp name is shared by every writer again; this is the race"
        )
        assert str(os.getpid()) in seen[0], f"no pid in temp name: {seen[0]}"

    def test_no_temp_survives_a_successful_write(self, live, tmp_path):
        live._write_live_status({"a": 1})
        assert list(tmp_path.glob("*.tmp")) == []
        assert json.loads(live.LIVE_STATUS_PATH.read_text()) == {"a": 1}


class TestStalenessGuardActuallyFires:
    """get_live_status's >300s re-aggregate path was DEAD from birth:
    `datetime.now(datetime.timezone.utc)` after `from datetime import datetime`
    is an AttributeError, and the surrounding except swallowed it -- so a stale
    status file was served as fresh forever (consumers got Aug-1 data on Aug 6,
    2026-08-06 feeds review, risk #1)."""

    def test_stale_file_triggers_reaggregation(self, live, monkeypatch):
        live.LIVE_STATUS_PATH.write_text(
            '{"updated_at": "2026-08-01T00:00:00Z", "step": 5}'
        )
        called = []
        monkeypatch.setattr(
            live, "aggregate_live_status", lambda: called.append(1) or {"fresh": True}
        )
        out = live.get_live_status()
        assert called, "stale file (5 days old) did not trigger re-aggregation"
        assert out == {"fresh": True}

    def test_fresh_file_is_served_as_is(self, live, monkeypatch):
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        live.LIVE_STATUS_PATH.write_text(
            json.dumps({"updated_at": now_iso, "step": 5})
        )
        monkeypatch.setattr(
            live,
            "aggregate_live_status",
            lambda: (_ for _ in ()).throw(AssertionError("must not re-aggregate")),
        )
        assert live.get_live_status()["step"] == 5

    def test_naive_timestamp_does_not_resurrect_the_dead_guard(self, live, monkeypatch):
        """fromisoformat on an offset-less string yields a naive datetime;
        aware-minus-naive raises TypeError into the same swallow. Stale must
        still win."""
        live.LIVE_STATUS_PATH.write_text(
            '{"updated_at": "2026-08-01T00:00:00", "step": 5}'
        )
        called = []
        monkeypatch.setattr(
            live, "aggregate_live_status", lambda: called.append(1) or {"fresh": True}
        )
        live.get_live_status()
        assert called, "naive stale timestamp slipped past the guard"
