# Solo personal project, no connection to employer, built with public/free-tier only
"""
Helper module for Ollama — local LLM router for BigBang Ava

Provides resilient Ollama detection and chat with auto-fallback.
No hard dependency: if httpx missing or Ollama down, returns None/false gracefully.
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from typing import Any
from urllib.parse import urlparse

OLLAMA_URLS = [
    "http://localhost:11434",
    "http://host.docker.internal:11434",
]

PREFERRED_MODELS = [
    "qwen3:32b",
    "qwen3:32b-instruct",
    "qwen3:14b",
    "qwen3:8b",
    "qwen3",
    "llama3.1:8b",
    "llama3.1",
    "qwen2.5:32b",
    "qwen2.5:14b",
    "qwen2.5:7b",
    "qwen2.5",
    "llama3",
    "llama3:8b",
    "mistral",
    "gemma3:4b",
]

_CACHED_BASE: str | None = None
_CACHED_AT: float = 0.0
_CACHE_TTL: float = 30.0


def _is_resolvable(host: str, timeout: float = 0.8) -> bool:
    """Fast DNS check that never blocks process exit.
    Returns quickly even if getaddrinfo would block 20s, using daemon thread.
    Also fast-skips host.docker.internal if not in /etc/hosts unless env allows.
    """
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    if host == "host.docker.internal":
        # Allow override via env
        allow = (
            os.environ.get("OLLAMA_ALLOW_DOCKER_HOST")
            or os.environ.get("BIGBANG_USE_DOCKER_HOST")
            or os.environ.get("OLLAMA_BASE", "")
        )
        if "host.docker.internal" not in allow:
            try:
                with open("/etc/hosts", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if "host.docker.internal" not in content:
                        return False
            except Exception:
                # If can't read hosts, skip to avoid 20s DNS block
                return False

    result: list[bool] = []

    def _do():
        try:
            socket.getaddrinfo(host, None)
            result.append(True)
        except Exception:
            result.append(False)

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if result:
        return result[0]
    # Timeout or no result => treat as not resolvable to avoid hanging
    return False


def _httpx_client(timeout: float = 2.0):
    try:
        import httpx
    except ImportError:
        return None
    try:
        to = httpx.Timeout(timeout, connect=min(timeout, 1.2))
    except Exception:
        to = timeout
    try:
        return httpx.Client(trust_env=False, timeout=to)
    except TypeError:
        try:
            return httpx.Client(timeout=to)
        except Exception:
            return None
    except Exception:
        return None


def get_ollama_base(timeout: float = 2.0, use_cache: bool = True) -> str | None:
    global _CACHED_BASE, _CACHED_AT

    if (
        use_cache
        and _CACHED_BASE is not None
        and (time.time() - _CACHED_AT) < _CACHE_TTL
    ):
        return _CACHED_BASE
    if (
        use_cache
        and _CACHED_AT
        and (time.time() - _CACHED_AT) < 5.0
        and _CACHED_BASE is None
    ):
        return None

    # Env override - if OLLAMA_BASE set, try it first
    env_base = (
        os.environ.get("OLLAMA_BASE")
        or os.environ.get("OLLAMA_URL")
        or os.environ.get("OLLAMA_HOST")
    )
    urls_to_try = []
    if env_base:
        # Normalize
        nb = env_base.rstrip("/")
        # If env_base doesn't include /api, use as base
        if not nb.endswith(":11434"):
            # allow full url
            pass
        urls_to_try.append(nb)
    urls_to_try.extend(OLLAMA_URLS)

    try:
        import httpx  # noqa: F401
    except ImportError:
        return None

    found: str | None = None
    for base in urls_to_try:
        # strip /api/tags if user passed full
        b = base
        if b.endswith("/api/tags"):
            b = b[: -len("/api/tags")]
        b = b.rstrip("/")
        parsed = urlparse(b)
        host = parsed.hostname or ""
        if host not in ("localhost", "127.0.0.1", "::1", ""):
            if not _is_resolvable(host, timeout=0.8):
                continue

        client = _httpx_client(timeout=timeout)
        if client is None:
            return None
        try:
            r = client.get(f"{b}/api/tags")
            if r.status_code == 200:
                found = b
                break
        except Exception:
            continue
        finally:
            try:
                client.close()
            except Exception:
                pass

    _CACHED_BASE = found
    _CACHED_AT = time.time()
    return found


def _clear_cache():
    global _CACHED_BASE, _CACHED_AT
    _CACHED_BASE = None
    _CACHED_AT = 0.0


def ollama_available(timeout: float = 2.0) -> bool:
    return get_ollama_base(timeout=timeout) is not None


def list_ollama_models(base: str | None = None, timeout: float = 2.0) -> list[str]:
    if base is None:
        base = get_ollama_base(timeout=timeout)
    else:
        base = base.rstrip("/")
    if not base:
        return []
    try:
        parsed = urlparse(base)
        host = parsed.hostname or ""
        if host not in ("localhost", "127.0.0.1", "::1", ""):
            if not _is_resolvable(host, timeout=0.8):
                return []
    except Exception:
        pass

    client = _httpx_client(timeout=timeout)
    if client is None:
        return []
    try:
        r = client.get(f"{base}/api/tags")
        if r.status_code != 200:
            return []
        data = r.json()
        models = data.get("models", []) if isinstance(data, dict) else []
        names = []
        for m in models:
            if isinstance(m, dict):
                n = m.get("name") or m.get("model")
                if n:
                    names.append(n)
            elif isinstance(m, str):
                names.append(m)
        return names
    except Exception:
        return []
    finally:
        try:
            client.close()
        except Exception:
            pass


def get_best_model(base: str | None = None, timeout: float = 2.0) -> str:
    available = list_ollama_models(base=base, timeout=timeout)
    if not available:
        return "qwen3:32b"
    lower_avail = {a.lower(): a for a in available}
    for pref in PREFERRED_MODELS:
        if pref.lower() in lower_avail:
            return lower_avail[pref.lower()]
    for pref in PREFERRED_MODELS:
        family = pref.split(":")[0]
        for av in available:
            if av.lower().startswith(family):
                return av
    return available[0]


def ollama_chat(
    model: str,
    messages: list[dict[str, str]],
    json_mode: bool = False,
    base: str | None = None,
    timeout: float = 60.0,
) -> str | None:
    if base is None:
        base = get_ollama_base(timeout=2.0)
    if not base:
        return None
    try:
        parsed = urlparse(base)
        host = parsed.hostname or ""
        if host not in ("localhost", "127.0.0.1", "::1", ""):
            if not _is_resolvable(host, timeout=0.8):
                return None
    except Exception:
        pass

    client = _httpx_client(timeout=timeout)
    if client is None:
        return None
    try:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        r = client.post(f"{base}/api/chat", json=payload)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                content = msg.get("content")
                if content:
                    return content
            if "response" in data:
                return data["response"]
        return None
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def extract_json_from_text(text: str) -> Any | None:
    if not text:
        return None
    t = text.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.IGNORECASE)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except Exception:
            pass
    first_brace = t.find("{")
    last_brace = t.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = t[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass
    first_br = t.find("[")
    last_br = t.rfind("]")
    if first_br != -1 and last_br != -1 and last_br > first_br:
        candidate = t[first_br : last_br + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass
    return None


# Solo personal project, no connection to employer, built with public/free-tier only
