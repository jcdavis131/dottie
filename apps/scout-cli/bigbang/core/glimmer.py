# Solo personal project, no connection to employer, built with public/free-tier only
"""
Glimmer — Meta's Muse Glimmer 30B local agent model provider for scout-cli.

Muse Glimmer is a 30B open-weight model designed to run AI agents locally
on a single consumer GPU (24GB VRAM). It's distilled from Muse Spark and
optimized for agentic workflows: tool calling, coding, file ops, screenshots.

This module makes scout-cli call local Glimmer instead of cloud:
- Ollama endpoint config (OLLAMA_BASE / GLIMMER_BASE)
- text+image multimodal inputs
- reasoning effort low/med/high/xhigh via system prompt
- function calling and coding tasks

Zero-deps stdlib + httpx, honest 503 when offline.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse resilient Ollama helpers from llm.py
try:
    from bigbang.core.llm import (
        get_ollama_base,
        list_ollama_models,
        get_best_model,
        _httpx_client,
        _is_resolvable,
    )
    _HAS_LLM = True
except ImportError:
    _HAS_LLM = False
    def get_ollama_base(timeout=2.0, use_cache=True): return None
    def list_ollama_models(base=None, timeout=2.0): return []
    def get_best_model(base=None, timeout=2.0): return "muse-glimmer:30b"
    def _is_resolvable(h,t=0.8): return True
    def _httpx_client(timeout=2.0): return None

GLIMMER_MODELS = [
    "muse-glimmer:30b",
    "muse-glimmer",
    "muse-glimmer:latest",
    "glimmer:30b",
    "glimmer",
    "spark-glimmer:30b",
]

PREFERRED_Glimmer = GLIMMER_MODELS

OLLAMA_URLS = [
    "http://localhost:11434",
    "http://host.docker.internal:11434",
]

REASONING_LEVELS = {
    "low": "Reasoning: low. Be concise, fast, direct. Skip internal monologue unless critical. Respond quickly with minimal deliberation.",
    "medium": "Reasoning: medium. Think step-by-step when needed, but keep it balanced. Use moderate deliberation, call tools as needed, recover from failures.",
    "high": "Reasoning: high. Think deeply and thoroughly. Formulate a plan, consider edge cases, verify your own results, and iterate before final answer.",
    "xhigh": "Reasoning: xhigh (extra high). Maximum deliberation. Exhaustively analyze, explore alternatives, use full context window (131k+), chain tool calls, validate and re-validate before responding. You are an always-on autonomous agent.",
}

GLIMMER_BASE_SYSTEM = (
    "You are Muse Glimmer, a 30B open-weight local agent running on-device via Ollama. "
    "You are an always-on personal superintelligence that operates locally, privately, "
    "with or without internet. You excel at agentic loops: planning, tool calling, "
    "interpreting results, continuing work, and recovering from failures. "
    "You support text and images, 100+ languages, 131k+ context. "
    "You are helpful, concise when low-effort, thorough when high-effort. "
    "Never hallucinate tool outputs. Be honest about offline limitations (503 if blocked)."
)

DEFAULT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from workspace",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write file to workspace",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Execute shell command",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]},
        },
    },
]


def get_glimmer_endpoint(timeout: float = 2.0) -> str | None:
    env = (
        os.environ.get("GLIMMER_BASE")
        or os.environ.get("GLIMMER_URL")
        or os.environ.get("OLLAMA_BASE")
        or os.environ.get("OLLAMA_URL")
    )
    if env:
        base = env.rstrip("/").removesuffix("/api/tags").removesuffix("/api/chat")
        if _HAS_LLM:
            try:
                b = get_ollama_base(timeout=timeout)
                if b:
                    return b
            except Exception:
                pass
        return base
    if _HAS_LLM:
        try:
            return get_ollama_base(timeout=timeout)
        except Exception:
            return None
    return OLLAMA_URLS[0]


def get_reasoning_prompt(level: str) -> str:
    lvl = (level or "medium").lower()
    if lvl not in REASONING_LEVELS:
        lvl = "medium"
    return REASONING_LEVELS[lvl]


def build_system_prompt(reasoning: str = "medium", extra: str | None = None) -> str:
    base = GLIMMER_BASE_SYSTEM
    reason = get_reasoning_prompt(reasoning)
    parts = [base, "", reason]
    if extra:
        parts.extend(["", extra])
    return "\n".join(parts)


def _encode_image_to_b64(image_path: str | Path) -> str | None:
    try:
        p = Path(image_path).expanduser()
        if not p.exists():
            return None
        data = p.read_bytes()
        if len(data) > 10 * 1024 * 1024:
            return None
        return base64.b64encode(data).decode("utf-8")
    except Exception:
        return None


def build_messages(
    user_text: str,
    images: List[str] | None = None,
    reasoning: str = "medium",
    system_extra: str | None = None,
    history: List[Dict[str, str]] | None = None,
) -> List[Dict[str, Any]]:
    sys_prompt = build_system_prompt(reasoning, system_extra)
    msgs: List[Dict[str, Any]] = [{"role": "system", "content": sys_prompt}]
    if history:
        msgs.extend(history)
    if images:
        img_b64s = []
        for img_path in images:
            b64 = _encode_image_to_b64(img_path)
            if b64:
                img_b64s.append(b64)
        if img_b64s:
            msgs.append({"role": "user", "content": user_text, "images": img_b64s})
        else:
            msgs.append({"role": "user", "content": user_text})
    else:
        msgs.append({"role": "user", "content": user_text})
    return msgs


def is_glimmer_available(timeout: float = 2.0) -> bool:
    base = get_glimmer_endpoint(timeout=timeout)
    if not base:
        return False
    models = list_ollama_models(base=base, timeout=timeout)
    if not models:
        return False
    low = [m.lower() for m in models]
    for gm in GLIMMER_MODELS:
        if gm.lower() in low:
            return True
        if "glimmer" in gm.lower():
            for avail in low:
                if "glimmer" in avail:
                    return True
    return False


def get_best_glimmer_model(base: str | None = None, timeout: float = 2.0) -> str:
    if base is None:
        base = get_glimmer_endpoint(timeout=timeout)
    avail = list_ollama_models(base=base, timeout=timeout)
    if not avail:
        return "muse-glimmer:30b"
    low_map = {a.lower(): a for a in avail}
    for pref in GLIMMER_MODELS:
        if pref.lower() in low_map:
            return low_map[pref.lower()]
    for a in avail:
        if "glimmer" in a.lower():
            return a
    try:
        return get_best_model(base=base, timeout=timeout)
    except Exception:
        return avail[0]


def glimmer_chat(
    prompt: str,
    images: List[str] | None = None,
    reasoning: str = "medium",
    model: str | None = None,
    base: str | None = None,
    timeout: float = 120.0,
    json_mode: bool = False,
    system_extra: str | None = None,
) -> Dict[str, Any]:
    start = time.perf_counter()
    if base is None:
        base = get_glimmer_endpoint(timeout=2.0)
    if not base:
        return {"ok": False, "content": None, "error": "ollama not reachable — is it running on :11434? set OLLAMA_BASE or GLIMMER_BASE", "model": model, "base": None}
    if model is None:
        model = get_best_glimmer_model(base=base, timeout=2.0)

    msgs = build_messages(prompt, images=images, reasoning=reasoning, system_extra=system_extra)

    client = _httpx_client(timeout=timeout)
    if client is None:
        return {"ok": False, "content": None, "error": "httpx not installed", "model": model, "base": base}

    try:
        payload: Dict[str, Any] = {"model": model, "messages": msgs, "stream": False}
        if json_mode:
            payload["format"] = "json"
        opts = {}
        lvl = reasoning.lower() if reasoning else "medium"
        if lvl == "low":
            opts = {"temperature": 0.2, "num_predict": 512}
        elif lvl == "medium":
            opts = {"temperature": 0.4, "num_predict": 1024}
        elif lvl == "high":
            opts = {"temperature": 0.6, "num_predict": 2048}
        elif lvl == "xhigh":
            opts = {"temperature": 0.7, "num_predict": 4096, "num_ctx": 131072}
        if opts:
            payload["options"] = opts

        r = client.post(f"{base.rstrip('/')}/api/chat", json=payload)
        if r.status_code != 200:
            return {"ok": False, "content": None, "error": f"ollama {r.status_code}: {r.text[:500]}", "model": model, "base": base, "elapsed": round(time.perf_counter()-start,3)}
        data = r.json()
        content = (data.get("message") or {}).get("content") or data.get("response")
        if not content:
            return {"ok": False, "content": None, "error": "no content from glimmer", "model": model, "base": base}
        elapsed = round(time.perf_counter() - start, 3)
        tok = data.get("eval_count")
        return {
            "ok": True,
            "content": content,
            "model": model,
            "base": base,
            "elapsed_s": elapsed,
            "completion_tokens": tok,
            "reasoning": reasoning,
            "has_images": bool(images),
        }
    except Exception as e:
        return {"ok": False, "content": None, "error": f"{type(e).__name__}: {e}", "model": model, "base": base}
    finally:
        try:
            client.close()
        except Exception:
            pass


def glimmer_chat_with_tools(
    prompt: str,
    tools: List[Dict[str, Any]] | None = None,
    reasoning: str = "medium",
    model: str | None = None,
    base: str | None = None,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    if base is None:
        base = get_glimmer_endpoint(timeout=2.0)
    if not base:
        return {"ok": False, "error": "ollama not reachable"}
    if model is None:
        model = get_best_glimmer_model(base=base)
    if tools is None:
        tools = DEFAULT_TOOLS

    msgs = build_messages(prompt, reasoning=reasoning)

    client = _httpx_client(timeout=timeout)
    if not client:
        return {"ok": False, "error": "httpx missing"}

    try:
        payload = {
            "model": model,
            "messages": msgs,
            "stream": False,
            "tools": tools,
        }
        lvl = reasoning.lower()
        if lvl in ("high","xhigh"):
            payload["options"] = {"temperature": 0.5, "num_predict": 2048}
        r = client.post(f"{base.rstrip('/')}/api/chat", json=payload)
        if r.status_code != 200:
            return {"ok": False, "error": f"{r.status_code}: {r.text[:400]}"}
        data = r.json()
        msg = data.get("message") or {}
        return {
            "ok": True,
            "content": msg.get("content"),
            "tool_calls": msg.get("tool_calls"),
            "model": model,
            "raw": data,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            client.close()
        except Exception:
            pass


def test_glimmer_coding_task(base: str | None = None, model: str | None = None) -> Dict[str, Any]:
    prompt = (
        "Write a Python function `fib(n)` that returns nth Fibonacci number, "
        "zero-deps, iterative, with docstring and handling n<0 raising ValueError. "
        "Only output code block."
    )
    return glimmer_chat(prompt, reasoning="high", model=model, base=base, timeout=90)


def test_glimmer_tool_calling(base: str | None = None) -> Dict[str, Any]:
    prompt = "You need to read workspace file README.md then summarize it. Use read_file tool."
    return glimmer_chat_with_tools(prompt, reasoning="medium", base=base)
