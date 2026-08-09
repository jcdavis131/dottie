#!/usr/bin/env python3
"""Render an operations digest from the scoreboard, TODO.md, and test inventory.

WHY: the ops venture needs one page stating what the monitor scoreboard
records, how much open work TODO.md holds, and how many repo-root self-test
files exist — numbers copied or counted, never derived beyond min/max, never
ranked. TODO.md is handled mechanically only: its own header warns that the
NEXT section is exhausted and that naming subsets rots, so this digest counts
open checkboxes and repeats the canonical pointer to HANDOFF.md verbatim; it
does not enumerate or rank items. An absent or unreadable scoreboard is stated
as a measured fact (the exporters-skip, never-invent precedent from
build_runs_readout.mjs). The test-file figure is a file count at generation
time, labeled as such — not a coverage claim. Sources cited in frontmatter are
the files whose bytes were read (scoreboard and TODO.md); test files are
counted by name only and are therefore stated in the body, not cited.

Called by the playbook engine (scripts/business/playbook.py), which resolves
inputs and injects the timestamp:

    uv run python scripts/business/playbook.py run ops --artifact ops-digest

Contract: generate(inputs, params, generated_at) -> {"ops_digest.md": text}.
Raises FileNotFoundError when the required TODO input is absent; the engine
maps that to status "skipped-missing-input". Pure over the given paths:
read-only, deterministic, no network. Loaded standalone by file path — stdlib
only, no package imports.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

_METHOD = (
    "Counts and copied figures from the monitor scoreboard JSON, open-checkbox "
    "count from TODO.md, and a repo-root self-test file count; no item is "
    "enumerated or ranked and no absent value is filled."
)
_NO_SCOREBOARD = "No monitor scoreboard was present at generation time."
_POINTER = (
    'TODO.md directs open-work triage to HANDOFF.md '
    '("Open, needing an operator decision").'
)
_OPEN_BOX_RE = re.compile(r"^\s*- \[ \]", flags=re.MULTILINE)


def _sha256(path: Path) -> str:
    """Hex sha256 of a file's bytes (small local helper; modules stay standalone)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_root() -> Path:
    """Repo root: DOTTIE_ROOT override, else three levels above this module."""
    override = os.environ.get("DOTTIE_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[3]


def _rel(path: Path) -> str:
    """Repo-relative posix path when possible; absolute posix otherwise."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(_repo_root()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _scoreboard_lines(paths: list[Path]) -> tuple[list[str], Path | None]:
    """Measured sentences about the scoreboard; (lines, cited path or None).

    A malformed or shapeless file is treated as absent and said so — numbers
    are copied from a parseable artifact or not stated at all.
    """
    if not paths:
        return [_NO_SCOREBOARD], None
    path = paths[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return [
            _NO_SCOREBOARD,
            f"A file existed at `{_rel(path)}` but did not parse as JSON; "
            "it is treated as absent and not cited.",
        ], None
    agents = data.get("agents") if isinstance(data, dict) else None
    totals = data.get("totals") if isinstance(data, dict) else None
    if not isinstance(agents, dict) or not isinstance(totals, dict):
        return [
            _NO_SCOREBOARD,
            f"A file existed at `{_rel(path)}` but lacked the agents/totals "
            "structure; it is treated as absent and not cited.",
        ], None
    lines = [
        f"Agents recorded: {len(agents)}. "
        f"Total events: {totals.get('events', '(not recorded)')}."
    ]
    rates = [
        row["ok_rate"]
        for row in agents.values()
        if isinstance(row, dict)
        and isinstance(row.get("ok_rate"), (int, float))
        and not isinstance(row.get("ok_rate"), bool)
    ]
    if rates:
        lines.append(
            f"OK-rate range: {min(rates)} (minimum) to {max(rates)} (maximum). "
            "Figures are copied from the scoreboard artifact; only the minimum "
            "and maximum are derived."
        )
    return lines, path


def generate(
    inputs: dict[str, list[Path]],
    params: dict[str, object],
    generated_at: str,
) -> dict[str, str]:
    """Build ops_digest.md from scoreboard, TODO.md, and the test-file count."""
    todo_paths = inputs.get("todo") or []
    if not todo_paths:
        raise FileNotFoundError("TODO.md absent")
    todo_path = todo_paths[0]
    try:
        todo_text = todo_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FileNotFoundError(f"TODO.md unreadable: {todo_path}") from exc
    open_count = len(_OPEN_BOX_RE.findall(todo_text))

    scoreboard_lines, scoreboard_path = _scoreboard_lines(
        inputs.get("scoreboard") or []
    )
    test_count = len(inputs.get("test_files") or [])

    sources = [(_rel(todo_path), _sha256(todo_path))]
    if scoreboard_path is not None:
        sources.insert(0, (_rel(scoreboard_path), _sha256(scoreboard_path)))

    out = [
        "---",
        "generated_by: scripts/business/generators/ops_digest.py",
        f"generated_at: {json.dumps(generated_at)}",
        "classification: REAL",
        "method: >-",
        "  Counts and copied figures from the monitor scoreboard JSON, open-checkbox",
        "  count from TODO.md, and a repo-root self-test file count; no item is",
        "  enumerated or ranked and no absent value is filled.",
        "measured: true",
        "sources:",
    ]
    for rel_path, digest in sources:
        out.append(f"  - path: {json.dumps(rel_path)}")
        out.append(f"    sha256: {json.dumps(digest)}")
    out += ["---", "", "# Operations digest", ""]
    out += ["## Scoreboard summary", ""]
    out += scoreboard_lines
    out += ["", "## Open work", ""]
    out.append(f"Open checkbox lines (`- [ ]`) in TODO.md: {open_count}.")
    out.append(_POINTER)
    out += ["", "## Test inventory", ""]
    out.append(
        f"repo-root self-test files: {test_count} "
        "(scripts/test_*.py, counted at generation time)"
    )
    out.append("")
    return {"ops_digest.md": "\n".join(out)}
