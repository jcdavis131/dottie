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
import subprocess
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


def git_ignored(base: Path):
    """Paths git ignores, or None if that cannot be determined.

    WHY. Without this the auditor reads GENERATED files. On 2026-08-01 a local run
    reported 11 unaccepted candidates against a 9-entry baseline while CI on the same
    commit was green — not a flaky gate, a different corpus: 10 of the 11 were
    `apps/dottie/data/research/workspaces/*/candidate_*.py`, model-written research
    output under `apps/dottie/.gitignore`'s `data/`. CI checks out the repo, never
    materialises them, and passes correctly.

    That divergence is worse than plain noise. It makes the ratchet unreproducible — the
    developer sees red, CI sees green, and the honest conclusion ("the tool is wrong")
    is the one that ends in `|| true`, which is instance #5 in this file's own docstring.

    IGNORED, not UNTRACKED. A file you have just written and not yet `git add`ed is
    exactly the file most worth auditing, so it stays in scope; only files git has been
    told to ignore are dropped. Returns None when git is unavailable, and the caller then
    scans everything and says so rather than silently narrowing what it checked.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(base), "ls-files", "--others", "--ignored",
             "--exclude-standard", "-z"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = set()
    for rel in proc.stdout.split("\0"):
        if rel:
            try:
                out.add((base / rel).resolve())
            except OSError:
                continue
    return out


def iter_files(base: Path, suffixes, ignored=None):
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix not in suffixes:
            continue
        if SKIP_PARTS & set(p.parts):
            continue
        if ignored:
            try:
                if p.resolve() in ignored:
                    continue
            except OSError:
                pass
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


def _is_chain_link(if_node, param):
    """Is this If's `orelse` merely the next `elif <param> == ...` link?

    Deliberately narrow. Python cannot distinguish `elif X` from `else:` + an indented
    `if X` — both are a lone If inside orelse — so "orelse is a single If" is NOT enough
    to call it a chain continuation. This also requires the nested test to compare THE
    SAME parameter, so a genuine else block that happens to open with an unrelated
    conditional, e.g.

        if kind == 'a':
            return 1
        else:
            if cache_is_cold():   # unrelated to `kind`
                warm()
            return fallback()

    still counts as a real else and clears the finding, which it should."""
    if len(if_node.orelse) != 1 or not isinstance(if_node.orelse[0], ast.If):
        return False
    test = if_node.orelse[0].test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == param
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
    )


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
            # `i.orelse` alone is WRONG here: Python encodes `elif` as a nested If inside
            # orelse, so for `if k=='a': ... elif k=='b': ...` the outer orelse is `[If]`
            # — non-empty — and the next chain LINK was being mistaken for a terminal
            # else. That single line is why the most common Python dispatch form was
            # invisible while the rarer sequential-`if` form was caught.
            has_else = any(i.orelse and not _is_chain_link(i, param) for i in ifs)
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

# `- name: Eval gate quick (nano)` — a workflow step's own declaration of what it is for.
_YAML_STEP_NAME = re.compile(r"^-?\s*name:\s*(\S.*)$")
# How far back to look for it. A step's run block is normally a handful of lines; scanning
# further risks attributing a NEIGHBOURING step's name and inventing a safety word that the
# suppressed step never claimed.
_NAME_LOOKBACK = 25


def _enclosing_step_name(logicals, idx):
    """The `name:` of the workflow step containing logicals[idx], or None.

    Walks backward to the FIRST `name:` seen, which is the enclosing step's own, and stops
    there — continuing would reach earlier steps and let one step's reassuring name excuse
    a different step's suppression.
    """
    for back in range(idx - 1, max(-1, idx - 1 - _NAME_LOOKBACK), -1):
        m = _YAML_STEP_NAME.match(logicals[back][1])
        if m:
            return m.group(1)
    return None


def find_suppressed_checks(path: Path, rel: str):
    """B: a check whose failure is discarded."""
    out = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return out
    logicals = list(_logical_lines(lines))
    is_yaml = rel.endswith((".yml", ".yaml"))
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
            elif is_yaml:
                # A CI step states its PURPOSE in `name:` and its COMMAND in `run:`, so
                # requiring the safety word on the suppressed line itself cannot see a
                # step called "Eval gate quick" whose run line is
                # `python -m ...cli --help | head -n 20 || true`. That exact step sat dead
                # in ci.yml for ten days: the module path has hyphens and is unimportable,
                # `|| true` ate the error, and this tool stayed silent because "gate" lives
                # on the name line. Same failure as the line-continuation miss fixed in
                # 5584570 — safety word and suppression on different lines — so the fix is
                # the same shape: widen the context to the construct a reader would treat
                # as one unit.
                name = _enclosing_step_name(logicals, idx)
                if name:
                    context = f"{name} {logical}"
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
    ignored = git_ignored(base)
    if ignored is None:
        print(
            "note: git unavailable, so gitignored files are being audited too — expect "
            "generated artifacts in the results and a verdict that will not match CI.",
            file=sys.stderr,
        )
    scanned["ignored_skipped"] = 0 if ignored is None else len(ignored)
    for p in iter_files(base, {".py"}, ignored):
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
    for p in iter_files(base, {".yml", ".yaml", ".sh", ".ps1", ".mjs", ".js"}, ignored):
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
