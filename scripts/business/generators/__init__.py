#!/usr/bin/env python3
"""Loader for venture artifact generators — the contract B2/B3 code against.

A generator is a standalone module at scripts/business/generators/<name>.py
loaded lazily BY FILE PATH (never imported at top level anywhere), so a
playbook may name a generator that has not landed yet: the engine maps the
FileNotFoundError below to status "skipped-missing-generator" instead of
crashing. Each generator module MUST expose:

    def generate(
        inputs: dict[str, list[pathlib.Path]],
        params: dict[str, object],
        generated_at: str,
    ) -> dict[str, str]

  inputs: declared input `name` -> resolved EXISTING paths (globs expanded,
    sorted, missing/unreadable entries filtered out).
  params: the artifact's `params` block ({} if absent). generated_at: UTC
    ISO-8601 stamp injected by the engine (tests pass a fixed value ->
    generators are deterministic).
  returns: output basename -> complete file text (JSON pre-serialized by the
    generator with sort_keys=True, indent=2; markdown as text).
  Missing/unusable REQUIRED content -> raise FileNotFoundError with a message
    (stdlib, so generator modules need no cross-lane import); the engine maps
    it to "skipped-missing-input".
  Generators are pure over their given paths: read-only, deterministic, no
    network. Sole sanctioned exception: changelog.py may invoke read-only
    `git` subprocesses (declared via params.base_ref, no file inputs).
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def load_generator(name: str, root: Path) -> ModuleType:
    """Load scripts/business/generators/<name>.py under `root` by file path.

    Raises FileNotFoundError when the module file is absent — the engine turns
    that into status "skipped-missing-generator".
    """
    path = root / "scripts" / "business" / "generators" / f"{name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"no generator module at {path}")
    spec = importlib.util.spec_from_file_location(
        f"dottie_business_generator_{name}", path
    )
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"cannot build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
