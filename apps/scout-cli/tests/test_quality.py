"""Quality — openswap #30 (SonarQube/CodeClimate -> stdlib ast/tokenize metrics
plus a sqlite trend store). Pure-logic core tests: every decision-point weight,
the nested-def boundary, size/depth/param measurement, qualname disambiguation,
import binding and unused detection with its documented exemptions, tokenize
SLOC/marker separation, the metrics-XOR-error honesty invariant, every rule
firing AND every rule staying quiet on a clean file, the config overlay, the
history store's regression comparison and its refusal to compare runs measured
under different weights, the drift guards against todos/goat_audit/reviewgraph,
and the real CLI in a subprocess. Offline and deterministic by construction:
every input is a string, no fixture is fetched and no socket is opened on any
path."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import openswap, quality

ROOT = Path(__file__).resolve().parents[1]

CLEAN_SOURCE = '''"""A module with nothing to report."""

from pathlib import Path


def head(path):
    """The first line of a file."""
    return Path(path).read_text(encoding="utf-8").splitlines()[0]
'''


def _tree(src: str) -> ast.Module:
    return ast.parse(src)


def _units(src: str) -> dict[str, dict]:
    """qualname -> unit row, measured under the default weights."""
    weights = quality.DEFAULT_CONFIG["weights"]
    return {u["qualname"]: u for u in quality.function_units(_tree(src), weights)}


def _cx(src: str, qualname: str = "f") -> int:
    return _units(src)[qualname]["complexity"]


def _report(src: str, path: str = "m.py", config=None) -> dict:
    return quality.file_report(src, path=path, config=config)


def _rules_fired(src: str, path: str = "m.py", config=None) -> set[str]:
    return {d["rule"] for d in _report(src, path=path, config=config)["diagnostics"]}


# ---- cyclomatic complexity: one test per decision-point kind -----------------


def test_a_straight_line_function_has_complexity_one():
    unit = _units("def f(a):\n    b = a + 1\n    return b\n")["f"]
    assert unit["complexity"] == 1
    assert unit["decisions"] == {}  # nothing was counted, so nothing is claimed


def test_if_elif_else_counts_each_test_and_not_the_else():
    assert _cx("def f(a):\n    if a:\n        return 1\n    return 2\n") == 2
    both = "def f(a):\n    if a == 1:\n        return 1\n    elif a == 2:\n        return 2\n    else:\n        return 3\n"
    assert _cx(both) == 3  # two tests, the else adds nothing
    assert _units(both)["f"]["decisions"] == {"If": 2}


def test_loops_and_handlers_each_add_one_and_finally_adds_nothing():
    assert _cx("def f(xs):\n    for x in xs:\n        pass\n") == 2
    assert _cx("def f(xs):\n    while xs:\n        xs.pop()\n") == 2
    src = (
        "def f():\n    try:\n        g()\n    except KeyError:\n        pass\n"
        "    except ValueError:\n        pass\n    finally:\n        h()\n"
    )
    assert _cx(src) == 3  # two handlers; try/finally themselves are not branches
    assert _units(src)["f"]["decisions"] == {"ExceptHandler": 2}


def test_async_for_and_async_def_are_measured_like_their_sync_forms():
    unit = _units("async def f(xs):\n    async for x in xs:\n        pass\n")["f"]
    assert unit["complexity"] == 2 and unit["is_async"] is True
    assert _units("def g(xs):\n    for x in xs:\n        pass\n")["g"]["is_async"] is False


def test_boolean_operators_count_per_extra_operand():
    assert _cx("def f(a, b):\n    return a and b\n") == 2
    assert _cx("def f(a, b, c):\n    return a and b and c\n") == 3  # +2, not +1
    assert _cx("def f(a, b, c):\n    return a or (b and c)\n") == 3


def test_comprehensions_count_the_loop_and_each_filter():
    assert _cx("def f(xs):\n    return [x for x in xs]\n") == 2
    assert _cx("def f(xs):\n    return [x for x in xs if x]\n") == 3
    assert _cx("def f(xs):\n    return [x for x in xs if x if x > 1]\n") == 4
    # a nested comprehension has two implied loops
    assert _cx("def f(xs):\n    return [y for x in xs for y in x]\n") == 3
    assert _cx("def f(xs):\n    return {k: v for k, v in xs}\n") == 2


def test_ternary_and_assert_are_counted_and_are_configurable():
    assert _cx("def f(a):\n    return 1 if a else 2\n") == 2
    assert _cx("def f(a):\n    assert a\n") == 2
    quiet = quality.default_config()
    quiet["weights"]["Assert"] = 0
    units = quality.function_units(_tree("def f(a):\n    assert a\n"), quiet["weights"])
    assert units[0]["complexity"] == 1  # the table is data, and the data is obeyed
    assert units[0]["decisions"] == {}


def test_match_wildcard_is_the_else_arm_and_a_guard_adds_one():
    plain = (
        "def f(a):\n    match a:\n        case 1:\n            return 1\n"
        "        case _:\n            return 2\n"
    )
    assert _cx(plain) == 2  # one real case; `case _` is the else
    guarded = (
        "def f(a):\n    match a:\n        case 1:\n            return 1\n"
        "        case x if x > 3:\n            return 2\n"
    )
    # `case x` is itself a catch-all (+0), so the 3rd point is the GUARD, not the
    # pattern; the breakdown attributes it to the match_case node it hangs off.
    assert _cx(guarded) == 3
    assert _units(guarded)["f"]["decisions"] == {"match_case": 2}
    unguarded_two = (
        "def f(a):\n    match a:\n        case 1:\n            return 1\n"
        "        case 2:\n            return 2\n"
    )
    assert _cx(unguarded_two) == 3  # two real patterns, no guard
    named_catchall = (
        "def f(a):\n    match a:\n        case 1:\n            return 1\n"
        "        case other:\n            return other\n"
    )
    assert _cx(named_catchall) == 2  # `case other:` is unconditional too


def test_a_nested_def_is_its_own_unit_and_never_inflates_its_parent():
    src = (
        "def outer(a):\n"
        "    def inner(b):\n"
        "        if b:\n"
        "            return 1\n"
        "        return 2\n"
        "    if a:\n"
        "        return inner(a)\n"
        "    return 0\n"
    )
    units = _units(src)
    assert units["outer"]["complexity"] == 2  # NOT 3: inner's branch is inner's
    assert units["outer.inner"]["complexity"] == 2
    assert units["outer"]["statements"] == 4  # def+if+return, plus the return; not inner's body
    assert set(units) == {"outer", "outer.inner"}


def test_a_class_body_does_not_hide_its_methods_or_leak_into_them():
    src = (
        "class C:\n"
        "    LIMIT = 3\n"
        "    def m(self, a):\n"
        "        if a:\n"
        "            return 1\n"
        "        return 2\n"
        "    class D:\n"
        "        def n(self):\n"
        "            return [x for x in range(2)]\n"
    )
    units = _units(src)
    assert set(units) == {"C.m", "C.D.n"}
    assert units["C.m"]["complexity"] == 2
    assert units["C.D.n"]["complexity"] == 2


def test_the_decisions_breakdown_always_reconstructs_the_score():
    src = (
        "def f(xs, a, b):\n"
        "    if a and b:\n"
        "        for x in xs:\n"
        "            try:\n"
        "                assert x\n"
        "            except ValueError:\n"
        "                pass\n"
        "    return [y for y in xs if y]\n"
    )
    unit = _units(src)["f"]
    assert unit["complexity"] == 1 + sum(unit["decisions"].values())
    assert unit["decisions"] == {
        "Assert": 1,
        "BoolOp": 1,
        "ExceptHandler": 1,
        "For": 1,
        "If": 1,
        "comprehension": 2,
    }
    assert unit["complexity"] == 8


def test_zeroing_every_weight_collapses_every_score_to_one():
    cfg = quality.default_config()
    for key in cfg["weights"]:
        cfg["weights"][key] = 0
    src = "def f(a, b):\n    if a and b:\n        return [x for x in range(3) if x]\n    return 0\n"
    assert quality.function_units(_tree(src), cfg["weights"])[0]["complexity"] == 1
    # and the default table counts all four: If, BoolOp, the loop, the filter
    assert _cx(src) == 5
    assert _units(src)["f"]["decisions"] == {"BoolOp": 1, "If": 1, "comprehension": 2}


# ---- size, depth, params, identity ------------------------------------------


def test_lines_statements_and_depth_measure_different_things():
    src = (
        "def f(xs):\n"
        '    """Doc\n\n    spanning lines.\n    """\n'
        "    for x in xs:\n"
        "        if x:\n"
        "            with open(str(x)) as fh:\n"
        "                fh.read()\n"
    )
    unit = _units(src)["f"]
    assert unit["lines"] == 9  # def through the last body line
    assert unit["statements"] == 5  # docstring, for, if, with, fh.read()
    assert unit["max_depth"] == 3  # for -> if -> with
    assert _units("def g():\n    return 1\n")["g"]["max_depth"] == 0


def test_max_depth_takes_the_deepest_branch_not_the_last_one():
    src = (
        "def f(a):\n"
        "    if a:\n"
        "        for x in a:\n"
        "            while x:\n"
        "                x -= 1\n"
        "    if a:\n"
        "        pass\n"
    )
    assert _units(src)["f"]["max_depth"] == 3


def test_params_counts_every_declared_form_including_self():
    src = "def f(a, /, b, *args, c=1, **kw):\n    return 0\n"
    assert _units(src)["f"]["params"] == 5
    method = "class C:\n    def m(self, a):\n        return a\n"
    assert _units(method)["C.m"]["params"] == 2  # self is declared, so it counts
    assert _units("def g():\n    return 0\n")["g"]["params"] == 0


def test_a_repeated_qualname_gets_a_stable_suffix_instead_of_collapsing():
    src = (
        "if True:\n"
        "    def f():\n"
        "        return 1\n"
        "else:\n"
        "    def f():\n"
        "        if 1:\n"
        "            return 2\n"
        "        return 3\n"
    )
    units = _units(src)
    assert set(units) == {"f", "f#2"}
    assert units["f"]["complexity"] == 1 and units["f#2"]["complexity"] == 2


def test_functions_are_found_inside_if_try_and_with_blocks():
    src = (
        "try:\n"
        "    def a():\n"
        "        return 1\n"
        "except ImportError:\n"
        "    def b():\n"
        "        return 2\n"
    )
    assert set(_units(src)) == {"a", "b"}


def test_module_complexity_sees_import_time_branching_and_excludes_functions():
    weights = quality.DEFAULT_CONFIG["weights"]
    src = (
        "import sys\n"
        "if sys.platform == 'win32':\n"
        "    MODE = 1\n"
        "else:\n"
        "    MODE = 2\n"
        "def f(a):\n"
        "    if a:\n"
        "        return 1\n"
        "    return 2\n"
    )
    score, decisions = quality.module_complexity(_tree(src), weights)
    assert score == 2 and decisions == {"If": 1}  # the def's own `if` is not here
    flat, _ = quality.module_complexity(_tree("x = 1\n"), weights)
    assert flat == 1


# ---- imports ----------------------------------------------------------------


def test_import_bindings_records_the_name_each_form_actually_binds():
    src = (
        "import os\n"
        "import os.path\n"
        "import os.path as osp\n"
        "from json import dumps\n"
        "from json import loads as jl\n"
        "from . import sibling\n"
        "from .mod import thing\n"
    )
    bindings = quality.import_bindings(_tree(src), src.splitlines())
    assert [(b["name"], b["line"]) for b in bindings] == [
        ("os", 1),
        ("os", 2),  # `import os.path` binds the ROOT package, not "os.path"
        ("osp", 3),
        ("dumps", 4),
        ("jl", 5),
        ("sibling", 6),
        ("thing", 7),
    ]
    bound = {b["name"]: b for b in bindings}
    assert bound["osp"]["module"] == "os.path"
    assert bound["sibling"]["module"] == "."
    assert bound["thing"]["module"] == ".mod"
    assert bound["jl"]["statement"] == "from json import loads as jl"


def test_unused_imports_finds_the_unreferenced_binding_only():
    src = "import os\nimport json\n\n\ndef f(p):\n    return os.path.join(p, 'x')\n"
    result = quality.unused_imports(_tree(src), src.splitlines())
    assert [b["name"] for b in result["unused"]] == ["json"]
    assert result["bindings"] == 2 and result["stars"] == []


def test_a_future_import_is_never_reported_unused():
    src = "from __future__ import annotations\n\nx = 1\n"
    result = quality.unused_imports(_tree(src), src.splitlines())
    assert result["unused"] == []  # a compiler directive is not a referenced name
    assert [b["name"] for b in quality.import_bindings(_tree(src), src.splitlines())] == [
        "annotations"
    ]


def test_noqa_suppresses_only_when_it_covers_the_unused_import_code():
    bare = "import os  # noqa\n"
    coded = "import os  # noqa: F401\n"
    multi = "import os  # noqa: E501, F401\n"
    other = "import os  # noqa: E501\n"
    for src in (bare, coded, multi):
        assert quality.unused_imports(_tree(src), src.splitlines())["unused"] == [], src
    assert [b["name"] for b in quality.unused_imports(_tree(other), other.splitlines())["unused"]] == ["os"]


def test_exporting_a_name_in_dunder_all_counts_as_using_it():
    src = 'from json import dumps\n\n__all__ = ["dumps"]\n'
    assert quality.unused_imports(_tree(src), src.splitlines())["unused"] == []
    without = "from json import dumps\n"
    assert len(quality.unused_imports(_tree(without), without.splitlines())["unused"]) == 1


def test_a_name_used_only_inside_a_quoted_annotation_counts_as_used():
    src = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from collections.abc import Sequence\n"
        "def f(xs: 'Sequence[int]') -> 'Sequence[int]':\n"
        "    return xs\n"
    )
    assert quality.unused_imports(_tree(src), src.splitlines())["unused"] == []
    assert "Sequence" in quality.used_names(_tree(src))
    # and a quoted name that appears nowhere is still not invented as a use
    assert "Mapping" not in quality.used_names(_tree(src))


def test_a_name_used_only_in_a_typing_cast_string_counts_as_used():
    src = "from json import JSONDecoder\nimport typing\ndef f(x):\n    return typing.cast('JSONDecoder', x)\n"
    assert quality.unused_imports(_tree(src), src.splitlines())["unused"] == []


def test_rebinding_an_imported_name_is_not_using_it():
    src = "import os\nos = None\n"
    assert [b["name"] for b in quality.unused_imports(_tree(src), src.splitlines())["unused"]] == [
        "os"
    ]
    used = "import os\ndel os\n"
    assert quality.unused_imports(_tree(used), used.splitlines())["unused"] == []


def test_a_star_import_is_reported_as_unanalyzable_not_as_unused():
    src = "from os import *\nimport json\n"
    result = quality.unused_imports(_tree(src), src.splitlines())
    assert [b["module"] for b in result["stars"]] == ["os"]
    assert [b["name"] for b in result["unused"]] == ["json"]  # the rest still works
    assert result["bindings"] == 1  # the star binds an unknowable set, so it is not one


def test_attribute_access_and_decorators_count_as_uses():
    src = (
        "import functools\nimport os\n"
        "@functools.cache\ndef f():\n    return os.sep\n"
    )
    assert quality.unused_imports(_tree(src), src.splitlines())["unused"] == []


# ---- tokenize-derived source metrics ----------------------------------------


def test_sloc_excludes_comments_and_blanks_and_spans_multiline_tokens():
    src = '# a comment\n\nx = {\n    "a": 1,\n}\n\n# another\ny = 2\n'
    m = quality.source_metrics(src)
    assert m["sloc"] == 4  # the 3-line dict literal plus y = 2
    assert m["comment_lines"] == 2
    assert m["blank_lines"] == 2
    assert m["total_lines"] == 8


def test_sloc_counts_every_line_a_multiline_string_token_spans():
    """The density denominator depends on this convention, so it is pinned.
    Found by mutation: the dict-literal case above tokenizes to one token PER
    line, so it could not distinguish "count the span" from "count the start"."""
    src = '"""One\ntwo\nthree\n"""\nx = 1\n'
    m = quality.source_metrics(src)
    assert m["sloc"] == 5  # the 4-line docstring token, plus x = 1
    assert m["comment_lines"] == 0 and m["blank_lines"] == 0


def test_markers_come_from_comments_and_string_hits_are_reported_separately():
    src = (
        "# TODO tighten this\n"
        'MESSAGE = "TODO: not a code comment"\n'
        "y = 1  # FIXME and XXX on one line\n"
    )
    m = quality.source_metrics(src)
    assert [x["marker"] for x in m["markers"]] == ["TODO", "FIXME", "XXX"]
    assert m["markers_in_strings"] == 1  # counted, labelled, and NOT in `markers`
    assert m["markers"][0]["line"] == 1 and m["markers"][2]["line"] == 3
    assert m["error"] is None


def test_marker_matching_is_case_sensitive_so_ordinary_prose_does_not_count():
    src = "# works around a bug in json, todo later\nx = 1\n"
    assert quality.source_metrics(src)["markers"] == []
    assert quality.source_metrics("# BUG in json\nx = 1\n")["markers"][0]["marker"] == "BUG"


def test_a_marker_inside_a_longer_word_is_not_a_marker():
    assert quality.source_metrics("# TODOS elsewhere\nx = 1\n")["markers"] == []
    assert quality.source_metrics("# XXXY\nx = 1\n")["markers"] == []


def test_source_metrics_reports_why_instead_of_returning_zeros():
    m = quality.source_metrics("x = '''unterminated\n")
    assert m["error"] and "TokenError" in m["error"]
    # EITHER numbers OR an error: no half-measured row
    assert m["sloc"] is None and m["markers"] is None and m["markers_in_strings"] is None


def test_todo_density_is_per_100_sloc_and_is_none_when_unmeasurable():
    assert quality.todo_density(2, 100) == 2.0
    assert quality.todo_density(1, 8) == 12.5
    assert quality.todo_density(0, 50) == 0.0  # measured and zero, not unknown
    assert quality.todo_density(None, 50) is None
    assert quality.todo_density(3, 0) is None  # no division by zero, no invented 0.0
    assert quality.todo_density(3, None) is None


def test_markers_are_attributed_to_the_innermost_enclosing_function():
    src = (
        "# TODO module level\n"
        "def outer():\n"
        "    # TODO outer\n"
        "    def inner():\n"
        "        # TODO inner\n"
        "        return 1\n"
        "    return inner\n"
    )
    report = _report(src)
    owners = {m["line"]: m["qualname"] for m in report["markers"]}
    assert owners == {1: None, 3: "outer", 5: "outer.inner"}


# ---- file_report: the honesty invariant and the rule table ------------------


def test_a_clean_file_fires_nothing_at_all():
    report = _report(CLEAN_SOURCE)
    assert report["diagnostics"] == []
    assert report["counts"]["functions"] == 1
    assert report["counts"]["todo_density"] == 0.0
    assert report["error"] is None


def test_a_file_with_no_functions_has_no_per_file_mean_either():
    """The scan-level mean is covered elsewhere; this pins the PER-FILE one, which
    a mutation showed was unasserted anywhere."""
    counts = _report("X = 1\nY = 2\n")["counts"]
    assert counts["functions"] == 0 and counts["complexity_total"] == 0
    assert counts["complexity_mean"] is None  # not 0.0: nothing was averaged
    assert counts["complexity_max"] is None
    assert _report(CLEAN_SOURCE)["counts"]["complexity_mean"] == 1.0  # and a real one is real


def test_an_unparsable_file_is_unmeasured_and_never_looks_clean():
    report = _report("def f(:\n    pass\n", path="broken.py")
    assert report["counts"] is None  # not a row of zeros
    assert "SyntaxError" in report["error"]
    assert [d["rule"] for d in report["diagnostics"]] == ["quality:file-unparsed"]
    assert report["diagnostics"][0]["severity"] == "error"
    assert report["units"] == [] and report["markers"] == []


def test_an_unreadable_file_is_unmeasured_and_never_looks_clean():
    report = quality.unreadable_report("gone.py", "OSError: nope")
    assert report["counts"] is None and report["error"] == "OSError: nope"
    assert [d["rule"] for d in report["diagnostics"]] == ["quality:file-unreadable"]
    assert report["unmeasured"] == ["file not measured: OSError: nope"]


@pytest.mark.parametrize(
    "src",
    [CLEAN_SOURCE, "def f(:\n", "", "# only a comment\n", "x = '''bad\n"],
)
def test_every_report_carries_exactly_one_of_counts_or_error(src):
    report = _report(src)
    assert (report["counts"] is None) != (report["error"] is None)


def test_a_tokenize_failure_leaves_the_density_unknown_and_says_so(monkeypatch):
    """Defensive branch: no input is known that ast parses while tokenize fails,
    so the failure is injected. The point under test is the honesty rule — an
    unmeasured density must be None WITH a reason, never 0.0."""
    monkeypatch.setattr(
        quality,
        "source_metrics",
        lambda text: {
            "sloc": None,
            "comment_lines": None,
            "blank_lines": None,
            "total_lines": 1,
            "markers": None,
            "markers_in_strings": None,
            "error": "TokenError: injected",
        },
    )
    report = _report("x = 1\n")
    assert report["counts"]["todo_markers"] is None
    assert report["counts"]["todo_density"] is None
    assert report["counts"]["sloc"] is None
    assert "tokenize failed" in report["unmeasured"][0]
    assert "quality:tokenize-failed" in {d["rule"] for d in report["diagnostics"]}


def test_complexity_rules_escalate_from_warning_to_error():
    warn = "def f(a):\n" + "".join(f"    if a == {i}:\n        return {i}\n" for i in range(9))
    error = "def f(a):\n" + "".join(f"    if a == {i}:\n        return {i}\n" for i in range(20))
    assert _cx(warn) == 10 and _cx(error) == 21
    assert "quality:complexity-warn" in _rules_fired(warn)
    assert "quality:complexity-error" not in _rules_fired(warn)
    fired = _rules_fired(error)
    assert "quality:complexity-error" in fired
    assert "quality:complexity-warn" not in fired  # escalated, not doubled up
    under = "def f(a):\n" + "".join(f"    if a == {i}:\n        return {i}\n" for i in range(8))
    assert _cx(under) == 9 and "quality:complexity-warn" not in _rules_fired(under)


def test_both_complexity_thresholds_are_inclusive_at_the_exact_boundary():
    """A score landing EXACTLY on a threshold must trip it. Found by mutation:
    the error rule was only ever tested at 21, so `>=` -> `>` survived."""
    thresholds = quality.DEFAULT_CONFIG["thresholds"]
    on_warn = "def f(a):\n" + "".join(f"    if a == {i}:\n        return {i}\n" for i in range(9))
    on_error = "def f(a):\n" + "".join(f"    if a == {i}:\n        return {i}\n" for i in range(19))
    assert _cx(on_warn) == thresholds["complexity_warn"] == 10
    assert _cx(on_error) == thresholds["complexity_error"] == 20
    assert "quality:complexity-warn" in _rules_fired(on_warn)
    assert "quality:complexity-error" in _rules_fired(on_error)
    # one below each boundary stays quiet, so the rule is a boundary and not a floor
    below_error = "def f(a):\n" + "".join(
        f"    if a == {i}:\n        return {i}\n" for i in range(18)
    )
    assert _cx(below_error) == 19
    assert _rules_fired(below_error) == {"quality:complexity-warn"}


def test_the_size_rules_fire_independently_of_complexity():
    long_fn = 'def f():\n    """\n' + "\n" * 60 + '    """\n'
    fired = _rules_fired(long_fn)
    assert fired == {"quality:function-long"}
    many = "def f():\n" + "".join(f"    x{i} = {i}\n" for i in range(51))
    assert _units(many)["f"]["statements"] == 51
    assert _rules_fired(many) == {"quality:function-statements"}
    deep = "def f(a):\n" + "".join(
        f"{'    ' * (i + 1)}if a:\n" for i in range(5)
    ) + "    " * 6 + "return 1\n"
    assert _units(deep)["f"]["max_depth"] == 5
    assert "quality:function-deep" in _rules_fired(deep)
    wide = "def f(a, b, c, d, e, g, h):\n    return 0\n"
    assert _rules_fired(wide) == {"quality:function-params"}


def test_the_size_and_density_thresholds_are_exclusive_at_the_exact_boundary():
    """`lines`/`statements`/`depth`/`params`/`density` fire ABOVE the threshold, so
    a function sitting exactly on it must stay quiet. Same mutation-found class of
    gap as the complexity boundary test above."""
    thresholds = quality.DEFAULT_CONFIG["thresholds"]
    at_limit = 'def f():\n    """\n' + "\n" * 57 + '    """\n'
    over = 'def f():\n    """\n' + "\n" * 58 + '    """\n'
    assert _units(at_limit)["f"]["lines"] == thresholds["function_lines"] == 60
    assert _units(over)["f"]["lines"] == 61
    assert _rules_fired(at_limit) == set() and _rules_fired(over) == {"quality:function-long"}

    fifty = "def f():\n" + "".join(f"    x{i} = {i}\n" for i in range(50))
    assert _units(fifty)["f"]["statements"] == thresholds["function_statements"] == 50
    assert _rules_fired(fifty) == set()

    depth4 = "def f(a):\n" + "".join(f"{'    ' * (i + 1)}if a:\n" for i in range(4)) + "    " * 5 + "a = 1\n"
    assert _units(depth4)["f"]["max_depth"] == thresholds["max_depth"] == 4
    assert _rules_fired(depth4) == set()

    six = "def f(a, b, c, d, e, g):\n    return 0\n"
    assert _units(six)["f"]["params"] == thresholds["params"] == 6
    assert _rules_fired(six) == set()

    exactly_two = "# TODO x\n" + "".join(f"x{i} = {i}\n" for i in range(50))
    report = _report(exactly_two)
    assert report["counts"]["sloc"] == 50
    assert report["counts"]["todo_density"] == thresholds["todo_density"] == 2.0
    assert _rules_fired(exactly_two) == set()
    over_two = "# TODO x\n" + "".join(f"x{i} = {i}\n" for i in range(40))
    assert _report(over_two)["counts"]["todo_density"] == 2.5
    assert _rules_fired(over_two) == {"quality:todo-density"}


def test_module_complexity_shares_the_warn_threshold_inclusively():
    thresholds = quality.DEFAULT_CONFIG["thresholds"]
    at_limit = "import sys\n" + "".join(f"if sys.argv == ['{i}']:\n    X = {i}\n" for i in range(9))
    below = "import sys\n" + "".join(f"if sys.argv == ['{i}']:\n    X = {i}\n" for i in range(8))
    assert _report(at_limit)["counts"]["module_complexity"] == thresholds["complexity_warn"] == 10
    assert _report(below)["counts"]["module_complexity"] == 9
    assert "quality:module-complexity" in _rules_fired(at_limit)
    assert "quality:module-complexity" not in _rules_fired(below)


def test_the_import_rules_fire_and_init_files_get_their_own_rule():
    src = "import os\n"
    assert _rules_fired(src) == {"quality:import-unused"}
    init = _rules_fired(src, path=str(Path("pkg") / "__init__.py"))
    assert init == {"quality:import-unused-init"}
    report = _report(src, path=str(Path("pkg") / "__init__.py"))
    assert report["diagnostics"][0]["severity"] == "suggestion"
    assert "__all__" in report["diagnostics"][0]["message"]
    assert _rules_fired("from os import *\n") == {"quality:import-star"}


def test_the_density_rule_fires_and_points_at_the_listing_tool():
    src = "# TODO one\n# FIXME two\nx = 1\n"
    report = _report(src)
    assert report["counts"]["todo_density"] == 200.0
    diag = [d for d in report["diagnostics"] if d["rule"] == "quality:todo-density"]
    assert len(diag) == 1  # ONE density finding, not one per marker
    assert "scout todos" in diag[0]["suggestion"]
    assert diag[0]["line"] == 1
    # under the threshold it stays quiet
    quiet = "# TODO one\n" + "".join(f"x{i} = {i}\n" for i in range(60))
    assert quality.todo_density(1, 60) < quality.DEFAULT_CONFIG["thresholds"]["todo_density"]
    assert "quality:todo-density" not in _rules_fired(quiet)


def test_import_time_branching_is_reported_even_with_no_functions():
    src = "import sys\n" + "".join(
        f"if sys.argv == ['{i}']:\n    X = {i}\n" for i in range(10)
    )
    report = _report(src)
    assert report["counts"]["functions"] == 0
    assert report["counts"]["module_complexity"] == 11
    assert "quality:module-complexity" in {d["rule"] for d in report["diagnostics"]}


def test_every_diagnostic_uses_the_family_schema_and_a_valid_severity():
    src = "import os\n# TODO x\ndef f(a, b, c, d, e, g, h):\n    return 0\n"
    diags = _report(src)["diagnostics"]
    assert [d["rule"] for d in diags] == [
        "quality:import-unused",
        "quality:todo-density",
        "quality:function-params",
    ]
    for d in diags:
        assert set(d) == {"path", "line", "col", "rule", "severity", "message", "suggestion", "source"}
        assert d["severity"] in openswap.SEVERITIES
        assert d["path"] == "m.py" and d["rule"].startswith("quality:")


def test_diagnostics_are_sorted_by_position():
    src = "import os\n\n\ndef f(a, b, c, d, e, g, h):\n    return 0\n"
    lines = [d["line"] for d in _report(src)["diagnostics"]]
    assert lines == sorted(lines) and len(lines) >= 2


def test_disabling_a_rule_silences_it_without_silencing_the_others():
    cfg = quality.default_config()
    cfg["rules"]["quality:import-unused"]["enabled"] = False
    src = "import os\n# TODO x\n"
    assert "quality:import-unused" in _rules_fired(src)
    assert "quality:import-unused" not in _rules_fired(src, config=cfg)
    assert "quality:todo-density" in _rules_fired(src, config=cfg)


def test_raising_a_threshold_changes_the_verdict_on_the_same_code():
    src = "def f(a):\n" + "".join(f"    if a == {i}:\n        return {i}\n" for i in range(9))
    cfg = quality.default_config()
    cfg["thresholds"]["complexity_warn"] = 11
    assert "quality:complexity-warn" in _rules_fired(src)
    assert "quality:complexity-warn" not in _rules_fired(src, config=cfg)


def test_changing_a_severity_changes_what_a_gate_sees():
    cfg = quality.default_config()
    cfg["rules"]["quality:import-unused"]["severity"] = "error"
    default = _report("import os\n")["diagnostics"][0]
    raised = _report("import os\n", config=cfg)["diagnostics"][0]
    assert default["severity"] == "warning" and raised["severity"] == "error"


# ---- config overlay ---------------------------------------------------------


def test_default_config_is_a_copy_a_caller_may_mutate():
    cfg = quality.default_config()
    cfg["thresholds"]["params"] = 99
    cfg["rules"]["quality:import-unused"]["enabled"] = False
    assert quality.DEFAULT_CONFIG["thresholds"]["params"] == 6
    assert quality.DEFAULT_CONFIG["rules"]["quality:import-unused"]["enabled"] is True


def test_load_config_merges_an_overlay(tmp_path):
    overlay = tmp_path / "org.json"
    overlay.write_text(
        json.dumps({"thresholds": {"params": 3}, "weights": {"Assert": 0},
                    "rules": {"quality:import-star": {"severity": "error"}}}),
        encoding="utf-8",
    )
    cfg = quality.load_config(overlay)
    assert cfg["thresholds"]["params"] == 3
    assert cfg["weights"]["Assert"] == 0
    assert cfg["rules"]["quality:import-star"]["severity"] == "error"
    assert cfg["thresholds"]["complexity_warn"] == 10  # untouched keys survive


@pytest.mark.parametrize(
    "payload",
    [
        {"nonsense": {}},
        {"thresholds": {"not_a_threshold": 1}},
        {"weights": {"NotANode": 1}},
        {"weights": {"If": "three"}},
        {"weights": {"If": True}},
        {"thresholds": {"params": -1}},
        {"rules": {"quality:not-a-rule": {}}},
        {"rules": {"quality:import-unused": "off"}},
        {"rules": {"quality:import-unused": {"severity": "catastrophe"}}},
        {"rules": {"quality:import-unused": {"threshold": "params"}}},
        ["not", "an", "object"],
    ],
)
def test_load_config_refuses_a_bad_overlay(tmp_path, payload):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        quality.load_config(bad)


def test_weights_fingerprint_tracks_the_table_and_ignores_key_order():
    base = dict(quality.DEFAULT_CONFIG["weights"])
    shuffled = {k: base[k] for k in sorted(base, reverse=True)}
    assert quality.weights_fingerprint(base) == quality.weights_fingerprint(shuffled)
    retuned = {**base, "Assert": 0}
    assert quality.weights_fingerprint(retuned) != quality.weights_fingerprint(base)


# ---- scan aggregate ---------------------------------------------------------


def test_scan_report_totals_and_keeps_unmeasured_files_out_of_the_numbers():
    good = _report("def f(a):\n    if a:\n        return 1\n    return 2\n", path="a.py")
    other = _report("def g():\n    return 1\n", path="b.py")
    bad = quality.unreadable_report("c.py", "OSError: nope")
    result = quality.scan_report([good, other, bad])
    assert result["files"] == 3 and result["files_measured"] == 2 and result["files_failed"] == 1
    assert result["totals"]["functions"] == 2
    assert result["totals"]["complexity_total"] == 3
    assert result["complexity_max"] == 2
    assert result["complexity_mean"] == 1.5  # 2 functions, not 3 files
    assert result["unmeasured"] == [{"path": "c.py", "error": "OSError: nope"}]
    assert result["findings"] == 1 and result["summary"]["by_rule"] == {"quality:file-unreadable": 1}


def test_scan_report_has_no_mean_when_there_is_nothing_to_average():
    result = quality.scan_report([_report("X = 1\n", path="a.py")])
    assert result["complexity_mean"] is None  # not 0.0
    assert result["complexity_max"] is None
    assert result["files_measured"] == 1 and result["totals"]["functions"] == 0


def test_scan_report_names_a_partially_measured_file_instead_of_summing_a_none(monkeypatch):
    report = _report("def f():\n    return 1\n", path="a.py")
    report["counts"]["todo_markers"] = None  # as a tokenize failure would leave it
    result = quality.scan_report([report])
    assert result["totals"]["todo_markers"] == 0
    assert result["partial"] == ["a.py: todo_markers not measured"]


def test_hottest_is_ranked_and_capped():
    reports = [
        _report(
            "def f(a):\n" + "".join(f"    if a == {i}:\n        return {i}\n" for i in range(3)),
            path="a.py",
        ),
        _report("def g():\n    return 1\n", path="b.py"),
    ]
    result = quality.scan_report(reports, top=1)
    assert [(u["path"], u["qualname"]) for u in result["hottest"]] == [("a.py", "f")]
    assert quality.scan_report(reports, top=5)["hottest"][1]["qualname"] == "g"


# ---- the sqlite trend store -------------------------------------------------


def _store():
    return quality.open_store(":memory:")


def _record(conn, src: str, *, label: str, path: str = "a.py", cfg=None, ts: float = 1.0) -> int:
    cfg = cfg or quality.default_config()
    reports = [quality.file_report(src, path=path, config=cfg)]
    return quality.record_run(
        conn,
        scan=quality.scan_report(reports),
        reports=reports,
        root="proj",
        ts=ts,
        weights=cfg["weights"],
        label=label,
    )


def test_open_store_creates_the_schema_and_stamps_its_version(tmp_path):
    db = tmp_path / "nested" / "quality.db"
    conn = quality.open_store(db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"runs", "units", "file_rows", "meta"} <= tables
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        assert version == quality.SCHEMA_VERSION
    finally:
        conn.close()
    assert db.exists()  # the parent directory was created for it


def test_record_run_stores_the_run_its_units_and_its_files():
    conn = _store()
    try:
        run_id = _record(conn, "def f(a):\n    if a:\n        return 1\n    return 2\n", label="one")
        run = quality.list_runs(conn)[0]
        assert run["id"] == run_id and run["label"] == "one"
        assert run["complexity_total"] == 2 and run["functions"] == 1
        units = conn.execute("SELECT qualname, complexity FROM units WHERE run_id=?", (run_id,)).fetchall()
        assert [tuple(u) for u in units] == [("f", 2)]
        files = conn.execute("SELECT path, sloc, error FROM file_rows WHERE run_id=?", (run_id,)).fetchall()
        assert [tuple(f) for f in files] == [("a.py", 4, None)]
    finally:
        conn.close()


def test_record_run_keeps_an_unmeasured_file_as_null_metrics_plus_its_error():
    conn = _store()
    try:
        reports = [quality.unreadable_report("gone.py", "OSError: nope")]
        run_id = quality.record_run(
            conn,
            scan=quality.scan_report(reports),
            reports=reports,
            root="proj",
            ts=1.0,
            weights=quality.DEFAULT_CONFIG["weights"],
        )
        row = conn.execute(
            "SELECT sloc, complexity_total, error FROM file_rows WHERE run_id=?", (run_id,)
        ).fetchone()
        assert row["sloc"] is None and row["complexity_total"] is None
        assert row["error"] == "OSError: nope"
        assert quality.list_runs(conn)[0]["files_failed"] == 1
    finally:
        conn.close()


def test_record_run_refuses_a_row_that_claims_both_or_neither():
    conn = _store()
    try:
        good = quality.file_report("def f():\n    return 1\n", path="a.py")
        both = {**good, "error": "invented"}
        neither = {**good, "counts": None}
        for doctored in (both, neither):
            with pytest.raises(ValueError, match="exactly one of counts/error"):
                quality.record_run(
                    conn,
                    scan=quality.scan_report([doctored]),
                    reports=[doctored],
                    root="proj",
                    ts=1.0,
                    weights=quality.DEFAULT_CONFIG["weights"],
                )
        assert quality.list_runs(conn) == []  # nothing was written
    finally:
        conn.close()


def test_list_runs_is_newest_first_and_honours_the_limit():
    conn = _store()
    try:
        for i in range(3):
            _record(conn, "def f():\n    return 1\n", label=f"r{i}", ts=float(i))
        assert [r["label"] for r in quality.list_runs(conn)] == ["r2", "r1", "r0"]
        assert [r["label"] for r in quality.list_runs(conn, limit=2)] == ["r2", "r1"]
    finally:
        conn.close()


def test_trend_reads_oldest_first_and_reports_the_delta():
    conn = _store()
    try:
        _record(conn, "def f():\n    return 1\n", label="a", ts=1.0)
        _record(conn, "def f(x):\n    if x:\n        return 1\n    return 2\n", label="b", ts=2.0)
        series = quality.trend(conn, "complexity_total")
        assert [p["label"] for p in series["series"]] == ["a", "b"]
        assert series["first"] == 1 and series["last"] == 2
        assert series["delta"] == 1 and series["min"] == 1 and series["max"] == 2
        assert series["points"] == 2 and series["missing"] == 0
        assert series["comparable"] is True and series["note"] is None
    finally:
        conn.close()


def test_trend_keeps_an_unmeasured_run_in_the_series_as_none():
    conn = _store()
    try:
        _record(conn, "X = 1\n", label="no-functions", ts=1.0)
        _record(conn, "def f():\n    return 1\n", label="has-one", ts=2.0)
        series = quality.trend(conn, "complexity_max")
        assert [p["value"] for p in series["series"]] == [None, 1]
        assert series["missing"] == 1
        assert series["first"] == 1 and series["delta"] is None  # one usable point only
    finally:
        conn.close()


def test_trend_refuses_a_metric_it_does_not_store():
    conn = _store()
    try:
        _record(conn, "def f():\n    return 1\n", label="a")
        with pytest.raises(ValueError, match="unknown metric"):
            quality.trend(conn, "vibes")
        for metric in quality.TREND_METRICS:
            # every advertised name really is a column: a typo in TREND_METRICS
            # would raise sqlite3.OperationalError here, not return a series
            assert quality.trend(conn, metric)["points"] == 1
    finally:
        conn.close()


def test_trend_flags_a_window_that_spans_two_weight_tables():
    conn = _store()
    try:
        retuned = quality.default_config()
        retuned["weights"]["If"] = 5
        _record(conn, "def f(a):\n    if a:\n        return 1\n", label="a", ts=1.0)
        _record(conn, "def f(a):\n    if a:\n        return 1\n", label="b", cfg=retuned, ts=2.0)
        series = quality.trend(conn, "complexity_total")
        assert series["delta"] == 4  # 1+1 became 1+5: the line moved
        assert series["comparable"] is False
        assert "weight tables" in series["note"]  # ...but not because the code did
    finally:
        conn.close()


def test_compare_runs_names_the_function_that_got_worse():
    conn = _store()
    try:
        base = _record(conn, "def f(a):\n    if a:\n        return 1\n", label="before", ts=1.0)
        head = _record(
            conn,
            "def f(a):\n    if a and a > 1:\n        for x in range(a):\n            return x\n",
            label="after",
            ts=2.0,
        )
        result = quality.compare_runs(conn, base, head)
        assert result["comparable"] is True and result["note"] is None
        assert result["regressions"] == [
            {"path": "a.py", "qualname": "f", "lineno": 1, "base": 2, "head": 4, "delta": 2}
        ]
        assert result["improvements"] == [] and result["added"] == [] and result["removed"] == []
        assert result["totals"]["complexity_total"] == {"base": 2, "head": 4, "delta": 2}
        assert result["base"]["label"] == "before" and result["head"]["label"] == "after"
    finally:
        conn.close()


def test_compare_runs_reports_improvements_additions_and_removals():
    conn = _store()
    try:
        base = _record(
            conn,
            "def f(a):\n    if a:\n        return 1\n    return 2\ndef gone():\n    return 0\n",
            label="before",
            ts=1.0,
        )
        head = _record(
            conn, "def f(a):\n    return a\ndef fresh(a):\n    if a:\n        return 1\n", label="after", ts=2.0
        )
        result = quality.compare_runs(conn, base, head)
        assert result["regressions"] == []
        assert result["improvements"] == [
            {"path": "a.py", "qualname": "f", "lineno": 1, "base": 2, "head": 1, "delta": -1}
        ]
        assert result["added"] == [{"path": "a.py", "qualname": "fresh", "complexity": 2}]
        assert result["removed"] == [{"path": "a.py", "qualname": "gone", "complexity": 1}]
    finally:
        conn.close()


def test_compare_runs_refuses_to_call_a_retune_a_regression():
    conn = _store()
    try:
        src = "def f(a):\n    if a:\n        return 1\n"
        base = _record(conn, src, label="before", ts=1.0)
        retuned = quality.default_config()
        retuned["weights"]["If"] = 9
        head = _record(conn, src, label="after", cfg=retuned, ts=2.0)
        result = quality.compare_runs(conn, base, head)
        assert result["comparable"] is False
        assert result["regressions"] == []  # the score moved; the code did not
        assert result["improvements"] == []
        assert "different weight tables" in result["note"]
        # the totals still show the movement, labelled as incomparable
        assert result["totals"]["complexity_total"] == {"base": 2, "head": 10, "delta": 8}
    finally:
        conn.close()


def test_compare_runs_rejects_an_unknown_run_id():
    conn = _store()
    try:
        run_id = _record(conn, "def f():\n    return 1\n", label="a")
        with pytest.raises(ValueError, match="no such run id"):
            quality.compare_runs(conn, run_id, 999)
        with pytest.raises(ValueError, match="no such run id"):
            quality.compare_runs(conn, 999, run_id)
    finally:
        conn.close()


def test_compare_runs_totals_do_not_invent_a_delta_from_a_missing_value():
    conn = _store()
    try:
        base = _record(conn, "X = 1\n", label="no-functions", ts=1.0)
        head = _record(conn, "def f():\n    return 1\n", label="has-one", ts=2.0)
        totals = quality.compare_runs(conn, base, head)["totals"]
        assert totals["complexity_max"] == {"base": None, "head": 1, "delta": None}
        assert totals["functions"]["delta"] == 1
    finally:
        conn.close()


# ---- anti-duplication drift guards -----------------------------------------


def test_marker_word_set_matches_the_todos_plugin_and_covers_goat_audit():
    """The marker list is not retyped on faith: extension/word-list drift between
    modules is a known bug class here, so the sets are compared for real."""
    from bigbang.plugins.todos import cli as todos_cli

    listed = set(re.findall(r"[A-Z]{3,}", todos_cli.MARKER_RE.pattern))
    assert listed == set(quality.MARKERS)
    goat = (ROOT / "scripts" / "goat_audit.py").read_text(encoding="utf-8")
    note_re = re.search(r"NOTE_RE = re\.compile\(r\"(?P<body>[^\"]+)\"\)", goat)
    assert note_re, "goat_audit.py no longer declares NOTE_RE the way this guard reads it"
    assert set(re.findall(r"[A-Z]{3,}", note_re.group("body"))) <= set(quality.MARKERS)


def test_python_extension_list_agrees_with_reviewgraph():
    from bigbang.plugins.reviewgraph import graph

    assert set(quality.PY_EXTS) <= graph.PY_SUFFIXES


def test_this_plugin_emits_no_per_marker_finding_because_todos_owns_that():
    src = "# TODO a\n# TODO b\n# TODO c\nx = 1\n"
    report = _report(src)
    assert len(report["markers"]) == 3  # they are all measured...
    density = [d for d in report["diagnostics"] if d["rule"] == "quality:todo-density"]
    assert len(density) == 1  # ...and reported as ONE density finding
    assert len(report["diagnostics"]) == 1


# ---- stdlib-only invariant (the whole point of the openswap family) ----------


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_imports_are_stdlib_only():
    roots = _import_roots(ROOT / "bigbang" / "core" / "quality.py")
    allowed = set(sys.stdlib_module_names) | {"bigbang"}
    assert roots <= allowed, f"non-stdlib imports: {sorted(roots - allowed)}"
    assert "ast" in roots and "sqlite3" in roots  # the guard is reading the real file


def test_plugin_cli_adds_no_dependency_beyond_typer():
    roots = _import_roots(ROOT / "bigbang" / "plugins" / "quality" / "cli.py")
    allowed = set(sys.stdlib_module_names) | {"bigbang", "typer"}
    assert roots <= allowed, f"new dependency: {sorted(roots - allowed)}"


def test_core_never_imports_a_plugin_which_would_invert_the_layering():
    text = (ROOT / "bigbang" / "core" / "quality.py").read_text(encoding="utf-8")
    assert "bigbang.plugins" not in text


def test_manifest_declares_zero_egress_and_only_the_store_as_writable():
    import yaml

    manifest = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "quality" / "manifest.yaml").read_text(encoding="utf-8")
    )
    caps = manifest["capabilities"]
    assert caps["network"]["enabled"] is False and caps["network"]["domains"] == []
    assert caps["secrets"]["allow"] == []
    assert caps["filesystem"]["paths"] == [".scout"]


def test_egress_guard_refuses_a_widened_manifest(monkeypatch):
    import typer

    from bigbang.plugins.quality import cli as quality_cli

    assert quality_cli._egress_guard("test")["network_enabled"] is False
    for widened in (
        {"capabilities": {"network": {"enabled": True, "domains": []}}},
        {"capabilities": {"network": {"enabled": False, "domains": ["sonarcloud.io"]}}},
    ):
        monkeypatch.setattr(quality_cli, "_MANIFEST", widened)
        with pytest.raises(typer.Exit):
            quality_cli._egress_guard("test")


def test_read_source_reports_why_instead_of_raising(tmp_path):
    from bigbang.plugins.quality import cli as quality_cli

    good = tmp_path / "ok.py"
    good.write_text("x = 1\n", encoding="utf-8")
    text, error = quality_cli._read_source(good)
    assert text == "x = 1\n" and error is None
    text, error = quality_cli._read_source(tmp_path)  # a directory is not readable text
    # the exact OSError subclass differs by platform, so assert the SHAPE
    # ("<SomethingError>: detail") rather than an or-chain of platform guesses
    assert text == ""
    assert error and error.split(":")[0].endswith("Error")


# ---- the real CLI in a subprocess (offline on every path) --------------------


def _cli(args):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(ROOT),
    )


def _py(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_cli_quality_hello_envelope():
    r = _cli(["quality", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert data["data"]["plugin"] == "quality"
    assert data["example"].startswith("scout ")  # the envelope teaches a real next step


def test_cli_quality_detect_reports_fallback_and_zero_egress():
    r = _cli(["quality", "detect"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["native_used"] is False
    assert data["egress"] == {
        "network_enabled": False,
        "domains": [],
        "reads": "local source files only",
    }
    assert "sonar-scanner" in data["native_never_executed"]
    assert data["native"]["binary"] == "sonar-scanner"


def test_cli_quality_rules_publishes_the_effective_policy():
    r = _cli(["quality", "rules"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert set(data["rules"]) == set(quality.DEFAULT_CONFIG["rules"])
    assert data["weights"] == quality.DEFAULT_CONFIG["weights"]
    assert data["thresholds"]["complexity_error"] == 20
    assert data["trend_metrics"] == list(quality.TREND_METRICS)
    assert data["markers"] == list(quality.MARKERS)
    assert data["weights_fingerprint"] == quality.weights_fingerprint(data["weights"])
    assert data["overlay"] is None


def test_cli_quality_rules_rejects_a_bad_overlay(tmp_path):
    bad = _py(tmp_path, "bad.json", '{"rules": {"quality:nope": {}}}')
    r = _cli(["quality", "rules", "--config", str(bad)])
    assert r.returncode == 1
    assert "bad config overlay" in json.loads(r.stdout)["error"]


def test_cli_quality_scan_finds_real_defects_and_gates(tmp_path):
    src = "import os\n# TODO fix\ndef f(a, b, c, d, e, g, h):\n"
    src += "".join(f"    if a == {i}:\n        return {i}\n" for i in range(20))
    target = _py(tmp_path, "hot.py", src)
    r = _cli(["quality", "scan", str(target), "--db", str(tmp_path / "h.db"), "--fail-on", "error"])
    assert r.returncode == 1  # the gate fires on the complexity error below
    data = json.loads(r.stdout)["data"]
    fired = {d["rule"] for d in data["diagnostics"]}
    assert {
        "quality:complexity-error",
        "quality:import-unused",
        "quality:todo-density",
        "quality:function-params",
    } <= fired
    assert data["summary"]["by_severity"]["error"] == 1  # complexity-error, exactly
    assert data["aggregate"]["files_measured"] == 1
    assert data["aggregate"]["complexity_max"] == 21
    assert data["native_used"] is False and data["recorded"] is True
    assert data["run_id"] == 1
    assert "units" not in data["files"][0]  # the per-unit table is opt-in


def test_cli_quality_scan_clean_file_exits_zero_and_reports_nothing(tmp_path):
    target = _py(tmp_path, "clean.py", CLEAN_SOURCE)
    r = _cli(
        ["quality", "scan", str(target), "--db", str(tmp_path / "h.db"), "--fail-on", "info", "--units"]
    )
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)["data"]
    assert data["diagnostics"] == [] and data["summary"]["total"] == 0
    assert data["files"][0]["units"][0]["qualname"] == "head"  # --units surfaced the table
    assert data["aggregate"]["totals"]["functions"] == 1


def test_cli_quality_scan_no_record_writes_nothing(tmp_path):
    target = _py(tmp_path, "clean.py", CLEAN_SOURCE)
    db = tmp_path / "never.db"
    r = _cli(["quality", "scan", str(target), "--db", str(db), "--no-record"])
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)["data"]
    assert data["recorded"] is False and data["run_id"] is None and data["db"] is None
    assert not db.exists()  # a read-only check really is read-only


def test_cli_quality_scan_walks_a_directory_and_skips_non_python(tmp_path):
    _py(tmp_path, "one.py", "import os\n")
    _py(tmp_path, "two.py", "import json\n")
    _py(tmp_path, "notes.txt", "import os\n")
    r = _cli(["quality", "scan", str(tmp_path), "--db", str(tmp_path / "h.db")])
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)["data"]
    assert data["aggregate"]["files"] == 2  # the .txt is not Python and was not read
    assert data["aggregate"]["totals"]["unused_imports"] == 2


def test_cli_quality_scan_counts_an_unparsable_file_as_unmeasured(tmp_path):
    _py(tmp_path, "broken.py", "def f(:\n")
    r = _cli(["quality", "scan", str(tmp_path), "--db", str(tmp_path / "h.db"), "--fail-on", "error"])
    assert r.returncode == 1  # unmeasured must never pass a gate
    data = json.loads(r.stdout)["data"]
    assert data["aggregate"]["files_failed"] == 1 and data["aggregate"]["files_measured"] == 0
    assert data["aggregate"]["complexity_mean"] is None
    assert [d["rule"] for d in data["diagnostics"]] == ["quality:file-unparsed"]


def test_cli_quality_scan_missing_path_fails_actionably(tmp_path):
    r = _cli(["quality", "scan", str(tmp_path / "nope.py")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "path not found" in data["error"]
    assert data["example"].startswith("scout ")


def test_cli_quality_scan_empty_directory_fails_actionably(tmp_path):
    (tmp_path / "empty").mkdir()
    r = _cli(["quality", "scan", str(tmp_path / "empty")])
    assert r.returncode == 1
    assert "no Python files found" in json.loads(r.stdout)["error"]


def test_cli_quality_scan_rejects_a_bad_fail_on(tmp_path):
    target = _py(tmp_path, "x.py", "x = 1\n")
    r = _cli(["quality", "scan", str(target), "--fail-on", "catastrophe"])
    assert r.returncode == 1
    assert "--fail-on must be one of" in json.loads(r.stdout)["error"]


def test_cli_quality_trend_rejects_an_unknown_metric(tmp_path):
    r = _cli(["quality", "trend", "--db", str(tmp_path / "h.db"), "--metric", "vibes"])
    assert r.returncode == 1
    assert "unknown metric" in json.loads(r.stdout)["error"]


def test_cli_quality_compare_needs_two_runs(tmp_path):
    target = _py(tmp_path, "clean.py", CLEAN_SOURCE)
    db = tmp_path / "h.db"
    _cli(["quality", "scan", str(target), "--db", str(db)])
    r = _cli(["quality", "compare", "--db", str(db)])
    assert r.returncode == 1
    assert "need two recorded runs" in json.loads(r.stdout)["error"]


def test_cli_quality_trend_and_compare_span_two_real_runs(tmp_path):
    db = tmp_path / "h.db"
    target = _py(tmp_path, "app.py", "def f(a):\n    if a:\n        return 1\n    return 2\n")
    first = _cli(["quality", "scan", str(target), "--db", str(db), "--label", "before"])
    assert first.returncode == 0, first.stdout + first.stderr
    target.write_text(
        "def f(a):\n    if a and a > 1:\n        for x in range(a):\n            return x\n    return 2\n",
        encoding="utf-8",
    )
    second = _cli(["quality", "scan", str(target), "--db", str(db), "--label", "after"])
    assert second.returncode == 0, second.stdout + second.stderr

    trend = json.loads(_cli(["quality", "trend", "--db", str(db)]).stdout)["data"]
    assert [p["label"] for p in trend["series"]] == ["before", "after"]
    assert trend["delta"] == 2 and trend["metric"] == "complexity_total"
    assert [r["label"] for r in trend["runs"]] == ["after", "before"]

    r = _cli(["quality", "compare", "--db", str(db), "--fail-on-regression"])
    assert r.returncode == 1  # a function got more complex
    data = json.loads(r.stdout)["data"]
    assert data["comparable"] is True
    assert [(x["qualname"], x["base"], x["head"]) for x in data["regressions"]] == [("f", 2, 4)]
    assert data["head"]["label"] == "after" and data["base"]["label"] == "before"


def test_cli_quality_compare_will_not_gate_across_two_weight_tables(tmp_path):
    db = tmp_path / "h.db"
    target = _py(tmp_path, "app.py", "def f(a):\n    if a:\n        return 1\n    return 2\n")
    cfg = _py(tmp_path, "cfg.json", '{"weights": {"If": 7}}')
    assert _cli(["quality", "scan", str(target), "--db", str(db)]).returncode == 0
    assert _cli(["quality", "scan", str(target), "--db", str(db), "--config", str(cfg)]).returncode == 0
    r = _cli(["quality", "compare", "--db", str(db), "--fail-on-regression"])
    assert r.returncode == 1  # "cannot determine" must not pass a gate
    data = json.loads(r.stdout)["data"]
    assert data["comparable"] is False and data["regressions"] == []
    assert "different weight tables" in data["note"]
    ok_run = _cli(["quality", "compare", "--db", str(db)])
    assert ok_run.returncode == 0  # without the gate flag it is a report, not a failure


def test_cli_quality_scan_dogfoods_this_plugins_own_core(tmp_path):
    """The scanner is run against the module it lives in — if the measurement were
    broken, the numbers below could not be reproduced from the file on disk."""
    core = ROOT / "bigbang" / "core" / "quality.py"
    r = _cli(["quality", "scan", str(core), "--db", str(tmp_path / "h.db"), "--no-record"])
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)["data"]
    expected = quality.file_report(core.read_text(encoding="utf-8"), path=str(core))
    assert data["files"][0]["counts"] == expected["counts"]
    assert data["aggregate"]["totals"]["functions"] == expected["counts"]["functions"]
    assert data["aggregate"]["files_failed"] == 0
    assert expected["counts"]["functions"] > 20  # a real module, not an empty read
    assert data["elapsed_ms"] > 0  # a >1000-line file cannot be measured in 0.0 ms
