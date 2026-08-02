"""Every skill that branches on `mode` must reject a mode it does not know.

WHY THIS FILE EXISTS. safety-scanner used to test `mode == "real"`, then `mode == "mock"`,
and let everything else fall through to the weak regex path while still returning a PASSING
verdict (fixed in e63954d). Probing the rest of the package on 2026-08-02 found the same
shape, differently expressed, in two skills that had no behavioural tests at all:

    run(mode="banana")  ->  jspace-inspector: a payload stamped `"mode": "real"`
    run(mode="banana")  ->  openwiki-sync:    a payload stamped `"mode": "real"`

Neither fails open on the VERDICT — both returned pass=False — so this is not the
safety-scanner bug repeated. It is the provenance half of it: the one field a caller reads
to tell mock from real reported what the code did rather than what was asked for, and a
typo silently ran the expensive real branch (for jspace-inspector, the canonical J-tests
against a live model).

Written as a SWEEP over the package rather than three separate tests, because the defect
was found by asking the same question of every skill, and a new skill should have to answer
it too. A per-skill test would have covered the two that were broken and nothing else.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _load(skill_dir: Path):
    spec = importlib.util.spec_from_file_location(
        f"_probe_{skill_dir.name.replace('-', '_')}", skill_dir / "skill.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mode_taking_skills():
    """Skills whose run() accepts a `mode` argument — the only ones this can apply to."""
    out = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if not (d / "skill.py").is_file():
            continue
        try:
            mod = _load(d)
            run = getattr(mod, "run", None)
            if run and "mode" in inspect.signature(run).parameters:
                out.append((d.name, mod))
        except Exception:
            # A skill that will not import is a different problem, caught elsewhere.
            continue
    return out


MODE_SKILLS = _mode_taking_skills()


def test_the_sweep_actually_found_skills():
    """Non-vacuity. An empty list would make every parametrised test below pass silently,
    which is the exact shape this package's own safety-scanner bug wore."""
    assert len(MODE_SKILLS) >= 4, f"only found {[n for n, _ in MODE_SKILLS]}"


@pytest.mark.parametrize("name,mod", MODE_SKILLS, ids=[n for n, _ in MODE_SKILLS])
def test_unknown_mode_is_refused_not_guessed(name, mod):
    """The core contract: an unrecognised mode must raise, not pick a branch.

    Deliberately NOT asserting a specific exception type — skills may reasonably differ —
    only that it refuses. Silently proceeding is the defect.
    """
    with pytest.raises(Exception) as exc:
        mod.run(mode="banana")
    assert "banana" in str(exc.value), (
        f"{name} rejected the mode but did not say which value was rejected; a caller "
        f"debugging a typo needs to see it. Got: {exc.value!r}"
    )


@pytest.mark.parametrize("name,mod", MODE_SKILLS, ids=[n for n, _ in MODE_SKILLS])
def test_mock_mode_still_works_and_labels_itself_mock(name, mod):
    """The guard must not have broken the path everything actually uses.

    Also pins the provenance half: mock output says mock. That is the field that was
    lying — `run(mode="banana")` returned `"mode": "real"` — so it is asserted rather
    than assumed to follow from the guard.
    """
    result = mod.run(mode="mock")
    assert isinstance(result, dict), f"{name} did not return a dict in mock mode"
    if "mode" in result:
        assert result["mode"] == "mock", (
            f"{name} ran in mock mode but labelled its output {result['mode']!r}"
        )
