# Solo personal project, no connection to employer, built with public/free-tier only
"""Provider/model profile registry — deepagents-pattern config for LLM backends.

Pattern adapted from LangChain deepagents' models docs (reviewed 2026-07-22):
specs are ``provider:model`` strings; init parameters register at PROVIDER
level (apply to every model of that provider) or MODEL level (one model),
and resolution merges provider -> model -> call-site overrides, later wins.

Policy-as-config: profiles are plain data (registerable at runtime, loadable
from JSON via ``load_profiles``), so ops can retune temperature/num_ctx per
box without a code edit — grep-able, auditable, testable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# provider -> params; (provider, model) -> params. Module-level registry —
# deliberate: one process, one policy, same as the trust registry.
_PROVIDER_PROFILES: dict[str, dict[str, Any]] = {}
_MODEL_PROFILES: dict[tuple[str, str], dict[str, Any]] = {}


def register_provider(provider: str, **params: Any) -> None:
    """Merge params into the provider-level profile (later calls win)."""
    _PROVIDER_PROFILES.setdefault(provider, {}).update(params)


def register_model(spec: str, **params: Any) -> None:
    """Merge params into one model's profile. spec = 'provider:model'."""
    provider, model = parse_spec(spec)
    _MODEL_PROFILES.setdefault((provider, model), {}).update(params)


def parse_spec(spec: str) -> tuple[str, str]:
    """'provider:model' -> (provider, model). Model may contain colons
    (ollama tags like qwen3:8b): split on the FIRST colon only; a bare name
    defaults to provider 'ollama' (the box's native backend)."""
    if ":" in spec:
        provider, model = spec.split(":", 1)
        if provider in KNOWN_PROVIDERS:
            return provider, model
        # not a known provider — treat the whole spec as an ollama tag
        return "ollama", spec
    return "ollama", spec


KNOWN_PROVIDERS = ("ollama", "koboldcpp", "openai", "anthropic", "dottie")


def resolve(spec: str, **overrides: Any) -> dict[str, Any]:
    """Merged config for a spec: provider profile <- model profile <-
    call-site overrides (later wins). Always carries provider + model."""
    provider, model = parse_spec(spec)
    params: dict[str, Any] = {}
    params.update(_PROVIDER_PROFILES.get(provider, {}))
    params.update(_MODEL_PROFILES.get((provider, model), {}))
    params.update({k: v for k, v in overrides.items() if v is not None})
    return {"provider": provider, "model": model, "params": params}


def load_profiles(path: str | Path) -> int:
    """Load a JSON profiles file:
    {"providers": {name: {params}}, "models": {"provider:model": {params}}}.
    Returns number of profiles applied. Missing file -> 0, honestly."""
    p = Path(path)
    if not p.exists():
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    n = 0
    for name, params in (data.get("providers") or {}).items():
        if isinstance(params, dict):
            register_provider(str(name), **params)
            n += 1
    for spec, params in (data.get("models") or {}).items():
        if isinstance(params, dict):
            register_model(str(spec), **params)
            n += 1
    return n


def reset_profiles() -> None:
    """Test hook: clear the registry."""
    _PROVIDER_PROFILES.clear()
    _MODEL_PROFILES.clear()


# The box's defaults (memory: qwen3:8b is the workhorse, NUM_GPU=0 keeps it
# in system RAM so it never contends with the trainer's VRAM).
register_provider("ollama", num_gpu=0, temperature=0.2)
register_model("ollama:qwen3:8b", num_ctx=8192)
