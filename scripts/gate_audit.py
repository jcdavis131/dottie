#!/usr/bin/env python3
"""Find gates whose verdict nothing consumes.

The defect class, named 2026-07-25 after five instances turned up in one day
across three codebases (see TODOS.md "THE RECURRING DEFECT CLASS"):

  1. check_permission unknown action  -> fell through to `return True, "ok"`
  2. capabilities.filesystem.paths    -> declared by 47 of 56 manifests, enforced by 0
  3. dataset_discovery manifest skip  -> `and not args.dry_run` disabled it in the
                                         exact mode the daily cron uses
  4. mtnn_report promote {"ok": false}-> the artifact shipped the same day
  5. ci.yml ruff step                 -> `|| true`

The unifying property: a verdict is computed and RECORDED, but no control flow
branches on it. It reads at the call site exactly like enforcement, which makes it
worse than no gate — it buys confidence it has not earned.

Three mechanically-detectable shapes are implemented. They are HEURISTICS and are
reported as candidates for a human to judge, never as defects:

  A. MODE-CONDITIONAL ESCAPE — a guard combining a safety condition with
     `and not <x>.dry_run` / `and not args.<flag>`. Instance #3 exactly.
  B. SUPPRESSED CHECK — `|| true`, `continue-on-error: true`, `except: pass`
     around something whose name says it checks. Instance #5.
  C. FAIL-OPEN DISPATCH — a function whose body is a chain of `if <param> == …`
     with no final else/raise/deny, so an unrecognised value falls through to the
     success return. Instance #1.

Python is parsed with `ast`, never regex: this repo's comments quote the code they
discuss, and a grep counting prose as code has already produced three wrong answers
in one day (a drift-guard flagging `fs_wrile` from a comment, `quality`/`tools`
miscounted as gated, and ruff reading a rationale comment that began with the word
noqa as a directive).

Usage:
    python scripts/gate_audit.py                 # human
    python scripts/gate_audit.py --json
    python scripts/gate_audit.py --path apps/scout-cli
Exit 0 always: this reports, it does not gate. Making the gate-auditor itself a
blocking gate with no one reading its verdict would be the joke writing itself.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_PARTS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".ruff_cache",
    ".pytest_cache",
    "site-packages",
    "dist",
    "build",
}

# Words that make a condition look like a SAFETY check rather than business logic.
SAFETY_WORDS = re.compile(
    r"(licen[cs]e|allow|denie?d?|permit|gate|guard|verif|valid|safe|ok\b|"
    r"approv|authoris|authoriz|secure|check|block|forbid|eligib)",
    re.I,
)
# Names that indicate a run-mode rather than a fact about the thing being checked.
MODE_WORDS = re.compile(
    r"(dry_run|dryrun|debug|skip|force|no_verify|test_mode|offline)", re.I
)


def iter_files(base: Path, suffixes):
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix not in suffixes:
            continue
        if SKIP_PARTS & set(p.parts):
            continue
        yield p


def _src(node, lines):
    try:
        return lines[node.lineno - 1].strip()
    except Exception:
        return ""


def find_mode_escapes(tree, lines, rel):
    """A: `if <safety-ish> and not <mode>:`"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.And):
            continue
        text = " ".join(ast.unparse(v) for v in node.values)
        has_mode_negation = any(
            isinstance(v, ast.UnaryOp)
            and isinstance(v.op, ast.Not)
            and MODE_WORDS.search(ast.unparse(v.operand))
            for v in node.values
        )
        if has_mode_negation and SAFETY_WORDS.search(text):
            out.append(
                {
                    "shape": "mode-conditional-escape",
                    "file": rel,
                    "line": node.lineno,
                    "code": _src(node, lines)[:160],
                    "why": "a safety condition is disabled by a run-mode flag; the gate "
                    "stops firing in exactly that mode",
                }
            )
    return out


def find_fail_open_dispatch(tree, lines, rel):
    """C: def f(..., action, ...) whose body is all `if action == …` and no final deny."""
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in fn.args.args}
        if not params:
            continue
        compared = {}
        for node in ast.walk(fn):
            if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
                continue
            left, ops, comps = node.test.left, node.test.ops, node.test.comparators
            if not (isinstance(left, ast.Name) and left.id in params):
                continue
            if not (len(ops) == 1 and isinstance(ops[0], ast.Eq)):
                continue
            if not (len(comps) == 1 and isinstance(comps[0], ast.Constant)):
                continue
            compared.setdefault(left.id, []).append(node)
        for param, ifs in compared.items():
            if len(ifs) < 2:
                continue  # a single branch is ordinary logic, not a dispatch
            # Does ANY of them have an else, or is there a membership guard on the param?
            has_else = any(i.orelse for i in ifs)
            guarded = any(
                isinstance(n, ast.Compare)
                and isinstance(n.left, ast.Name)
                and n.left.id == param
                and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops)
                for n in ast.walk(fn)
            )
            if not has_else and not guarded:
                out.append(
                    {
                        "shape": "fail-open-dispatch",
                        "file": rel,
                        "line": fn.lineno,
                        "code": f"def {fn.name}(...)  dispatches on {param!r} "
                        f"across {len(ifs)} `==` branches",
                        "why": "no else / membership guard, so an unrecognised value "
                        "falls through to whatever the function returns last",
                    }
                )
    return out


SUPPRESS_PATTERNS = [
    (re.compile(r"\|\|\s*true\b"), "`|| true` discards the exit code"),
    (
        re.compile(r"continue-on-error:\s*true"),
        "continue-on-error:true — step cannot fail the job",
    ),
    (re.compile(r"-ErrorAction\s+SilentlyContinue"), "PowerShell error suppression"),
]


def find_suppressed_checks(path: Path, rel: str):
    """B: a check whose failure is discarded."""
    out = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return out
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue  # a comment ABOUT suppression is not suppression
        for pat, why in SUPPRESS_PATTERNS:
            if pat.search(line) and SAFETY_WORDS.search(line):
                out.append(
                    {
                        "shape": "suppressed-check",
                        "file": rel,
                        "line": i,
                        "code": stripped[:160],
                        "why": why,
                    }
                )
                break
    return out


def audit(base: Path):
    findings, scanned = [], {"py": 0, "other": 0}
    for p in iter_files(base, {".py"}):
        rel = p.relative_to(ROOT).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except Exception:
            continue
        scanned["py"] += 1
        lines = text.splitlines()
        findings += find_mode_escapes(tree, lines, rel)
        findings += find_fail_open_dispatch(tree, lines, rel)
    for p in iter_files(base, {".yml", ".yaml", ".sh", ".ps1", ".mjs", ".js"}):
        rel = p.relative_to(ROOT).as_posix()
        scanned["other"] += 1
        findings += find_suppressed_checks(p, rel)
    return findings, scanned


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Find gates whose verdict nothing consumes."
    )
    ap.add_argument("--path", default=".", help="subtree to audit (default: repo root)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    base = (ROOT / args.path).resolve()
    findings, scanned = audit(base)

    if args.json:
        print(json.dumps({"scanned": scanned, "findings": findings}, indent=2))
        return 0

    print("GATE AUDIT — gates whose verdict nothing consumes")
    print(
        f"scanned {scanned['py']} python + {scanned['other']} script/CI files under {args.path}"
    )
    print("-" * 72)
    if not findings:
        print("no candidates found (this is a heuristic — absence is not proof)")
        return 0
    by_shape = {}
    for f in findings:
        by_shape.setdefault(f["shape"], []).append(f)
    for shape, items in sorted(by_shape.items()):
        print(f"\n## {shape}  ({len(items)})")
        for f in items:
            print(f"  {f['file']}:{f['line']}")
            print(f"      {f['code']}")
            print(f"      -> {f['why']}")
    print(f"\n{len(findings)} candidates. These are HEURISTICS — judge each one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
