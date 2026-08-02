#!/usr/bin/env python3
"""Cross-check clock times claimed in TODOS.md against the git history.

Why this exists (TODOS 5.3.R88): I fabricated the timestamp in every 5.3 R-entry from R72
to R87 -- 14 of them, running 3.5-4.5 hours ahead of the real clock. It survived every
review pass because the times were internally consistent: monotonic, ~15-20 minutes apart,
plausible against the narrative. A fabrication that is self-consistent cannot be caught by
re-reading it. Only an external source catches it.

I had already been corrected on exactly this earlier in the same session, written the
lesson down, and then done it again for the next twelve entries. So the lesson needed to
stop being prose and start being a command that fails.

The check: each `### 5.3.R<N>` entry is dated by a commit whose subject mentions `R<N>`,
giving every claimed HH:MM a real calendar day. No such timestamp may fall in the FUTURE
relative to HEAD -- work is described after it happens.

Deliberately narrow. It does not try to prove a timestamp is RIGHT (unknowable from here);
it proves one is not IMPOSSIBLE. That suffices: all 14 fabrications sat hours ahead of the
clock, so this catches them.

The first draft compared each time against its own entry's commit, which was stricter and
wrong: entries get amended by later commits whose subjects never name them (R86's control
note was added by a commit titled 'record the capacity control as in-flight'), so honest
edits were flagged. Struck-through and quoted text is skipped too -- a correction entry
necessarily reproduces the wrong values it is fixing, and flagging those punishes the fix.

Coverage is partial and says so: entries predating the R-numbered commit convention have no
commit naming them and are reported as unchecked rather than silently passed.

Usage:
    python scripts/check_todos_timestamps.py          # report, exit 1 on any violation
    python scripts/check_todos_timestamps.py --list   # show every entry and its commit

"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# TODO.md, not TODOS.md. This script was written 2026-07-20 against a root TODOS.md; on
# 2026-07-26 `41534f2` ("TODO.md is now the single list — TODOS.md merged in, then
# deduped") deleted that file, and this path was never updated. Every invocation since
# died with FileNotFoundError before checking anything -- for six days, while
# scripts/README.md advertised it as "Ops discipline 9.5: run it on any tick that writes
# TODOS". Found 2026-08-02 by running it.
#
# It died SILENTLY because nothing ran it. A checker wired into no pipeline has the same
# value as one that always passes, which is this repo's own named defect class pointed at
# its own tooling. That is why it is now a CI step, not just a README instruction.
#
# The 107 `### 5.3.R<N>` entries live in TODO.md; apps/ava-factory/TODOS.md still exists
# but has 0 of them, so it is deliberately not scanned.
TODOS = REPO / "TODO.md"

ENTRY_RE = re.compile(r"^### 5\.3\.R(\d+)\b", re.M)
# HH:MM, but not durations like 02:16:43 and not inside a longer number.
TIME_RE = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
# Struck-through text and quoted text both intentionally reproduce WRONG old values --
# R88 quotes the fabricated times it is correcting. Flagging those would punish the fix.
STRUCK_RE = re.compile(r"~~.*?~~", re.S)
QUOTED_RE = re.compile(r"[\"“].*?[\"”]", re.S)


def head_datetime() -> datetime:
    """HEAD's author time -- the ceiling. Nothing recorded can postdate the last commit."""
    out = subprocess.run(["git", "log", "-1", "--format=%ad", "--date=format:%Y-%m-%d %H:%M"],
                         cwd=REPO, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=30).stdout or ""
    return datetime.strptime(out.strip(), "%Y-%m-%d %H:%M")


def commit_times_by_entry() -> dict[str, tuple[str, str, str]]:
    """Map 'R83' -> (HH:MM, sha, YYYY-MM-DD) using each entry's own commit, newest wins."""
    # encoding="utf-8" is NOT optional: text=True alone decodes with the locale codepage
    # (cp1252 here), and these commit subjects are full of em dashes. Writing this checker
    # for TODOS 5.3.R88 I hit exactly the failure R79 catalogued -- 21 encoding-less calls
    # across the repo -- inside the script enforcing the OTHER lesson. errors="replace" so a
    # stray byte degrades one character instead of killing an integrity check.
    proc = subprocess.run(
        ["git", "log", "--format=%h%x09%ad%x09%s", "--date=format:%Y-%m-%d %H:%M"],
        cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    out = proc.stdout or ""      # never None: a git failure must not become AttributeError
    found: dict[str, tuple[str, str, str]] = {}
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, stamp, subject = parts
        day, when = stamp.split(" ", 1)
        for m in re.finditer(r"\bR(\d+)\b", subject):
            key = "R" + m.group(1)
            found.setdefault(key, (when, sha, day))   # first hit = newest commit for that entry
    return found


def entries() -> list[tuple[str, str]]:
    """[( 'R83', body ), ...] -- body is the text until the next entry heading."""
    text = TODOS.read_text(encoding="utf-8", errors="replace")
    marks = [(m.start(), "R" + m.group(1)) for m in ENTRY_RE.finditer(text)]
    out = []
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((name, text[pos:end]))
    return out


def main() -> int:
    """Invariant: no time claimed in an entry may be in the FUTURE relative to HEAD.

    Deliberately weaker than "matches its own commit". An entry is often amended by a later
    commit whose subject never names it (R86's control note was added by 38797eb, titled
    'record the capacity control as in-flight'), so a per-entry ceiling flags honest edits.
    Future-relative-to-HEAD is *provable* and has no such false positives -- and it catches
    the real failure mode exactly: every one of R72-R87's fabrications sat hours ahead of
    the clock.

    Dates come from each entry's commit, so times are compared as full datetimes and a
    23:00 entry from a previous day is not flagged against a 14:34 HEAD today.
    """
    show_all = "--list" in sys.argv

    # A missing list is a broken checker, not a clean bill of health. Stated explicitly
    # because the previous failure mode was a raw FileNotFoundError traceback, which reads
    # as "the tool is broken" rather than "the tool cannot see what it audits" -- and
    # because an empty scan must never be able to print OK.
    if not TODOS.exists():
        print(f"CANNOT CHECK: {TODOS} does not exist.")
        print("This script audits the `### 5.3.R<N>` entries; point TODOS at the file")
        print("that holds them. It has moved once already (41534f2) and went unnoticed.")
        return 2

    commits = commit_times_by_entry()
    head = head_datetime()
    violations, checked, skipped = [], 0, []

    for name, body in entries():
        if name not in commits:
            skipped.append(name)
            continue
        when, sha, day = commits[name]
        body = QUOTED_RE.sub("", STRUCK_RE.sub("", body))
        claimed = {f"{int(h):02d}:{m}" for h, m in TIME_RE.findall(body)}
        if show_all:
            print(f"{name:<6} commit {sha} {day} {when}  claims: {sorted(claimed) or '-'}")
        for t in sorted(claimed):
            checked += 1
            stamp = datetime.strptime(f"{day} {t}", "%Y-%m-%d %H:%M")
            if stamp > head:
                violations.append((name, t, day, sha, when))

    matched = len(entries()) - len(skipped)
    print(f"\nchecked {checked} claimed time(s) across "
          f"{matched} entries with a matching commit")

    # Non-vacuity. Finding zero entries means the file moved again or the heading format
    # changed -- both of which previously produced a confident pass over nothing.
    if not entries():
        print(f"\nCANNOT CHECK: no `### 5.3.R<N>` entries found in {TODOS.name}.")
        print("Either the entries moved or the heading format changed. Refusing to")
        print("report OK on an empty scan.")
        return 2
    if skipped:
        print(f"{len(skipped)} entries have no commit naming them and were NOT checked "
              f"(they predate the R-numbered commit convention)")

    if violations:
        print(f"\n{len(violations)} IMPOSSIBLE TIMESTAMP(S) -- in the future relative to "
              f"HEAD ({head:%Y-%m-%d %H:%M}):\n")
        for name, t, day, sha, when in violations:
            print(f"  {name}: claims {day} {t}, but HEAD is {head:%H:%M} "
                  f"(entry committed {sha} at {when})")
        print("\nA time that has not happened yet was not read from a clock.")
        print("Fix: git log --date=format:'%H:%M' -- use that, or write the sha instead.")
        return 1

    print(f"OK -- no claimed time is in the future (HEAD {head:%Y-%m-%d %H:%M}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
