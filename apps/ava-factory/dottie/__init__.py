"""Dottie — real implementation package.

Solo personal project, no connection to employer, built with public/free-tier only.

The repo root holds the original v6.4 blueprint (train_1b_deepspeed.py,
eval_branch_harness.py, ...), which is mock scaffolding kept for reference.
Everything under `dottie/` is the real, tested implementation that supersedes it.

Renamed from Ava (placeholder) → Dottie on 2026-07-16.

Exports are PEP 562 lazy on purpose: the model/config/tokenizer pull in torch,
and the CPU pipeline images (collector/curator/janitor) ship without torch by
design. An eager `from .model import ...` here took the whole CPU fleet down at
import time (cutover 2026-07-19). Anything that truly needs the model still gets
it — `from dottie import DottieModel1B` resolves lazily on first access.
"""

# Namespace package merge — fixes dottie name collision (HANDOFF.md #2)
# Both apps/dottie and apps/ava-factory contribute to `dottie` namespace.
# Without this, only first sys.path entry wins, 35 tests fail ModuleNotFoundError dottie.rl.
# Measured 36->1 failed, 286 passed. Zero-deps true, stdlib only.
from pkgutil import extend_path
try:
    __path__ = extend_path(__path__, __name__)
except NameError:
    # __path__ not yet defined when imported as namespace — define via pkgutil
    from pkgutil import extend_path as _ep
    import sys as _sys
    __path__ = _ep([], __name__)

from importlib import import_module

__version__ = "6.5.0-dottie"

# name -> (submodule, attribute); Ava names are legacy aliases of the Dottie ones.
_LAZY_EXPORTS = {
    "DottieConfig": ("dottie.config", "DottieConfig"),
    "DottieModel1B": ("dottie.model", "DottieModel1B"),
    "DottieTokenizer": ("dottie.tokenizer", "DottieTokenizer"),
    "AvaConfig": ("dottie.config", "DottieConfig"),
    "AvaModel1B": ("dottie.model", "DottieModel1B"),
    "AvaTokenizer": ("dottie.tokenizer", "DottieTokenizer"),
}

# Deliberately empty: `from dottie import *` (the ava compat shim does this) must
# not force the lazy names — that would re-import torch into torch-less images.
__all__: list = []


def __getattr__(name: str):
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_name), attr)
    globals()[name] = value  # cache: subsequent access skips __getattr__
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
