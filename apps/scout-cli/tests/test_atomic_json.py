"""State files must survive a crash mid-write, and must never read as empty.

The bug this pins, measured 2026-07-29 against the real `bigbang.core.security`:

    vault before      : ['AWS', 'HF_TOKEN', 'OPENAI_KEY']
    after torn write  : []            <- _load caught everything, returned {}
    after next set    : ['NEW_KEY']   <- loss made permanent

`_save` used `FILE.write_text(...)`, which truncates before writing, and `_load`
did `except Exception: return {}`. Because every mutation is a read-modify-write,
ONE torn file plus ONE ordinary `set_secret` destroyed the whole vault silently.
The write being non-atomic is the smaller half; the fail-silent read is what made
it permanent.

    cd apps/scout-cli && python -m pytest tests/test_atomic_json.py -q
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from bigbang.core import atomic_json


class TestReadRefusesToInventEmptiness:
    def test_missing_file_returns_the_default(self, tmp_path):
        """Missing IS genuinely empty -- this must not become an error."""
        assert atomic_json.read_json(tmp_path / "nope.json", {"a": 1}) == {"a": 1}

    def test_corrupt_file_raises_instead_of_reading_as_empty(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text('{"HF_TOKEN": "aaa", "OPENAI_K')  # died mid-write
        with pytest.raises(atomic_json.CorruptStateFileError):
            atomic_json.read_json(p, {})

    def test_the_corrupt_bytes_are_preserved(self, tmp_path):
        """Refusing to parse must not also mean refusing to keep the only copy.
        Whatever survived the torn write is often most of the data."""
        p = tmp_path / "state.json"
        p.write_text('{"HF_TOKEN": "aaa", "OPENAI_K')
        with pytest.raises(atomic_json.CorruptStateFileError):
            atomic_json.read_json(p, {})
        backups = list(tmp_path.glob("state.json.corrupt-*"))
        assert len(backups) == 1, f"corrupt bytes not preserved: {list(tmp_path.iterdir())}"
        assert "HF_TOKEN" in backups[0].read_text()

    def test_a_json_array_is_not_a_state_file(self, tmp_path):
        """Valid JSON, wrong shape. Callers do data["tools"][name] = ... and would
        get a TypeError far from the cause."""
        p = tmp_path / "state.json"
        p.write_text("[1, 2, 3]")
        with pytest.raises(atomic_json.CorruptStateFileError):
            atomic_json.read_json(p, {})

    def test_a_good_file_round_trips(self, tmp_path):
        """Anti-vacuity: if reads raised on everything the tests above prove nothing."""
        p = tmp_path / "state.json"
        atomic_json.write_json(p, {"k": "v"})
        assert atomic_json.read_json(p, {}) == {"k": "v"}


class TestWriteSurvivesConcurrencyAndCrashes:
    def test_the_temp_name_carries_the_pid(self, tmp_path, monkeypatch):
        """A fixed temp name is shared by every concurrent writer -- the exact race
        fixed in the herd ledger (0ae2dc6), where 4 processes produced 3334 errors
        in 6 seconds. Asserts on the file actually created, not on the expression."""
        seen = []
        real = Path.replace

        def spy(self, target):
            seen.append(Path(self).name)
            return real(self, target)

        monkeypatch.setattr(Path, "replace", spy)
        atomic_json.write_json(tmp_path / "state.json", {"a": 1})
        assert seen, "nothing was replaced -- the write was not atomic"
        assert seen[0] != "state.json.tmp", "temp name is shared again; this is the race"
        assert str(os.getpid()) in seen[0], f"no pid in temp name: {seen[0]}"

    def test_no_temp_file_survives_a_successful_write(self, tmp_path):
        atomic_json.write_json(tmp_path / "state.json", {"a": 1})
        assert list(tmp_path.glob("*.tmp")) == []

    def test_a_transient_permission_error_is_retried(self, tmp_path, monkeypatch):
        calls = {"n": 0}
        real = Path.replace

        def flaky(self, target):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(32, "being used by another process")
            return real(self, target)

        monkeypatch.setattr(Path, "replace", flaky)
        atomic_json.write_json(tmp_path / "state.json", {"a": 1})
        assert calls["n"] == 3
        assert atomic_json.read_json(tmp_path / "state.json", {}) == {"a": 1}

    def test_a_permanent_failure_raises_and_leaves_no_temp(self, tmp_path, monkeypatch):
        """Both directions. Swallowing would mean the file silently stops updating;
        not cleaning up would litter one temp per failed run."""
        monkeypatch.setattr(
            Path, "replace", lambda self, t: (_ for _ in ()).throw(PermissionError(13, "denied"))
        )
        with pytest.raises(PermissionError):
            atomic_json.write_json(tmp_path / "state.json", {"a": 1})
        assert list(tmp_path.glob("*.tmp")) == []

    @pytest.mark.skipif(os.name != "posix", reason="Windows chmod cannot express 0600")
    def test_mode_is_applied_before_the_file_becomes_visible(self, tmp_path):
        """Chmod AFTER the replace leaves a window where the vault is readable by
        others. Applying it to the temp closes that window."""
        p = tmp_path / "secrets.json"
        atomic_json.write_json(p, {"k": "v"}, mode=stat.S_IRUSR | stat.S_IWUSR)
        assert p.stat().st_mode & 0o777 == 0o600


class TestTheVaultScenarioThatLostThreeSecrets:
    """End-to-end on the real module, because the unit tests above would all pass
    while security.py still called write_text/except-return-{}."""

    @pytest.fixture()
    def vault(self, tmp_path, monkeypatch):
        from bigbang.core import security

        monkeypatch.setattr(security, "VAULT_DIR", tmp_path)
        monkeypatch.setattr(security, "VAULT_FILE", tmp_path / "secrets.json")
        return security

    def test_a_torn_vault_does_not_read_as_empty(self, vault, tmp_path):
        vault.VAULT_FILE.write_text('{"HF_TOKEN": "aaa", "OPENAI_KEY": "bbb", "AWS": "ccc"}')
        assert sorted(vault._load()) == ["AWS", "HF_TOKEN", "OPENAI_KEY"]
        vault.VAULT_FILE.write_text('{"HF_TOKEN": "aaa", "OPENAI_K')
        with pytest.raises(atomic_json.CorruptStateFileError):
            vault._load()

    def test_the_next_set_secret_cannot_cement_the_loss(self, vault):
        """THE regression. Previously: torn read -> {} -> add one key -> save, and
        the other three were gone with no error."""
        vault.VAULT_FILE.write_text('{"HF_TOKEN": "aaa", "OPENAI_KEY": "bbb", "AWS": "ccc"}')
        vault.VAULT_FILE.write_text('{"HF_TOKEN": "aaa", "OPENAI_K')
        with pytest.raises(atomic_json.CorruptStateFileError):
            vault.set_secret("NEW_KEY", "zzz")
        # and the damaged bytes are still on disk, under one name or the other
        surviving = "".join(
            p.read_text(errors="ignore") for p in vault.VAULT_FILE.parent.iterdir()
        )
        assert "HF_TOKEN" in surviving, "the only copy of the data was destroyed"

    def test_a_healthy_vault_still_round_trips(self, vault):
        """Anti-vacuity: the gate must not have broken normal use."""
        vault.set_secret("A", "1")
        vault.set_secret("B", "2")
        assert vault.get_secret("A") == "1"
        assert vault.get_secret("B") == "2"
        assert json.loads(vault.VAULT_FILE.read_text()) == {"A": "1", "B": "2"}


class TestAuthRegistryHasTheSameProtection:
    """auth.json is the other read-modify-write store, and it holds credentials.

    Its old `_load_auth` docstring said "Returns {} if missing/corrupt" -- the
    behaviour was documented, the consequence was not. Same trap as the vault:
    a torn auth.json read as {} and the next login wrote that back.
    """

    @pytest.fixture()
    def auth(self, tmp_path, monkeypatch):
        from bigbang.plugins.auth import cli as auth_cli

        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        reg = tmp_path / ".local" / "share" / "bigbang" / "auth.json"
        reg.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(auth_cli, "REG", reg)
        return auth_cli

    def test_a_torn_auth_registry_does_not_read_as_empty(self, auth):
        auth._save_auth({"github": {"method": "token"}, "google": {"method": "pat"}})
        assert sorted(auth._load_auth()) == ["github", "google"]
        auth.REG.write_text('{"github": {"method": "tok')
        with pytest.raises(atomic_json.CorruptStateFileError):
            auth._load_auth()

    def test_the_registry_write_is_atomic(self, auth, monkeypatch):
        seen = []
        real = Path.replace

        def spy(self, target):
            seen.append(Path(self).name)
            return real(self, target)

        monkeypatch.setattr(Path, "replace", spy)
        auth._save_auth({"github": {"method": "token"}})
        assert seen and seen[0] != "auth.json.tmp"
        assert str(os.getpid()) in seen[0]

    def test_a_healthy_registry_still_round_trips(self, auth):
        """Anti-vacuity, and it also covers the gate added in df11ca3 -- if the
        fs_write enforcement denied this path the write would raise, not pass."""
        auth._save_auth({"github": {"method": "token"}})
        assert auth._load_auth() == {"github": {"method": "token"}}
