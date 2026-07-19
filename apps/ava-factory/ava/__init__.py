"""Backward-compat shim: ava -> dottie. Ava was placeholder, now Dottie."""

from dottie import *  # noqa: F401,F403
import importlib
import sys
# Lazy redirect any submodule import ava.X -> dottie.X
try:
    import dottie as _dottie_pkg
    sys.modules.setdefault(__name__, _dottie_pkg)
    # For submodules, Python will try ava.<sub> ; we proxy via dottie
    # Create wrapper module for common submodules on demand via __getattr__
except Exception:
    pass

# Keep old names as aliases
try:
    from dottie.config import DottieConfig as AvaConfig, DottieConfig
    from dottie.model import DottieModel1B as AvaModel1B
    from dottie.tokenizer import DottieTokenizer as AvaTokenizer
    DottieModel1B_alias = AvaModel1B
except Exception:
    pass
