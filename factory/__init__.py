"""Factory package shim (deprecated).

The factory/ modules have been migrated to dottie_loop/ (step 6 of Dottie
consolidation). This shim preserves `python -m factory` for backward
compatibility. Update your imports to dottie_loop.* directly.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "The 'factory' package is deprecated; use 'dottie_loop' instead. "
    "See dottie_loop.factory_cli for the CLI.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export the migrated modules for backward compatibility
from dottie_loop.factory_cli import main  # noqa: F401
from dottie_loop.factory_config import Factory, FactoryError  # noqa: F401

__all__ = ["__version__", "main", "Factory", "FactoryError"]
__version__ = "0.1.0"
