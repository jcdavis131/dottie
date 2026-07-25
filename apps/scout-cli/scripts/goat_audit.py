#!/usr/bin/env python3
# Solo personal project, no connection to employer, built with public/free-tier only.
"""GOAT audit (Carmack/Bellard rubric) — automated, per-plugin, every run.

The July-23 audit (tasks/artifacts/goat_audit_monorepo.md) was a one-shot human
read. This is the mechanizable subset, run automatically so every NEW build is
held to the same bar the family claims:

  1 Dependency economy (Bellard) — non-stdlib imports. The openswap premise is
    zero new deps, so a single third-party import is a real finding.
  2 Dead code & speculative abstraction (Carmack) — module-level defs never
    referenced in their own file; commented-out code blocks.
  3 Self-containedness — hardcoded absolute paths, Path.home()/$HOME layout
    assumptions, machine-specific scratch dirs. (This is exactly how
    toil_finder_nightly.py became unrunnable on this box.)
  4 Test honesty — does a test file exist, does it import the plugin, does it
    actually assert? A test that would pass with the feature deleted is a defect
    under this repo's anti-mock doctrine.
  5 Hot-path clarity — longest function and file LOC. Length is a proxy, not a
    verdict; it flags candidates for a human read.
  6 Honest notes — TODO/FIXME/HACK/XXX density.

Scores are heuristics and say so. The point is REGRESSION DETECTION, not a
league table: --baseline snapshots today's debt, --check fails only when a
plugin gets worse. That keeps it adoptable in CI on day one instead of being
disabled the first time it goes red on pre-existing debt.

Usage:
  python scripts/goat_audit.py                     # human report, all plugins
  python scripts/goat_audit.py --plugin sitemap    # one plugin
  python scripts/goat_audit.py --json              # machine-readable
  python scripts/goat_audit.py --baseline          # write .goat_baseline.json
  python scripts/goat_audit.py --check             # exit 1 only on regressions
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

SC = Path(__file__).resolve().parents[1]          # apps/scout-cli
PLUGINS = SC / "bigbang" / "plugins"
TESTS = SC / "tests"
BASELINE = SC / ".goat_baseline.json"

# Third-party imports are the finding; everything the stdlib ships is fine.
# sys.stdlib_module_names is 3.10+, which this repo targets (3.11).
STDLIB = set(getattr(sys, "stdlib_module_names", set()))
# first-party roots that are not third-party deps
FIRST_PARTY = {"bigbang", "dottie", "ava", "harness", "scout"}


def _declared_deps() -> set[str]:
    """Distribution names scout-cli already declares in pyproject.

    D1 must flag NEW dependencies, not the framework's existing ones — the
    openswap premise is "adds no dependency", and `import yaml` in a plugin is
    not a new dep when PyYAML is already required. Without this the check cries
    wolf on almost every plugin and gets ignored, which is how a lint dies.
    """
    names = {"yaml"}  # PyYAML imports as `yaml`; keep even if the parse fails
    try:
        import tomllib  # stdlib 3.11+
        data = tomllib.loads((SC / "pyproject.toml").read_text(encoding="utf-8"))
    except Exception:
        return names
    reqs = (data.get("project") or {}).get("dependencies") or []
    for r in reqs:
        base = re.split(r"[<>=!~\[; ]", str(r).strip(), 1)[0].strip().lower()
        if base:
            names.add(base.replace("-", "_"))
    return names

ABS_PATH_RE = re.compile(r"""['"](?:[A-Za-z]:[\\/]|/home/|/Users/|/mnt/[a-z]/)""")
HOME_RE = re.compile(r"Path\.home\(\)|os\.path\.expanduser|environ\[['\"]HOME")
NOTE_RE = re.compile(r"#.*\b(TODO|FIXME|HACK|XXX)\b")
COMMENTED_CODE_RE = re.compile(r"^\s*#\s*(?:def |class |return |import |if |for |while )")


def _clamp(v: float) -> int:
    return max(0, min(10, int(round(v))))


def _run_tests(name: str) -> tuple[bool, str]:
    """Actually EXECUTE a plugin's suite. Returns (passed, detail).

    Without this, D4 measured only the PRESENCE and density of assertions, never
    their outcome — so a plugin whose tests fail could score a perfect 10.00.
    That was a real hole: CI's pytest step ends in `|| true`, so a broken plugin
    passed on both paths. Caught on `charts` (10.00 while 1 test was red).
    Opt-in because each suite takes ~45-90s; the CI gate scopes it to --plugin.
    """
    import subprocess
    tf = TESTS / f"test_{name}.py"
    if not tf.exists():
        return False, "no test file"
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", str(tf), "-q", "--no-header"],
                           cwd=str(SC), capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001 — report, never mask
        return False, f"could not run pytest: {type(e).__name__}"
    tail = (p.stdout or "").strip().split("\n")[-1][:120]
    return p.returncode == 0, tail


def audit_plugin(name: str, run_tests: bool = False) -> dict:
    """Score one plugin on the mechanizable slice of the rubric."""
    pdir = PLUGINS / name
    cli = pdir / "cli.py"
    src = cli.read_text(encoding="utf-8", errors="replace") if cli.exists() else ""
    lines = src.split("\n")
    findings: list[str] = []

    # ---- D1 dependency economy -------------------------------------------
    third_party: list[str] = []
    tree = None
    if src:
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            findings.append(f"D1/D5: cli.py does not parse ({e.msg} line {e.lineno})")
    for node in ast.walk(tree) if tree else []:
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:      # relative import — first-party by definition
                continue
            mods = [(node.module or "").split(".")[0]]
        for m in mods:
            if m and m not in STDLIB and m not in FIRST_PARTY:
                third_party.append(m)
    third_party = sorted(set(third_party))
    declared = _declared_deps()
    undeclared = [m for m in third_party if m.lower().replace("-", "_") not in declared]
    if undeclared:
        findings.append(f"D1: UNDECLARED third-party imports {undeclared} — the openswap premise "
                        f"is that an adapter adds no dependency")
    d1 = 10 if not undeclared else max(2, 10 - 3 * len(undeclared))

    # ---- D2 dead code ----------------------------------------------------
    dead: list[str] = []
    if tree:
        defs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for d in defs:
            if d.startswith("_") and src.count(d) <= 1:
                dead.append(d)
    commented = sum(1 for ln in lines if COMMENTED_CODE_RE.match(ln))
    if dead:
        findings.append(f"D2: defined-but-unreferenced helpers {dead[:5]}")
    if commented > 3:
        findings.append(f"D2: {commented} commented-out code lines")
    d2 = _clamp(10 - 1.5 * len(dead) - 0.3 * commented)

    # ---- D3 self-containedness ------------------------------------------
    abs_hits = [i + 1 for i, ln in enumerate(lines) if ABS_PATH_RE.search(ln)]
    home_hits = [i + 1 for i, ln in enumerate(lines) if HOME_RE.search(ln)]
    if abs_hits:
        findings.append(f"D3: hardcoded absolute path at line(s) {abs_hits[:4]}")
    if home_hits:
        findings.append(f"D3: HOME-layout assumption at line(s) {home_hits[:4]} (portability)")
    d3 = _clamp(10 - 4 * len(abs_hits) - 1.5 * len(home_hits))

    # ---- D4 test honesty -------------------------------------------------
    tf = TESTS / f"test_{name}.py"
    if tf.exists():
        t = tf.read_text(encoding="utf-8", errors="replace")
        asserts = len(re.findall(r"\bassert\b", t))
        imports_plugin = name in t
        test_fns = len(re.findall(r"^def test_", t, re.M))
        empty = test_fns - len(re.findall(r"assert", t)) if test_fns > asserts else 0
        if not imports_plugin:
            findings.append(f"D4: test_{name}.py never references the plugin — may pass with it deleted")
        if asserts == 0:
            findings.append(f"D4: test_{name}.py has no assertions")
        d4 = _clamp((10 if imports_plugin else 4) - (6 if asserts == 0 else 0)
                    - (2 if test_fns and asserts / max(1, test_fns) < 1 else 0))
        tinfo = {"exists": True, "test_fns": test_fns, "asserts": asserts,
                 "references_plugin": imports_plugin}
        # Assertions that FAIL are not test honesty — they are a broken plugin.
        if run_tests:
            ok, detail = _run_tests(name)
            tinfo["suite_passed"] = ok
            tinfo["suite_detail"] = detail
            if not ok:
                findings.append(f"D4: TESTS FAIL ({detail}) — scored 0; a passing "
                                f"assertion count means nothing if the suite is red")
                d4 = 0
    else:
        findings.append(f"D4: NO test file (expected tests/test_{name}.py)")
        d4, tinfo = 0, {"exists": False, "test_fns": 0, "asserts": 0, "references_plugin": False}

    # ---- D5 hot-path clarity --------------------------------------------
    longest, longest_name = 0, ""
    for node in ast.walk(tree) if tree else []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and getattr(node, "end_lineno", None):
            span = node.end_lineno - node.lineno
            if span > longest:
                longest, longest_name = span, node.name
    loc = len([ln for ln in lines if ln.strip() and not ln.strip().startswith("#")])
    if longest > 80:
        findings.append(f"D5: {longest_name}() is {longest} lines — candidate for a human read")
    d5 = _clamp(10 - max(0, (longest - 60) / 20) - max(0, (loc - 600) / 200))

    # ---- D6 honest notes -------------------------------------------------
    notes = [i + 1 for i, ln in enumerate(lines) if NOTE_RE.search(ln)]
    if len(notes) > 3:
        findings.append(f"D6: {len(notes)} TODO/FIXME/HACK notes")
    has_doc = bool(tree and ast.get_docstring(tree))
    if not has_doc:
        findings.append("D6: cli.py has no module docstring stating what it replaces / why")
    d6 = _clamp(10 - 0.7 * len(notes) - (3 if not has_doc else 0))

    # A MISSING implementation must never read as a clean one. Absence of
    # problems is not quality: an empty/absent cli.py trivially has no bad
    # imports, no dead code and no long functions, which floated a hollow
    # `feeds` plugin to 7.83 and would have passed a --min-mean 7.0 gate.
    # Incomplete scaffolding scores 0 across the board and says why.
    if not cli.exists() or loc == 0:
        findings.insert(0, "INCOMPLETE: no cli.py implementation (scaffolding only) — "
                           "scored 0; absence of findings is not quality")
        scores = {k: 0 for k in ("d1_dependency", "d2_dead_code", "d3_self_contained",
                                 "d4_test_honesty", "d5_hot_path", "d6_honest_notes")}
        return {"plugin": name, "has_cli": cli.exists(),
                "has_manifest": (pdir / "manifest.yaml").exists(), "loc": loc,
                "scores": scores, "mean": 0.0, "incomplete": True,
                "third_party": [], "tests": tinfo, "findings": findings}

    scores = {"d1_dependency": d1, "d2_dead_code": d2, "d3_self_contained": d3,
              "d4_test_honesty": d4, "d5_hot_path": d5, "d6_honest_notes": d6}
    return {
        "plugin": name,
        "has_cli": cli.exists(),
        "has_manifest": (pdir / "manifest.yaml").exists(),
        "loc": loc,
        "scores": scores,
        "mean": round(sum(scores.values()) / len(scores), 2),
        "third_party": third_party,
        "tests": tinfo,
        "findings": findings,
    }


def discover() -> list[str]:
    if not PLUGINS.is_dir():
        return []
    return sorted(p.name for p in PLUGINS.iterdir()
                  if p.is_dir() and not p.name.startswith("__") and (p / "cli.py").exists())


def main() -> int:
    ap = argparse.ArgumentParser(description="Automated Carmack/Bellard GOAT audit of scout-cli plugins.")
    ap.add_argument("--plugin", action="append", help="audit only this plugin (repeatable)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--baseline", action="store_true", help="write the current state as the accepted baseline")
    ap.add_argument("--check", action="store_true", help="exit 1 only if a plugin REGRESSED vs the baseline")
    ap.add_argument("--run-tests", action="store_true",
                    help="EXECUTE each plugin's suite; D4 scores 0 if it fails (slow, ~45-90s each)")
    ap.add_argument("--min-mean", type=float, default=None,
                    help="also fail if any audited plugin's mean is below this (new builds only)")
    args = ap.parse_args()

    names = args.plugin or discover()
    reports = [audit_plugin(n, run_tests=args.run_tests) for n in names]
    doc = {"tool": "goat_audit.py", "rubric": "Carmack/Bellard 1-10 (heuristic, mechanizable subset)",
           "count": len(reports), "plugins": reports}

    if args.baseline:
        BASELINE.write_text(json.dumps({r["plugin"]: r["mean"] for r in reports}, indent=2) + "\n",
                            encoding="utf-8")
        print(f"baseline written: {BASELINE} ({len(reports)} plugins)")
        return 0

    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        worst = sorted(reports, key=lambda r: r["mean"])
        print(f"GOAT audit — {len(reports)} plugins (heuristic; regressions are the signal)\n")
        for r in worst:
            s = r["scores"]
            print(f"  {r['mean']:5.2f}  {r['plugin']:<12} "
                  f"D1 {s['d1_dependency']:2d} D2 {s['d2_dead_code']:2d} D3 {s['d3_self_contained']:2d} "
                  f"D4 {s['d4_test_honesty']:2d} D5 {s['d5_hot_path']:2d} D6 {s['d6_honest_notes']:2d}"
                  f"  ({r['loc']} loc)")
        flagged = [r for r in reports if r["findings"]]
        if flagged:
            print("\nfindings:")
            for r in flagged:
                print(f"  [{r['plugin']}]")
                for f in r["findings"]:
                    print(f"    - {f}")

    rc = 0
    if args.check:
        base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
        regressions = [(r["plugin"], base[r["plugin"]], r["mean"])
                       for r in reports if r["plugin"] in base and r["mean"] < base[r["plugin"]] - 0.01]
        new_bad = [r for r in reports
                   if r["plugin"] not in base and args.min_mean is not None and r["mean"] < args.min_mean]
        for p, was, now in regressions:
            print(f"REGRESSION: {p} {was} -> {now}", file=sys.stderr)
            rc = 1
        for r in new_bad:
            print(f"NEW PLUGIN BELOW BAR: {r['plugin']} mean {r['mean']} < {args.min_mean}", file=sys.stderr)
            rc = 1
        if rc == 0:
            print("\nno regressions vs baseline.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
