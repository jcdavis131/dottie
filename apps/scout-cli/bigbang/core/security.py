"""Security foundation — vault, encryption-ready, no plaintext secrets in repo"""

import json
import os
import stat
from pathlib import Path

VAULT_DIR = Path.home() / ".local" / "share" / "bigbang"
VAULT_FILE = VAULT_DIR / "secrets.json"
VAULT_DIR.mkdir(parents=True, exist_ok=True)


def _load():
    if not VAULT_FILE.exists():
        return {}
    try:
        return json.loads(VAULT_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict):
    VAULT_FILE.write_text(json.dumps(data, indent=2))
    # 0600 perms
    try:
        os.chmod(VAULT_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


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
