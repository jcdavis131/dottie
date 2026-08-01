#!/usr/bin/env python3
"""Tests for the gate auditor.

The auditor exists to find "a gate whose verdict nothing consumes". If it ever
stops detecting, it becomes an instance of the very class it hunts — a check whose
verdict nobody reads. These tests pin it against the TWO REAL BUGS it was built
from, reduced to minimal fixtures, plus the false positives found on first run so
they stay classified.

    python scripts/test_gate_audit.py
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "gate_audit", Path(__file__).resolve().parent / "gate_audit.py"
)
ga = importlib.util.module_from_spec(_SPEC)
sys.modules["gate_audit"] = ga
_SPEC.loader.exec_module(ga)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    tail = f"  — {detail}" if detail and not cond else ""
    print(f"{'PASS' if cond else 'FAIL'}  {name}{tail}")


def scan(src: str):
    tree = ast.parse(src)
    lines = src.splitlines()
    return ga.find_mode_escapes(tree, lines, "f.py") + ga.find_fail_open_dispatch(
        tree, lines, "f.py"
    )


# ---------------------------------------------------------------------------
# The two real bugs, reduced. These MUST stay detected.
# ---------------------------------------------------------------------------

# Instance #3: dataset_discovery.py — the licence skip was disabled in --dry-run,
# the exact mode the daily cron uses.
BUG_MODE_ESCAPE = '''
def write_manifest(cands, args):
    for cand in cands:
        if not cand.get("license_ok", False) and not args.dry_run:
            continue
        emit(cand)
'''
hits = scan(BUG_MODE_ESCAPE)
check(
    "catches the real --dry-run licence escape (instance #3)",
    any(h["shape"] == "mode-conditional-escape" for h in hits),
    str(hits),
)

# Instance #1: check_permission fell through to `return True, "ok"` for an
# unrecognised action, so a typo'd action name wrote freely.
BUG_FAIL_OPEN = '''
def check_permission(manifest, action, resource):
    if action == "network":
        return False, "denied"
    if action == "fs_write":
        return False, "denied"
    if action == "secret":
        return False, "denied"
    return True, "ok"
'''
hits = scan(BUG_FAIL_OPEN)
check(
    "catches the real fail-open dispatch (instance #1)",
    any(h["shape"] == "fail-open-dispatch" for h in hits),
    str(hits),
)

# ---------------------------------------------------------------------------
# The fixes must NOT be flagged, or the auditor cries wolf forever.
# ---------------------------------------------------------------------------
FIXED_MODE_ESCAPE = '''
def write_manifest(cands, args):
    for cand in cands:
        if not cand.get("license_ok", False):
            continue
        emit(cand)
'''
check("fixed escape is clean", scan(FIXED_MODE_ESCAPE) == [], str(scan(FIXED_MODE_ESCAPE)))

FIXED_FAIL_OPEN = '''
KNOWN = ("network", "fs_write", "secret")
def check_permission(manifest, action, resource):
    if action not in KNOWN:
        return False, "unknown policy action"
    if action == "network":
        return False, "denied"
    if action == "fs_write":
        return False, "denied"
    if action == "secret":
        return False, "denied"
    return True, "ok"
'''
check(
    "membership guard clears the dispatch finding",
    not any(h["shape"] == "fail-open-dispatch" for h in scan(FIXED_FAIL_OPEN)),
    str(scan(FIXED_FAIL_OPEN)),
)

# ---------------------------------------------------------------------------
# Precision: things that look similar but are ordinary logic.
# ---------------------------------------------------------------------------
check(
    "a mode flag with NO safety word is not flagged",
    scan('''
def f(args):
    if verbose and not args.dry_run:
        print("x")
''') == [],
    "business logic gated on a mode is normal",
)

check(
    "a single == branch is not a dispatch",
    scan('''
def f(kind):
    if kind == "a":
        return 1
    return 2
''') == [],
)

check(
    "an else on the dispatch clears it",
    not any(h["shape"] == "fail-open-dispatch" for h in scan('''
def f(kind):
    if kind == "a":
        return 1
    if kind == "b":
        return 2
    else:
        raise ValueError(kind)
''')),
)

# ---------------------------------------------------------------------------
# Known false positives from the first real run — pinned so they stay classified
# and nobody re-investigates them from scratch.
# ---------------------------------------------------------------------------
check(
    "a formatting dispatch with a real default still trips the heuristic (KNOWN FP)",
    any(h["shape"] == "fail-open-dispatch" for h in scan('''
def _weight_for(k):
    if k == "phrase":
        return 3.0
    if k == "participial":
        return 0.5
    if k == "connector":
        return 1.2
    return 1.5
''')),
    "documents the heuristic's cost: an explicit trailing default is indistinguishable "
    "from a fall-through by shape alone",
)

# ---------------------------------------------------------------------------
# Suppressed-check detection, and the prose exclusion.
# ---------------------------------------------------------------------------
import tempfile

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "ci.yml"
    p.write_text(
        "      - name: license check\n"
        "        run: ruff check . || true\n"
        "      # a comment explaining that `|| true` on a license gate is bad\n",
        encoding="utf-8",
    )
    found = ga.find_suppressed_checks(p, "ci.yml")
    check("catches `|| true` on a check (instance #5)", len(found) == 1, str(found))
    check(
        "a COMMENT about `|| true` is not itself a finding",
        all(f["line"] != 3 for f in found),
        "grep counting prose as code has produced three wrong answers in this repo",
    )

# ---------------------------------------------------------------------------
# Baseline / --check. Added 2026-08-01 alongside the opt-in gating mode.
#
# The module docstring's "exit 0 always" is a DELIBERATE decision, so the first
# test here pins that the default did not change. The rest pin the ratchet: judged
# candidates stay quiet, NEW ones fail. If a baseline could not silence a judged
# false positive, the next move would be `|| true` on the whole step -- this tool's
# own instance #5, recreated by the tool that hunts it.
# ---------------------------------------------------------------------------
import json as _json
import subprocess as _sp
import tempfile as _tf

_GA = str(Path(__file__).resolve().parent / "gate_audit.py")


def _run(*a):
    return _sp.run([sys.executable, _GA, *a], capture_output=True, text=True)


# A subtree with a KNOWN-stable candidate (cite.py's style dispatch, judged an
# acceptable formatting helper 2026-08-01) and only ~52 files, so the subprocess
# round-trips below stay fast. Deliberately NOT packages/ava-skills: that went to
# zero candidates the moment the safety-scanner fail-open was fixed, which broke
# this fixture on first run and is now pinned as its own assertion instead.
_FIXTURE_PATH = "apps/scout-cli/bigbang/core"

_fake = {"file": "a/b.py", "shape": "fail-open-dispatch", "code": "def f(...)", "why": "w"}

check(
    "finding_key ignores line number (it drifts on unrelated edits above it)",
    ga.finding_key({**_fake, "line": 10}) == ga.finding_key({**_fake, "line": 999}),
)
check(
    "finding_key separates different shapes at the same location",
    ga.finding_key(_fake) != ga.finding_key({**_fake, "shape": "suppressed-check"}),
)
check(
    "finding_key changes when the dispatching line itself is edited",
    ga.finding_key(_fake) != ga.finding_key({**_fake, "code": "def f(x, y)"}),
    "editing the flagged line is exactly when a re-judgement is wanted",
)

_r = _run("--path", _FIXTURE_PATH)
check("default run still exits 0 with candidates present (documented contract)",
      _r.returncode == 0, _r.stdout[-200:])

with _tf.TemporaryDirectory() as _d:
    _bl = Path(_d) / "baseline.json"

    _r = _run("--path", _FIXTURE_PATH, "--write-baseline", str(_bl))
    check("--write-baseline exits 0 and writes a file", _r.returncode == 0 and _bl.exists())
    _data = _json.loads(_bl.read_text(encoding="utf-8"))
    check("baseline records the candidates", len(_data["accepted"]) > 0, str(_data)[:200])
    check("baseline carries a judgment field to fill in",
          all("judgment" in e for e in _data["accepted"]))

    _r = _run("--path", _FIXTURE_PATH, "--check", "--baseline", str(_bl))
    check("--check exits 0 when every candidate is baselined", _r.returncode == 0,
          _r.stdout[-300:])

    # Drop one entry -> that candidate is now "new" -> must fail.
    _data["accepted"] = _data["accepted"][1:]
    _bl.write_text(_json.dumps(_data), encoding="utf-8")
    _r = _run("--path", _FIXTURE_PATH, "--check", "--baseline", str(_bl))
    check("--check exits 1 on a candidate absent from the baseline", _r.returncode == 1,
          f"rc={_r.returncode} out={_r.stdout[-300:]}")
    check("the failure names the new candidate", "NEW candidate" in _r.stdout, _r.stdout[-300:])

    # A baseline entry with no live counterpart is reported, never fatal.
    _data["accepted"].append(
        {"file": "gone.py", "shape": "fail-open-dispatch", "code": "def x(...)",
         "judgment": "fixed since"}
    )
    _bl.write_text(_json.dumps(_data), encoding="utf-8")
    _r = _run("--path", _FIXTURE_PATH, "--check", "--baseline", str(_bl))
    check("a stale baseline entry is reported as prunable", "prune it" in _r.stdout,
          _r.stdout[-300:])

    _r = _run("--path", "scripts", "--check", "--baseline", str(_bl))
    check("stale entries alone do NOT fail the check (a fix is good news)",
          _r.returncode == 0, f"rc={_r.returncode} out={_r.stdout[-300:]}")

_sc_findings, _ = ga.audit(ga.ROOT / "packages/ava-skills")
check(
    "safety-scanner's fail-open is GONE from the auditor's view (fixed 2026-08-01)",
    _sc_findings == [],
    f"regression: {_sc_findings}",
)

_r = _run("--path", "scripts", "--check", "--baseline", "does/not/exist.json")
check("a missing baseline path errors instead of silently accepting nothing",
      _r.returncode != 0, f"rc={_r.returncode}")
check("--check without --baseline is rejected",
      _run("--path", "scripts", "--check").returncode != 0)


# ---------------------------------------------------------------------------
# Non-vacuity: the auditor must actually reach files.
# ---------------------------------------------------------------------------
findings, scanned = ga.audit(ga.ROOT / "apps/scout-cli")
check("audit() scans a real subtree", scanned["py"] > 100, f"scanned={scanned}")

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
