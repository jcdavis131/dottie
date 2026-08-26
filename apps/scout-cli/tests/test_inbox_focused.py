"""Focused regression tests for inbox lane — statuses, lifecycle, 0600, expiration, corrupt-state."""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest

from bigbang.plugins.inbox.cli import (
    INBOX_DIR,
    cmd_approve,
    cmd_clear,
    cmd_deny,
    cmd_list,
    cmd_park,
    cmd_show,
)


def _clean_inbox():
    # conftest already redirects HOME, but clean any leftover in this tmp home
    d = Path(INBOX_DIR)
    if d.exists():
        for f in d.glob("*.json"):
            try:
                f.unlink()
            except Exception:
                pass


@pytest.fixture(autouse=True)
def _isolated_inbox():
    _clean_inbox()
    yield
    _clean_inbox()


def test_park_and_list_pending():
    res = cmd_park("comms send", '{"to":"a@b"}', "unattended", 3600)
    assert res["ok"] is True
    data = res.get("data") or res
    # ok may wrap in data
    parked_id = (data.get("parked") if "parked" in data else (res.get("data") or {}).get("parked"))
    if parked_id is None:
        parked_id = res["data"]["parked"]
    lst = cmd_list(pending_only=True)
    assert lst["ok"] is True
    items = lst["data"]["items"] if "data" in lst else lst["items"]
    assert len(items) == 1
    assert items[0]["id"] == parked_id
    assert items[0]["status"] == "pending"


def test_0600_perms():
    res = cmd_park("test", "{}", "unattended", 3600)
    parked_id = res["data"]["parked"] if "data" in res else res["parked"]
    p = INBOX_DIR / f"{parked_id}.json"
    assert p.exists()
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_approve_lifecycle():
    res = cmd_park("calendar create", '{"title":"x"}', "unattended", 3600)
    pid = res["data"]["parked"] if "data" in res else res["parked"]
    appr = cmd_approve(pid)
    assert appr["ok"] is True
    assert appr["data"]["status"] == "approved" if "data" in appr else appr["status"] == "approved"
    # show should reflect approved
    sh = cmd_show(pid)
    assert sh["ok"] is True
    doc = sh["data"]["ask"] if "data" in sh else sh["ask"]
    assert doc["status"] == "approved"


def test_deny_lifecycle():
    res = cmd_park("system run", '{"cmd":"ls"}', "unattended", 3600)
    pid = res["data"]["parked"] if "data" in res else res["parked"]
    den = cmd_deny(pid, "not now")
    assert den["ok"] is True
    sh = cmd_show(pid)
    doc = sh["data"]["ask"] if "data" in sh else sh["ask"]
    assert doc["status"] == "denied"
    assert doc["deny_reason"] == "not now"


def test_pending_only_excludes_expired():
    # park with 1s ttl, wait 2s, list pending should exclude it, list all should include expired
    res = cmd_park("test", "{}", "unattended", 1)
    pid = res["data"]["parked"] if "data" in res else res["parked"]
    time.sleep(2)
    lst_pending = cmd_list(pending_only=True)
    items_pending = lst_pending["data"]["items"] if "data" in lst_pending else lst_pending["items"]
    assert all(it["id"] != pid for it in items_pending), "expired should not appear in pending-only"
    lst_all = cmd_list(pending_only=False)
    items_all = lst_all["data"]["items"] if "data" in lst_all else lst_all["items"]
    # find our expired one
    found = [it for it in items_all if it["id"] == pid]
    assert len(found) == 1
    assert found[0]["status"] == "expired"


def test_clear_approved():
    res = cmd_park("test", "{}", "unattended", 3600)
    pid = res["data"]["parked"] if "data" in res else res["parked"]
    cmd_approve(pid)
    clr = cmd_clear(approved=True, force=True)
    assert clr["ok"] is True
    cleared = clr["data"]["cleared"] if "data" in clr else clr["cleared"]
    assert cleared == 1
    assert not (INBOX_DIR / f"{pid}.json").exists()


def test_show_missing_is_io_missing():
    res = cmd_show("deadbeef")
    assert res["ok"] is False
    assert res["errorClass"] == "IO_MISSING"


def test_corrupt_state_does_not_crash_list():
    # write a corrupt json file, list should skip it, not crash
    d = INBOX_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / "corrupt.json").write_text("{not json", encoding="utf-8")
    try:
        lst = cmd_list(pending_only=False)
        assert lst["ok"] is True
    finally:
        try:
            (d / "corrupt.json").unlink()
        except Exception:
            pass
