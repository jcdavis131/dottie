#!/usr/bin/env python3
"""Skip-until-vendored loader for Critic's neardup v2.1 suite.

The suite itself is byte-identical Critic ``test_critic_neardup_v2_1.py``
stored next to this file as ``critic_neardup_v2_1.py`` (sha256
ad7cc0a94775ae38cb18856a57011bab83a8f258be0bdecf4177bfacaa7138e4).
It targets mill module ``neardup_tokens-v2_1`` at
``/workspace/helpers/neardup_tokens-v2_1.py``. That module is not vendored;
these 32 cases skip until it is. Discover must not import the suite file
directly: it loads the helper at import time.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import unittest
from pathlib import Path

_SUITE_FILE = Path(__file__).with_name("critic_neardup_v2_1.py")
_HELPER = Path("/workspace/helpers/neardup_tokens-v2_1.py")
_SUITE_SHA256 = "ad7cc0a94775ae38cb18856a57011bab83a8f258be0bdecf4177bfacaa7138e4"
_SKIP = "neardup_tokens-v2_1 is not vendored"


def _suite_test_names() -> tuple[str, ...]:
    tree = ast.parse(_SUITE_FILE.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                names.append(item.name)
    return tuple(names)


class CriticNeardupV21PinTests(unittest.TestCase):
    def test_suite_file_sha256_byte_identical(self) -> None:
        digest = hashlib.sha256(_SUITE_FILE.read_bytes()).hexdigest()
        self.assertEqual(digest, _SUITE_SHA256)
        self.assertEqual(len(_suite_test_names()), 32)


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str | None) -> unittest.TestSuite:
    if not _HELPER.is_file():
        class CriticNeardupV21SkipUntilVendored(unittest.TestCase):
            pass

        def _bind(name: str):
            @unittest.skip(_SKIP)
            def skipped(_self: unittest.TestCase) -> None:
                raise AssertionError("unreachable")

            skipped.__name__ = name
            skipped.__qualname__ = f"CriticNeardupV21SkipUntilVendored.{name}"
            return skipped

        for name in _suite_test_names():
            setattr(CriticNeardupV21SkipUntilVendored, name, _bind(name))
        tests.addTests(loader.loadTestsFromTestCase(CriticNeardupV21SkipUntilVendored))
        return tests
    spec = importlib.util.spec_from_file_location("critic_neardup_v2_1", _SUITE_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_SUITE_FILE}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tests.addTests(loader.loadTestsFromModule(mod))
    return tests
