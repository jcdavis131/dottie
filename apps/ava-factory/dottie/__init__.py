"""Dottie — real implementation package.

Solo personal project, no connection to employer, built with public/free-tier only.

The repo root holds the original v6.4 blueprint (train_1b_deepspeed.py,
eval_branch_harness.py, ...), which is mock scaffolding kept for reference.
Everything under `dottie/` is the real, tested implementation that supersedes it.

Renamed from Ava (placeholder) → Dottie on 2026-07-16.
"""

__version__ = "6.5.0-dottie"

# Re-export main classes with new names + legacy aliases
try:
    from .config import DottieConfig
    from .model import DottieModel1B
    from .tokenizer import DottieTokenizer
    # Legacy aliases for backward compat
    AvaConfig = DottieConfig
    AvaModel1B = DottieModel1B
    AvaTokenizer = DottieTokenizer
except Exception:
    # During partial renames, ignore
    pass

__all__ = ["DottieConfig", "DottieModel1B", "DottieTokenizer"]
