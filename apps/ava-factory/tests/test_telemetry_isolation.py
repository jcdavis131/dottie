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
import sys
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


def test_the_per_mode_log_sink_is_not_the_real_logs_dir(telemetry):
    """The instance this file's own docstring predicted and then missed.

    test_no_telemetry_path_lands_inside_the_repo says it exactly: "a partial redirect that
    fixed TELEMETRY_DIR while leaving one path hardcoded would pass the test above and
    still write to a live file." It then checks four constants, and _LOGS_DIR — the one
    that WAS hardcoded — is not among them:

        telemetry.py:44  TELEMETRY_DIR  <- DOTTIE_TELEMETRY_DIR / AVA_TELEMETRY_DIR / reports
        telemetry.py:61  _LOGS_DIR      <- _REPO_ROOT / "logs"      no env escape at all

    log_event() appends to _LOGS_DIR/cron-dottie-<source>.log, so the suite wrote into the
    repo's own logs/ on every run WITH the redirect in place. Caught 2026-08-02 by the
    state-pollution gate's first CI run against this suite (763402e), not by this file.

    Checked separately from the four above because it lives under logs/, not reports/, so a
    REAL_REPORTS prefix check cannot see it.
    """
    real_logs = (APP_ROOT / "logs").resolve()
    resolved = Path(telemetry._LOGS_DIR).resolve()
    assert resolved != real_logs, (
        f"_LOGS_DIR is the live logs directory ({resolved}). log_event() will append to "
        "the repo's own cron-dottie-*.log files. _LOGS_DIR has NO env var — restore the "
        "explicit rebind in tests/conftest.py."
    )


def test_the_conftest_rebind_did_not_silently_no_op():
    """The rebind is inside a try/except ImportError. That can pass by doing nothing.

    Not hypothetical, and not a guess: while sweeping for other un-redirectable sinks I ran
    a capture harness as `python <elsewhere>/script.py`, which puts the SCRIPT's directory
    on sys.path[0] instead of the cwd. `import dottie.telemetry` in conftest failed, the
    except swallowed it, `_telemetry` became None, and the rebind silently did not happen.
    The suite still collected and still passed. That is the whole failure mode.

    The except is still correct — if dottie is unimportable, no test can import it either,
    so there is no writer to redirect — but "correct when it fires" is not "harmless when
    it fires by accident". This asserts it did not fire here.
    """
    conftest = sys.modules.get("conftest") or sys.modules.get("tests.conftest")
    assert conftest is not None, "conftest module not importable by name; adjust this test"
    assert getattr(conftest, "_telemetry", None) is not None, (
        "conftest's `import dottie.telemetry` failed and was swallowed, so _LOGS_DIR was "
        "never rebound. The suite is writing to the repo's real logs/ directory."
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
