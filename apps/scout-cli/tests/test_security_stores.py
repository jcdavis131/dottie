"""bigbang.core.security keeps two stores; they used to disagree.

get_secret() reads keyring FIRST, then env, then the file vault. set_secret() wrote the
file ONLY, and delete_secret() checked the file first and touched keyring only when the
file missed -- the inverse of the read order. Three consequences, all found 2026-08-02 by
reading the read path and the write path side by side:

    keyring-only     delete_secret -> False   but the secret WAS deleted
    keyring + file   delete_secret -> True    and get_secret() STILL returned it
    stale keyring    set_secret(new) then get_secret() -> the OLD value

The middle one is the security defect: `scout secrets rm` and `scout auth logout` reported
success, list_secrets() agreed the key was gone, and the credential stayed readable.

WHY A FAKE BACKEND. keyring is an optional extra (pyproject: `security = ["keyring"]`) and
is NOT installed here, so on the default install all three are latent -- they fire only for
someone who installed the extra whose purpose is safer credential storage. The bugs are
pure control flow, so a fake backend proves them exactly. It is also the only responsible
option: the real call is keyring.delete_password("bigbang-cli", ...) against the developer's
Windows Credential Manager, and probing that with a live delete is how you destroy a
credential to learn that you can.

conftest.py already redirects HOME, so the file vault here is a throwaway.
"""

from __future__ import annotations

import sys

import pytest

from bigbang.core import security

SERVICE = "bigbang-cli"


class FakeKeyring:
    """Minimal stand-in. Records calls so tests can assert the module reached it."""

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}
        self.deleted: list[str] = []
        self.written: list[str] = []

    def get_password(self, service, key):
        return self.store.get((service, key))

    def set_password(self, service, key, value):
        self.written.append(key)
        self.store[(service, key)] = value

    def delete_password(self, service, key):
        if (service, key) not in self.store:
            # Matches the real API: deleting an absent entry raises.
            raise RuntimeError("no such password")
        self.deleted.append(key)
        del self.store[(service, key)]


@pytest.fixture
def kr(monkeypatch):
    """Install a fake keyring. security.py imports it inside each call, so this lands."""
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    return fake


@pytest.fixture
def no_keyring(monkeypatch):
    """The default install: `import keyring` raises ImportError."""
    monkeypatch.setitem(sys.modules, "keyring", None)  # `import keyring` -> ImportError
    return None


def test_the_fake_backend_is_actually_consulted(kr):
    """Non-vacuity for every test below.

    If monkeypatching sys.modules did not take, the fake would sit unused and each
    assertion would silently degrade into a test of the file vault alone.
    """
    kr.store[(SERVICE, "PROBE")] = "from-keyring"
    assert security.get_secret("PROBE") == "from-keyring"
    assert security._keyring_has("PROBE") is True


# --- delete ------------------------------------------------------------------------


def test_deleting_a_keyring_only_secret_reports_true(kr):
    """Returned False before. `secrets rm` printed ok=false on a successful delete."""
    kr.store[(SERVICE, "K")] = "v"
    assert security.delete_secret("K") is True
    assert security.get_secret("K") is None


def test_delete_removes_the_keyring_copy_when_the_file_also_has_one(kr):
    """The security defect. Reported success while the credential stayed readable."""
    kr.store[(SERVICE, "K")] = "keyring-copy"
    security.set_secret("K", "file-copy")
    assert security.delete_secret("K") is True
    assert security.get_secret("K") is None, "secret survived a successful-looking delete"
    assert "K" in kr.deleted
    assert "K" not in security.list_secrets()


def test_delete_of_an_absent_key_is_false_and_touches_nothing(kr):
    """Non-vacuity: delete_secret must be capable of returning False.

    Without this, a version that returned True unconditionally would satisfy both
    tests above.
    """
    assert security.delete_secret("NEVER_STORED") is False
    assert kr.deleted == []


def test_a_failing_keyring_delete_propagates(kr, monkeypatch):
    """Swallowing it would recreate the original bug: success reported, secret alive."""
    kr.store[(SERVICE, "K")] = "v"

    def boom(service, key):
        raise RuntimeError("keychain is locked")

    monkeypatch.setattr(kr, "delete_password", boom)
    with pytest.raises(RuntimeError, match="locked"):
        security.delete_secret("K")


# --- set ---------------------------------------------------------------------------


def test_rotation_is_not_shadowed_by_a_stale_keyring_entry(kr):
    """set_secret wrote the file only, and get_secret prefers keyring."""
    kr.store[(SERVICE, "K")] = "OLD-rotated-out"
    security.set_secret("K", "NEW-rotated-in")
    assert security.get_secret("K") == "NEW-rotated-in"


def test_set_never_creates_a_new_keyring_entry(kr):
    """The deliberate limit on the fix.

    Refreshing an entry the user already has is keeping their store truthful. Creating
    one puts a credential in the OS keychain that nobody asked this tool to put there.
    """
    security.set_secret("BRAND_NEW", "v")
    assert kr.written == []
    assert (SERVICE, "BRAND_NEW") not in kr.store
    assert security.get_secret("BRAND_NEW") == "v"


# --- default install ---------------------------------------------------------------


def test_without_keyring_everything_still_works(no_keyring):
    """keyring is an optional extra. The common install must be unaffected."""
    security.set_secret("PLAIN", "v")
    assert security.get_secret("PLAIN") == "v"
    assert "PLAIN" in security.list_secrets()
    assert security.delete_secret("PLAIN") is True
    assert security.get_secret("PLAIN") is None
    assert security.delete_secret("PLAIN") is False


def test_a_broken_backend_does_not_break_reads(monkeypatch):
    """A locked keychain or absent D-Bus must degrade to the file vault, not raise."""

    class Broken:
        def get_password(self, service, key):
            raise RuntimeError("no backend available")

    monkeypatch.setitem(sys.modules, "keyring", Broken())
    security.set_secret("K", "file-value")
    assert security.get_secret("K") == "file-value"
    assert security._keyring_has("K") is False
