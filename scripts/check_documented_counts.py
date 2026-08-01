#!/usr/bin/env python3
"""Verify that the lint-debt numbers written in the workflows still reproduce.

WHY THIS EXISTS. On 2026-08-01 a single session corrected roughly fifteen stale numbers
across ci.yml, lint.yml, HANDOFF.md and TODO.md — 334 -> 263, 1156 -> 2260, 2226 -> 2260,
553 -> 859, 80 -> 89, 10 -> 9, 23.6 GB -> 59 GB, and more. The last one is the argument
for automating it: the ruff figure was measured and written as **263**, and then a commit
LATER THE SAME DAY closed 11 findings, making it 252. A number written by hand went
stale in hours, by the same author, inside one session.

Every one of those was found by someone deciding to re-measure. That is not a process,
it is luck. This checks the subset that is MECHANICALLY reproducible — a ruff count is
exactly a ruff count — so drift in it is caught rather than stumbled over.

SCOPE, deliberately narrow. It does NOT try to verify prose, test counts, or timings.
Those need a suite run or a live service and would make this slow and flaky, and a check
that cries wolf gets `|| true`'d — which is instance #5 in gate_audit.py's own docstring.
Only the ruff debt figures, which are cheap and exact.

    python scripts/check_documented_counts.py           # report
    python scripts/check_documented_counts.py --check   # exit 1 on drift

THE COST THIS IMPOSES, stated because it is real and was introduced deliberately.
It fires in BOTH directions, so a legitimate lint CLEANUP also reds the build until the
figure is updated — fix five findings and CI complains that 252 no longer reproduces.
That is friction on exactly the behaviour the ratchet wants to encourage.

It is kept anyway, for one reason: the number lives in the step NAME, which is what a
human reads to decide whether lint is under control. A figure that is too LOW is as
misleading as one that is too high, and "it only drifted in the good direction" is how
286 -> 263 -> 252 went unnoticed three times. The remedy is a one-line edit and the
failure message prints the exact value to paste.

If the friction ever outweighs the rot, the honest reversal is to drop --check from CI
and keep the reporting mode — NOT to add a tolerance band, which would restore the
silent drift this exists to stop.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUFF_PIN = "ruff@0.15.22"  # must match both workflows; see lint.yml's "ONE ruff version"

# The soft-lint scope, kept in ONE place. Both workflows lint exactly these.
SOFT_PACKAGES = [
    "packages/ava-open-harness",
    "packages/personal-graphify",
    "apps/scout-cli",
]
EXCLUDE = "apps/scout-cli/.venv"

# Where the number is written for a human to read. Both files state it in the step name.
DOCUMENTED = [
    (Path(".github/workflows/ci.yml"), re.compile(r"Ruff lint \(non-blocking — (\d+) known findings")),
    (Path(".github/workflows/lint.yml"), re.compile(r"Ruff check \(non-blocking — (\d+) known findings")),
]


def measure(packages) -> int:
    """Fresh ruff finding count, via the pinned version the workflows use."""
    if not shutil.which("uvx"):
        raise RuntimeError("uvx not on PATH — cannot measure with the pinned ruff")
    out = subprocess.run(
        ["uvx", RUFF_PIN, "check", *packages, "--exclude", EXCLUDE, "--output-format=concise"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    # ruff prints one `path:line:col: CODE msg` per finding; the summary lines have no colon-digit
    return sum(1 for ln in out.splitlines() if re.search(r":\d+:\d+:", ln))


def workflow_scope(path: Path) -> list[str] | None:
    """The packages a workflow's soft-lint step ACTUALLY passes to ruff.

    Parsed rather than assumed. The first version of this script compared its own
    SOFT_PACKAGES list against a total measured from that same list — a tautology that
    could never fail, which a mutation test caught: adding a package to SOFT_PACKAGES
    changed nothing because both sides moved together. An assertion that cannot fail is
    the defect class gate_audit.py exists to find, so it is replaced by a comparison
    against the real command line.
    """
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    # The step's `run:` may be one line (ci.yml) or a `|` block with backslash
    # continuations (lint.yml); join continuations before matching, same fold
    # gate_audit.py needed for the identical reason.
    joined, buf = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        buf = f"{buf} {line}" if buf else line
        if buf.endswith("\\"):
            buf = buf[:-1].rstrip()
            continue
        joined.append(buf)
        buf = ""
    for line in joined:
        if "ruff" in line and "check" in line and "--exclude" in line:
            found = re.findall(r"(packages/[\w.-]+|apps/[\w.-]+)", line)
            pkgs = [p for p in found if not p.startswith(EXCLUDE)]
            if pkgs:
                return sorted(set(pkgs))
    return None


def documented() -> list[tuple[Path, int | None]]:
    out = []
    for rel, pat in DOCUMENTED:
        path = ROOT / rel
        if not path.exists():
            out.append((rel, None))
            continue
        m = pat.search(path.read_text(encoding="utf-8"))
        out.append((rel, int(m.group(1)) if m else None))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 when a documented number has drifted")
    args = ap.parse_args(argv)

    fresh = measure(SOFT_PACKAGES)
    per_pkg = {p: measure([p]) for p in SOFT_PACKAGES}
    docs = documented()

    print("DOCUMENTED-COUNT CHECK — ruff debt")
    print(f"  fresh total : {fresh}")
    for p, n in per_pkg.items():
        print(f"      {p:34}{n:>6}")
    total_pkg = sum(per_pkg.values())
    print(f"  sum of parts: {total_pkg}"
          f"{'  OK' if total_pkg == fresh else '   MISMATCH — combined vs per-package'}")

    # Compare against what the workflows REALLY lint, not against this script's own list.
    scope_drift = []
    for rel, _pat in DOCUMENTED:
        actual = workflow_scope(ROOT / rel)
        if actual is None:
            print(f"  {rel}: could not parse the ruff scope from its run: line")
            scope_drift.append((rel, None))
        elif actual != sorted(SOFT_PACKAGES):
            print(f"  {rel}: SCOPE DRIFT — workflow lints {actual}, this script measures "
                  f"{sorted(SOFT_PACKAGES)}")
            scope_drift.append((rel, actual))
    print()

    drift, missing = [], []
    for rel, n in docs:
        if n is None:
            missing.append(rel)
            print(f"  {rel}: no documented figure found  (pattern changed?)")
        else:
            same = n == fresh
            print(f"  {rel}: documented {n}{'  OK' if same else f'  STALE — fresh is {fresh}'}")
            if not same:
                drift.append((rel, n))

    if not args.check:
        return 0
    if missing:
        print("\nFAIL: a documented figure could not be located — the step name or this "
              "script's pattern changed. Fix whichever is wrong; do not delete the check.")
        return 1
    if scope_drift:
        print("\nFAIL: this script and the workflows no longer lint the same set, so the "
              "number it verifies is not the number they report. Reconcile SOFT_PACKAGES.")
        return 1
    if total_pkg != fresh:
        print(f"\nFAIL: per-package sum {total_pkg} != combined {fresh} — ruff is counting "
              "differently across invocations; investigate before trusting either figure.")
        return 1
    if drift:
        print(f"\nFAIL: {len(drift)} documented figure(s) stale. Update to {fresh}, and say "
              "WHY it moved next to it — a bare number with no reason is what rots.")
        return 1
    print("\nOK: every documented ruff figure reproduces.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
