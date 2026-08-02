#!/usr/bin/env python3
"""Fail when HANDOFF.md's "current state" block has drifted too far from HEAD.

WHY THIS EXISTS. HANDOFF.md carries a hand-written HEAD sha in the block a reader is told
to trust first, and it has gone stale four times:

    recorded da657d9   ->  23 commits landed        (same day)
    recorded f274be8   ->  37 commits landed
    recorded 8693a27   ->  27 commits landed
    recorded d99c93d   ->  10 commits landed        (same SESSION as the refresh)

The file already warns about this in its own header — "verify against `git log`, not
memory" — and the warning has not worked, because a warning is not a mechanism. Every one
of those was found by someone deciding to re-measure, which is luck rather than process.

This is the same move scripts/check_documented_counts.py makes for the ruff figures, for
the same reason: a number a human maintains by hand rots, and the only fix that holds is a
check that fails.

WHY A THRESHOLD AND NOT EQUALITY. Requiring the recorded sha to equal HEAD is
unsatisfiable — the commit that updates HANDOFF.md changes HEAD, so it would fail on its
own landing. Drift is allowed up to MAX_DRIFT; the point is to catch 27-commit rot, not to
demand the block be rewritten every push.

    python scripts/check_handoff_fresh.py           # report
    python scripts/check_handoff_fresh.py --check   # exit 1 when drift exceeds the budget

DELIBERATELY NARROW. It checks ONE thing: is the recorded sha an ancestor of HEAD, and how
far back. It does not try to verify suite counts or disk figures in the same block — those
need a CI run or a live filesystem, and a check that cries wolf gets `|| true`'d, which is
instance #5 in gate_audit.py's own docstring.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HANDOFF = REPO / "HANDOFF.md"

# Chosen against the observed failures: the four stale blocks drifted 10, 23, 27 and 37
# commits. 20 catches the three worst while leaving ordinary multi-commit sessions alone.
# The 10-commit case will pass, and that is the accepted cost of not nagging on every push.
MAX_DRIFT = 20

# The sha in the live block, e.g. "**Re-measured 2026-08-02, not carried forward.** HEAD `d99c93d`".
HEAD_RE = re.compile(r"HEAD `([0-9a-f]{7,40})`")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    ).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when drift exceeds budget")
    args = ap.parse_args()

    if not HANDOFF.exists():
        print(f"CANNOT CHECK: {HANDOFF} does not exist.")
        return 2

    text = HANDOFF.read_text(encoding="utf-8", errors="replace")
    m = HEAD_RE.search(text)
    if not m:
        # An empty scan must not read as a pass: if the phrasing changed, this check is
        # blind and should say so rather than report freshness it never measured.
        print("CANNOT CHECK: no ``HEAD `<sha>` `` found in HANDOFF.md.")
        print("The block's phrasing changed, so this check is blind. Fix the regex or the")
        print("block — do not leave it silently passing.")
        return 2

    recorded = m.group(1)
    head = git("rev-parse", "HEAD")
    if not head:
        print("CANNOT CHECK: git rev-parse HEAD produced nothing.")
        return 2

    if not git("cat-file", "-t", recorded):
        print(f"UNKNOWN SHA: HANDOFF.md records `{recorded}`, which is not in this repo.")
        print("Either the block predates a history rewrite or the sha is a typo.")
        return 1 if args.check else 0

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", recorded, "HEAD"],
        cwd=REPO, capture_output=True, timeout=60,
    ).returncode == 0
    if not ancestor:
        print(f"NOT ON THIS BRANCH: HANDOFF.md records `{recorded}`, which is not an")
        print(f"ancestor of HEAD ({head[:7]}). The block describes a different history.")
        return 1 if args.check else 0

    drift = len([x for x in git("rev-list", f"{recorded}..HEAD").splitlines() if x])
    print(f"HANDOFF.md records HEAD `{recorded}`; actual HEAD is `{head[:7]}`.")
    print(f"drift: {drift} commit(s)   budget: {MAX_DRIFT}")

    if drift > MAX_DRIFT:
        print()
        print(f"STALE: the block a reader is told to trust first is {drift} commits behind.")
        print("Re-measure it against `git log` — HEAD, suite counts, disk — and say how it")
        print("was measured, not just what it says. Prior drift at each refresh: 23, 37, 27,")
        print("10. A warning in the file did not stop any of them.")
        return 1 if args.check else 0

    print("OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
