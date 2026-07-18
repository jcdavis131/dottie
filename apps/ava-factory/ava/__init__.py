"""Ava — real implementation package.

Solo personal project, no connection to employer, built with public/free-tier
only.

The repo root holds the original v6.4 blueprint (train_1b_deepspeed.py,
eval_branch_harness.py, ...), which is mock scaffolding kept for reference.
Everything under `ava/` is the real, tested implementation that supersedes it.

Exceptions — these root modules are real and are imported from here after the
spec-04 bug fixes: model_1b.py, multi_jspace_module.py, server.py.
"""

__version__ = "0.1.0"
