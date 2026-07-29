# Solo personal project, no connection to employer, built with public/free-tier only
"""The resolution error must name the file that already holds the answer.

`resolve.factory_code_root()` used to fail with the probed-path list and stop. Technically
honest, and it cost four hours (TODOS 5.3.R87): the daemon has always had
AVA_FACTORY_ROOT set in a gitignored machine-local env file two directories away, so
the error meant "this SHELL is unconfigured" while it read as "this REPO is broken".
A whole suite was reported red and a nonexistent operator decision was requested.

The hint IS the fix, and nothing pinned it. A later tidy-up of the message would drop
it silently and cost the next reader the same four hours, so these tests pin the three
things that make it work: it appears when the variable is unset, it stays away when it
is set (where it would be noise), and the path it names is real.

    cd apps/dottie && python -m pytest tests/test_resolve_error_message.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dottie import resolve

# apps/dottie/, from apps/dottie/tests/
APP = Path(__file__).resolve().parents[1]
ENV_DIR = APP / "research_orchestration"
ENV_EXAMPLE = ENV_DIR / "research_env.local.ps1.example"


def _force_failure(monkeypatch, env_value):
    """Make resolution fail deterministically, with AVA_FACTORY_ROOT as given."""
    if env_value is None:
        monkeypatch.delenv("AVA_FACTORY_ROOT", raising=False)
    else:
        monkeypatch.setenv("AVA_FACTORY_ROOT", env_value)
    # No candidate contains the factory code, so every path is exhausted and the
    # message is built. Patching the predicate rather than the candidate list keeps
    # the real probe order in the message.
    monkeypatch.setattr(resolve, "_has_factory_code", lambda _c: False)
    with pytest.raises(resolve.DottieResolutionError) as excinfo:
        resolve.factory_code_root()
    return str(excinfo.value)


def test_the_named_env_file_lives_where_the_message_says(tmp_path, monkeypatch):
    """Anti-rot, and the reason this file exists at all. An error message that names
    a path is a promise; if the directory moves, the message becomes a lie that reads
    like help. The `.local.ps1` itself is GITIGNORED (apps/dottie/.gitignore:8), so a
    fresh clone legitimately lacks it — assert the tracked directory and the tracked
    `.example` instead, which is what a new box actually copies from."""
    msg = _force_failure(monkeypatch, None)
    named = "apps/dottie/research_orchestration/research_env.local.ps1"
    assert named in msg, f"message no longer names the env file: {msg}"
    assert ENV_DIR.is_dir(), f"message names {named} but {ENV_DIR} does not exist"
    assert ENV_EXAMPLE.is_file(), (
        f"{ENV_EXAMPLE.name} is gone, so a fresh clone has nothing to copy from and "
        f"the message points at a file that can never exist there"
    )


def test_the_example_actually_sets_the_variable_the_message_promises():
    """The message says "read that file for this box's working value". If the example
    stopped setting AVA_FACTORY_ROOT, that sentence would send the reader somewhere
    that does not answer the question."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "AVA_FACTORY_ROOT" in text, (
        f"{ENV_EXAMPLE.name} no longer sets AVA_FACTORY_ROOT"
    )


def test_hint_appears_when_the_variable_is_unset(monkeypatch):
    msg = _force_failure(monkeypatch, None)
    assert "AVA_FACTORY_ROOT is NOT set in this environment" in msg
    assert "gitignored" in msg, "the message no longer says why the file is missing"


def test_hint_is_absent_when_the_variable_is_set(monkeypatch, tmp_path):
    """The other half, and the half that makes the first one meaningful. If the hint
    were unconditional it would fire when AVA_FACTORY_ROOT IS set — where "it is NOT
    set" is simply false and sends the reader to the wrong file."""
    msg = _force_failure(monkeypatch, str(tmp_path))
    assert "is NOT set in this environment" not in msg, (
        "the hint fires even when the variable is set, and then it is wrong"
    )
    assert "research_env.local.ps1" not in msg


def test_the_probed_paths_are_still_reported(monkeypatch, tmp_path):
    """The hint ADDS to the old message; it must not have replaced it. The probe list
    is what tells you which checkout was actually consulted."""
    msg = _force_failure(monkeypatch, str(tmp_path))
    assert "Probed:" in msg
    assert str(tmp_path) in msg, "an explicit AVA_FACTORY_ROOT is not in the probe list"
    assert "Set AVA_FACTORY_ROOT or DOTTIE_ROOT" in msg
