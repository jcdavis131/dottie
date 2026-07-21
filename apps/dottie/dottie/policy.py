# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie policy providers — the pluggable "brains" behind the CodeAct loop.

Each provider satisfies the factory's ``Policy`` contract from
``apps/ava-factory/ava/rl/codeact_loop.py``: ``transcript: str -> next assistant turn: str``.
Three backends:

  * :class:`OllamaPolicy` — real HTTP calls to an Ollama server (the user's local qwen3:32b by
    default). This is the only backend with real task capability today.
  * :class:`AvaPolicy`    — the trainee: wraps the factory's real ``TorchModelPolicy`` over a
    smoke-scale ava checkpoint. Zero capability today; exists for the training flywheel.
  * :class:`EchoPolicy`   — a clearly-labeled deterministic plumbing-test policy for CI
    (``plumbing_only=True``). Never a capability measurement.

Honesty rule: an unreachable server / missing checkpoint / missing torch raises
:class:`DottiePolicyUnavailable` with the true cause. No backend ever emits a canned fake reply.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import httpx

from dottie import resolve

DEFAULT_OLLAMA_URL = "http://host.docker.internal:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:32b"

# Transcript markers — must match ava/rl/codeact_loop.py (and the factory datagen) exactly.
USER = "<|user|>"
ASSISTANT = "<|assistant|>"

_MARKER_SPLIT = re.compile(r"<\|(user|assistant)\|>\n?")
_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

# The CodeAct protocol, explained to a chat model that was not trained on the transcript format.
CODEACT_SYSTEM_PROMPT = (
    "You are Dottie, a personal assistant agent that acts by writing Python.\n"
    "Protocol (CodeAct):\n"
    "- To act, emit exactly ONE fenced code block per turn: ```python ... ```\n"
    "  The code runs in a persistent sandboxed interpreter; you will receive an Observation\n"
    "  with its stdout / value / error, then you may act again.\n"
    "- The sandbox has no network and no filesystem writes outside its scratch dir.\n"
    "- When you have the answer, reply with plain prose and NO code block. That final turn is\n"
    "  shown to the user; you may start it with 'FINAL:'.\n"
    "- Never invent an Observation; only the environment produces them."
)


class DottiePolicyUnavailable(RuntimeError):
    """The selected policy backend cannot run (server down, checkpoint/torch missing).

    Raised instead of returning a fabricated turn — the repo's anti-fabrication rule."""


class PolicyProvider:
    """Base contract: a named, probe-able callable ``transcript -> next assistant turn``."""

    name: str = "abstract"
    plumbing_only: bool = False  # True => CI plumbing harness, never a capability claim

    def __call__(self, transcript: str) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def probe(self) -> dict[str, Any]:
        """Real availability check (no fabrication): returns {'available': bool, ...}."""
        raise NotImplementedError  # pragma: no cover - abstract


def transcript_to_messages(transcript: str) -> list[dict[str, str]]:
    """Parse the CodeAct transcript (``<|user|>``/``<|assistant|>`` marked) into chat messages.

    Sandbox Observations are rendered by the loop as user turns (``Observation:\\n...``), which
    is exactly the role a chat API expects them in."""
    parts = _MARKER_SPLIT.split(transcript)
    messages: list[dict[str, str]] = []
    # parts = [preamble, role, content, role, content, ...]; a non-empty preamble (no leading
    # marker) is treated as user content so a bare prompt still works.
    if parts and parts[0].strip():
        messages.append({"role": "user", "content": parts[0].strip()})
    for role, content in zip(parts[1::2], parts[2::2], strict=False):
        content = content.strip()
        if content:
            messages.append({"role": role, "content": content})
    return messages


def strip_think(text: str) -> str:
    """Remove closed ``<think>...</think>`` blocks (qwen3-style reasoning preamble).

    The CodeAct loop treats a turn with no ```python fence as the FINAL answer, so leaked
    reasoning must not masquerade as the user-facing reply. An unclosed block is left as-is
    (we never guess at where it would have ended)."""
    return _THINK_BLOCK.sub("", text).strip()


class OllamaPolicy(PolicyProvider):
    """Real next-turn generation over HTTP against an Ollama server (``/api/chat``).

    Base URL from ``DOTTIE_OLLAMA_URL`` (default ``http://host.docker.internal:11434``), model
    from ``DOTTIE_OLLAMA_MODEL`` (default ``qwen3:32b``). Non-streaming; sensible timeouts
    (connect fast-fails, generation may take minutes on a 32b local model). Unreachable server
    or HTTP error => :class:`DottiePolicyUnavailable` with the true cause."""

    name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        *,
        connect_timeout_s: float = 5.0,
        read_timeout_s: float | None = None,
        temperature: float = 0.2,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("DOTTIE_OLLAMA_URL") or DEFAULT_OLLAMA_URL
        ).rstrip("/")
        self.model = (
            model or os.environ.get("DOTTIE_OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
        )
        if read_timeout_s is None:
            # Env knob for slow local models (partial VRAM offload, thinking modes). A timeout
            # still refuses honestly — this only sets how long we wait for a REAL reply.
            read_timeout_s = float(
                os.environ.get("DOTTIE_OLLAMA_READ_TIMEOUT_S") or 300.0
            )
        # DOTTIE_OLLAMA_THINK=false disables thinking on models that support it (e.g. qwen3):
        # for strict-JSON research completions the long CoT only burns the read timeout.
        think_env = os.environ.get("DOTTIE_OLLAMA_THINK")
        self.think: bool | None = (
            None
            if think_env is None
            else think_env.strip().lower() in ("1", "true", "yes")
        )
        self.timeout = httpx.Timeout(
            connect=connect_timeout_s,
            read=read_timeout_s,
            write=30.0,
            pool=connect_timeout_s,
        )
        self.temperature = float(temperature)

    def __call__(self, transcript: str) -> str:
        messages = [{"role": "system", "content": CODEACT_SYSTEM_PROMPT}]
        messages += transcript_to_messages(transcript)
        return self._chat(messages)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Plain single-turn completion WITHOUT the CodeAct agent protocol.

        The research workers use this: under the CodeAct system prompt the model answers with
        fenced Python + FINAL prose (its agent protocol), not the strict JSON the research
        prompts demand. ``temperature`` overrides the instance default per call (ideation wants
        diverse sampling; code generation wants precision). Same honest transport/refusal
        semantics as ``__call__``."""
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        return self._chat(messages, temperature=temperature)

    def _chat(self, messages: list, *, temperature: float | None = None) -> str:
        options: dict = {
            "temperature": self.temperature
            if temperature is None
            else float(temperature)
        }
        # DOTTIE_OLLAMA_NUM_GPU=0 pins inference to CPU (doctrine: the GPU belongs to
        # model TRAINING; LLM inference and everything else run on CPU). Any integer is
        # passed through as the number of offloaded layers.
        num_gpu = os.environ.get("DOTTIE_OLLAMA_NUM_GPU")
        if num_gpu is not None and num_gpu.strip() != "":
            options["num_gpu"] = int(num_gpu)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        # DOTTIE_OLLAMA_KEEP_ALIVE controls how long Ollama keeps the model RESIDENT after
        # a call (e.g. "30s", "0" to unload immediately). Measured 2026-07-20: the research
        # loop calls every ~4 min, inside Ollama's 5-minute default, so with NUM_GPU=0 the
        # model never unloads and squats ~5.3 GB of system RAM permanently — which is what
        # starved the WSL VM and took the whole container fleet down. Unset = Ollama's
        # default (fast, memory-hungry); set it when the fleet must share this box.
        keep_alive = os.environ.get("DOTTIE_OLLAMA_KEEP_ALIVE")
        if keep_alive is not None and keep_alive.strip() != "":
            payload["keep_alive"] = keep_alive.strip()
        if self.think is not None:
            payload["think"] = self.think
        try:
            r = httpx.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
        except httpx.HTTPError as e:
            raise DottiePolicyUnavailable(
                f"Ollama server unreachable at {self.base_url} ({type(e).__name__}: {e}). "
                "Dottie will not fabricate a reply. Start Ollama (`ollama serve`) or point "
                "DOTTIE_OLLAMA_URL at a running server."
            ) from e
        if r.status_code != 200:
            raise DottiePolicyUnavailable(
                f"Ollama at {self.base_url} returned HTTP {r.status_code} for model "
                f"{self.model!r}: {r.text[:300]}. If the model is missing, pull it "
                f"(`ollama pull {self.model}`) or set DOTTIE_OLLAMA_MODEL."
            )
        try:
            content = r.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as e:
            raise DottiePolicyUnavailable(
                f"Ollama at {self.base_url} returned an unexpected /api/chat payload "
                f"({e}): {r.text[:300]}"
            ) from e
        return strip_think(str(content))

    def probe(self) -> dict[str, Any]:
        """Real ping: GET /api/tags. Reports whether the configured model is present."""
        base = {"backend": self.name, "url": self.base_url, "model": self.model}
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as e:
            return {**base, "available": False, "error": f"{type(e).__name__}: {e}"}
        return {
            **base,
            "available": True,
            "models_count": len(models),
            "model_present": any(
                m == self.model or m.split(":")[0] == self.model.split(":")[0]
                for m in models
            ),
        }


class AvaPolicy(PolicyProvider):
    """The trainee backend: the factory's real ``TorchModelPolicy`` over an ava checkpoint.

    HONEST CAPABILITY STATEMENT: ava checkpoints today are smoke-scale (nano preset, ~90 base +
    ~25 agentic-branch optimizer steps on ~17MB synthetic data) with ZERO task capability — an
    untrained-scale model emits noise turns, and that is its honest output. This backend exists
    so the training flywheel (rollouts -> rewards -> GRPO -> re-eval) has a real model to train,
    NOT to provide useful assistance yet. Use the ollama backend for actual tasks.

    Checkpoint from ``DOTTIE_AVA_CKPT`` or the dottie-aware probe of
    ``runs/cpu_pilot/agentic/agentic_final.pt`` (falling back to ``base/base_final.pt``) across
    the factory candidates. Torch + model are imported/loaded lazily on first call; a missing
    checkpoint or missing torch raises :class:`DottiePolicyUnavailable` honestly."""

    name = "ava"

    def __init__(
        self,
        ckpt: str | None = None,
        *,
        device: str = "cpu",
        max_new_tokens: int = 48,
        temperature: float = 0.8,
        top_k: int = 50,
        context_window: int = 768,
        seed: int = 0,
    ) -> None:
        env_ckpt = os.environ.get("DOTTIE_AVA_CKPT")
        self.ckpt: Path | None = Path(ckpt or env_ckpt) if (ckpt or env_ckpt) else None
        self.device = device
        self.max_new_tokens = int(max_new_tokens)
        self.temperature = float(temperature)
        self.top_k = int(top_k)
        self.context_window = int(context_window)
        self.seed = int(seed)
        self._policy: Any = None  # lazily-built TorchModelPolicy

    def _resolve_ckpt(self) -> Path:
        if self.ckpt is not None:
            if not self.ckpt.is_file():
                raise DottiePolicyUnavailable(
                    f"ava checkpoint not found at {self.ckpt} (from DOTTIE_AVA_CKPT or "
                    "constructor). Dottie refuses to decode from a nonexistent checkpoint. "
                    "Produce one with the factory's scripts/cpu_pilot_e2e.py."
                )
            return self.ckpt
        found = resolve.default_ava_ckpt()
        if found is None:
            raise DottiePolicyUnavailable(
                "no ava checkpoint found; probed: "
                + ", ".join(str(p) for p in resolve.ava_ckpt_candidates())
                + ". Set DOTTIE_AVA_CKPT or run the factory's scripts/cpu_pilot_e2e.py."
            )
        return found

    def _ensure_loaded(self) -> None:
        if self._policy is not None:
            return
        ckpt_path = self._resolve_ckpt()
        try:
            import torch
        except ImportError as e:
            raise DottiePolicyUnavailable(
                "the ava backend needs torch, which is not installed in this environment "
                f"({e}). Install torch or use the ollama/echo backends."
            ) from e
        try:
            root = resolve.ensure_factory_on_path()
        except resolve.DottieResolutionError as e:
            raise DottiePolicyUnavailable(str(e)) from e
        from ava.config import AvaConfig
        from ava.model import build_model
        from ava.rl.codeact_policy import TorchModelPolicy
        from ava.tokenizer import EOS_ID, AvaTokenizer

        tok_candidates = [
            ckpt_path.parent.parent / "tokenizer" / "ava_nano_bpe.json",
            root / "runs" / "cpu_pilot" / "tokenizer" / "ava_nano_bpe.json",
        ]
        tok_path = next((p for p in tok_candidates if p.is_file()), None)
        if tok_path is None:
            raise DottiePolicyUnavailable(
                "ava tokenizer not found (a real model over a mock tokenizer would decode "
                "garbage — refused). Probed: "
                + ", ".join(str(p) for p in tok_candidates)
            )
        try:
            cfg = AvaConfig.load("nano")
            model = build_model(cfg)
            blob = torch.load(
                str(ckpt_path), map_location=self.device, weights_only=False
            )
            model.load_state_dict(blob.get("model", blob))
            model.to(self.device)
            model.eval()
            tokenizer = AvaTokenizer.load(str(tok_path))
        except Exception as e:
            raise DottiePolicyUnavailable(
                f"failed to load ava checkpoint {ckpt_path}: {type(e).__name__}: {e}"
            ) from e
        self._policy = TorchModelPolicy(
            model,
            tokenizer,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            top_k=self.top_k,
            context_window=self.context_window,
            eos_id=EOS_ID,
            seed=self.seed,
            device=self.device,
        )
        self._loaded_ckpt = ckpt_path

    def __call__(self, transcript: str) -> str:
        self._ensure_loaded()
        return self._policy(transcript)

    def probe(self) -> dict[str, Any]:
        """Checkpoint existence + torch importability — checked, not loaded (probe is cheap)."""
        base: dict[str, Any] = {
            "backend": self.name,
            "capability_note": "smoke-scale checkpoint, zero task capability; flywheel trainee",
        }
        try:
            import importlib.util

            torch_ok = importlib.util.find_spec("torch") is not None
        except Exception:  # pragma: no cover - importlib misbehaving
            torch_ok = False
        try:
            ckpt = self._resolve_ckpt()
        except DottiePolicyUnavailable as e:
            return {
                **base,
                "available": False,
                "torch_installed": torch_ok,
                "error": str(e),
            }
        if not torch_ok:
            return {
                **base,
                "available": False,
                "ckpt": str(ckpt),
                "torch_installed": False,
                "error": "torch not installed",
            }
        return {**base, "available": True, "ckpt": str(ckpt), "torch_installed": True}


class EchoPolicy(PolicyProvider):
    """Deterministic plumbing-test policy (CI). ``plumbing_only=True`` — NEVER a capability
    measurement. It drives the REAL sandbox with a fixed two-action script (arithmetic +
    one ``get_clock()`` tool call), then closes with a clearly-labeled FINAL that echoes the
    task prompt. One instance per episode (it is stateful across turns)."""

    name = "echo"
    plumbing_only = True

    def __init__(self) -> None:
        self._i = 0

    @staticmethod
    def _first_user_prompt(transcript: str) -> str:
        msgs = transcript_to_messages(transcript)
        for m in msgs:
            if m["role"] == "user":
                return m["content"].splitlines()[0][:80]
        return ""

    def __call__(self, transcript: str) -> str:
        turns = [
            "Thought: plumbing check — execute real code in the real sandbox.\n"
            "```python\nx = 21 * 2\nprint('dottie-echo', x)\nx\n```",
            "Thought: exercise one bound tool call.\n"
            "```python\nnow = get_clock()\nnow\n```",
            "FINAL: EchoPolicy plumbing run complete (deterministic, plumbing_only=True; "
            f"not a capability measurement). Prompt was: {self._first_user_prompt(transcript)}",
        ]
        if self._i >= len(turns):
            return ""  # exhausted -> the loop terminates honestly as policy_empty
        turn = turns[self._i]
        self._i += 1
        return turn

    def probe(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": True,
            "plumbing_only": True,
            "note": "deterministic CI plumbing policy; not a capability measurement",
        }


class FactoryPolicy(PolicyProvider):
    """The SERVED Dottie brain: the factory server's ``POST /chat`` (hot-reloaded
    checkpoint on the GPU box, ``DOTTIE_FACTORY_URL``, default ``:8000``) — the same
    endpoint the arxiviq assistant surface talks to, so promoting a gated checkpoint
    to "Dottie's brain" is exactly: eval gate passes -> this backend serves it.

    HONEST CAPABILITY STATEMENT: capability is whatever the currently-served
    checkpoint earned at the eval gate — no more. The server truncates at turn
    boundaries; an unreachable server raises :class:`DottiePolicyUnavailable` with
    the true reason, never a fabricated turn."""

    name = "factory"

    def __init__(
        self,
        base_url: str | None = None,
        *,
        max_tokens: int = 256,
        temperature: float = 0.8,
        read_timeout_s: float | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("DOTTIE_FACTORY_URL") or "http://localhost:8000"
        ).rstrip("/")
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        if read_timeout_s is None:
            read_timeout_s = float(
                os.environ.get("DOTTIE_FACTORY_READ_TIMEOUT_S") or 120.0
            )
        self.timeout = httpx.Timeout(
            connect=5.0, read=read_timeout_s, write=30.0, pool=5.0
        )

    def _chat(
        self, messages: list[dict[str, str]], *, temperature: float | None = None
    ) -> str:
        payload = {
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
            if temperature is None
            else float(temperature),
        }
        try:
            r = httpx.post(f"{self.base_url}/chat", json=payload, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise DottiePolicyUnavailable(
                f"factory server unreachable at {self.base_url} ({type(e).__name__}: {e}). "
                "Dottie will not fabricate a reply. Serve it with the dottie-factory compose "
                "(server service) or point DOTTIE_FACTORY_URL at a running server."
            ) from e
        if r.status_code != 200:
            raise DottiePolicyUnavailable(
                f"factory server at {self.base_url} returned HTTP {r.status_code}: "
                f"{r.text[:300]}"
            )
        try:
            return r.json()["content"]
        except (ValueError, KeyError, TypeError) as e:
            raise DottiePolicyUnavailable(
                f"factory server returned an unparseable /chat body: {e}"
            ) from e

    def __call__(self, transcript: str) -> str:
        # /chat knows only the frozen user/assistant convention (tokenizer SPECIALS) —
        # the CodeAct system contract rides in the first user turn.
        messages = transcript_to_messages(transcript)
        if messages and messages[0]["role"] == "user":
            messages[0] = {
                "role": "user",
                "content": CODEACT_SYSTEM_PROMPT + "\n\n" + messages[0]["content"],
            }
        else:
            messages.insert(0, {"role": "user", "content": CODEACT_SYSTEM_PROMPT})
        return self._chat(messages)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str:
        text = f"{system}\n\n{prompt}" if system else prompt
        return self._chat([{"role": "user", "content": text}], temperature=temperature)

    def probe(self) -> dict[str, Any]:
        try:
            r = httpx.get(f"{self.base_url}/pipeline/status", timeout=self.timeout)
            ok = r.status_code == 200
            mode = (r.json().get("mode", {}) or {}).get("id") if ok else None
            return {
                "backend": self.name,
                "available": ok,
                "base_url": self.base_url,
                "server_mode": mode,
            }
        except httpx.HTTPError as e:
            return {
                "backend": self.name,
                "available": False,
                "base_url": self.base_url,
                "error": f"{type(e).__name__}: {e}",
            }


BACKENDS = ("ollama", "ava", "echo", "factory")


def get_policy(backend: str, **kwargs: Any) -> PolicyProvider:
    """Fresh provider per episode (EchoPolicy is stateful; Ava/Ollama are cheap shells)."""
    if backend == "ollama":
        return OllamaPolicy(**kwargs)
    if backend == "ava":
        return AvaPolicy(**kwargs)
    if backend == "echo":
        return EchoPolicy(**kwargs)
    if backend == "factory":
        return FactoryPolicy(**kwargs)
    raise ValueError(f"unknown backend {backend!r}; choices: {', '.join(BACKENDS)}")
