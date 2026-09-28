"""The llm tier: one chat completion through ``bigbang.core.llm``, measured.

One backend, local only: Ollama at ``OLLAMA_HOST`` (default
``http://localhost:11434``), model ``DOTTIE_LLM_MODEL`` (default
:data:`DEFAULT_OLLAMA_MODEL`). Cost 0.

:data:`DEFAULT_OLLAMA_MODEL` moved from ``qwen2.5:7b-instruct`` to ``qwen3:8b``
on 2026-09-27 (Cam, PR #67 review): the old default is not pulled on this box
(``ollama list`` shows only ``qwen3:8b`` and ``agentos-qwen``), so the llm tier
was unavailable here unless ``DOTTIE_LLM_MODEL`` was set — the harness's own
``qwen2.5:7b-instruct`` runbook example never actually ran locally. This
changes which model produces "scout router probe" labels: a probe run without
``DOTTIE_LLM_MODEL`` set now records ``ollama:qwen3:8b`` instead of
``ollama:qwen2.5:7b-instruct``. qwen3 is a thinking model; ``final_answer()``
already takes the LAST ``ANSWER:`` line, so a leaked ``<think>`` block ahead of
it is harmless, but a fenced-code reply still returns the whole content
verbatim (pre-existing behavior, unchanged here).

The hosted Anthropic and OpenAI fallbacks were removed on 2026-09-27 (Cam's
no-paid-APIs rule; his answer for Dottie's paid code paths was "Remove them").
Their env vars (:data:`REMOVED_BACKEND_ENV`) are never read for a call. When
one is still set and Ollama is down, the :class:`ExecutorUnavailable` message
says the backend was removed, so the tier fails closed and never quietly
behaves as if the hosted model had been consulted.

Ollama unreachable raises :class:`ExecutorUnavailable` saying why, and the
outcome is never labelled. Tokens are the backend's own usage counts; latency
is measured around the call.
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

DEFAULT_OLLAMA_MODEL = "qwen3:8b"
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


BACKENDS = (("ollama", _ollama, True),)

#: The env vars that used to select a hosted fallback, per removed backend.
REMOVED_BACKEND_ENV = {
    "anthropic": ("DOTTIE_ANTHROPIC_MODEL", "ANTHROPIC_API_KEY"),
    "openai": ("DOTTIE_OPENAI_MODEL", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
}


def removed_backend_notes() -> list[str]:
    """One line per removed hosted backend whose env vars are still set.

    Setting them used to route this tier to a paid API when Ollama was down. They
    are ignored now; saying so in the refusal keeps the operator from reading an
    unavailable tier as a flaky key.
    """
    notes = []
    for name, env in REMOVED_BACKEND_ENV.items():
        set_vars = [v for v in env if os.environ.get(v, "").strip()]
        if set_vars:
            notes.append(f"{name} backend {llm.REMOVED_BACKENDS[name]} ({', '.join(set_vars)} ignored)")
    return notes


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
    raise ExecutorUnavailable("no LLM backend reachable: " + "; ".join(skipped + removed_backend_notes()))


def run(goal: str) -> ExecResult:
    return complete(goal)
