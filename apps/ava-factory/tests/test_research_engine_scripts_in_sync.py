"""`research-engine/scripts/` duplicates `scripts/` — this keeps them from DIVERGING.

Found 2026-07-20 (TODOS 5.3.R80). Seven scripts exist as byte-identical copies in two
places under ``apps/ava-factory``:

    scripts/<name>.py                 (31 files; the general script dir)
    research-engine/scripts/<name>.py (7 files; all duplicates of the above)

Both are reachable, so this is not dead code that can simply be deleted:
``research-engine/run_autoresearch.sh`` does ``cd "$RESEARCH_ROOT"`` and then runs
``python3 scripts/autoresearch_runner.py`` — resolving to the research-engine copy — while
``scripts/autoresearch_runner.py`` itself resolves ``FACTORY_ROOT / "research-engine"`` as
a data root, i.e. it expects to be run from the factory root. Which file executes depends
on the entry point.

They are identical TODAY. The hazard is the day they are not: a fix applied to one copy
would silently not reach the other, and the behaviour would depend on how the job was
launched — the least debuggable failure shape there is. Nothing enforced that; now
something does.

This test deliberately asserts EQUALITY rather than picking a winner. Deduplicating (a
shim, a symlink, or deleting one side and fixing the caller) is a real change to how the
research jobs are launched and belongs to the operator, not to a test. Until then, the
invariant that matters is that the two copies never drift apart.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

_FACTORY = Path(__file__).resolve().parent.parent
_SCRIPTS = _FACTORY / "scripts"
_RE_SCRIPTS = _FACTORY / "research-engine" / "scripts"


def _duplicated_names() -> list[str]:
    if not _RE_SCRIPTS.is_dir() or not _SCRIPTS.is_dir():
        return []
    return sorted(
        p.name for p in _RE_SCRIPTS.glob("*.py") if (_SCRIPTS / p.name).is_file()
    )


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_the_duplicate_set_is_still_what_we_measured():
    """If a copy is added or removed, this test should be re-read, not silently pass.

    A drift check that quietly covers zero files is worse than no check: it reports green
    while enforcing nothing. Measured 2026-07-20: exactly 7 duplicated names.
    """
    names = _duplicated_names()
    if not _RE_SCRIPTS.is_dir():
        pytest.skip("research-engine/scripts/ is gone — the duplication was resolved")
    assert names, (
        "research-engine/scripts/ exists but duplicates nothing — re-read this test"
    )
    assert len(names) == 7, (
        f"the duplicate set changed: {len(names)} pairs now, 7 when this was written "
        f"({names}). Update the count deliberately, having checked WHY it changed."
    )


@pytest.mark.parametrize("name", _duplicated_names())
def test_duplicated_script_copies_are_byte_identical(name: str):
    """Both copies are live entry points; drift makes behaviour depend on the launcher."""
    a, b = _SCRIPTS / name, _RE_SCRIPTS / name
    assert _sha(a) == _sha(b), (
        f"{name} has DIVERGED between scripts/ and research-engine/scripts/.\n"
        f"  {a}\n  {b}\n"
        "Both are reachable (run_autoresearch.sh runs the research-engine copy), so a fix "
        "applied to only one silently does not reach jobs launched the other way. Either "
        "apply the change to both, or resolve the duplication properly and update this test."
    )
