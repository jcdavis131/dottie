"""AST pair extraction — the three Phase-1 vulnerabilities, and leakage.

The single most important property is NOT in the guide's vulnerability list: the
docstring must not survive inside the positive. If it does, the query appears
verbatim in the document it is supposed to retrieve, every metric goes up, and the
model has learned string matching. That is the exact shape of a fake win, and this
platform has already recorded three research `sota` rows that all turned out to be
artifacts.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "ast_pairs", Path(__file__).resolve().parents[1] / "scripts" / "ast_pairs.py"
)
ap = importlib.util.module_from_spec(_SPEC)
sys.modules["ast_pairs"] = ap
_SPEC.loader.exec_module(ap)


GOOD = '''
import os
from pathlib import Path

def resolve_config(name):
    """Locate the configuration file for a named environment and return its path."""
    base = Path(os.environ.get("CFG", "."))
    candidate = base / f"{name}.yaml"
    return candidate if candidate.exists() else None
'''


class TestNoQueryLeakage:
    """The property that decides whether the data is worth training on."""

    def test_docstring_is_absent_from_the_positive(self):
        pairs, _ = ap.extract_file(GOOD)
        assert len(pairs) == 1
        p = pairs[0]
        assert "Locate the configuration file" not in p["positive"], (
            "the query appears verbatim in its own positive — the retrieval task "
            "is string matching, and every metric will be inflated"
        )
        assert p["query"].startswith("Locate the configuration file")

    def test_the_body_still_survives(self):
        """Stripping must remove the docstring, not the function."""
        p = ap.extract_file(GOOD)[0][0]
        assert "candidate.exists()" in p["positive"]
        assert "def resolve_config" in p["positive"]


class TestV1GarbageDocstrings:
    @pytest.mark.parametrize(
        "doc,why",
        [
            ("", "empty"),
            ("   \n  ", "whitespace only"),
            ("Get value.", "under the word floor"),
            ("TODO: write this properly later on when there is time", "TODO marker"),
            ("FIXME broken, do not use this function at all please", "FIXME marker"),
            (":param x: the x\n:return: the value\n:rtype: int", "pure boilerplate"),
            ("Args:\n    x: a thing\nReturns:\n    another thing", "pure boilerplate"),
        ],
    )
    def test_rejected(self, doc, why):
        keep, reason = ap.heuristic_ok(doc)
        assert not keep, f"{why}: kept with reason {reason!r}"
        assert reason and reason != "ok"

    def test_prose_plus_boilerplate_is_kept(self):
        """A real description that ALSO has :param lines must survive — rejecting
        it would throw away most well-documented code."""
        keep, _ = ap.heuristic_ok(
            "Resolve the environment configuration path for a service.\n"
            ":param name: the service\n:return: a Path or None"
        )
        assert keep

    def test_word_count_counts_prose_only(self):
        """Boilerplate lines must not pad a short description over the floor."""
        keep, reason = ap.heuristic_ok(
            "Get it.\n:param a: aaa\n:param b: bbb\n:param c: ccc\n:return: value"
        )
        assert not keep, f"boilerplate padded a 2-word description: {reason}"


class TestV3ContextPacking:
    def test_imports_are_packed(self):
        p = ap.extract_file(GOOD)[0][0]
        assert "import os" in p["positive"]
        assert "from pathlib import Path" in p["positive"]

    def test_class_context_is_packed_and_symbol_qualified(self):
        src = '''
import json

class ConfigStore:
    def load(self, key):
        """Read a stored configuration value by its key and decode the JSON."""
        raw = self._backend.get(key)
        return json.loads(raw) if raw else None
'''
        pairs, _ = ap.extract_file(src)
        assert len(pairs) == 1
        p = pairs[0]
        assert "class ConfigStore:" in p["positive"], "class context was stripped"
        assert "import json" in p["positive"]
        assert p["symbol"] == "ConfigStore.load"

    def test_module_level_function_has_no_fabricated_class(self):
        p = ap.extract_file(GOOD)[0][0]
        assert "class " not in p["positive"]
        assert p["symbol"] == "resolve_config"


class TestV2IsNotSilentlyClaimed:
    def test_pairs_are_marked_as_docstring_sourced(self):
        """V2 (semantic gap) is NOT mitigated here — it needs synthetic queries.
        Every pair must say where it came from so a later synthetic layer stays
        distinguishable in the mixture instead of blending in."""
        p = ap.extract_file(GOOD)[0][0]
        assert p["source"] == "docstring"


class TestRobustness:
    def test_syntax_error_is_reported_not_raised(self):
        pairs, rej = ap.extract_file("def broken(:\n  pass", path="bad.py")
        assert pairs == []
        assert rej and "unparseable" in rej[0]["reason"]

    def test_empty_and_trivial_inputs(self):
        for src in ("", "\n", "x = 1"):
            pairs, _ = ap.extract_file(src)
            assert pairs == []

    def test_function_whose_body_is_only_a_docstring_is_dropped(self):
        src = '''
def stub():
    """This function is a placeholder and has no implementation body at all."""
'''
        pairs, rej = ap.extract_file(src)
        assert pairs == [], "a body-less stub is not a training positive"
        assert any("too short" in r["reason"] for r in rej)

    def test_async_functions_are_extracted(self):
        src = '''
import asyncio

async def fetch_all(urls):
    """Fetch every URL concurrently and return the decoded response bodies."""
    tasks = [asyncio.create_task(_get(u)) for u in urls]
    return await asyncio.gather(*tasks)
'''
        pairs, _ = ap.extract_file(src)
        assert len(pairs) == 1 and pairs[0]["symbol"] == "fetch_all"

    def test_import_packing_is_bounded(self):
        # Body must clear MIN_CODE_CHARS — the first version of this fixture had a
        # 30-char body and extracted nothing, so the assertion never ran.
        src = (
            "\n".join(f"import mod{i}" for i in range(60))
            + '''

def f(x):
    """Do a genuinely described thing with the supplied argument value."""
    scaled = x * 2 + 1
    adjusted = scaled - (x % 3)
    return max(adjusted, 0)
'''
        )
        pairs, rej = ap.extract_file(src)
        assert pairs, f"fixture extracted nothing: {rej}"
        assert pairs[0]["positive"].count("import mod") <= ap.MAX_IMPORTS_PACKED

    def test_google_style_body_cannot_pad_the_word_floor(self):
        """Regression on the bug this suite found: only the section HEADER was
        treated as boilerplate, so indented lines under Args:/Returns: counted as
        prose and pushed a 2-word description over the floor."""
        keep, reason = ap.heuristic_ok(
            "Get it.\nArgs:\n    alpha: the first thing\n    beta: the second thing\n"
            "Returns:\n    something entirely different"
        )
        assert not keep, f"section bodies padded a 2-word description: {reason}"

    def test_a_dedented_line_after_a_section_is_prose_again(self):
        keep, _ = ap.heuristic_ok(
            "Args:\n    x: a thing\nThis trailing sentence genuinely describes the "
            "behaviour of the function."
        )
        assert keep, "a real description after a section must still count"


class TestHonestScope:
    def test_only_python_is_claimed(self):
        """The guide's multi-language router is not implemented. LANGUAGES must
        not advertise languages this module cannot parse."""
        assert ap.LANGUAGES == ("python",)

    def test_extracted_pairs_declare_their_language(self):
        assert ap.extract_file(GOOD)[0][0]["language"] == "python"


class TestAgainstTheRealTree:
    def test_non_vacuous_on_scout_cli(self):
        """Guards against a refactor that silently extracts nothing."""
        # parents[2] is apps/ — parents[3] was the repo root and silently SKIPPED,
        # which is how a non-vacuity guard quietly stops guarding.
        base = Path(__file__).resolve().parents[2] / "scout-cli" / "bigbang" / "core"
        if not base.exists():
            pytest.skip(f"scout-cli not present at {base}")
        total = 0
        for p in list(base.glob("*.py"))[:25]:
            pairs, _ = ap.extract_file(p.read_text(encoding="utf-8", errors="replace"))
            total += len(pairs)
        assert total > 20, f"only {total} pairs from 25 real files — extractor broken?"
