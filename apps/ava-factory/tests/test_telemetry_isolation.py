"""The suite must not write to the operator's live telemetry.

WHY THIS FILE EXISTS. Until 2026-08-01 every `pytest tests` run appended test records to
the real apps/ava-factory/reports/ava_telemetry.jsonl (measured: 41938 -> 47183 bytes) and
rewrote dottie_telemetry.jsonl. dottie/telemetry.py resolves TELEMETRY_DIR ONCE AT IMPORT
TIME from DOTTIE_TELEMETRY_DIR / AVA_TELEMETRY_DIR, falling back to `<repo>/reports`, and
the suite set neither — so importing the module bound every telemetry path to live files.

The fix is three lines in tests/conftest.py. Three lines are easy to delete during an
unrelated cleanup, and the symptom is invisible: the suite still passes, the pollution just
resumes, and nobody notices until real telemetry has test records in it. A fix with no test
is a fix with a countdown on it, so this asserts the redirect rather than trusting it.

An earlier sweep (`79cad30`) concluded this suite touched no real state. It was measured
honestly against the wrong corpus — home directories only, while these files live in-repo
and gitignored, invisible to both that snapshot and `git status`. This test is deliberately
an assertion about paths rather than another diff, because a diff can be clean for reasons
that have nothing to do with the property being checked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent
REAL_REPORTS = APP_ROOT / "reports"


@pytest.fixture(scope="module")
def telemetry():
    return pytest.importorskip("dottie.telemetry")


def test_telemetry_dir_is_not_the_real_reports_dir(telemetry):
    """The whole point. If conftest's redirect is removed, this is what catches it."""
    resolved = Path(telemetry.TELEMETRY_DIR).resolve()
    assert resolved != REAL_REPORTS.resolve(), (
        f"TELEMETRY_DIR is the live reports directory ({resolved}). The suite will append "
        "test records to the operator's real telemetry. Restore the "
        "DOTTIE_TELEMETRY_DIR / AVA_TELEMETRY_DIR redirect at the top of tests/conftest.py."
    )


def test_no_telemetry_path_lands_inside_the_repo(telemetry):
    """Not just the directory — every derived file path.

    Checked individually because they are separate module-level constants: a partial
    redirect that fixed TELEMETRY_DIR while leaving one path hardcoded would pass the test
    above and still write to a live file.
    """
    for name in ("JSONL_PATH", "LIVE_STATUS_PATH", "LEGACY_JSONL", "LEGACY_LIVE"):
        path = Path(getattr(telemetry, name)).resolve()
        assert not str(path).startswith(str(REAL_REPORTS.resolve())), (
            f"{name} resolves inside the live reports directory: {path}"
        )


def test_the_redirect_env_vars_are_actually_set():
    """Non-vacuity guard for the two assertions above.

    Both tests compare against REAL_REPORTS. If dottie.telemetry ever stopped exposing
    these constants, or the module were skipped, they could pass while checking nothing.
    This pins the mechanism itself: conftest sets the environment, and it must still be set
    when tests run. os.environ rather than monkeypatch, because subprocesses inherit the
    environment and cannot see a monkeypatch.
    """
    for var in ("DOTTIE_TELEMETRY_DIR", "AVA_TELEMETRY_DIR"):
        value = os.environ.get(var)
        assert value, f"{var} is unset — tests/conftest.py's redirect is not in effect"
        assert Path(value).resolve() != REAL_REPORTS.resolve(), (
            f"{var} points at the live reports directory"
        )
