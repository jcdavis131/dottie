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

GLIMMER_MODELS = [
    "muse-glimmer:30b",
    "muse-glimmer",
    "muse-glimmer:latest",
    "glimmer:30b",
    "glimmer",
]

PREFERRED_MODELS = [
    "muse-glimmer:30b",
    "muse-glimmer",
    "muse-glimmer:latest",

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


# --- KoboldCpp / OpenAI-compatible backend ----------------------------------
# KoboldCpp (github.com/LostRuins/koboldcpp — the ONLY trusted source; the
# koboldcpp[.]com domain is a known phishing clone) speaks several protocols at
# once: an OpenAI-compatible API on :5001/v1, an Ollama-compatible API on :11434,
# and its native /api. We target the OpenAI /v1 surface because it is the most
# portable (llama.cpp-server, vLLM, and OpenAI itself all speak it) and returns a
# `usage` block we can turn into tokens/sec. NOTE: if you instead launch KoboldCpp
# on port 11434, the existing ollama_chat() path already drives it UNCHANGED — no
# code needed, just point OLLAMA_BASE at it.
KOBOLDCPP_URLS = [
    "http://localhost:5001",
    "http://host.docker.internal:5001",
]


def koboldcpp_available(base: str | None = None, timeout: float = 2.0) -> str | None:
    """Return a reachable KoboldCpp OpenAI base (no trailing slash), or None.
    Never raises; honours KOBOLDCPP_BASE / OPENAI_BASE_URL env overrides."""
    env_base = os.environ.get("KOBOLDCPP_BASE") or os.environ.get("OPENAI_BASE_URL")
    urls = ([base.rstrip("/")] if base else []) \
        + ([env_base.rstrip("/")] if env_base else []) + KOBOLDCPP_URLS
    client = _httpx_client(timeout=timeout)
    if client is None:
        return None
    try:
        for b in urls:
            b = b.rstrip("/")
            host = urlparse(b).hostname or ""
            if host not in ("localhost", "127.0.0.1", "::1", "") and not _is_resolvable(host, 0.8):
                continue
            try:
                r = client.get(f"{b}/v1/models")
                if r.status_code == 200:
                    return b
            except Exception:
                continue
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def openai_chat(
    model: str,
    messages: list[dict[str, str]],
    base: str,
    *,
    json_mode: bool = False,
    timeout: float = 120.0,
    max_tokens: int | None = None,
) -> dict[str, Any] | None:
    """One non-streaming OpenAI /v1/chat/completions call. Returns
    {"content": str, "completion_tokens": int|None} or None on ANY failure.
    Works against KoboldCpp, llama.cpp-server, vLLM, or OpenAI."""
    client = _httpx_client(timeout=timeout)
    if client is None:
        return None
    try:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        r = client.post(f"{base.rstrip('/')}/v1/chat/completions", json=payload)
        if r.status_code != 200:
            return None
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        content = (choices[0].get("message") or {}).get("content")
        if content is None:
            return None
        usage = data.get("usage") or {}
        return {"content": content, "completion_tokens": usage.get("completion_tokens")}
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def _ollama_generate(
    model: str,
    messages: list[dict[str, str]],
    base: str,
    *,
    json_mode: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any] | None:
    """Like ollama_chat() but also surfaces the server-side eval_count +
    eval_duration so callers can compute the model's own tokens/sec (which
    excludes network/queueing). Returns dict or None."""
    client = _httpx_client(timeout=timeout)
    if client is None:
        return None
    try:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if json_mode:
            payload["format"] = "json"
        r = client.post(f"{base.rstrip('/')}/api/chat", json=payload)
        if r.status_code != 200:
            return None
        data = r.json()
        content = (data.get("message") or {}).get("content") or data.get("response")
        if content is None:
            return None
        dur_ns = data.get("eval_duration") or 0
        return {
            "content": content,
            "completion_tokens": data.get("eval_count"),
            "server_seconds": (dur_ns / 1e9) if dur_ns else None,
        }
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


# The interval clock, as a module attribute so a test can pin it (same seam as
# _httpx_client above). perf_counter, never time(): time() is wall-clock, so an
# NTP step mid-request can make an interval zero or negative, and it is coarse
# enough that a fast call measures exactly 0.0 -- which trips the `elapsed > 0`
# guard below and drops tok_per_s exactly when the backend is at its FASTEST.
# perf_counter is monotonic and finer, but still NOT infinitely fine (measured on
# this box: 324/2000 trivial intervals read 0.0), so a rate assertion must pin
# this rather than rely on the call being slow enough to register.
_clock = time.perf_counter


def chat_with_metrics(
    backend: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    base: str | None = None,
    json_mode: bool = False,
    timeout: float = 120.0,
    max_tokens: int | None = None,
    context_shift: bool | None = None,
) -> dict[str, Any]:
    """Backend-dispatching chat that returns a telemetry dict and NEVER raises.

    backend in {"ollama", "koboldcpp"}. On any failure: ok=False + a human error
    and content=None — we never fabricate a completion. ``tok_per_s`` is
    wall-clock; ``server_tok_per_s`` uses the backend's own timing when reported
    (Ollama's eval_duration). ``context_shift`` is recorded as-launched telemetry,
    not detected per-request (it is a KoboldCpp startup flag)."""
    backend = (backend or "ollama").lower()
    meta: dict[str, Any] = {
        "ok": False, "backend": backend, "model": model, "base": base,
        "content": None, "completion_tokens": None, "elapsed_s": None,
        "tok_per_s": None, "server_tok_per_s": None,
        "context_shift": context_shift, "error": None,
    }
    try:
        server_seconds: float | None = None
        if backend in ("kobold", "koboldcpp", "openai"):
            b = base or koboldcpp_available(timeout=timeout)
            if not b:
                meta["error"] = "koboldcpp not reachable — launch it on :5001 or set KOBOLDCPP_BASE"
                return meta
            meta["base"] = b
            t0 = _clock()
            res = openai_chat(model, messages, b, json_mode=json_mode,
                              timeout=timeout, max_tokens=max_tokens)
            elapsed = _clock() - t0
        elif backend == "ollama":
            b = base or get_ollama_base(timeout=timeout)
            if not b:
                meta["error"] = "ollama not reachable — is it running on :11434?"
                return meta
            meta["base"] = b
            t0 = _clock()
            res = _ollama_generate(model, messages, b, json_mode=json_mode, timeout=timeout)
            elapsed = _clock() - t0
            server_seconds = res.get("server_seconds") if res else None
        else:
            meta["error"] = f"unknown backend {backend!r} — use ollama|koboldcpp"
            return meta

        meta["elapsed_s"] = round(elapsed, 4)
        if not res or res.get("content") is None:
            meta["error"] = "backend returned no completion"
            return meta
        toks = res.get("completion_tokens")
        meta.update(ok=True, content=res["content"], completion_tokens=toks)
        if toks and elapsed > 0:
            meta["tok_per_s"] = round(toks / elapsed, 2)
        if toks and server_seconds and server_seconds > 0:
            meta["server_tok_per_s"] = round(toks / server_seconds, 2)
        return meta
    except Exception as e:  # the dispatcher must never raise into the CLI
        meta["error"] = f"{type(e).__name__}: {e}"
        return meta


# Solo personal project, no connection to employer, built with public/free-tier only
