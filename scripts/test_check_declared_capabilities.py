#!/usr/bin/env python3
"""Tests for the declared-capability ratchet.

The checker exists to catch a manifest that names directories a plugin may write while no
code consults the list. If the checker itself stops detecting, it becomes an instance of
exactly that — a verdict nobody can rely on. These pin the parts that would fail silently:
the two vacuity guards, the baseline contract, and that the audit actually reaches plugins.

    python scripts/test_check_declared_capabilities.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "check_declared_capabilities", _HERE / "check_declared_capabilities.py"
)
cdc = importlib.util.module_from_spec(_SPEC)
sys.modules["check_declared_capabilities"] = cdc
_SPEC.loader.exec_module(cdc)

BASELINE = _HERE / "declared_capabilities_baseline.json"
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    tail = f"  — {detail}" if detail and not cond else ""
    print(f"{'PASS' if cond else 'FAIL'}  {name}{tail}")


def _run(*args):
    return subprocess.run(
        [sys.executable, str(_HERE / "check_declared_capabilities.py"), *args],
        capture_output=True, text=True,
    )


# --- manifest parsing -------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    mf = Path(d) / "manifest.yaml"
    mf.write_text("capabilities:\n  filesystem:\n    paths: ['~/a/', '~/b/']\n",
                  encoding="utf-8")
    check("declared_paths reads capabilities.filesystem.paths",
          cdc.declared_paths(mf) == ["~/a/", "~/b/"])

    mf.write_text("capabilities:\n  network:\n    allowed_domains: []\n", encoding="utf-8")
    check("a manifest with no filesystem block declares nothing",
          cdc.declared_paths(mf) is None)

    # An EMPTY list is not a restriction. Treating it as one would baseline plugins that
    # never claimed anything, inflating the known-debt list with noise.
    mf.write_text("capabilities:\n  filesystem:\n    paths: []\n", encoding="utf-8")
    check("an empty paths list is not a declaration", cdc.declared_paths(mf) is None)

    mf.write_text("this: [is: not: valid: yaml\n", encoding="utf-8")
    check("unparseable manifest returns None rather than raising",
          cdc.declared_paths(mf) is None)

# --- guard detection --------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    plug = Path(d) / "plug"
    (plug / "sub").mkdir(parents=True)
    (plug / "cli.py").write_text("x = 1\n", encoding="utf-8")
    check("a plugin with no guard is reported unenforced", not cdc.enforces(plug))

    # Nested, because several plugins keep the call in a helper rather than cli.py.
    (plug / "sub" / "store.py").write_text(
        "from bigbang.core.policy import enforce_or_raise\n", encoding="utf-8")
    check("the guard is found in a NESTED module, not just cli.py", cdc.enforces(plug))

# --- the real tree ----------------------------------------------------------
rows = cdc.audit()
check("audit() reaches the real plugin tree", len(rows) > 30, f"got {len(rows)}")
check("audit() finds plugins that DO enforce", any(r["enforced"] for r in rows))
check("audit() finds plugins that do NOT enforce", any(not r["enforced"] for r in rows))
check("every row carries the paths it declared",
      all(r["declared"] for r in rows))

# --- baseline contract ------------------------------------------------------
data = json.loads(BASELINE.read_text(encoding="utf-8"))
accepted = data["accepted"]
check("baseline covers every currently-unenforced plugin",
      {r["plugin"] for r in rows if not r["enforced"]} <= {e["plugin"] for e in accepted})
check("every baseline entry carries a NON-EMPTY judgement",
      all(e.get("judgment", "").strip() for e in accepted),
      "an empty judgement means nobody actually read it")

r = _run("--check", "--baseline", str(BASELINE))
check("--check exits 0 when every gap is baselined", r.returncode == 0, r.stdout[-200:])

r = _run("--check", "--baseline", str(_HERE / "does-not-exist.json"))
check("a missing baseline is an ERROR, not an empty one", r.returncode == 1,
      "treating it as empty would make the ratchet pass by finding nothing")

r = _run("--check")
check("--check without --baseline is rejected", r.returncode == 2)

# Drop one entry and the ratchet must name the plugin it no longer covers.
with tempfile.TemporaryDirectory() as d:
    trimmed = Path(d) / "b.json"
    victim = accepted[0]["plugin"]
    trimmed.write_text(json.dumps(
        {"accepted": [e for e in accepted if e["plugin"] != victim]}), encoding="utf-8")
    r = _run("--check", "--baseline", str(trimmed))
    check("an unbaselined gap fails the ratchet", r.returncode == 1)
    check("the failure names the offending plugin", victim in r.stdout, r.stdout[-200:])

# A baseline listing a plugin that now enforces should be reported prunable, but must NOT
# fail — a fix is good news, and failing on it would teach people to stop fixing things.
with tempfile.TemporaryDirectory() as d:
    padded = Path(d) / "b.json"
    padded.write_text(json.dumps(
        {"accepted": [*accepted, {"plugin": "zzz-not-a-plugin", "declared": ["~/x"],
                                  "judgment": "fixture"}]}), encoding="utf-8")
    r = _run("--check", "--baseline", str(padded))
    check("a stale baseline entry is reported, not failed", r.returncode == 0)
    check("the stale entry is named so it can be pruned", "zzz-not-a-plugin" in r.stdout)

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
