"""HF → training-text adapters keyed by ``SourceSpec.adapter``.

Adapters are pure functions: ``rec -> {text, _task_type?, _concept?} | None``.
They never open the network; the collector streams HF rows and calls these.
"""
from __future__ import annotations

from collections.abc import Callable

from dottie.datagen.swe_traj_adapt import adapt_record as swe_react
from dottie.datagen.xlam_adapt import adapt_record as xlam_react

AdapterFn = Callable[[dict], dict | None]

ADAPTERS: dict[str, AdapterFn] = {
    "xlam_react": xlam_react,
    "swe_react": swe_react,
}


def apply_adapter(adapter: str | None, rec: dict) -> dict | None:
    """Run ``adapter`` on ``rec``. Unknown names raise; missing adapter is identity."""
    if not adapter:
        return rec
    try:
        fn = ADAPTERS[adapter]
    except KeyError as e:
        raise ValueError(
            f"unknown adapter {adapter!r}; known: {sorted(ADAPTERS)}"
        ) from e
    return fn(rec)
