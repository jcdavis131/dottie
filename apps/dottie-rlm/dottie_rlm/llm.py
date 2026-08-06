"""LLM backends for the dottie-rlm harness (SPEC v1, llm.py contract).

- ``Backend`` protocol: ``complete(messages, *, max_tokens) -> str``.
- ``OllamaBackend``: local Ollama /api/chat, stream=False, hard 300s timeout,
  raises :class:`BackendUnavailable` with an actionable message on failure.
- ``OpenAICompatBackend``: any OpenAI-compatible /chat/completions endpoint.
  The API key comes from the environment ONLY (default ``DOTTIE_RLM_API_KEY``),
  is read at call time, is never stored on the instance, and never appears in
  logs, reprs, or error messages.
- ``FakeBackend``: deterministic scripted replies for tests — zero network.
  Over-consuming the script raises :class:`FakeBackendExhausted` so a test
  that asks for more completions than it scripted fails loudly instead of
  looping.
- ``resolve_backend(spec)``: parses ``"fake:"``, ``"ollama:<model>"``,
  ``"openai:<base_url>:<model>"``.

House rule (SPEC): the harness degrades honestly — if no backend is reachable
the call refuses with a clear error; nothing is fabricated.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

import requests

__all__ = [
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_OLLAMA_HOST",
    "DEFAULT_OLLAMA_MODEL",
    "HARD_TIMEOUT_S",
    "Backend",
    "BackendUnavailable",
    "FakeBackend",
    "FakeBackendExhausted",
    "OllamaBackend",
    "OpenAICompatBackend",
    "resolve_backend",
]

DEFAULT_OLLAMA_MODEL = "qwen3:8b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_API_KEY_ENV = "DOTTIE_RLM_API_KEY"
#: Hard wall on any single completion HTTP call (SPEC: 300s).
HARD_TIMEOUT_S = 300.0


class BackendUnavailable(RuntimeError):  # noqa: N818 — public API name (SPEC v1); renaming breaks importers
    """The LLM backend cannot serve this completion.

    The message is always actionable: it says what was tried and what the
    operator should do about it. It never contains an API key.
    """


class FakeBackendExhausted(RuntimeError):  # noqa: N818 — public API name (SPEC v1); renaming breaks importers
    """A FakeBackend was asked for more replies than its script contains."""


@runtime_checkable
class Backend(Protocol):
    """Anything that can turn a chat message list into a completion string."""

    def complete(self, messages: list[dict], *, max_tokens: int) -> str:
        """Return the assistant reply for ``messages``. May raise
        :class:`BackendUnavailable`."""
        ...  # pragma: no cover - protocol body


class OllamaBackend:
    """Local Ollama chat backend (``POST {host}/api/chat``, stream=False).

    NOTE (this box): qwen3:8b runs with NUM_GPU=0 — it loads into system RAM,
    so completions are CPU-speed. That is expected, not a hang.
    """

    def __init__(
        self,
        model: str = DEFAULT_OLLAMA_MODEL,
        host: str = DEFAULT_OLLAMA_HOST,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout_s = HARD_TIMEOUT_S

    def __repr__(self) -> str:  # no secrets involved, plain repr
        return f"OllamaBackend(model={self.model!r}, host={self.host!r})"

    def complete(self, messages: list[dict], *, max_tokens: int) -> str:
        url = f"{self.host}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": int(max_tokens)},
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout_s)
        except requests.exceptions.RequestException as exc:
            raise BackendUnavailable(
                f"Ollama is unreachable at {url} "
                f"({type(exc).__name__}: {exc}). "
                f"Start the server with `ollama serve`, confirm the model is "
                f"pulled with `ollama pull {self.model}`, then retry. "
                f"(On this box qwen3:8b runs NUM_GPU=0 / system RAM — slow is "
                f"normal, unreachable is not.)"
            ) from exc
        if resp.status_code != 200:
            raise BackendUnavailable(
                f"Ollama at {url} returned HTTP {resp.status_code}: "
                f"{resp.text[:500]}. "
                f"Confirm the model name ({self.model!r}) is pulled: "
                f"`ollama pull {self.model}`."
            )
        try:
            content = resp.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise BackendUnavailable(
                f"Ollama at {url} returned an unparseable chat response "
                f"({type(exc).__name__}); body starts: {resp.text[:200]!r}. "
                f"This usually means an Ollama version mismatch — check "
                f"`ollama --version`."
            ) from exc
        if not isinstance(content, str):
            raise BackendUnavailable(
                f"Ollama at {url} returned a non-string message content "
                f"({type(content).__name__}); refusing to fabricate a reply."
            )
        return content


class OpenAICompatBackend:
    """OpenAI-compatible chat backend (``POST {base_url}/chat/completions``).

    The API key is read from the environment variable named by
    ``api_key_env`` at *call* time. It is never accepted as an argument,
    never read from a file, never stored on the instance, and never included
    in any exception message or repr.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str = DEFAULT_API_KEY_ENV,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout_s = HARD_TIMEOUT_S

    def __repr__(self) -> str:  # key is not on the instance; repr is safe
        return (
            f"OpenAICompatBackend(base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key_env={self.api_key_env!r})"
        )

    def complete(self, messages: list[dict], *, max_tokens: int) -> str:
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            raise BackendUnavailable(
                f"No API key available: set the {self.api_key_env} "
                f"environment variable. Keys are read from the environment "
                f"only — never from files — and are never logged."
            )
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "stream": False,
        }
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=self.timeout_s,
            )
        except requests.exceptions.RequestException as exc:
            # Exception class name only — never str(exc), which could echo
            # request details on some transport errors.
            raise BackendUnavailable(
                f"OpenAI-compatible endpoint unreachable at {url} "
                f"({type(exc).__name__}). Check the base_url and network, "
                f"then retry."
            ) from exc
        if resp.status_code != 200:
            body = resp.text[:300].replace(api_key, "***")
            raise BackendUnavailable(
                f"OpenAI-compatible endpoint {url} returned HTTP "
                f"{resp.status_code}: {body}. Check the model name "
                f"({self.model!r}) and that {self.api_key_env} holds a valid "
                f"key."
            )
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise BackendUnavailable(
                f"OpenAI-compatible endpoint {url} returned an unparseable "
                f"chat response ({type(exc).__name__}); body starts: "
                f"{resp.text[:200].replace(api_key, '***')!r}."
            ) from exc
        if not isinstance(content, str):
            raise BackendUnavailable(
                f"OpenAI-compatible endpoint {url} returned a non-string "
                f"message content ({type(content).__name__}); refusing to "
                f"fabricate a reply."
            )
        return content


class FakeBackend:
    """Deterministic scripted backend for tests. Zero network.

    Pops replies from ``script`` in order. Asking for more replies than the
    script contains raises :class:`FakeBackendExhausted` — a test that
    over-consumes must fail, not loop.

    ``calls`` records ``(messages, max_tokens)`` per invocation so tests can
    assert on what the loop actually sent.
    """

    def __init__(self, script: list[str]) -> None:
        self._script: list[str] = list(script)
        self.calls: list[tuple[list[dict], int]] = []

    def __repr__(self) -> str:
        return (
            f"FakeBackend(remaining={len(self._script)}, "
            f"consumed={len(self.calls)})"
        )

    @property
    def remaining(self) -> int:
        return len(self._script)

    def complete(self, messages: list[dict], *, max_tokens: int) -> str:
        self.calls.append((messages, max_tokens))
        if not self._script:
            raise FakeBackendExhausted(
                f"FakeBackend script exhausted after {len(self.calls) - 1} "
                f"replies; the test asked for one more completion than it "
                f"scripted."
            )
        return self._script.pop(0)


def resolve_backend(spec: str) -> Backend:
    """Resolve a backend spec string into a Backend instance.

    Accepted forms (SPEC):
      - ``"fake:"``               -> FakeBackend([])   (empty script;
        ``"fake:<reply>"`` scripts that single reply — handy for CLI smoke)
      - ``"ollama:<model>"``      -> OllamaBackend(model)  (``"ollama:"`` /
        ``"ollama"`` use the default model, qwen3:8b)
      - ``"openai:<base_url>:<model>"`` -> OpenAICompatBackend; the model is
        everything after the LAST colon, so base_url may contain ``://`` and
        ``:port``.

    Anything else raises ValueError with the accepted forms spelled out.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError(
            "Backend spec must be a non-empty string: 'fake:', "
            "'ollama:<model>', or 'openai:<base_url>:<model>'."
        )
    scheme, _, rest = spec.strip().partition(":")
    scheme = scheme.lower()
    if scheme == "fake":
        return FakeBackend([rest] if rest else [])
    if scheme == "ollama":
        return OllamaBackend(model=rest.strip() or DEFAULT_OLLAMA_MODEL)
    if scheme == "openai":
        base_url, sep, model = rest.rpartition(":")
        if not sep or not base_url.strip() or not model.strip():
            raise ValueError(
                f"OpenAI backend spec must be 'openai:<base_url>:<model>' "
                f"(model after the last colon); got {spec!r}."
            )
        return OpenAICompatBackend(base_url=base_url.strip(), model=model.strip())
    raise ValueError(
        f"Unknown backend spec {spec!r}; expected 'fake:', 'ollama:<model>', "
        f"or 'openai:<base_url>:<model>'."
    )
