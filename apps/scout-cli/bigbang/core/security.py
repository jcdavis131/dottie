"""Security foundation — vault, encryption-ready, no plaintext secrets in repo"""

import os
import stat
from pathlib import Path

from bigbang.core import atomic_json

VAULT_DIR = Path.home() / ".local" / "share" / "bigbang"
VAULT_FILE = VAULT_DIR / "secrets.json"
VAULT_DIR.mkdir(parents=True, exist_ok=True)


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
    atomic_json.write_json(
        VAULT_FILE, data, mode=stat.S_IRUSR | stat.S_IWUSR
    )


def set_secret(key: str, value: str):
    data = _load()
    data[key] = value
    _save(data)


def get_secret(key: str):
    # 1. keyring attempt (optional)
    try:
        import keyring

        v = keyring.get_password("bigbang-cli", key)
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
    data = _load()
    return list(data.keys())


def delete_secret(key: str):
    data = _load()
    if key in data:
        del data[key]
        _save(data)
        return True
    try:
        import keyring

        keyring.delete_password("bigbang-cli", key)
    except Exception:
        pass
    return False


# Future: age/sops encryption
