#!/usr/bin/env python3
"""Tests for GOAT's D2 dimension, which was wrong in both directions.

D2 scores dead code. Until 2026-08-02 it used two greps over raw source text, and the
audit it produces is what decides which plugin gets worked on next — so a wrong D2 does
not just misreport, it misdirects. `todos` was the LOWEST-scored plugin in the repo (5.33)
partly because all four of its "commented-out code lines" were English:

    # if target is inside default root, no confirm
    # if single file, narrow filter to that file name

and because its Typer entry point `_todos_root` was counted as an unreferenced helper.

The other direction is worse, because it is silent. `src.count(name) <= 1` is a SUBSTRING
count, so a dead `_httpx_client` looked used every time `_httpx_client_fallback` was
mentioned, and dead `_load`/`_save` shims in auth looked used on every `_load_auth` call.
Three genuinely dead functions were hidden that way and are deleted in the same commit.

    python apps/scout-cli/scripts/test_goat_audit.py
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("goat_audit", _HERE / "goat_audit.py")
goat = importlib.util.module_from_spec(_SPEC)
sys.modules["goat_audit"] = goat
_SPEC.loader.exec_module(goat)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    tail = f"  - {detail}" if detail and not cond else ""
    print(f"{'PASS' if cond else 'FAIL'}  {name}{tail}")


# --- prose must not be counted as code ---------------------------------------------

PROSE = [
    "        # if target is inside default root, no confirm",
    "                # if single file, narrow filter to that file name",
    "            # if it looks like a path containing slash or backslash",
    "                    # if scanning outside root, relative to scan_root or absolute",
    "    # for the record, this is prose",
    "# return early was considered and rejected",
    "# while this is true, it is not code",
    "# TODO",
]
for line in PROSE:
    check(f"prose not counted: {line.strip()[:52]}", not goat._is_commented_code(line))

# --- real commented-out code must still be counted ---------------------------------

CODE = [
    "    # return True",
    "    # import os",
    "    # if x:",
    "    # for i in range(3):",
    "    # def helper(a, b):",
    "        # while running:",
    "    # client = httpx.Client()",
]
for line in CODE:
    check(f"code still counted: {line.strip()[:52]}", goat._is_commented_code(line))


# --- dead-helper detection ----------------------------------------------------------

SRC = '''
@app.callback(invoke_without_command=True)
def _todos_root(ctx):
    """Entry point. Typer holds the reference; the name appears once in the file."""
    return _scan(ctx)

def _scan(ctx):
    return _scan_markers(ctx)

def _scan_markers(ctx):
    return 1

def _genuinely_dead(x):
    return x

def _named_only_in_a_docstring(x):
    return x

def user_facing(x):
    """Mentions _named_only_in_a_docstring but never calls it."""
    return x
'''
dead = goat._dead_helpers(ast.parse(SRC))

check("a decorator-registered entry point is not dead", "_todos_root" not in dead, str(dead))
check("a helper called by the entry point is not dead", "_scan" not in dead, str(dead))
check("a helper whose name CONTAINS another is not dead", "_scan_markers" not in dead, str(dead))
check("a genuinely unused helper IS dead", "_genuinely_dead" in dead, str(dead))
check(
    "a name mentioned only in a docstring does not count as a use",
    "_named_only_in_a_docstring" in dead,
    str(dead),
)
check(
    "public (non-underscore) functions are out of scope",
    "user_facing" not in dead,
    str(dead),
)

# The old rule, run on the same source, to pin WHY this changed rather than assert it.
old = [
    n.name
    for n in ast.parse(SRC).body
    if isinstance(n, ast.FunctionDef) and n.name.startswith("_") and SRC.count(n.name) <= 1
]
check(
    "the old substring rule really did flag the entry point",
    "_todos_root" in old,
    f"old={old} — if this stops being true the docstring above is stale",
)
check(
    "the old substring rule really did miss the docstring-only helper",
    "_named_only_in_a_docstring" not in old,
    f"old={old}",
)

# --- the audit still runs end to end ------------------------------------------------

report = goat.audit_plugin(_HERE.parent / "bigbang" / "plugins" / "todos")
check("audit_plugin returns a scored report", isinstance(report, dict) and "mean" in report,
      str(report)[:200])
check(
    "todos no longer loses points to prose comments",
    not any("commented-out" in f for f in report.get("findings", [])),
    str(report.get("findings")),
)

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
