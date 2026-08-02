"""The ava plugin's factory resolution. 813 loc, no test file until 2026-08-02.

GOAT scored ava 5.50, last in the repo. Reading it rather than acting on the number found a
LIVE defect: `scout ava` was operating against a superseded factory checkout.

    DOTTIE_ROOT                            <unset>
    ~/workspace/dottie/apps/ava-factory    does not exist
    -> ~/workspace/ava-agi-factory-v6-4    EXISTS, and won                 <- superseded
    <repo>/apps/ava-factory                EXISTS, never consulted         <- canonical

Two causes. The canonical repo-relative path was not a candidate at all, and the legacy
fallback was `return`ed WITHOUT an .exists() check while the two candidates above it were
guarded — so the one path nobody verified is the one that shipped.

These pin the ORDER, not just the happy path. A test that only asserts "resolves to
something that exists" would have passed against the superseded tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bigbang.plugins.ava import cli as ac


def test_resolves_to_the_checkout_this_plugin_lives_in():
    """The defect. The canonical factory sits in the same repo as this file."""
    got = ac._resolve_factory_root()
    assert got.exists(), got
    assert got.name == "ava-factory", got
    # It must be THIS repo's copy, not a sibling checkout that happens to exist.
    repo = Path(ac.__file__).resolve()
    assert str(got).lower().startswith(str(repo.parents[5]).lower()), (
        f"resolved outside this checkout: {got} (repo root {repo.parents[5]})"
    )


def test_does_not_pick_the_superseded_standalone_tree():
    """~/workspace/ava-agi-factory-v6-4 exists on the dev box and used to win.

    Named explicitly rather than checked generically: this is the exact path that shipped,
    and a generic 'resolves to something' assertion passed against it for as long as the
    bug existed.
    """
    got = ac._resolve_factory_root()
    assert "ava-agi-factory-v6-4" not in str(got), (
        f"resolved to the superseded standalone factory: {got}"
    )


def test_dottie_root_is_honoured_when_it_points_at_a_real_tree(tmp_path, monkeypatch):
    """The operator override still works — non-vacuity for the ordering above.

    Without this, a resolver hardcoded to the repo-relative path would satisfy both tests
    above and silently ignore DOTTIE_ROOT.
    """
    fake = tmp_path / "apps" / "ava-factory"
    fake.mkdir(parents=True)
    monkeypatch.setenv("DOTTIE_ROOT", str(tmp_path))
    # The in-repo canonical path is found first by design, so assert the override is
    # REACHED rather than that it wins: point the walk at a tree with no apps/ava-factory.
    monkeypatch.setattr(ac, "__file__", str(tmp_path / "nowhere" / "cli.py"))
    got = ac._resolve_factory_root()
    assert got == fake, got


def test_a_nonexistent_dottie_root_falls_through(tmp_path, monkeypatch):
    """A DOTTIE_ROOT pointing nowhere must not be returned unchecked."""
    monkeypatch.setenv("DOTTIE_ROOT", str(tmp_path / "does-not-exist"))
    got = ac._resolve_factory_root()
    assert got.exists(), got
    assert "does-not-exist" not in str(got)


def test_every_candidate_is_existence_checked(monkeypatch, tmp_path):
    """The structural fix. The old code guarded two candidates and returned a third raw.

    With no candidate present the resolver must still name the CANONICAL location, so an
    error message points at where the factory should be rather than where it used to be.
    """
    monkeypatch.delenv("DOTTIE_ROOT", raising=False)
    monkeypatch.setattr(ac, "__file__", str(tmp_path / "nowhere" / "cli.py"))
    monkeypatch.setattr(ac.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    got = ac._resolve_factory_root()
    assert "ava-agi-factory-v6-4" not in str(got), (
        f"fell back to the superseded tree when nothing existed: {got}"
    )


def test_module_level_factory_constant_matches_the_resolver():
    """FACTORY is bound at import. If the two ever disagree, 15 call sites read the stale one.

    Lowercase in the test name because ruff N802 flags an uppercase segment, and spending a
    noqa on a test name is not worth it — same call as PROBE_VALUE in test_secrets.py.
    """
    assert ac.FACTORY == ac._resolve_factory_root()


@pytest.mark.parametrize("attr", ["FACTORY"])
def test_factory_constant_is_a_path(attr):
    assert isinstance(getattr(ac, attr), Path)
