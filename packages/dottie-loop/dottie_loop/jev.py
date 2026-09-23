"""File-path loader for System One's frozen validator (``apps/jev-v0/decision_io.py``).

jev-v0 sits outside the uv workspace (its ``--go`` extras pin torch), so it is
not importable as a package. Its ``decision_io`` module is stdlib only, and it
is the single definition of ``jev-decision-schema-1.0.0``: the router pack,
the eval and the checkpoint identity all go through it rather than a copy.
``DOTTIE_JEV_DIR`` overrides the location (an installed scout without the
monorepo must set it to use the training loop).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

from dottie_loop.errors import InvalidInputError

SCHEMA_ID = "jev-decision-schema-1.0.0"


def jev_dir() -> Path:
    env = os.environ.get("DOTTIE_JEV_DIR")
    if env:
        return Path(env)
    # packages/dottie-loop/dottie_loop/jev.py -> repo root
    return Path(__file__).resolve().parents[3] / "apps" / "jev-v0"


def load_decision_io() -> Any:
    """Import ``decision_io`` by path; raise InvalidInputError when it is missing or drifted."""
    cached = sys.modules.get("jev_decision_io")
    if cached is not None:
        return cached
    path = jev_dir() / "decision_io.py"
    if not path.is_file():
        raise InvalidInputError(f"System One validator not found at {path} (set DOTTIE_JEV_DIR)", field="jev_dir")
    spec = importlib.util.spec_from_file_location("jev_decision_io", path)
    if spec is None or spec.loader is None:
        raise InvalidInputError(f"cannot load {path}", field="jev_dir")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jev_decision_io"] = mod
    spec.loader.exec_module(mod)
    if mod.SCHEMA_ID != SCHEMA_ID:
        del sys.modules["jev_decision_io"]
        raise InvalidInputError(f"jev-v0 schema is {mod.SCHEMA_ID}, the router writes {SCHEMA_ID}", field="schema")
    return mod
