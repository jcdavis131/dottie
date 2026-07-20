"""
registry.py — evaluation registry with decorator @register_eval

Solo personal project, no connection to employer, built with public/free-tier only
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

EvalFn = Callable[..., dict[str, Any]]
EVAL_REGISTRY: dict[str, dict[str, Any]] = {}


def register_eval(
    name: str,
    description: str = "",
    group: str = "general",
    requires_model: bool = True,
):
    """Decorator to register an eval.

    Usage:
      @register_eval(name="spider_ant", description="...", group="jspace")
      def eval_fn(model, tokenizer, device, **kwargs): ...
    """

    def decorator(fn: EvalFn) -> EvalFn:
        if name in EVAL_REGISTRY:
            raise ValueError(f"eval {name!r} already registered")
        EVAL_REGISTRY[name] = {
            "fn": fn,
            "description": description,
            "group": group,
            "requires_model": requires_model,
        }
        # Return fn unchanged — the old wraps() wrapper was a no-op passthrough.
        return fn

    return decorator


def list_evals(group: str | None = None) -> list[str]:
    if group is None:
        return sorted(EVAL_REGISTRY.keys())
    return sorted([k for k, v in EVAL_REGISTRY.items() if v["group"] == group])


def get_eval(name: str) -> dict[str, Any]:
    if name not in EVAL_REGISTRY:
        raise KeyError(f"eval {name!r} not found. Available: {list_evals()}")
    return EVAL_REGISTRY[name]
