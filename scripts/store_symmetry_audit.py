#!/usr/bin/env python3
"""Find mutations that clear one store and leave another one holding the value.

THE DEFECT, found 2026-08-02 in bigbang/core/security.py and fixed in a2ccea5.

The vault keeps TWO stores. `get_secret` read keyring FIRST, then env, then the file.
`delete_secret` read the FILE first and touched keyring only when the file MISSED --
the exact inverse -- so:

    keyring + file   delete_secret -> True   and get_secret() STILL returned the value
                     `secrets rm` and `auth logout` reported success, list_secrets()
                     agreed the key was gone, and the credential stayed readable.

The shape in source, which is what this detects:

    def delete_secret(key):
        data = _load()
        if key in data:
            del data[key]
            _save(data)          <- store A
            return True          <- EARLY RETURN
        try:
            import keyring
            keyring.delete_password(...)   <- store B, now unreachable in the case
        except Exception:                     where A had the key
            pass
        return False

A mutating function touches store A, returns, and touches store B afterwards. B is
therefore reached only when A missed. If the caller's READ path consults both, the
mutation is a partial one wearing the name of a complete one.

WHY THIS IS NOT JUST "grep for two stores". The bug is not that keyring is absent from
`delete_secret` -- it is right there, which is exactly why it survived review and why an
earlier version of this sweep (which looked for a store the writers never mention) found
nothing. The defect is ORDERING. So the detector keys on statement order around a
returning branch, parsed with `ast`, never regex: this repo's comments quote the code
they discuss, and a grep counting prose as code has already produced three wrong answers
in one day.

WHAT IT WILL NOT CATCH, stated so the 0 is read correctly:
  - stores reached through a helper, one call deeper than the flagged function
  - `sys.exit` / raise instead of `return` as the early exit
  - the read path's own ordering; this looks only at mutations
A clean run means this SHAPE is absent, not that every store is symmetric.

NON-VACUITY. A sweep that cannot fail is worth nothing, which is this repo's most
repeated lesson. `--check` therefore runs a self-test FIRST against an embedded copy of
the real pre-fix `delete_secret`, and exits non-zero if the detector no longer flags it.
A refactor that quietly blinds the detector fails the build instead of turning it green.

Usage:
    python scripts/store_symmetry_audit.py                  # human report
    python scripts/store_symmetry_audit.py --json
    python scripts/store_symmetry_audit.py --path apps/scout-cli
    python scripts/store_symmetry_audit.py --check          # self-test, then exit 1 on hits

Unlike gate_audit.py this DOES gate by default in --check mode, and does so without a
baseline. That is affordable only because the shape is rare -- 0 hits across 1293 files
at the time of writing -- so the first hit is worth a human read rather than a triage
queue. If it ever starts firing broadly, add a judged baseline the way gate_audit.py did;
do NOT add a tolerance.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# Functions that CHANGE state. A read-only function cannot leave a store stale.
MUTATING = re.compile(
    r"^_?(set|save|write|store|put|delete|remove|rm|clear|update|logout|revoke|purge)"
)

# Calls/imports that stand in for "a persistent store was touched". Deliberately broad:
# this reports candidates for a human to read, and a missed store is worse than a
# false positive that takes ten seconds to dismiss.
STORE_MARKER = re.compile(
    r"keyring|vault|secret|token|credential|registry|ledger|cache|"
    r"_save|_write|_store|_persist|_flush",
    re.I,
)

SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".git"}

# The real pre-fix delete_secret, verbatim from a2ccea5^. Embedded rather than read from
# git so the self-test still works in a shallow clone or an exported tree.
KNOWN_BUG_FIXTURE = '''
def delete_secret(key: str):
    data = _load()
    if key in data:
        del data[key]
        _save(data)
        return True
    try:
        import keyring

        keyring.delete_password("bigbang-cli", key)
    except Exception:
        pass
    return False
'''


def store_markers(node: ast.AST) -> set[str]:
    """Names in this subtree that look like a persistent store being touched."""
    found: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name and STORE_MARKER.search(name):
                found.add(name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                if STORE_MARKER.search(alias.name):
                    found.add(alias.name)
    return found


def scan_tree(tree: ast.AST) -> list[dict]:
    """Mutating functions that reach a second store only after an early return."""
    hits: list[dict] = []
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in fns:
        if not MUTATING.match(fn.name):
            continue
        # Walk the function's OWN top-level statements in order. Nesting is deliberately
        # not followed: an early return inside a nested block does not skip what comes
        # after the block at the outer level.
        after_returning_branch: set[str] | None = None
        for stmt in fn.body:
            if after_returning_branch is not None:
                later = store_markers(stmt)
                if later:
                    hits.append(
                        {
                            "function": fn.name,
                            "line": fn.lineno,
                            "before_return": sorted(after_returning_branch),
                            "after_return": sorted(later),
                        }
                    )
                    break
            if isinstance(stmt, ast.If) and any(
                isinstance(x, ast.Return) for x in ast.walk(stmt)
            ):
                marks = store_markers(stmt)
                if marks:
                    after_returning_branch = marks
    return hits


def scan_path(root: Path) -> tuple[list[dict], int]:
    hits: list[dict] = []
    scanned = 0
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue
        scanned += 1
        for hit in scan_tree(tree):
            hits.append({"file": str(path), **hit})
    return hits, scanned


def self_test() -> bool:
    """The detector must still flag the bug it was written for.

    Printed loudly either way. A silent self-test is a gate whose verdict nothing
    consumes, which is the sibling defect class this repo already tracks.
    """
    found = scan_tree(ast.parse(KNOWN_BUG_FIXTURE))
    ok = any(f["function"] == "delete_secret" for f in found)
    if ok:
        h = found[0]
        print(
            f"self-test PASS  detector flags the real pre-fix delete_secret "
            f"(before={h['before_return']} after={h['after_return']})"
        )
    else:
        print(
            "self-test FAIL  the detector no longer flags security.py's pre-fix "
            "delete_secret. A clean run below would mean nothing."
        )
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Find mutations that clear one store and leave another holding the value."
    )
    ap.add_argument(
        "--path",
        action="append",
        default=None,
        help="Root to scan (repeatable). Default: apps/ and packages/.",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--check",
        action="store_true",
        help="run the non-vacuity self-test, then exit 1 on any hit",
    )
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    roots = [Path(p) for p in args.path] if args.path else [repo / "apps", repo / "packages"]

    if args.check and not self_test():
        return 2

    all_hits: list[dict] = []
    total = 0
    for root in roots:
        if not root.exists():
            print(f"skip (missing): {root}", file=sys.stderr)
            continue
        hits, scanned = scan_path(root)
        all_hits.extend(hits)
        total += scanned

    if args.json:
        print(json.dumps({"scanned": total, "hits": all_hits}, indent=2))
    else:
        print(f"scanned {total} files under {', '.join(str(r) for r in roots)}")
        print()
        if not all_hits:
            print("0 candidates. This SHAPE is absent — see the module docstring for")
            print("what that does and does not rule out.")
        for h in all_hits:
            print(f"{h['file']}:{h['line']}  {h['function']}()")
            print(f"   store touched before the early return : {h['before_return']}")
            print(f"   store touched only after it           : {h['after_return']}")
            print("   -> reached only when the first store missed. If the matching read")
            print("      path consults both, this mutation is partial.")
            print()

    if args.check and all_hits:
        print(f"FAIL: {len(all_hits)} candidate(s). Read each; see the docstring.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
