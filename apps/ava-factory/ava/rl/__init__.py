"""ava.rl — canonical re-export of dottie.rl (factory owns RL)
Real implementation lives in dottie.rl; ava-factory shims here for legacy imports.
Do NOT replace sys.modules — keep as package so submodules like codeact_loop still resolvable.
"""
from __future__ import annotations
try:
    from dottie.rl import *  # noqa: F401,F403
    from dottie import rl as _canonical
    # expose canonical attrs
    RLVariant = getattr(_canonical, "RLVariant", None)
    export_rft_dataset = getattr(_canonical, "export_rft_dataset", None)
    train_step = getattr(_canonical, "train_step", None)
except Exception:
    # fallback stubs when dottie not on path (CI minimal)
    RLVariant = None
    export_rft_dataset = None
    train_step = None

# allow import ava.rl.codeact_loop later if present elsewhere
__all__ = ["RLVariant", "export_rft_dataset", "train_step"]
