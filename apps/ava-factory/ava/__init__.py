"""Backward-compat shim: ava -> dottie. Ava was placeholder, now Dottie.

A meta-path finder aliases EVERY ``ava.*`` import to the corresponding ``dottie.*``
module OBJECT — not a copy. The per-file redirect stubs (ava/config.py etc.) looked
equivalent but were not: ``from ava.pipeline.janitor import X`` loaded janitor.py a
SECOND time under the ava name, so the codebase ran with two module objects per file —
monkeypatches and module state hit one copy while functions resolved globals in the
other (observed live: test_janitor's patched delete_shard_files was never called).
The finder guarantees one brain: ``sys.modules['ava.X'] is sys.modules['dottie.X']``.
"""

import importlib
import importlib.abc
import importlib.util
import sys

from dottie import *  # noqa: F403


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, real):
        self._real = real

    def create_module(self, spec):
        return self._real  # hand the import system the EXISTING module object

    def exec_module(self, module):
        pass  # already executed under its dottie name


class _AvaAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("ava."):
            return None
        try:
            real = importlib.import_module("dottie." + fullname[4:])
        except ImportError:
            return None  # no dottie counterpart — let normal import (stubs) try
        return importlib.util.spec_from_loader(fullname, _AliasLoader(real))


if not any(isinstance(f, _AvaAliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _AvaAliasFinder())

# Legacy aliases for direct `from ava import AvaConfig`-style imports.
try:
    from dottie.config import DottieConfig
    from dottie.config import DottieConfig as AvaConfig  # noqa: F401
    from dottie.model import DottieModel1B as AvaModel1B  # noqa: F401
    from dottie.tokenizer import DottieTokenizer as AvaTokenizer  # noqa: F401
except (
    Exception
):  # partial installs (torch-less images) — lazy dottie exports still work
    pass
