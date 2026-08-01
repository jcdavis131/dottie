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

THE DEFAULT ABOVE IS UNCHANGED AND DELIBERATE — do not "fix" it. But 2026-08-01
surfaced its cost: the first repo-WIDE run (every prior run was `--path
apps/scout-cli`) found a REAL fail-open in `packages/ava-skills/skills/
safety-scanner`, where any unrecognised `mode` silently degraded to the weak regex
scanner and still returned `pass: True`. The tool could always have caught it;
nobody had run it there. A report only works if someone runs it, and for months
nobody did — which is this file's own defect class, one level up, aimed at itself.

The resolution keeps the author's reasoning intact instead of overriding it. The
objection was to blocking "with no one reading its verdict"; a baseline is exactly
the record of someone having read it:

    python scripts/gate_audit.py --write-baseline scripts/gate_audit_baseline.json
    python scripts/gate_audit.py --check --baseline scripts/gate_audit_baseline.json

`--check` is OPT-IN and exits 1 only on candidates ABSENT from the baseline, so
judged false positives stay quiet (they must, or the next step is `|| true` — this
tool's own instance #5) while a NEWLY introduced fail-open fails loudly. Plain
`gate_audit.py` behaves exactly as it always has.
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
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".ruff_cache",
    ".pytest_cache", "site-packages", "dist", "build",
}

# Words that make a condition look like a SAFETY check rather than business logic.
SAFETY_WORDS = re.compile(
    r"(licen[cs]e|allow|denie?d?|permit|gate|guard|verif|valid|safe|ok\b|"
    r"approv|authoris|authoriz|secure|check|block|forbid|eligib)",
    re.I,
)
# Names that indicate a run-mode rather than a fact about the thing being checked.
MODE_WORDS = re.compile(r"(dry_run|dryrun|debug|skip|force|no_verify|test_mode|offline)", re.I)


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
            # ...or does the function simply END by refusing? The docstring has always
            # said a dispatch is cleared by "no final else/raise/deny", but the `raise`
            # half was never implemented, so an honest terminator like
            #     raise ValueError(f"unknown backend {backend!r}; choices: ...")
            # was reported as a fail-open anyway. apps/dottie/dottie/policy.py::get_policy
            # is exactly that and sat in the baseline judged a false positive. Telling a
            # CORRECT pattern it is wrong is the expensive kind of noise: it teaches
            # people to distrust the tool and baseline everything that comes out of it.
            ends_in_raise = bool(fn.body) and isinstance(fn.body[-1], ast.Raise)
            guarded = any(
                isinstance(n, ast.Compare)
                and isinstance(n.left, ast.Name)
                and n.left.id == param
                and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops)
                for n in ast.walk(fn)
            )
            if not has_else and not guarded and not ends_in_raise:
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
    # `:` is the shell no-op builtin, i.e. exactly `true`; `; true` is the sequential
    # form. Both are one-keystroke rewrites of `|| true` and were previously invisible.
    (re.compile(r"\|\|\s*(true|:)\s*(#.*)?$"), "`|| true` discards the exit code"),
    (re.compile(r";\s*true\s*(#.*)?$"), "`; true` discards the exit code"),
    (re.compile(r"continue-on-error:\s*true"), "continue-on-error:true — step cannot fail the job"),
    (re.compile(r"-ErrorAction\s+SilentlyContinue"), "PowerShell error suppression"),
]

# Patterns that are STEP-scoped rather than command-scoped. `continue-on-error: true`
# sits on its own YAML line and governs the whole step, so the thing being suppressed is
# named on a DIFFERENT line (the step's `name:`/`run:`). Requiring a safety word on the
# key's own line made this pattern dead on arrival — it is declared, but in real Actions
# YAML the two conditions can essentially never both hold. Found 2026-08-01 by probing
# shape B with a set of real suppression idioms rather than waiting to trip over one.
# The window is deliberately small and the safety-word requirement is KEPT: dropping it
# would flag every legitimate optional or matrix step.
_STEP_SCOPED = re.compile(r"continue-on-error")
_STEP_WINDOW = 6


def find_suppressed_checks(path: Path, rel: str):
    """B: a check whose failure is discarded."""
    out = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return out
    logicals = list(_logical_lines(lines))
    for idx, (start, logical) in enumerate(logicals):
        if logical.startswith("#") or logical.startswith("//"):
            continue  # a comment ABOUT suppression is not suppression
        for pat, why in SUPPRESS_PATTERNS:
            # Step-scoped keys name what they suppress on a NEARBY line, not their own.
            context = logical
            if _STEP_SCOPED.search(logical):
                context = " ".join(
                    ln for _, ln in logicals[max(0, idx - 1): idx + _STEP_WINDOW]
                )
            if pat.search(logical) and SAFETY_WORDS.search(context):
                out.append(
                    {
                        "shape": "suppressed-check",
                        "file": rel,
                        "line": start,
                        "code": logical[:160],
                        "why": why,
                    }
                )
                break
    return out


def _logical_lines(lines):
    """Yield (start_line_number, joined_text), folding shell line-continuations.

    Added 2026-08-01 after this tool caught ci.yml's single-line `ruff check ... ||
    true` but MISSED lint.yml's identical construct, which is written as:

        ruff check --statistics \\
          packages/foo \\
          --exclude bar || true

    The old matcher needed the suppression pattern and a safety word on the SAME
    physical line; here "check" is on the first and "|| true" on the last, so neither
    line matched alone. Folding continuations first makes the two forms equivalent,
    which is what a reader would expect them to be.

    The reported line is where the logical line STARTS — that is where the check's name
    is, so a reader lands on `ruff check ...` rather than on a bare `--exclude` tail.
    Single lines (the common case) pass through unchanged, so existing findings keep
    their identity and the baseline does not churn."""
    buf, start = None, None
    for i, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if buf is None:
            buf, start = stripped, i
        else:
            buf = f"{buf} {stripped}"
        if buf.endswith("\\"):
            buf = buf[:-1].rstrip()  # continues on the next physical line
            continue
        yield start, buf
        buf, start = None, None
    if buf is not None:
        yield start, buf


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


def finding_key(f: dict) -> str:
    """Identity of a candidate, for baseline matching. Line number is DELIBERATELY
    excluded — it drifts every time anything above it is edited, and a baseline keyed
    on it would go stale on unrelated changes and re-flag already-judged code. The
    `code` snippet IS included: editing the dispatching line itself is exactly the
    event that should force a re-judgement."""
    return f"{f['file']}::{f['shape']}::{f['code'].strip()}"


def load_baseline(path: Path) -> dict[str, str]:
    """{finding_key: judgment}. Missing file is an error, not an empty baseline —
    silently treating a typo'd --baseline path as 'nothing accepted' would make
    --check pass or fail for the wrong reason, which is this file's own defect class."""
    if not path.exists():
        raise FileNotFoundError(
            f"baseline {path} does not exist; run --write-baseline to create it"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return {finding_key(e): e.get("judgment", "") for e in data.get("accepted", [])}


def main() -> int:
    ap = argparse.ArgumentParser(description="Find gates whose verdict nothing consumes.")
    ap.add_argument("--path", default=".", help="subtree to audit (default: repo root)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--baseline", help="JSON file of already-judged, accepted candidates")
    ap.add_argument("--check", action="store_true",
                     help="exit 1 if any candidate is NOT in --baseline. OPT-IN: the "
                          "default still exits 0 always, see the module docstring.")
    ap.add_argument("--write-baseline", metavar="PATH",
                     help="write the current findings out as an accepted baseline")
    args = ap.parse_args()

    base = (ROOT / args.path).resolve()
    findings, scanned = audit(base)

    if args.write_baseline:
        out = Path(args.write_baseline)
        existing = {}
        if out.exists():  # preserve judgments already written for surviving findings
            existing = {
                finding_key(e): e.get("judgment", "")
                for e in json.loads(out.read_text(encoding="utf-8")).get("accepted", [])
            }
        payload = {
            "_doc": (
                "Candidates already judged acceptable. `gate_audit.py --check "
                "--baseline <this file>` exits 1 only on candidates absent from this "
                "list, so a NEW fail-open dispatch fails loudly while judged ones stay "
                "quiet. Each entry SHOULD carry a judgment saying why it is acceptable "
                "— an empty judgment means nobody has actually read it yet."
            ),
            "accepted": [
                {"file": f["file"], "shape": f["shape"], "code": f["code"],
                 "judgment": existing.get(finding_key(f), "")}
                for f in sorted(findings, key=lambda f: (f["file"], f["shape"], f["code"]))
            ],
        }
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(findings)} accepted candidates -> {out}")
        return 0

    if args.check:
        if not args.baseline:
            ap.error("--check requires --baseline")
        accepted = load_baseline(Path(args.baseline))
        seen = {finding_key(f) for f in findings}
        new = [f for f in findings if finding_key(f) not in accepted]
        stale = sorted(k for k in accepted if k not in seen)

        for k in stale:
            # Reported, never fatal: a vanished candidate means someone FIXED something.
            print(f"note: baseline entry no longer present (prune it): {k}")
        if not new:
            print(f"gate audit: no new candidates ({len(accepted)} judged, "
                  f"{len(stale)} stale). OK")
            return 0
        print(f"gate audit: {len(new)} NEW candidate(s) not in {args.baseline}")
        for f in new:
            print(f"  {f['file']}:{f['line']}  [{f['shape']}]")
            print(f"      {f['code']}")
            print(f"      -> {f['why']}")
        print("\nJudge each. If acceptable, add it to the baseline WITH a judgment; "
              "if not, fix it.")
        return 1

    if args.json:
        print(json.dumps({"scanned": scanned, "findings": findings}, indent=2))
        return 0

    print("GATE AUDIT — gates whose verdict nothing consumes")
    print(f"scanned {scanned['py']} python + {scanned['other']} script/CI files under {args.path}")
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
