"""The suite must not be able to reach the operator's real home.

WHY THIS FILE EXISTS. This suite once wrote to the developer's real secrets vault, auth
store, skill registry, audit log, herd ledger and dottie-claw directory — every run. It was
found the hard way: a diagnostic write destroyed ~/.local/share/bigbang/herd/sessions.json
(3798 bytes, no backup, not recoverable). The remedy was `tests/conftest.py` redirecting
HOME and USERPROFILE to a throwaway directory before anything imports.

That remedy is two `os.environ` assignments. Two lines are easy to lose in an unrelated
cleanup, and the failure is silent — the suite still passes, it just starts writing to real
files again, and the next person finds out the way the first one did. So this asserts the
redirect instead of trusting it.

Deliberately an assertion about the environment rather than a before/after diff of the
filesystem. A diff can come back clean because nothing happened to run that write path this
time; that is a property of the run, not of the isolation. This checks the isolation.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEMP_ROOT = Path(tempfile.gettempdir()).resolve()


def _under_temp(path: Path) -> bool:
    try:
        return str(path.resolve()).startswith(str(TEMP_ROOT))
    except OSError:
        return False


def test_home_resolves_into_a_throwaway_directory():
    """`Path.home()` is what the vault, auth store and registry all build their paths from.

    On Windows it follows USERPROFILE and on POSIX it follows HOME, which is why conftest
    sets BOTH. The real profile (C:/Users/<name>) does not live under %TEMP%, so this
    discriminates cleanly: if the redirect goes away, home becomes the real one and this
    fails immediately.
    """
    home = Path.home()
    assert _under_temp(home), (
        f"Path.home() is {home}, which is not under {TEMP_ROOT}. The suite can now write "
        "to real user state — restore the HOME/USERPROFILE redirect at the top of "
        "tests/conftest.py. This suite previously destroyed a real herd ledger."
    )


def test_both_env_vars_are_set_and_agree():
    """POSIX reads HOME, Windows reads USERPROFILE.

    Setting only one leaves the suite isolated on the developer's platform and writing to
    real state on the other, which is the kind of bug that survives review because it
    passes everywhere it gets run.
    """
    home_env = os.environ.get("HOME")
    profile_env = os.environ.get("USERPROFILE")
    assert home_env, "HOME is unset — conftest's redirect is not in effect"
    assert profile_env, "USERPROFILE is unset — conftest's redirect is not in effect"
    assert Path(home_env).resolve() == Path(profile_env).resolve(), (
        f"HOME ({home_env}) and USERPROFILE ({profile_env}) disagree, so isolation holds "
        "on one platform and not the other"
    )
    assert _under_temp(Path(home_env)), f"HOME is not under {TEMP_ROOT}"


def test_the_redirect_is_visible_to_subprocesses():
    """os.environ, not monkeypatch — the distinction the original fix turned on.

    Parts of this CLI shell out, and a child process inherits `os.environ` but cannot see a
    pytest monkeypatch. An isolation that only holds in-process would leave exactly the
    subprocess paths writing to the real home, so this asserts a real child agrees.
    """
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; print(Path.home())"],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"probe failed: {out.stderr[:200]}"
    child_home = Path(out.stdout.strip())
    assert _under_temp(child_home), (
        f"a subprocess sees home as {child_home}, outside {TEMP_ROOT}. The redirect is not "
        "reaching children — check it uses os.environ rather than monkeypatch."
    )
