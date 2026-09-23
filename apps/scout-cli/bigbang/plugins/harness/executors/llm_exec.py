"""The llm tier: one chat completion through ``bigbang.core.llm``, measured.

Backend chain, first reachable wins:

1. Ollama at ``OLLAMA_HOST`` (default ``http://localhost:11434``), model
   ``DOTTIE_LLM_MODEL`` (default :data:`DEFAULT_OLLAMA_MODEL`). Cost 0 (local).
2. Anthropic, when ``ANTHROPIC_API_KEY`` and ``DOTTIE_ANTHROPIC_MODEL`` are set.
3. An OpenAI-compatible endpoint, when ``OPENAI_API_KEY`` and
   ``DOTTIE_OPENAI_MODEL`` are set (``OPENAI_BASE_URL``, default the OpenAI API).

No backend reachable raises :class:`ExecutorUnavailable` naming why each one
was skipped, and the outcome is never labelled. Tokens are the backend's own
usage counts; latency is measured around the call.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from bigbang.core import llm
from bigbang.plugins.harness.executors.base import (
    ExecResult,
    ExecutorUnavailable,
    price,
)

DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct"
SYSTEM_PROMPT = (
    "You are a careful assistant. Solve the task. If the task asks for code, reply with one ```python block "
    "containing the complete code and nothing else. Otherwise think briefly, then give the final answer alone "
    "on the last line as: ANSWER: <answer>"
)
_ANSWER = re.compile(r"ANSWER:\s*(.+?)\s*$", re.I | re.M)


def ollama_base() -> str:
    from dottie_loop.env import ollama_host

    base = (ollama_host() or "http://localhost:11434").strip().rstrip("/")
    return base if "://" in base else f"http://{base}"


def final_answer(content: str) -> str:
    """The ``ANSWER:`` line when there is one; the whole reply when it carries code."""
    if "```" in content:
        return content
    found = _ANSWER.findall(content)
    return found[-1].strip() if found else content.strip()


def _ollama(messages: list[dict[str, str]], timeout: float) -> tuple[dict[str, Any] | None, str, str]:
    base = ollama_base()
    model = os.environ.get("DOTTIE_LLM_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL
    reachable = llm.get_ollama_base(timeout=2.0, use_cache=False)
    if reachable is None:
        return None, f"ollama:{model}", f"ollama not reachable at {base} (start `ollama serve`)"
    res = llm._ollama_generate(model, messages, reachable, timeout=timeout)
    if res is None:
        return None, f"ollama:{model}", f"ollama at {reachable} returned no completion (run `ollama pull {model}`)"
    return res, f"ollama:{model}", ""


def _anthropic(messages: list[dict[str, str]], timeout: float) -> tuple[dict[str, Any] | None, str, str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("DOTTIE_ANTHROPIC_MODEL", "").strip()
    if not key or not model:
        return None, "anthropic", "ANTHROPIC_API_KEY and DOTTIE_ANTHROPIC_MODEL not both set"
    res = llm.anthropic_chat(model, messages, key, timeout=timeout)
    return res, f"anthropic:{model}", "" if res else "anthropic call failed"


def _openai(messages: list[dict[str, str]], timeout: float) -> tuple[dict[str, Any] | None, str, str]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("DOTTIE_OPENAI_MODEL", "").strip()
    if not key or not model:
        return None, "openai", "OPENAI_API_KEY and DOTTIE_OPENAI_MODEL not both set"
    base = os.environ.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
    res = llm.openai_chat(model, messages, base, timeout=timeout, api_key=key)
    return res, f"openai:{model}", "" if res else f"openai-compatible call to {base} failed"


BACKENDS = (("ollama", _ollama, True), ("anthropic", _anthropic, False), ("openai", _openai, False))


def complete(prompt: str, *, system: str = SYSTEM_PROMPT, timeout: float = 120.0, tier: str = "llm") -> ExecResult:
    """One completion from the first reachable backend. ExecutorUnavailable when none is."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    skipped: list[str] = []
    for _name, call, local in BACKENDS:
        t0 = time.perf_counter()
        res, label, why = call(messages, timeout)
        latency = round((time.perf_counter() - t0) * 1000, 3)
        if res is None or res.get("content") is None:
            skipped.append(why or f"{label}: no completion")
            continue
        pt, ct = res.get("prompt_tokens"), res.get("completion_tokens")
        cost, basis = price(pt, ct, local=local)
        content = str(res["content"])
        return ExecResult(
            tier=tier, backend=label, answer=final_answer(content), text=content,
            tokens={"prompt": pt, "completion": ct, "total": (pt or 0) + (ct or 0) if pt is not None or ct is not None else None},
            latency_ms=latency, cost_usd=cost, cost_basis=basis, meta={"skipped_backends": skipped},
        )
    raise ExecutorUnavailable("no LLM backend reachable: " + "; ".join(skipped))


def run(goal: str) -> ExecResult:
    return complete(goal)
