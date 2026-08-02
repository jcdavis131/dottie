#!/usr/bin/env python3
"""Tests for the store-symmetry audit.

The audit currently reports 0 across the repo. A detector that reports 0 is
indistinguishable from a detector that is broken, so almost everything here is about
proving it can still fire — on the real bug, and on variations of it — and that it stays
quiet on the guard-clause pattern that looks similar and is fine.

    python scripts/test_store_symmetry_audit.py
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "store_symmetry_audit", _HERE / "store_symmetry_audit.py"
)
ssa = importlib.util.module_from_spec(_SPEC)
sys.modules["store_symmetry_audit"] = ssa
_SPEC.loader.exec_module(ssa)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    tail = f"  - {detail}" if detail and not cond else ""
    print(f"{'PASS' if cond else 'FAIL'}  {name}{tail}")


def _run(*args):
    return subprocess.run(
        [sys.executable, str(_HERE / "store_symmetry_audit.py"), *args],
        capture_output=True,
        text=True,
    )


def scan(src: str):
    return ssa.scan_tree(ast.parse(src))


# --- the bug it was written for -------------------------------------------------------

hits = scan(ssa.KNOWN_BUG_FIXTURE)
check("flags the real pre-fix delete_secret", len(hits) == 1, str(hits))
check(
    "names both stores, in order",
    hits and hits[0]["before_return"] == ["_save"] and hits[0]["after_return"] == ["keyring"],
    str(hits),
)
check("self_test() agrees", ssa.self_test() is True)

# The fixture must be the real thing, not a paraphrase that happens to trip the detector.
check(
    "fixture is the real function, not a mock-up",
    'keyring.delete_password("bigbang-cli", key)' in ssa.KNOWN_BUG_FIXTURE
    and "_save(data)" in ssa.KNOWN_BUG_FIXTURE,
)

# The docstring calls the fixture verbatim from a2ccea5^. Checked rather than trusted:
# a fixture edited to keep the detector happy would turn this whole file into theatre.
#
# Missing git history FAILS here rather than skipping. That is the same call this repo
# already made for scripts/test_retrieval_eval.py (ci.yml sets fetch-depth: 0 for it) --
# a test that passes by checking nothing when the environment is thin is the vacuous-green
# shape these scripts exist to prevent.
_git = subprocess.run(
    ["git", "show", "a2ccea5^:apps/scout-cli/bigbang/core/security.py"],
    capture_output=True, text=True, cwd=str(_HERE.parent),
)
if _git.returncode != 0:
    check("git history is available to verify the fixture", False,
          "needs full history: git fetch --unshallow")
else:
    _real = next(
        n for n in ast.walk(ast.parse(_git.stdout))
        if isinstance(n, ast.FunctionDef) and n.name == "delete_secret"
    )
    check(
        "fixture is verbatim from a2ccea5^",
        ast.get_source_segment(_git.stdout, _real).strip()
        == ssa.KNOWN_BUG_FIXTURE.strip(),
    )

# --- the fixed version must be clean --------------------------------------------------

FIXED = '''
def delete_secret(key: str) -> bool:
    removed_keyring = False
    if _keyring_has(key):
        _keyring().delete_password(KEYRING_SERVICE, key)
        removed_keyring = True
    data = _load()
    removed_file = key in data
    if removed_file:
        del data[key]
        _save(data)
    return removed_keyring or removed_file
'''
check("the shipped fix is NOT flagged", scan(FIXED) == [], str(scan(FIXED)))

# --- must stay quiet on things that merely resemble it --------------------------------

GUARD_CLAUSE = '''
def save_thing(x):
    if x is None:
        return False
    _save(x)
    return True
'''
check(
    "a plain guard clause is not flagged",
    scan(GUARD_CLAUSE) == [],
    "an early return with no store before it is the normal pattern",
)

READ_ONLY = '''
def get_thing(key):
    data = _load()
    if key in data:
        _save(data)
        return data[key]
    import keyring
    return keyring.get_password("s", key)
'''
check(
    "read functions are out of scope",
    scan(READ_ONLY) == [],
    "only mutations can leave a store stale",
)

SINGLE_STORE = '''
def delete_thing(key):
    data = _load()
    if key in data:
        del data[key]
        return True
    return False
'''
check("one store with an early return is not flagged", scan(SINGLE_STORE) == [])

# --- variations that MUST still fire --------------------------------------------------

ASYNC_VARIANT = '''
async def delete_token(key):
    if key in _cache:
        _save(_cache)
        return True
    import keyring
    keyring.delete_password("s", key)
'''
check("async mutations are scanned too", len(scan(ASYNC_VARIANT)) == 1, str(scan(ASYNC_VARIANT)))

ELIF_VARIANT = '''
def purge_credential(key):
    if key in _vault_cache:
        _flush(key)
        return True
    _persist(key)
    return False
'''
check("helper-named stores fire", len(scan(ELIF_VARIANT)) == 1, str(scan(ELIF_VARIANT)))

# --- CLI contract ---------------------------------------------------------------------

r = _run("--path", str(_HERE))
check("default mode exits 0 even with findings", r.returncode == 0, r.stdout[-200:])
check("reports the scan size", "scanned" in r.stdout, r.stdout[-200:])

r = _run("--check", "--path", str(_HERE))
check("--check runs the self-test first", "self-test PASS" in r.stdout, r.stdout[-300:])

r = _run("--json", "--path", str(_HERE))
check("--json emits parseable output", r.stdout.strip().startswith("{"), r.stdout[:120])

# --check must actually fail on a hit, or it is decoration.
with tempfile.TemporaryDirectory() as d:
    bad = Path(d) / "bad.py"
    bad.write_text(ssa.KNOWN_BUG_FIXTURE, encoding="utf-8")
    r = _run("--check", "--path", d)
    check("--check exits 1 on a real hit", r.returncode == 1, f"rc={r.returncode}")
    check("the failure names the function", "delete_secret" in r.stdout, r.stdout[-300:])

# And must pass on a tree with none.
with tempfile.TemporaryDirectory() as d:
    (Path(d) / "ok.py").write_text(FIXED, encoding="utf-8")
    r = _run("--check", "--path", d)
    check("--check exits 0 on a clean tree", r.returncode == 0, r.stdout[-300:])

# --- the repo itself ------------------------------------------------------------------

r = _run("--check")
check(
    "the repo is currently clean",
    r.returncode == 0,
    f"rc={r.returncode} -- a NEW hit is the point of this file; read it, do not silence it",
)

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
