"""Skip test modules whose dependencies aren't in the current image.

The two images are deliberately disjoint: `ava/cpu` carries the data stack
(datasets, datasketch, zstandard, tokenizers) and no torch; `ava/gpu` carries
torch and no data stack. Neither is wrong -- a 2.5GB CUDA wheel has no business
in a collector container. So a module that imports what this image lacks is
skipped, not an error.

Running the full suite therefore means running it in BOTH images:
    make test        # cpu: pipeline
    make test-gpu    # gpu: model, losses, trainer
"""

from __future__ import annotations

import importlib.util

_MODULE_REQUIREMENTS = {
    "test_model.py": ["torch"],
    "test_jlosses.py": ["torch"],
    "test_train_smoke.py": ["torch"],
    "test_eval_harness.py": ["torch"],
    "test_no_mock.py": [],
    "test_collector.py": ["datasets", "zstandard"],
    "test_curator.py": ["datasketch", "zstandard", "tokenizers"],
    "test_datagen.py": ["zstandard"],
    "test_tokenizer.py": ["tokenizers", "zstandard"],
    "test_data.py": ["numpy", "tokenizers", "yaml"],
    "test_manifest.py": [],
    "test_flow.py": ["yaml"],
}


def _missing(mods: list[str]) -> list[str]:
    return [m for m in mods if importlib.util.find_spec(m) is None]


def pytest_ignore_collect(collection_path, config):  # noqa: ARG001
    reqs = _MODULE_REQUIREMENTS.get(collection_path.name)
    if not reqs:
        return False
    return bool(_missing(reqs))
