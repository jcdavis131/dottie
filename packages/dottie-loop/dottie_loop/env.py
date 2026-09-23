"""One name per setting across Dottie's clients.

Ollama's endpoint is ``OLLAMA_HOST`` (the name Ollama itself reads). The
spellings clients grew over time (``OLLAMA_BASE``, ``OLLAMA_URL``,
``DOTTIE_OLLAMA_URL``) are still accepted as deprecated aliases: the first one
set is used when ``OLLAMA_HOST`` is not, and a ``FutureWarning`` (once per
alias per process) says to rename it. Stdlib only.
"""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

OLLAMA_ENV = "OLLAMA_HOST"
OLLAMA_ALIASES = ("OLLAMA_BASE", "OLLAMA_URL", "DOTTIE_OLLAMA_URL")
_warned: set[str] = set()


def _warn_alias(name: str) -> None:
    if name in _warned:
        return
    _warned.add(name)
    warnings.warn(f"{name} is deprecated; set {OLLAMA_ENV} (Dottie's one Ollama endpoint variable)",
                  FutureWarning, stacklevel=3)


def ollama_env_values(env: Mapping[str, str] | None = None) -> list[str]:
    """Every configured Ollama endpoint value, ``OLLAMA_HOST`` first, then aliases (warned)."""
    env = os.environ if env is None else env
    out: list[str] = []
    for name in (OLLAMA_ENV, *OLLAMA_ALIASES):
        value = str(env.get(name) or "").strip()
        if value:
            if name != OLLAMA_ENV:
                _warn_alias(name)
            out.append(value)
    return out


def ollama_host(env: Mapping[str, str] | None = None, default: str | None = None) -> str | None:
    """The Ollama endpoint: ``OLLAMA_HOST``, else the first deprecated alias set, else ``default``."""
    values = ollama_env_values(env)
    return values[0] if values else default
