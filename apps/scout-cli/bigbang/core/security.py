"""Security foundation — vault, encryption-ready, no plaintext secrets in repo"""

import os
import stat
from pathlib import Path

from bigbang.core import atomic_json

VAULT_DIR = Path.home() / ".local" / "share" / "bigbang"
VAULT_FILE = VAULT_DIR / "secrets.json"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
try:
    VAULT_DIR.chmod(0o700)
    # also tighten parent ~/.local/share/bigbang parent chain if owned by us
    parent = VAULT_DIR.parent
    if parent.exists():
        try:
            parent.chmod(0o700)
        except Exception:
            pass
except Exception:
    pass


def _load():
    """Vault contents, or {} when there is no vault yet.

    A CORRUPT vault raises rather than reading as empty. It used to
    `except Exception: return {}`, and because every mutation here is a
    read-modify-write, one torn file plus one ordinary `set_secret` destroyed
    everything with no error -- measured 2026-07-29:

        vault before      : ['AWS', 'HF_TOKEN', 'OPENAI_KEY']
        after torn write  : []            <- swallowed
        after next set    : ['NEW_KEY']   <- loss made permanent

    Missing is genuinely empty. Unreadable is not.
    """
    return atomic_json.read_json(VAULT_FILE, {})


def _save(data: dict):
    # Atomic + 0600 applied to the temp BEFORE it becomes the vault, so there is
    # no window where secrets.json exists with default permissions.
    #
    # ON WINDOWS THE 0600 DOES NOTHING, and that is worth saying here rather than letting
    # the line above imply a guarantee it does not deliver. Measured 2026-08-02:
    #
    #     mode after write            0o666
    #     os.chmod(p, 0o600)          before 0o666 -> after 0o666   (no effect)
    #
    # Python's chmod on Windows only toggles the read-only bit; group/other bits are not
    # the access control mechanism there. The vault IS still private on that platform —
    # `icacls` shows SYSTEM, Administrators and the owning user only, inherited from the
    # user profile — but by NTFS ACLs, not by this call. Anyone hardening this further
    # should reach for ACLs on Windows rather than assume the mode argument covers it.
    atomic_json.write_json(
        VAULT_FILE, data, mode=stat.S_IRUSR | stat.S_IWUSR
    )


KEYRING_SERVICE = "bigbang-cli"


def _keyring():
    """The keyring module, or None when it is not installed / has no backend.

    keyring is an OPTIONAL extra (pyproject: `security = ["keyring"]`, `all`), so on a
    default install there is no second store and every helper below is a no-op. That is
    also why the three bugs this module was fixed for went unnoticed: they only fire
    once someone installs the extra whose entire purpose is safer credential storage.
    """
    try:
        import keyring

        return keyring
    except Exception:
        return None


def _keyring_has(key: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        return kr.get_password(KEYRING_SERVICE, key) is not None
    except Exception:
        # No backend, locked keychain, D-Bus absent. Nothing to reconcile against.
        return False


def set_secret(key: str, value: str):
    """Store `value` under `key` in the file vault, and refresh an EXISTING keyring copy.

    It used to write the file only. get_secret() reads keyring FIRST, so a keyring entry
    left over from an earlier tool silently shadowed the file and rotation did nothing --
    the failure mode being: you rotate a leaked credential, the CLI reports it stored,
    and every subsequent read hands back the leaked one. Measured with a fake backend:

        keyring holds     : OLD-rotated-out
        set_secret(K3, "NEW-rotated-in")
        get_secret(K3)    : OLD-rotated-out    <- rotation silently ineffective

    Only an entry that ALREADY exists is updated. Writing new ones would put credentials
    into the OS keychain that nobody asked this tool to put there, which is a different
    decision than keeping an existing one truthful.
    """
    data = _load()
    data[key] = value
    _save(data)
    if _keyring_has(key):
        # Deliberately unguarded: a backend that holds the key and then refuses the
        # write must not be reported as a successful rotation.
        _keyring().set_password(KEYRING_SERVICE, key, value)


def get_secret(key: str):
    # 1. keyring attempt (optional)
    kr = _keyring()
    if kr is not None:
        try:
            v = kr.get_password(KEYRING_SERVICE, key)
            if v:
                return v
        except Exception:
            pass
    # 2. env BB_ upper
    env_key = f"BB_SECRET_{key.upper()}"
    if env_key in os.environ:
        return os.environ[env_key]
    # 3. file vault
    data = _load()
    return data.get(key)


def list_secrets():
    """Keys in the FILE vault. Not an inventory of everything get_secret() can return.

    keyring exposes no portable enumeration API -- Windows Credential Manager in
    particular cannot be listed through it -- so a keyring-only secret is readable by
    get_secret() and invisible here. The `secrets list` output says so rather than
    implying a completeness this cannot deliver.
    """
    data = _load()
    return list(data.keys())


def delete_secret(key: str) -> bool:
    """Remove `key` from every store get_secret() reads back. True if any held it.

    The old version checked the file FIRST and touched keyring only when the file did
    not have the key -- the exact inverse of get_secret()'s order. Two consequences,
    both measured with a fake backend (neither needs a real keychain, both are pure
    control flow):

        keyring-only    delete_secret -> False   but the secret WAS deleted
                        `secrets rm` / `auth logout` reported failure on success.

        keyring + file  delete_secret -> True    and get_secret() STILL returns it
                        reported success, credential survives, list_secrets() agrees
                        it is gone. That is the serious one.

    Env vars are NOT deleted here and cannot be: BB_SECRET_* belongs to the caller's
    process. `secrets rm` and `auth logout` say so in their output instead of letting
    "deleted" imply "no longer readable".
    """
    removed_keyring = False
    if _keyring_has(key):
        # Unguarded on purpose. If the backend holds the key and the delete fails, that
        # exception is the honest answer; swallowing it into `return False` would be the
        # same report-one-thing-do-another defect in a narrower disguise.
        _keyring().delete_password(KEYRING_SERVICE, key)
        removed_keyring = True

    data = _load()
    removed_file = key in data
    if removed_file:
        del data[key]
        _save(data)

    return removed_keyring or removed_file


# Future: age/sops encryption
