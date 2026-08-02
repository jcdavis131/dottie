"""Give the whole suite a throwaway HOME, so tests cannot write real user state.

WHY THIS FILE EXISTS. Nothing here monkeypatches a path; it redirects HOME/USERPROFILE
once, at import time, before any test module is loaded. That single lever moves
`Path.home()` for the pytest process AND for every subprocess it spawns (children
inherit `os.environ`), which matters because a child cannot see a monkeypatch — the
gap that let the following slip through for a long time:

  ~/.local/share/bigbang/secrets.json   `secrets set` / `rm` ran as real subprocesses
                                        against the DEVELOPER'S VAULT. The vault is a
                                        read-modify-write, and this repo already
                                        measured (3e301cb) that a torn vault plus one
                                        ordinary `set` is TOTAL loss of every secret.
  ~/.local/share/bigbang/auth.json      same, via `auth set-token`.
  ~/.local/share/bigbang/registry.json  same, via `tools add` / `tools rm`.
  ~/.local/share/bigbang/audit.jsonl    EVERY CLI subprocess appends here. Measured
                                        2026-08-01: 43.4 MB, 28,778 entries, no
                                        rotation anywhere in audit.py, and the command
                                        histogram is dominated by test traffic
                                        (`coverage report` x1435, `cite import` x1051)
                                        — a security audit trail swamped by its own
                                        test suite.
  ~/.dottie-claw/skills/                test_forge_loop installs a scaffolded tool
                                        beside REAL user skills (talk-like-a-caveman
                                        lives there).
  ~/.local/share/bigbang/herd/          the herd ledger. A diagnostic of mine
                                        destroyed 3798 bytes of it on 2026-08-01;
                                        that is what prompted this sweep.

WHY A conftest AND NOT 30 EDITED FILES. ~30 test modules spawn subprocesses. Patching
each is 30 chances to miss one, and a new test file added tomorrow would be unprotected
by default. This is opt-out-by-omission turned into safe-by-default.

WHY MODULE LEVEL AND NOT AN AUTOUSE FIXTURE. Several modules read `Path.home()` (and
bigbang.core.security computes VAULT_DIR, then mkdir's it) at IMPORT time. A fixture
runs after collection, so the real home would already have been touched. conftest.py is
imported before any test module, so this is early enough to matter.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Held at module scope so it lives for the whole session and is cleaned on exit.
#
# ignore_cleanup_errors is load-bearing on Windows, not defensive padding: the suite
# leaves sqlite handles and short-lived child processes touching this tree, so the
# teardown hit `PermissionError: [WinError 32] ... being used by another process` and
# printed a shutdown traceback AFTER the green result line. A run that prints a
# traceback while passing is how people learn to skim the tail of the output, which is
# the same "permanently-red trains you to ignore red" failure this repo already names
# for CI. The dir lands in %TEMP% and the OS reclaims it.
_HOME_TMP = tempfile.TemporaryDirectory(
    prefix="scout-tests-home-", ignore_cleanup_errors=True
)
os.environ["HOME"] = _HOME_TMP.name
os.environ["USERPROFILE"] = _HOME_TMP.name

# HOME is not the only lever, and assuming it was let a real write escape for as long as
# this file has existed. `policy.user_policy_file()` resolves in this order:
#
#     BIGBANG_POLICY_FILE  ->  XDG_CONFIG_HOME  ->  Path.home() / ".config"
#
# so both env vars sit ABOVE the redirect. `load_user_policy()` MATERIALIZES the default
# policy when the file is absent, so any test that consults policy writes it — and on a
# machine where XDG_CONFIG_HOME is set, that write lands outside the throwaway home.
#
# Found 2026-08-02 by the state-pollution gate on its first CI run (40044b1):
#
#     ADDED (1): /home/runner/.config/bigbang/policy.yaml
#     POLLUTION: 1 change(s) outside scheduler-owned paths, out of 196 watched
#
# It could not be seen locally: ~/.config/bigbang/policy.yaml ALREADY EXISTS on the dev
# box, so the same suite produced no diff there. A fresh runner has an empty home, which
# is the only environment where "was this created?" is answerable.
#
# HONEST LIMIT ON THIS FIX. The precedence gap above is PROVEN — with XDG_CONFIG_HOME set,
# user_policy_file() resolves outside the redirected home, measured directly. What is NOT
# proven is that XDG_CONFIG_HOME is what did it on the runner: the write did not reproduce
# on Windows under a forced XDG_CONFIG_HOME across test_policy/test_reach/test_core_extra
# (119 passed, nothing written), and subprocess envs were ruled out — every one in this
# repo is built from os.environ.copy(). The remaining candidate is a POSIX-only path.
#
# So this closes a real hole and CI adjudicates whether it was THE hole. The gate stays
# armed either way; if it fires again the step now dumps the resolved policy path and the
# relevant env vars, so the next run answers the question instead of narrowing it.
os.environ["XDG_CONFIG_HOME"] = str(Path(_HOME_TMP.name) / ".config")
os.environ.pop("BIGBANG_POLICY_FILE", None)
