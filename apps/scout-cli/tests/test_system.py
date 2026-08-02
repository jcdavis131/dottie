"""`scout system doctor`. 203 loc, no test file until 2026-08-02.

Doctor reported TWO permanent failures on a correctly-configured machine, and a report that
is always red is one people learn to skim — the same failure this repo already names for CI
and for tracebacks printed after a green result.

    ok=False MEMORY.md   C:\\Users\\jcdav\\MEMORY.md missing
    ok=False vault       secrets.json exists but mode is 0o666 (want 0600)

NEITHER WAS AN EXPOSURE, and that was established by measuring rather than by reasoning:

    mode                 0o666
    os.chmod(p, 0o600)   before 0o666 -> after 0o666        (no effect on Windows)
    icacls secrets.json  SYSTEM:(I)(F) Administrators:(I)(F) NUGATRON\\jcdav:(I)(F)
                         no Users, no Everyone

The vault IS private on Windows, via NTFS ACLs inherited from the user profile. What is not
true is that the 0600 in security.py delivered it — Python's chmod there only toggles the
read-only bit. ~/MEMORY.md is a personal convention the CLI neither requires nor creates.

The POSIX branch is NOT deleted, only skipped on nt. These tests exercise both so the real
check cannot rot behind a platform guard.
"""

from __future__ import annotations

import os
import stat

import pytest

from bigbang.plugins.system import cli as sc


def _check(name: str, checks: list[dict]) -> dict:
    for c in checks:
        if c["check"] == name:
            return c
    raise AssertionError(f"no {name} check in {[c['check'] for c in checks]}")


@pytest.fixture
def checks(capsys):
    """Run doctor against a POPULATED home.

    conftest.py redirects HOME to a throwaway, where ~/.local/share/bigbang is empty — so
    the file checks legitimately report "missing" and a test asserting they pass would be
    asserting the wrong thing. The files are created first so the assertions below are
    about MODE and REQUIREDNESS, which is what actually changed, rather than about
    existence.
    """
    import json
    from pathlib import Path

    from bigbang.core.output import set_json_mode

    share = Path.home() / ".local" / "share" / "bigbang"
    share.mkdir(parents=True, exist_ok=True)
    for name in ("secrets.json", "audit.jsonl", "registry.json"):
        (share / name).write_text("{}", encoding="utf-8")

    set_json_mode(True)
    try:
        sc.doctor()
        payload = json.loads(capsys.readouterr().out)
    finally:
        set_json_mode(False)
    return (payload.get("data") or payload)["checks"]


def test_doctor_has_no_permanently_failing_check(checks):
    """The defect. Two checks could never pass on this platform."""
    failing = [c["check"] for c in checks if not c.get("ok")]
    # Genuinely-down external services are allowed to fail; these two are not services.
    assert "MEMORY.md" not in failing, failing
    assert "vault" not in failing, failing


def test_memory_md_is_informational_not_required(checks):
    c = _check("MEMORY.md", checks)
    assert c["ok"] is True
    assert c.get("informational") is True
    if "not present" in c["status"]:
        assert "optional" in c["status"], c["status"]


def test_vault_check_says_what_actually_protects_it_on_windows(checks):
    """A green check that explains nothing is only half a fix.

    On nt the status has to say the mode is not the mechanism, or the next reader
    'hardens' the vault by re-applying a chmod that does nothing.
    """
    c = _check("vault", checks)
    if os.name == "nt":
        assert c["ok"] is True
        assert c.get("caveat") == "posix-mode-not-applicable"
        assert "NTFS" in c["status"] or "ACL" in c["status"], c["status"]


def test_the_posix_mode_check_still_fires_on_posix(tmp_path, monkeypatch):
    """Non-vacuity for the platform guard. The 0600 rule must survive on the platform
    where it is real — skipping on nt must not mean deleting the check."""
    monkeypatch.setattr(sc._os, "name", "posix")
    victim = tmp_path / "secrets.json"
    victim.write_text("{}", encoding="utf-8")
    victim.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)  # 0640, not 0600

    got = sc._file_check("vault", victim, require_mode_0600=True)
    assert got["ok"] is False, got
    assert "want 0600" in got["status"], got


def test_the_posix_check_passes_at_0600(tmp_path, monkeypatch):
    """The other direction: a correct mode must not be reported as a failure."""
    monkeypatch.setattr(sc._os, "name", "posix")
    good = tmp_path / "secrets.json"
    good.write_text("{}", encoding="utf-8")
    good.chmod(stat.S_IRUSR | stat.S_IWUSR)

    got = sc._file_check("vault", good, require_mode_0600=True)
    # On Windows chmod cannot actually produce 0600, so only assert the branch logic when
    # the filesystem can express it.
    if (good.stat().st_mode & 0o777) == 0o600:
        assert got["ok"] is True, got


def test_a_missing_file_still_fails(tmp_path):
    """The check must remain capable of failing for the reason it exists."""
    got = sc._file_check("vault", tmp_path / "nope.json", require_mode_0600=True)
    assert got["ok"] is False
    assert "missing" in got["status"]


def test_the_security_summary_does_not_contradict_the_vault_check(checks, capsys):
    """70bfa38 fixed the per-check status and left the SUMMARY claiming 0600 anyway.

    A report whose headline contradicts the line below it is worse than either being wrong
    alone — a reader who skims takes the headline.
    """
    import json
    import os

    from bigbang.core.output import set_json_mode

    set_json_mode(True)
    try:
        sc.doctor()
        payload = json.loads(capsys.readouterr().out)
    finally:
        set_json_mode(False)
    security = (payload.get("data") or payload)["security"]

    if os.name == "nt":
        assert "NTFS" in security or "ACL" in security, security
        assert not security.startswith("vault 0600"), security
    else:
        assert "0600" in security, security
