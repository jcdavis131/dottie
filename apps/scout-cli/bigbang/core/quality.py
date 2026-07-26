# Solo personal project, no connection to employer, built with public/free-tier only
"""Quality — per-function AST code metrics with history (openswap #30: SonarQube / CodeClimate).

What the paid products sell is not the arithmetic — McCabe published cyclomatic
complexity in 1976 and `ast` ships in the stdlib. What they sell is a SERVER that
keeps the time series so today's number means something next to last week's, and
a quality gate wired to it. This adapter deletes the server: the metrics are
computed here from source text, and the history lives in a sqlite file on this
box. There is no scanner token, no project key and no intake host, so "no source
ever left the machine" is architectural rather than a retention promise.

MEASURES (all per FUNCTION, then rolled up per file and per run):
- cyclomatic complexity, reported WITH the per-node-type breakdown that produced
  it (`decisions`), because tools disagree about what a decision point is;
- size: physical `lines`, `statements`, `max_depth` of nesting, `params`;
- dead imports: bound names never referenced in their own module;
- TODO/FIXME/HACK/XXX/BUG density, normalized per 100 SLOC;
- module-level complexity, so a script whose whole flow is at import time cannot
  score clean just because it defines no functions.

OVERLAP — checked before a line was written, and stated because a near-duplicate
would be a failure rather than a delivery:

* `scripts/goat_audit.py` scores a PLUGIN on a six-dimension rubric by reading
  ONLY that plugin's cli.py, and its size signal is deliberately a proxy: the
  longest function's line SPAN, "a proxy, not a verdict". It has no notion of
  cyclomatic complexity, no per-function table, no unused-import analysis, and
  its only persistence is one mean per plugin in .goat_baseline.json. This module
  is the other axis: every function in an arbitrary tree, real branch counting,
  and a run-indexed sqlite series. goat_audit stays the rubric; nothing here
  scores a plugin and nothing here should be wired into that baseline file.
* `bigbang/plugins/reviewgraph` also parses Python with `ast` into sqlite, so the
  distinction matters: reviewgraph stores RELATIONSHIPS (imports, calls,
  inherits) to answer "what does this diff touch" and rank fan-in for review
  context. It measures no property of a function's body, and its `compute_risks`
  is fan-in/import-cycles/git-churn — coupling, not complexity. This module
  stores per-unit MEASUREMENTS over time and answers "did this get worse".
  Neither is a superset; the drift guard in the tests pins PY_EXTS against
  reviewgraph's suffix set so the two cannot disagree about what Python is.
* `bigbang/plugins/todos` already lists markers. That is why nothing here emits a
  per-marker finding: this module emits ONE density finding per file and defers
  the listing to `scout todos`. The two also differ on purpose — todos matches
  case-insensitively (a listing tool wants recall) while density needs precision,
  so MARKERS here are matched case-sensitively in upper case; "works around a bug
  in json" must not inflate a ratio. The marker WORD set is drift-guarded against
  todos.MARKER_RE and goat_audit's NOTE_RE in the tests instead of being retyped
  on faith, because extension-list drift between modules is a known bug class in
  this repo. This module also reads markers from `tokenize` COMMENT tokens rather
  than a line regex, so a "# TODO" inside a string literal is not counted, and
  the count of markers that appear in STRING tokens is reported separately as a
  labelled exclusion rather than silently dropped.
* `bigbang/core/prose.py` + `readability.py` score natural-language prose
  (Flesch, passive voice). Different input axis entirely: no code is parsed there
  and no English is scored here.
* SIBLING RISK, stated rather than denied: ranks 29-34 are being built
  concurrently and are not visible from here. Anything in that batch replacing a
  dependency/SBOM/licence scanner will also enumerate a module's imports, and
  anything replacing a coverage service will also walk Python with `ast`. If a
  sibling landed import enumeration, `import_bindings` is the seam to share and
  the honest fix is to derive one from the other, not to keep both.

HONESTY RULES that shape the code:
- A file has EITHER metrics OR an `error`, never both, never neither, and
  `record_run` re-checks that at the storage boundary. `counts` is None on a
  file that could not be read or parsed, not a row of zeros: zero complexity is
  a measurement, and no measurement was taken.
- Every run stores a fingerprint of the weight table that produced it, so
  `compare_runs` REFUSES to call a difference a regression when the two runs were
  measured under different weights. Re-tuning a threshold must not manufacture a
  trend.
- Means are None when there is nothing to average, never 0.0.
- The weight table is data (`DEFAULT_CONFIG["weights"]`, published by the CLI and
  overlayable with JSON): radon, mccabe and lizard do not agree on `assert`,
  boolean operators or comprehensions, so the choice is exposed and the
  per-function `decisions` breakdown makes any single score auditable instead of
  asking the reader to trust it.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import sqlite3
import tokenize
from pathlib import Path
from typing import Any

from bigbang.core import openswap

SCHEMA_VERSION = "1"

# Python only, and it says so. SonarQube is multi-language; this adapter is not,
# because a hand-rolled parser for a second language would produce numbers whose
# meaning nobody could defend. Non-Python files are counted as skipped WITH the
# reason rather than silently ignored. Drift-guarded against reviewgraph's
# PY_SUFFIXES in the tests (importing a plugin from core would invert the layering
# and is what the guard exists to avoid).
PY_EXTS = (".py",)

# Case-sensitive upper case on purpose — see the module docstring. Sorted so the
# set comparison in the drift guard is order-independent.
MARKERS = ("BUG", "FIXME", "HACK", "TODO", "XXX")
_MARKER_RE = re.compile(r"\b(" + "|".join(MARKERS) + r")\b")

# flake8/ruff suppression, matched on the physical line exactly as flake8 itself
# matches it. F401 is the unused-import code; a bare directive with no code list
# suppresses everything. (Spelled apart in this comment on purpose: written out
# in full it is a directive ruff would try to apply to this very line.)
_NOQA_RE = re.compile(
    r"#\s*noqa(?::\s*(?P<codes>[A-Za-z]+[0-9]+(?:[,\s]+[A-Za-z]+[0-9]+)*))?", re.I
)
_UNUSED_IMPORT_CODE = "F401"

# Tokens that are not code for SLOC purposes. Everything else contributes every
# physical line it spans, so a 20-line dict literal counts 20 and a comment-only
# line counts 0 — the standard SLOC convention, stated because density depends
# on it.
_NON_CODE_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
    }
)

# ast node types that open a nesting level for `max_depth`.
_NESTING_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Match,
)
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

DEFAULT_CONFIG: dict[str, Any] = {
    # One decision point per +1. `else`, `finally`, `with` and `return` are 0
    # because they add no branch a test would need to cover separately.
    "weights": {
        "If": 1,  # `elif` is a nested If node, so it is counted once each
        "For": 1,
        "AsyncFor": 1,
        "While": 1,
        "ExceptHandler": 1,  # one per handler, including a bare `except:`
        "IfExp": 1,  # ternary
        "Assert": 1,  # a conditional raise is a branch; set 0 to follow mccabe
        "BoolOp": 1,  # per EXTRA operand: `a and b and c` is +2
        "comprehension": 1,  # the implied loop
        "comprehension_if": 1,  # each filter clause
        "match_case": 1,  # a wildcard `case _:` is the else arm and scores 0
        "match_guard": 1,
    },
    "thresholds": {
        "complexity_warn": 10,
        "complexity_error": 20,
        "function_lines": 60,
        "function_statements": 50,
        "max_depth": 4,
        "params": 6,
        "todo_density": 2.0,  # markers per 100 SLOC
    },
    "rules": {
        "quality:complexity-error": {
            "enabled": True,
            "severity": "error",
            "threshold": "complexity_error",
        },
        "quality:complexity-warn": {
            "enabled": True,
            "severity": "warning",
            "threshold": "complexity_warn",
        },
        "quality:module-complexity": {
            "enabled": True,
            "severity": "warning",
            "threshold": "complexity_warn",
        },
        "quality:function-long": {
            "enabled": True,
            "severity": "warning",
            "threshold": "function_lines",
        },
        "quality:function-statements": {
            "enabled": True,
            "severity": "suggestion",
            "threshold": "function_statements",
        },
        "quality:function-deep": {
            "enabled": True,
            "severity": "warning",
            "threshold": "max_depth",
        },
        "quality:function-params": {
            "enabled": True,
            "severity": "suggestion",
            "threshold": "params",
        },
        "quality:import-unused": {
            "enabled": True,
            "severity": "warning",
            "threshold": None,
        },
        # __init__.py re-exports a name by importing it, so an unreferenced
        # import there is a convention rather than a defect. Reported at a lower
        # severity under its own id instead of being hidden.
        "quality:import-unused-init": {
            "enabled": True,
            "severity": "suggestion",
            "threshold": None,
        },
        "quality:import-star": {"enabled": True, "severity": "info", "threshold": None},
        "quality:todo-density": {
            "enabled": True,
            "severity": "suggestion",
            "threshold": "todo_density",
        },
        # Neither of these is a code-quality opinion: a file that was not
        # measured must never leave a gate looking clean.
        "quality:file-unparsed": {
            "enabled": True,
            "severity": "error",
            "threshold": None,
        },
        "quality:file-unreadable": {
            "enabled": True,
            "severity": "error",
            "threshold": None,
        },
        "quality:tokenize-failed": {
            "enabled": True,
            "severity": "info",
            "threshold": None,
        },
    },
}

SCOPE_LIMITS = (
    "static single-file analysis of Python only: complexity is counted from the"
    " ast, so a branch that only exists at runtime (getattr dispatch, a decorator"
    " that rewrites the body) is invisible; an import referenced only from eval,"
    " globals(), a doctest or a re-export without __all__ cannot be seen as used,"
    " which is why __init__.py unused imports get their own lower-severity rule;"
    " a nested def is its own unit and adds nothing to its parent's score; no"
    " cross-file duplication detection (see scout dupes) and no coverage data"
)

TREND_METRICS = (
    "complexity_total",
    "complexity_max",
    "complexity_mean",
    "functions",
    "sloc",
    "todo_markers",
    "todo_density",
    "unused_imports",
    "findings",
    "files_failed",
)


# ---- config (policy-as-config) ----------------------------------------------


def default_config() -> dict[str, Any]:
    """A deep copy of the built-in policy, safe for a caller to mutate."""
    return {
        "weights": dict(DEFAULT_CONFIG["weights"]),
        "thresholds": dict(DEFAULT_CONFIG["thresholds"]),
        "rules": {rid: dict(cfg) for rid, cfg in DEFAULT_CONFIG["rules"].items()},
    }


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """The built-in policy with an optional JSON overlay merged over it.

    Overlay shape: {"weights": {...}, "thresholds": {...}, "rules": {...}}. An
    unknown section, weight, threshold or rule id is a HARD error, and so is a
    bad severity or a non-numeric threshold — silently ignoring a typo would ship
    a gate that does not gate, and silently accepting an unknown weight would let
    a config claim to count something this core never looks at.
    """
    cfg = default_config()
    if path is None:
        return cfg
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            "config overlay must be a JSON object with weights/thresholds/rules"
        )
    unknown_sections = sorted(set(raw) - set(cfg))
    if unknown_sections:
        raise ValueError(
            f"unknown config section(s) {unknown_sections}; expected {sorted(cfg)}"
        )
    _merge_numbers(cfg, raw, "weights")
    _merge_numbers(cfg, raw, "thresholds")
    _merge_rules(cfg, raw)
    return cfg


def _merge_numbers(cfg: dict[str, Any], raw: dict[str, Any], section: str) -> None:
    """Overlay one numeric section, rejecting unknown keys and non-numbers."""
    for key, value in (raw.get(section) or {}).items():
        if key not in cfg[section]:
            raise ValueError(
                f"unknown {section} key {key!r} (see: scout quality rules)"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{section}.{key} must be a number, got {value!r}")
        if value < 0:
            raise ValueError(f"{section}.{key} must not be negative, got {value!r}")
        cfg[section][key] = value


def _merge_rules(cfg: dict[str, Any], raw: dict[str, Any]) -> None:
    """Overlay rule settings; a rule may not move its own threshold binding."""
    for rid, settings in (raw.get("rules") or {}).items():
        if rid not in cfg["rules"]:
            raise ValueError(f"unknown rule id {rid!r} (see: scout quality rules)")
        if not isinstance(settings, dict):
            raise ValueError(f"rule {rid!r}: settings must be a JSON object")
        sev = settings.get("severity")
        if sev is not None and sev not in openswap.SEVERITIES:
            raise ValueError(
                f"rule {rid!r}: severity must be one of {'|'.join(openswap.SEVERITIES)}"
            )
        if "threshold" in settings:
            raise ValueError(
                f"rule {rid!r}: a rule names its threshold in code; tune it under"
                ' "thresholds" instead'
            )
        cfg["rules"][rid].update(settings)


def weights_fingerprint(weights: dict[str, Any]) -> str:
    """Stable short digest of a weight table, stamped on every recorded run.

    Two runs measured under different weights are not comparable, and this is
    what lets `compare_runs` say so instead of reporting the retune as a
    regression in the code.
    """
    canonical = json.dumps(
        {k: weights[k] for k in sorted(weights)}, separators=(",", ":")
    )
    return hashlib.blake2b(canonical.encode("utf-8"), digest_size=8).hexdigest()


# ---- complexity --------------------------------------------------------------


def _is_wildcard_pattern(pattern: ast.AST) -> bool:
    """`case _:` / `case x:` — an unconditional catch-all, i.e. the else arm."""
    return isinstance(pattern, ast.MatchAs) and pattern.pattern is None


def _node_weight(node: ast.AST, weights: dict[str, Any]) -> int:
    """The decision points this ONE node contributes."""
    if isinstance(node, ast.BoolOp):
        return int(weights.get("BoolOp", 0)) * (len(node.values) - 1)
    if isinstance(node, ast.comprehension):
        return int(weights.get("comprehension", 0)) + int(
            weights.get("comprehension_if", 0)
        ) * len(node.ifs)
    if isinstance(node, ast.match_case):
        total = (
            0
            if _is_wildcard_pattern(node.pattern)
            else int(weights.get("match_case", 0))
        )
        if node.guard is not None:
            total += int(weights.get("match_guard", 0))
        return total
    return int(weights.get(type(node).__name__, 0))


def count_decisions(body: list[ast.stmt], weights: dict[str, Any]) -> dict[str, int]:
    """Decision points in `body`, keyed by node type, NOT entering nested defs.

    A nested function or class is its own unit with its own row, so folding its
    branches into the parent would double-count them in the file total.
    """
    counts: dict[str, int] = {}
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, _DEF_NODES):
            continue
        added = _node_weight(node, weights)
        if added:
            counts[type(node).__name__] = counts.get(type(node).__name__, 0) + added
        stack.extend(ast.iter_child_nodes(node))
    return counts


def complexity_of(
    body: list[ast.stmt], weights: dict[str, Any]
) -> tuple[int, dict[str, int]]:
    """McCabe: 1 + decision points. Returns (score, breakdown-by-node-type)."""
    counts = count_decisions(body, weights)
    return 1 + sum(counts.values()), dict(sorted(counts.items()))


def max_depth(body: list[ast.stmt]) -> int:
    """Deepest nesting of control structures in `body`; a flat body is 0."""
    deepest = 0
    stack: list[tuple[ast.AST, int]] = [(n, 0) for n in body]
    while stack:
        node, level = stack.pop()
        if isinstance(node, _DEF_NODES):
            continue  # its own unit measures its own nesting
        here = level + 1 if isinstance(node, _NESTING_NODES) else level
        deepest = max(deepest, here)
        stack.extend((child, here) for child in ast.iter_child_nodes(node))
    return deepest


def count_statements(body: list[ast.stmt]) -> int:
    """Statements in `body`, excluding the bodies of nested defs (own units)."""
    total = 0
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.stmt):
            total += 1
        if isinstance(node, _DEF_NODES):
            continue  # counted as one statement; its insides are its own unit
        stack.extend(ast.iter_child_nodes(node))
    return total


def count_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Declared parameters, `self`/`cls` included (they are declared)."""
    args = node.args
    total = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    return total + (1 if args.vararg else 0) + (1 if args.kwarg else 0)


def _iter_functions(node: ast.AST, prefix: str = ""):
    """(FunctionDef, qualname) for every def, methods and closures included."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNC_NODES):
            qual = f"{prefix}{child.name}"
            yield child, qual
            yield from _iter_functions(child, f"{qual}.")
        elif isinstance(child, ast.ClassDef):
            yield from _iter_functions(child, f"{prefix}{child.name}.")
        else:
            yield from _iter_functions(child, prefix)


def function_units(tree: ast.AST, weights: dict[str, Any]) -> list[dict[str, Any]]:
    """One measurement row per function/method/closure, in source order.

    A qualname repeated inside one file (a conditional redefinition, or two
    methods of the same name) is disambiguated with a `#2` suffix so the history
    store has a stable identity per unit instead of collapsing two functions into
    one row.
    """
    rows: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for node, qual in _iter_functions(tree):
        seen[qual] = seen.get(qual, 0) + 1
        unique = qual if seen[qual] == 1 else f"{qual}#{seen[qual]}"
        score, decisions = complexity_of(node.body, weights)
        end = getattr(node, "end_lineno", None) or node.lineno
        rows.append(
            {
                "qualname": unique,
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": end,
                "col": node.col_offset + 1,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "complexity": score,
                "decisions": decisions,
                "lines": end - node.lineno + 1,
                "statements": count_statements(node.body),
                "max_depth": max_depth(node.body),
                "params": count_params(node),
            }
        )
    rows.sort(key=lambda r: (r["lineno"], r["qualname"]))
    return rows


def module_complexity(
    tree: ast.Module, weights: dict[str, Any]
) -> tuple[int, dict[str, int]]:
    """The same formula applied to the code that runs at IMPORT time.

    Without this a 300-line script with no def in it would score perfectly clean
    while being exactly the code SonarQube would flag.
    """
    return complexity_of(list(tree.body), weights)


# ---- imports ----------------------------------------------------------------


def _noqa_suppresses(lines: list[str], start: int, end: int) -> bool:
    """Does any physical line of this statement carry a matching `# noqa`?"""
    for index in range(start - 1, min(end, len(lines))):
        m = _NOQA_RE.search(lines[index])
        if m is None:
            continue
        codes = m.group("codes")
        if codes is None:
            return True
        if _UNUSED_IMPORT_CODE in {c.upper() for c in re.split(r"[,\s]+", codes) if c}:
            return True
    return False


def import_bindings(tree: ast.Module, lines: list[str]) -> list[dict[str, Any]]:
    """Every name an import statement BINDS, plus why it may be exempt.

    `import a.b` binds `a`; `import a.b as c` binds `c`; `from a import b` binds
    `b`; `from a import *` binds an unknowable set and is recorded with
    `star=True` so the caller can report that rather than guess.
    """
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        base = {
            "line": node.lineno,
            "col": node.col_offset + 1,
            "noqa": _noqa_suppresses(lines, node.lineno, end),
        }
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(
                    {
                        **base,
                        "name": alias.asname or alias.name.split(".")[0],
                        "module": alias.name,
                        "star": False,
                        # a __future__ import is a compiler directive, never a
                        # referenced name — reporting it unused would be wrong
                        "future": False,
                        "statement": f"import {alias.name}"
                        + (f" as {alias.asname}" if alias.asname else ""),
                    }
                )
            continue
        module = node.module or ""
        prefix = "." * node.level + module
        for alias in node.names:
            out.append(
                {
                    **base,
                    "name": None if alias.name == "*" else (alias.asname or alias.name),
                    "module": prefix,
                    "star": alias.name == "*",
                    "future": module == "__future__",
                    "statement": f"from {prefix} import {alias.name}"
                    + (f" as {alias.asname}" if alias.asname else ""),
                }
            )
    out.sort(key=lambda r: (r["line"], r["col"], r["name"] or "*"))
    return out


def _signature_annotations(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.AST]:
    """Parameter and return annotations of one def, absent ones dropped."""
    args = node.args
    every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    found = [a.annotation for a in every if a is not None and a.annotation is not None]
    if node.returns is not None:
        found.append(node.returns)
    return found


def _annotation_expressions(tree: ast.Module) -> list[ast.AST]:
    """Every annotation subtree, where a name may hide inside a string."""
    found: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, _FUNC_NODES):
            found.extend(_signature_annotations(node))
        elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
            found.append(node.annotation)
        elif isinstance(node, ast.Call):
            # typing.cast("Foo", x) — the only call form where a string argument
            # is an annotation by contract rather than by convention
            target = node.func
            name = (
                target.attr
                if isinstance(target, ast.Attribute)
                else getattr(target, "id", "")
            )
            if name == "cast" and node.args:
                found.append(node.args[0])
    return found


def used_names(tree: ast.Module) -> set[str]:
    """Names the module actually REFERENCES, string annotations included.

    Generous on purpose in exactly one direction: for unused-import analysis a
    false positive tells someone to delete an import their code needs, so a name
    that appears in a `TYPE_CHECKING` block and then only inside a quoted
    annotation counts as used. `__all__` entries count too — exporting a name IS
    using it. A Store-only name does not count: `import x` followed by `x = 1`
    leaves the import unused.
    """
    names = {
        node.id
        # `x.y` and `x.y = 1` both put x in Load context, so the attribute chain
        # needs no separate case — the root Name is always a Load.
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del))
    }
    return names | _dunder_all_names(tree) | _forward_ref_names(tree)


def _dunder_all_names(tree: ast.Module) -> set[str]:
    """String entries of `__all__` — exporting a name is using it."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        names.update(_string_constants(node))
    return names


def _string_constants(node: ast.AST) -> list[str]:
    """Every string literal anywhere under `node`."""
    return [
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]


def _forward_ref_names(tree: ast.Module) -> set[str]:
    """Names hiding inside quoted annotations, e.g. `def f(x: "Sequence")`."""
    names: set[str] = set()
    for annotation in _annotation_expressions(tree):
        for text in _string_constants(annotation):
            try:
                inner = ast.parse(text, mode="eval")
            except SyntaxError:
                continue  # not a forward reference, just a string in a Literal[]
            names.update(sub.id for sub in ast.walk(inner) if isinstance(sub, ast.Name))
    return names


def unused_imports(tree: ast.Module, lines: list[str]) -> dict[str, Any]:
    """Bound-but-never-referenced imports, plus the analysis's own blind spots.

    Returns {"unused": [...], "stars": [...], "bindings": n}. `stars` is not a
    finding about the star's contents — a `from x import *` cannot be resolved
    without importing x, which this core will not do — it is the labelled reason
    the module's namespace is only partly knowable.
    """
    referenced = used_names(tree)
    unused: list[dict[str, Any]] = []
    stars: list[dict[str, Any]] = []
    bindings = import_bindings(tree, lines)
    for binding in bindings:
        if binding["star"]:
            stars.append(binding)
            continue
        if binding["future"] or binding["noqa"] or binding["name"] in referenced:
            continue
        unused.append(binding)
    return {
        "unused": unused,
        "stars": stars,
        "bindings": sum(1 for b in bindings if not b["star"]),
    }


# ---- source-text metrics (tokenize, so strings are not comments) -------------


def source_metrics(text: str) -> dict[str, Any]:
    """SLOC, comment/blank lines and marker positions from real tokens.

    EITHER the token-derived numbers OR `error`, never both: a file tokenize
    cannot walk has no measured SLOC, so its density is unknown rather than 0.
    Markers found inside STRING tokens are counted separately and NOT included in
    `markers` — a "TODO" in a docstring or a test fixture is not a code comment,
    and hiding that exclusion would overstate precision.
    """
    result: dict[str, Any] = {
        "sloc": None,
        "comment_lines": None,
        "blank_lines": None,
        "total_lines": len(text.splitlines()),
        "markers": None,
        "markers_in_strings": None,
        "error": None,
    }
    code_rows: set[int] = set()
    comment_rows: set[int] = set()
    markers: list[dict[str, Any]] = []
    in_strings = 0
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError) as e:
        result["error"] = f"{type(e).__name__}: {e}"
        return result
    for token in tokens:
        if token.type == tokenize.COMMENT:
            comment_rows.add(token.start[0])
            for m in _MARKER_RE.finditer(token.string):
                markers.append(
                    {
                        "marker": m.group(1),
                        "line": token.start[0],
                        "col": token.start[1] + 1 + m.start(),
                        "text": " ".join(token.string.strip().split())[:120],
                    }
                )
            continue
        if token.type == tokenize.STRING:
            in_strings += len(_MARKER_RE.findall(token.string))
        if token.type in _NON_CODE_TOKENS:
            continue
        code_rows.update(range(token.start[0], token.end[0] + 1))
    blank = sum(1 for line in text.splitlines() if not line.strip())
    result.update(
        {
            "sloc": len(code_rows),
            "comment_lines": len(comment_rows - code_rows),
            "blank_lines": blank,
            "markers": sorted(markers, key=lambda m: (m["line"], m["col"])),
            "markers_in_strings": in_strings,
        }
    )
    return result


def attribute_markers(
    markers: list[dict[str, Any]], units: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Tag each marker with the INNERMOST function whose span contains it."""
    tagged = []
    for marker in markers:
        owner = None
        for unit in units:
            if unit["lineno"] <= marker["line"] <= unit["end_lineno"]:
                if owner is None or unit["lineno"] > owner["lineno"]:
                    owner = unit
        tagged.append({**marker, "qualname": owner["qualname"] if owner else None})
    return tagged


def todo_density(markers: int | None, sloc: int | None) -> float | None:
    """Markers per 100 SLOC, or None when either input was not measured.

    A 0-SLOC file (a stub, or a module of nothing but comments) has NO density
    rather than a division by zero or a fabricated 0.0.
    """
    if markers is None or not sloc:
        return None
    return round(markers * 100.0 / sloc, 2)


# ---- per-file report --------------------------------------------------------


def file_report(
    text: str, *, path: str, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One Python file -> measurements + diagnostics. Pure; never raises.

    A SyntaxError produces `counts: None` and an `error`, so an unparsed file is
    visibly unmeasured instead of contributing a clean row of zeros.
    """
    cfg = config or default_config()
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as e:
        detail = f"{type(e).__name__}: {e}"
        return _unmeasured(path, detail, "quality:file-unparsed", cfg)
    units = function_units(tree, cfg["weights"])
    mod_score, mod_decisions = module_complexity(tree, cfg["weights"])
    imports = unused_imports(tree, lines)
    source = source_metrics(text)
    markers = attribute_markers(source["markers"] or [], units)
    scores = [u["complexity"] for u in units]
    counts = {
        "sloc": source["sloc"],
        "comment_lines": source["comment_lines"],
        "blank_lines": source["blank_lines"],
        "total_lines": source["total_lines"],
        "functions": len(units),
        "statements": sum(u["statements"] for u in units),
        "complexity_total": sum(scores),
        "complexity_max": max(scores) if scores else None,
        "complexity_mean": round(sum(scores) / len(scores), 2) if scores else None,
        "module_complexity": mod_score,
        "todo_markers": len(markers) if source["error"] is None else None,
        "todo_density": todo_density(
            len(markers) if source["error"] is None else None, source["sloc"]
        ),
        "markers_in_strings": source["markers_in_strings"],
        "unused_imports": len(imports["unused"]),
        "import_bindings": imports["bindings"],
    }
    report = {
        "path": path,
        "error": None,
        "counts": counts,
        "units": units,
        "module_decisions": mod_decisions,
        "unused": imports["unused"],
        "stars": imports["stars"],
        "markers": markers,
        "unmeasured": [],
    }
    if source["error"] is not None:
        report["unmeasured"].append(
            f"SLOC and marker density not measured: tokenize failed ({source['error']})"
        )
    report["diagnostics"] = _audit_file(report, cfg)
    return report


def _unmeasured(
    path: str, error: str, rule: str, cfg: dict[str, Any]
) -> dict[str, Any]:
    """A file that was not measured, shaped like one that was — minus the numbers."""
    settings = cfg["rules"].get(rule) or {}
    diags = []
    if settings.get("enabled", True):
        diags.append(
            openswap.diagnostic(
                path=path,
                line=0,
                col=1,
                rule=rule,
                severity=settings.get("severity", "error"),
                message=f"not measured, so nothing about it is known: {error}",
                suggestion="fix the file or exclude it from the scan; it is NOT counted as clean",
            )
        )
    return {
        "path": path,
        "error": error,
        "counts": None,
        "units": [],
        "module_decisions": {},
        "unused": [],
        "stars": [],
        "markers": [],
        "unmeasured": [f"file not measured: {error}"],
        "diagnostics": diags,
    }


def unreadable_report(
    path: str, error: str, *, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A file that could not be READ is not a file that passed."""
    return _unmeasured(
        path, error, "quality:file-unreadable", config or default_config()
    )


def _audit_file(report: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Measurements -> family diagnostics. Thresholds come from `cfg`."""
    diags: list[dict[str, Any]] = []
    path = report["path"]
    thresholds = cfg["thresholds"]

    def add(
        rule: str,
        message: str,
        *,
        line: int,
        col: int = 1,
        suggestion: str | None = None,
    ) -> None:
        settings = cfg["rules"].get(rule) or {}
        if not settings.get("enabled", True):
            return
        diags.append(
            openswap.diagnostic(
                path=path,
                line=line,
                col=col,
                rule=rule,
                severity=settings.get("severity", "warning"),
                message=message,
                suggestion=suggestion,
            )
        )

    for unit in report["units"]:
        _audit_unit(unit, thresholds, add)
    counts = report["counts"]
    if counts["module_complexity"] >= thresholds["complexity_warn"]:
        add(
            "quality:module-complexity",
            f"module-level code has complexity {counts['module_complexity']}"
            f" (>= {thresholds['complexity_warn']}), and it runs on import",
            line=1,
            suggestion="move import-time branching into a function that can be called and tested",
        )
    init = Path(path).name == "__init__.py"
    rule = "quality:import-unused-init" if init else "quality:import-unused"
    for binding in report["unused"]:
        extra = (
            " (a package __init__ may be re-exporting it; add __all__ to say so)"
            if init
            else ""
        )
        add(
            rule,
            f"`{binding['statement']}` binds {binding['name']!r}, which this module"
            f" never references{extra}",
            line=binding["line"],
            col=binding["col"],
            suggestion="delete it, or mark the re-export with __all__ / # noqa: F401",
        )
    for binding in report["stars"]:
        add(
            "quality:import-star",
            f"`{binding['statement']}` binds an unknowable set of names, so this"
            " module's namespace is only partly analyzable here",
            line=binding["line"],
            col=binding["col"],
            suggestion="import the names you use explicitly",
        )
    density = counts["todo_density"]
    if density is not None and density > thresholds["todo_density"]:
        add(
            "quality:todo-density",
            f"{counts['todo_markers']} {'/'.join(MARKERS)} marker(s) over"
            f" {counts['sloc']} SLOC is {density} per 100 SLOC, above"
            f" {thresholds['todo_density']}",
            line=(report["markers"][0]["line"] if report["markers"] else 1),
            suggestion="run `scout todos --path <this file>` for the individual markers",
        )
    for note in report["unmeasured"]:
        add("quality:tokenize-failed", note, line=0)
    return openswap.sort_diagnostics(diags)


def _audit_unit(unit: dict[str, Any], thresholds: dict[str, Any], add: Any) -> None:
    """The four per-function size/shape rules for ONE unit."""
    where = unit["qualname"]
    breakdown = (
        ", ".join(f"{k}={v}" for k, v in unit["decisions"].items()) or "no branches"
    )
    if unit["complexity"] >= thresholds["complexity_error"]:
        add(
            "quality:complexity-error",
            f"{where}() has cyclomatic complexity {unit['complexity']}"
            f" (>= {thresholds['complexity_error']}); decisions: {breakdown}",
            line=unit["lineno"],
            col=unit["col"],
            suggestion="split it: every branch needs its own test to be covered",
        )
    elif unit["complexity"] >= thresholds["complexity_warn"]:
        add(
            "quality:complexity-warn",
            f"{where}() has cyclomatic complexity {unit['complexity']}"
            f" (>= {thresholds['complexity_warn']}); decisions: {breakdown}",
            line=unit["lineno"],
            col=unit["col"],
        )
    if unit["lines"] > thresholds["function_lines"]:
        add(
            "quality:function-long",
            f"{where}() spans {unit['lines']} lines (> {thresholds['function_lines']})",
            line=unit["lineno"],
            col=unit["col"],
        )
    if unit["statements"] > thresholds["function_statements"]:
        add(
            "quality:function-statements",
            f"{where}() has {unit['statements']} statements"
            f" (> {thresholds['function_statements']})",
            line=unit["lineno"],
            col=unit["col"],
        )
    if unit["max_depth"] > thresholds["max_depth"]:
        add(
            "quality:function-deep",
            f"{where}() nests {unit['max_depth']} levels deep"
            f" (> {thresholds['max_depth']})",
            line=unit["lineno"],
            col=unit["col"],
            suggestion="invert a guard or extract the inner block",
        )
    if unit["params"] > thresholds["params"]:
        add(
            "quality:function-params",
            f"{where}() declares {unit['params']} parameters (> {thresholds['params']})",
            line=unit["lineno"],
            col=unit["col"],
        )


# ---- run aggregate ----------------------------------------------------------

_TOTAL_KEYS = (
    "sloc",
    "functions",
    "statements",
    "complexity_total",
    "todo_markers",
    "unused_imports",
    "import_bindings",
)


def scan_report(reports: list[dict[str, Any]], *, top: int = 10) -> dict[str, Any]:
    """Totals over files. Unmeasured files are counted as unmeasured, not zeros."""
    totals = dict.fromkeys(_TOTAL_KEYS, 0)
    measured = 0
    failed: list[dict[str, Any]] = []
    scores: list[int] = []
    units: list[dict[str, Any]] = []
    diags: list[dict[str, Any]] = []
    partial: list[str] = []
    for report in reports:
        diags.extend(report["diagnostics"])
        if report["counts"] is None:
            failed.append({"path": report["path"], "error": report["error"]})
            continue
        measured += 1
        for key in _TOTAL_KEYS:
            value = report["counts"].get(key)
            if value is None:
                partial.append(f"{report['path']}: {key} not measured")
                continue
            totals[key] += int(value)
        for unit in report["units"]:
            scores.append(unit["complexity"])
            units.append({**unit, "path": report["path"]})
    hottest = sorted(units, key=lambda u: (-u["complexity"], u["path"], u["qualname"]))[
        :top
    ]
    return {
        "files": len(reports),
        "files_measured": measured,
        "files_failed": len(failed),
        "totals": totals,
        "complexity_max": max(scores) if scores else None,
        "complexity_mean": round(sum(scores) / len(scores), 2) if scores else None,
        "todo_density": todo_density(totals["todo_markers"], totals["sloc"]),
        "hottest": hottest,
        "unmeasured": failed,
        "partial": sorted(set(partial)),
        "findings": len(diags),
        "summary": openswap.summarize(diags),
    }


# ---- the history store ------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    label TEXT,
    root TEXT NOT NULL,
    weights_fp TEXT NOT NULL,
    files INTEGER NOT NULL,
    files_measured INTEGER NOT NULL,
    files_failed INTEGER NOT NULL,
    functions INTEGER NOT NULL,
    sloc INTEGER NOT NULL,
    complexity_total INTEGER NOT NULL,
    complexity_max INTEGER,
    complexity_mean REAL,
    todo_markers INTEGER NOT NULL,
    todo_density REAL,
    unused_imports INTEGER NOT NULL,
    findings INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS units(
    run_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    qualname TEXT NOT NULL,
    lineno INTEGER NOT NULL,
    complexity INTEGER NOT NULL,
    lines INTEGER NOT NULL,
    statements INTEGER NOT NULL,
    max_depth INTEGER NOT NULL,
    params INTEGER NOT NULL,
    PRIMARY KEY(run_id, path, qualname)
);
CREATE TABLE IF NOT EXISTS file_rows(
    run_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    sloc INTEGER,
    functions INTEGER,
    complexity_total INTEGER,
    module_complexity INTEGER,
    todo_markers INTEGER,
    unused_imports INTEGER,
    error TEXT,
    PRIMARY KEY(run_id, path)
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the trend store — this plugin's OWN sqlite file.

    Deliberately not shared with reviewgraph's graph db: that store is a symbol
    graph rebuilt incrementally from the current tree, while this one is an
    append-only series of past runs. Mixing them would make "the last run" and
    "the current tree" the same row and destroy the trend.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def record_run(
    conn: sqlite3.Connection,
    *,
    scan: dict[str, Any],
    reports: list[dict[str, Any]],
    root: str,
    ts: float,
    weights: dict[str, Any],
    label: str | None = None,
) -> int:
    """Append one run and its per-unit/per-file rows; returns the run id.

    The value-XOR-error rule is re-checked HERE, at the storage boundary, not
    only where the report was built: a row that claims both metrics and an error
    (or neither) is refused, because a trend built on such a row would average a
    file that was never measured into the health of one that was.
    """
    for report in reports:
        if (report["counts"] is None) == (report.get("error") is None):
            raise ValueError(
                f"{report['path']}: a file row must carry exactly one of counts/error"
            )
    totals = scan["totals"]
    cur = conn.execute(
        "INSERT INTO runs(ts, label, root, weights_fp, files, files_measured, files_failed,"
        " functions, sloc, complexity_total, complexity_max, complexity_mean, todo_markers,"
        " todo_density, unused_imports, findings)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            float(ts),
            label,
            root,
            weights_fingerprint(weights),
            scan["files"],
            scan["files_measured"],
            scan["files_failed"],
            totals["functions"],
            totals["sloc"],
            totals["complexity_total"],
            scan["complexity_max"],
            scan["complexity_mean"],
            totals["todo_markers"],
            scan["todo_density"],
            totals["unused_imports"],
            scan["findings"],
        ),
    )
    run_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT OR REPLACE INTO units(run_id, path, qualname, lineno, complexity, lines,"
        " statements, max_depth, params) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                report["path"],
                unit["qualname"],
                unit["lineno"],
                unit["complexity"],
                unit["lines"],
                unit["statements"],
                unit["max_depth"],
                unit["params"],
            )
            for report in reports
            for unit in report["units"]
        ],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO file_rows(run_id, path, sloc, functions, complexity_total,"
        " module_complexity, todo_markers, unused_imports, error) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                report["path"],
                (report["counts"] or {}).get("sloc"),
                (report["counts"] or {}).get("functions"),
                (report["counts"] or {}).get("complexity_total"),
                (report["counts"] or {}).get("module_complexity"),
                (report["counts"] or {}).get("todo_markers"),
                (report["counts"] or {}).get("unused_imports"),
                report.get("error"),
            )
            for report in reports
        ],
    )
    conn.commit()
    return run_id


def list_runs(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    """Recorded runs, newest first."""
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()
    return [dict(row) for row in rows]


def trend(conn: sqlite3.Connection, metric: str, *, limit: int = 20) -> dict[str, Any]:
    """One metric across runs, OLDEST first, so the series reads left to right.

    A run whose value is NULL keeps its place in the series with value None: a
    scan that measured nothing must not be silently dropped, or the line would
    imply continuity that the data does not have.
    """
    if metric not in TREND_METRICS:
        raise ValueError(
            f"unknown metric {metric!r}; expected one of {', '.join(TREND_METRICS)}"
        )
    # The metric name is picked from the row in Python rather than interpolated
    # into the SQL: every name in TREND_METRICS is a literal column, but building
    # a query by concatenation is a habit worth not having.
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()
    series = [
        {
            "id": row["id"],
            "ts": row["ts"],
            "label": row["label"],
            "weights_fp": row["weights_fp"],
            "value": row[metric],
        }
        for row in reversed(rows)
    ]
    values = [r["value"] for r in series if r["value"] is not None]
    fps = {r["weights_fp"] for r in series}
    return {
        "metric": metric,
        "points": len(series),
        "series": series,
        "first": values[0] if values else None,
        "last": values[-1] if values else None,
        "delta": (values[-1] - values[0]) if len(values) > 1 else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "missing": sum(1 for r in series if r["value"] is None),
        "comparable": len(fps) <= 1,
        "note": None
        if len(fps) <= 1
        else f"{len(fps)} different weight tables across this window, so the shape"
        " of the line is not purely a change in the code",
    }


def _units_of(
    conn: sqlite3.Connection, run_id: int
) -> dict[tuple[str, str], dict[str, Any]]:
    rows = conn.execute(
        "SELECT path, qualname, lineno, complexity, lines, statements, max_depth, params"
        " FROM units WHERE run_id = ?",
        (int(run_id),),
    ).fetchall()
    return {(r["path"], r["qualname"]): dict(r) for r in rows}


def _run_row(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (int(run_id),)).fetchone()
    return dict(row) if row else None


def compare_runs(
    conn: sqlite3.Connection, base_id: int, head_id: int
) -> dict[str, Any]:
    """Per-unit deltas between two runs, and whether they may be compared at all.

    `comparable` is False when the two runs were measured under different weight
    tables, and then `regressions` is EMPTY rather than plausible-looking: after
    a retune every score moves, and calling that a regression in the code would
    be a fabricated finding. The caller is expected to treat "cannot determine"
    as a gate failure, not as a pass.
    """
    base_run = _run_row(conn, base_id)
    head_run = _run_row(conn, head_id)
    missing = [
        str(rid)
        for rid, row in ((base_id, base_run), (head_id, head_run))
        if row is None
    ]
    if missing:
        raise ValueError(f"no such run id(s): {', '.join(missing)}")
    comparable = base_run["weights_fp"] == head_run["weights_fp"]
    base_units = _units_of(conn, base_id)
    head_units = _units_of(conn, head_id)
    added = sorted(set(head_units) - set(base_units))
    removed = sorted(set(base_units) - set(head_units))
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    if comparable:
        for key in sorted(set(base_units) & set(head_units)):
            before = base_units[key]["complexity"]
            after = head_units[key]["complexity"]
            if after == before:
                continue
            row = {
                "path": key[0],
                "qualname": key[1],
                "lineno": head_units[key]["lineno"],
                "base": before,
                "head": after,
                "delta": after - before,
            }
            (regressions if after > before else improvements).append(row)
        regressions.sort(key=lambda r: (-r["delta"], r["path"], r["qualname"]))
        improvements.sort(key=lambda r: (r["delta"], r["path"], r["qualname"]))
    totals = {
        metric: {
            "base": base_run[metric],
            "head": head_run[metric],
            "delta": None
            if base_run[metric] is None or head_run[metric] is None
            else round(head_run[metric] - base_run[metric], 2),
        }
        for metric in TREND_METRICS
    }
    return {
        "base": {
            "id": base_run["id"],
            "ts": base_run["ts"],
            "label": base_run["label"],
        },
        "head": {
            "id": head_run["id"],
            "ts": head_run["ts"],
            "label": head_run["label"],
        },
        "comparable": comparable,
        "note": None
        if comparable
        else f"runs used different weight tables ({base_run['weights_fp']} vs"
        f" {head_run['weights_fp']}), so no per-unit delta here is attributable to"
        " the code; re-scan both trees under one table before gating on this",
        "regressions": regressions,
        "improvements": improvements,
        "added": [
            {"path": p, "qualname": q, "complexity": head_units[(p, q)]["complexity"]}
            for p, q in added
        ],
        "removed": [
            {"path": p, "qualname": q, "complexity": base_units[(p, q)]["complexity"]}
            for p, q in removed
        ],
        "totals": totals,
    }
