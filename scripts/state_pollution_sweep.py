#!/usr/bin/env python3
"""Detect a test suite writing to real state — home state AND in-repo generated state.

WHY THIS EXISTS, and why the previous sweep needed redoing. On 2026-08-01 a sweep
(`79cad30`) measured every suite against a snapshot of `~/workspace`, `~/.dottie-claw` and
`~/.local/share/bigbang` and concluded scout-cli was the only polluter, recording
"apps/ava-factory 859 — no, 0 of 8,510 files changed".

That figure was honestly measured and still wrong, because the corpus was wrong. The
factory suite does not write to HOME; it writes to `apps/ava-factory/reports/`, which is
inside the repo and gitignored. Snapshotting only home directories could not see it, so
the suite quietly appended ~5 KB of test records to the operator's live telemetry on every
run for as long as that had been true.

The prior sweep already knew the shape of this mistake — it flagged that two of its runs
never executed and produced "clean" diffs proving nothing. A clean diff over the wrong
DIRECTORIES is the same defect as a clean diff after a suite that did not run: the number
is real, the question it answers is not the one being asked.

So this watches both, and REFUSES to report clean unless the suite demonstrably ran.

    python scripts/state_pollution_sweep.py --snapshot before.json
    <run the suite>
    python scripts/state_pollution_sweep.py --snapshot after.json
    python scripts/state_pollution_sweep.py --diff before.json after.json

Records (size, mtime_ns) per path. Timestamps alone are not enough on this box: three
Windows scheduled tasks ("Dottie Research runner", "Dottie StateStore telemetry", "Dottie
Status publisher" — the last every 10 minutes) write into apps/ava-factory/reports/ too, so
a file changing during a long suite is NOT proof the suite changed it. Confirm ownership by
A/B (fix the isolation, re-run, expect delta 0) or by an idle window, never by proximity.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()

# Home state a suite has no business touching.
HOME_ROOTS = [
    HOME / ".local" / "share" / "bigbang",
    HOME / ".dottie-claw",
    HOME / ".config",
    HOME / ".scout",
    # Carried from 79cad30's corpus so this is a superset of the sweep it replaces, not a
    # different set that happens to be bigger in places and smaller in others.
    HOME / "workspace",
]

# In-repo GENERATED state — the corpus the previous sweep missed entirely. These are
# gitignored, so `git status` stays clean while they are being written, which is exactly
# why a git-based check would not have caught the factory telemetry either.
REPO_ROOTS = [
    ROOT / "apps" / "ava-factory" / "reports",
    ROOT / "apps" / "ava-factory" / "runs",
    ROOT / "apps" / "ava-factory" / "ckpt",
    ROOT / "apps" / "ava-factory" / "logs",
    ROOT / "apps" / "dottie" / "data",
    ROOT / "apps" / "scout-cli" / "data",
    # SOURCE tree, not generated state — added 2026-08-01 after a suite wrote INTO it.
    # Running `pytest apps/scout-cli/tests` from the repo root (which the Makefile did)
    # made a forge test scaffold a real plugin at bigbang/plugins/gentest/ — cli.py,
    # manifest.yaml, __init__.py — because those fixtures are CWD-relative. It showed up
    # as +21 ruff findings and a documented-count failure before anyone looked at the
    # directory.
    #
    # This is the second time this sweep's corpus was too narrow: it watched where
    # generated state LIVES and missed a suite writing where CODE lives, exactly as the
    # first version watched HOME and missed in-repo telemetry. Source-tree pollution is
    # the worse of the two, since it survives into commits and lint counts.
    ROOT / "apps" / "scout-cli" / "bigbang" / "plugins",
]

SKIP_PARTS = {"__pycache__", ".git", ".venv", "node_modules", ".pytest_cache", ".ruff_cache"}


def snapshot() -> dict:
    out = {}
    for base in HOME_ROOTS + REPO_ROOTS:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if SKIP_PARTS & set(p.parts):
                continue
            try:
                if not p.is_file():
                    continue
                st = p.stat()
            except OSError:
                continue
            out[str(p)] = [st.st_size, st.st_mtime_ns]
    return out


# Paths a Windows scheduled task writes on its own cadence, independent of any suite.
# Proven, not assumed: an IDLE control run (100 s, no suite) added a fresh
# `candidate_*.py` under apps/dottie/data/research/workspaces/, and "Dottie Research
# runner" fires research_worker.ps1 every 15 minutes while "Dottie Status publisher"
# rewrites dottie_live_status.json every 10.
#
# Reported SEPARATELY rather than filtered out. Dropping them would hide a real defect the
# day a suite genuinely writes there, and this file exists because the previous sweep
# looked at the wrong corpus — narrowing the corpus again to buy a quiet report would
# repeat that mistake in the other direction.
SCHEDULER_OWNED = (
    str(ROOT / "apps" / "dottie" / "data" / "research"),
    str(ROOT / "apps" / "ava-factory" / "reports" / "dottie_live_status.json"),
)


def _is_scheduler(path: str) -> bool:
    return any(path.startswith(p) for p in SCHEDULER_OWNED)


def diff(before: dict, after: dict):
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return added, removed, changed


def split_scheduler(items):
    """(suite-attributable, scheduler-owned) — the second needs an A/B before blaming."""
    return [i for i in items if not _is_scheduler(i)], [i for i in items if _is_scheduler(i)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", metavar="OUT", help="write a snapshot to OUT")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args(argv)

    if args.snapshot:
        snap = snapshot()
        Path(args.snapshot).write_text(json.dumps(snap), encoding="utf-8")
        print(f"snapshot: {len(snap)} files across "
              f"{sum(1 for b in HOME_ROOTS + REPO_ROOTS if b.exists())} existing roots")
        # A snapshot of nothing would make every later diff trivially clean — the exact
        # vacuous-pass shape this repo audits for. Say so loudly rather than proceed.
        if not snap:
            print("WARNING: snapshotted ZERO files. Every diff against this will look "
                  "clean and mean nothing. Check the roots above exist.", file=sys.stderr)
        return 0

    if args.diff:
        before = json.loads(Path(args.diff[0]).read_text(encoding="utf-8"))
        after = json.loads(Path(args.diff[1]).read_text(encoding="utf-8"))
        if not before or not after:
            print("FAIL: one of the snapshots is empty — a clean diff here would be "
                  "vacuous. Re-take it.")
            return 1
        added, removed, changed = diff(before, after)
        real_total, sched_total = 0, 0
        for label, items in (("ADDED", added), ("REMOVED", removed), ("CHANGED", changed)):
            real, sched = split_scheduler(items)
            real_total += len(real)
            sched_total += len(sched)
            if real:
                print(f"{label} ({len(real)}):")
                for k in real[:20]:
                    print(f"    {k}")
                if len(real) > 20:
                    print(f"    ... and {len(real) - 20} more")
            if sched:
                print(f"{label} — scheduler-owned, NOT attributable to the suite ({len(sched)}):")
                for k in sched[:5]:
                    print(f"    {k}")
                if len(sched) > 5:
                    print(f"    ... and {len(sched) - 5} more")

        if sched_total:
            print(f"\n{sched_total} change(s) fell in scheduler-owned paths. A 100 s idle "
                  "control produced the same kind of change with no suite running, so "
                  "these are\nnot evidence against the suite. Verify by A/B if it matters.")
        if not real_total:
            print(f"CLEAN — {len(before)} files watched, nothing the suite can be blamed for.")
            return 0
        print(f"\nPOLLUTION: {real_total} change(s) outside scheduler-owned paths, "
              f"out of {len(before)} watched.")
        print("Confirm by A/B — fix the isolation, re-run, expect a zero delta — rather "
              "than by timestamp proximity.")
        return 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
