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
    "test_grow.py": ["torch"],
    "test_jlosses.py": ["torch"],
    "test_train_smoke.py": ["torch"],
    "test_eval_harness.py": ["torch"],
    "test_no_mock.py": [],
    # NOT "datasets": collector.py imports it LAZILY (inside the HF path, ~line 307), so the
    # test module imports and its 15 tests pass without it. Declaring it here silently
    # dropped all 15 from every full-suite run on any box without `datasets` -- including
    # this one -- with no skip line and no error, because pytest_ignore_collect is invisible
    # in the summary. The suite just reported a smaller number that still looked healthy
    # (470 instead of 485). Measured 2026-07-20, TODOS 5.3.R83.
    "test_collector.py": ["zstandard"],
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


def pytest_report_header(config):  # noqa: ARG001
    """Say OUT LOUD which modules this image is skipping, and why.

    ``pytest_ignore_collect`` is invisible: an ignored module produces no skip line, no
    error, and no mention in the summary -- the collected count simply shrinks. A stale
    entry in the table above therefore reads exactly like a healthy run.

    That is not hypothetical. ``test_collector.py`` declared ``datasets``, which
    collector.py only imports lazily, so 15 real tests were dropped from every full-suite
    run on this box while it still reported a confident "470 passed" (TODOS 5.3.R83). It
    was found by diffing per-file collection against whole-suite collection -- not by
    anything the suite itself said.

    Computed from the table rather than recorded during collection, so it is independent of
    hook ordering and prints even when nothing is ignored.
    """
    lines = []
    for mod, reqs in sorted(_MODULE_REQUIREMENTS.items()):
        gone = _missing(reqs) if reqs else []
        if gone:
            lines.append(f"  {mod} - missing {', '.join(gone)}")
    if not lines:
        return "image deps: complete (no test modules ignored)"
    return "\n".join(
        [f"image deps: IGNORING {len(lines)} test module(s) - these tests DO NOT RUN here:"]
        + lines
        + ["  (run the other image too; see the module docstring)"]
    )
