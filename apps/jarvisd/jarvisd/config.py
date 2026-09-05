"""Environment-driven configuration (spec §7) and the fail-closed bind rule (§2).

Every setting has an env var; CLI flags override env; env overrides the default.
`validate()` is the single place the fail-closed rule lives: a non-loopback bind
without `JARVIS_BEARER` refuses to start.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8790
DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"

# Rate limits per minute (spec §2). Overridable for operators who run many
# agents behind one id; defaults are the spec's.
DEFAULT_RATE_IP = 1000
DEFAULT_RATE_KEY = 60
DEFAULT_RATE_AGENT = 20

_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})


class ConfigError(ValueError):
    """Raised when the configuration cannot be served safely."""


def is_loopback(host: str) -> bool:
    """True when `host` only ever binds the local machine.

    Accepts the usual names plus any address inside 127.0.0.0/8 or ::1.
    `0.0.0.0`, `::` and real hostnames are NOT loopback.
    """
    h = host.strip().strip("[]").lower()
    if h in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def default_db_path() -> Path:
    """`~/.local/share/jarvisd/jarvis.db` unless `JARVIS_DB` says otherwise."""
    raw = os.environ.get("JARVIS_DB", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share" / "jarvisd" / "jarvis.db"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from e


@dataclass(frozen=True)
class Config:
    """Resolved daemon configuration. Build with `Config.from_env(...)`."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    db_path: Path = field(default_factory=default_db_path)
    bearer: str | None = None
    public_host: str | None = None
    workspace: Path = field(default_factory=lambda: Path.home() / "workspace")
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    expose_scout: bool = False
    sse: bool = True
    rate_ip: int = DEFAULT_RATE_IP
    rate_key: int = DEFAULT_RATE_KEY
    rate_agent: int = DEFAULT_RATE_AGENT

    @classmethod
    def from_env(
        cls,
        *,
        host: str | None = None,
        port: int | None = None,
        db: str | Path | None = None,
        bearer_env: str = "JARVIS_BEARER",
        expose_scout: bool | None = None,
        sse: bool | None = None,
        public_host: str | None = None,
    ) -> Config:
        """Resolve config from the environment, with explicit overrides winning.

        Args:
            host: bind host (overrides `JARVIS_HOST`).
            port: bind port (overrides `JARVIS_PORT`).
            db: SQLite path (overrides `JARVIS_DB`).
            bearer_env: name of the env var holding the static bearer.
            expose_scout: re-export `scout_<plugin>` tools.
            sse: also mount the legacy SSE transport at `/sse`.
            public_host: hostname for the DNS-rebinding allowlist
                (overrides `JARVIS_PUBLIC_HOST`).
        """
        env = os.environ
        raw_bearer = env.get(bearer_env, "").strip() or None
        raw_public = (public_host or env.get("JARVIS_PUBLIC_HOST", "")).strip() or None
        ws_raw = env.get("JARVIS_WORKSPACE", "").strip()
        workspace = Path(ws_raw).expanduser() if ws_raw else Path.home() / "workspace"
        return cls(
            host=(host or env.get("JARVIS_HOST", "").strip() or DEFAULT_HOST),
            port=port if port is not None else _env_int("JARVIS_PORT", DEFAULT_PORT),
            db_path=Path(db).expanduser() if db else default_db_path(),
            bearer=raw_bearer,
            public_host=raw_public,
            workspace=workspace,
            model=env.get("JARVIS_MODEL", "").strip() or DEFAULT_MODEL,
            effort=env.get("JARVIS_EFFORT", "").strip() or DEFAULT_EFFORT,
            expose_scout=bool(expose_scout),
            sse=True if sse is None else bool(sse),
            rate_ip=_env_int("JARVIS_RATE_IP", DEFAULT_RATE_IP),
            rate_key=_env_int("JARVIS_RATE_KEY", DEFAULT_RATE_KEY),
            rate_agent=_env_int("JARVIS_RATE_AGENT", DEFAULT_RATE_AGENT),
        )

    @property
    def loopback(self) -> bool:
        """True when the bind host is loopback-only."""
        return is_loopback(self.host)

    @property
    def auth_enabled(self) -> bool:
        """Auth is on whenever a bearer is configured."""
        return self.bearer is not None

    @property
    def audit_path(self) -> Path:
        """`<db dir>/audit.jsonl` (spec §2)."""
        return self.db_path.parent / "audit.jsonl"

    @property
    def runs_dir(self) -> Path:
        """Where `harness.run` writes checkpoints: `<workspace>/bundles/ultra/runs`."""
        return self.workspace / "bundles" / "ultra" / "runs"

    def validate(self) -> None:
        """Fail closed: a non-loopback bind without a bearer refuses to start."""
        if not self.auth_enabled and not self.loopback:
            raise ConfigError(
                f"refusing to bind {self.host}:{self.port} without JARVIS_BEARER — "
                "set the bearer or bind a loopback host (127.0.0.1)"
            )
        if not 0 < self.port < 65536:
            raise ConfigError(f"port out of range: {self.port}")

    def status_notes(self) -> list[str]:
        """Human-readable caveats for the `/` status page."""
        notes: list[str] = []
        if not self.auth_enabled:
            notes.append(
                "AUTH DISABLED: no JARVIS_BEARER set; allowed only because the bind "
                f"host {self.host!r} is loopback"
            )
        if not self.loopback and not self.public_host:
            notes.append(
                "DNS-rebinding allowlist off: non-loopback bind without "
                "JARVIS_PUBLIC_HOST (bearer auth is the guard)"
            )
        return notes


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "Config",
    "ConfigError",
    "default_db_path",
    "is_loopback",
]
