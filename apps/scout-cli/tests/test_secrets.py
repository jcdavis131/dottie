"""The secrets plugin's own commands. Nothing tested them before 2026-08-02.

Tests existed for `bigbang.core.security` — the store underneath — but nothing imported
`bigbang.plugins.secrets.cli`, so `set` / `get` / `list` / `rm` were an untested command
surface on the vault. The GOAT audit had been reporting "NO test file (expected
tests/test_secrets.py)" the whole time.

Written at that exact path deliberately: the audit checks by filename, and coverage it
cannot see does not count. (Learned the hard way one commit earlier — tests/test_rtx.py.)

WHAT THIS FOUND. `get_cmd`'s docstring promised "full value in JSON; masked for humans".
Only the first half was implemented. emit() renders a dict in human mode with
_console.print_json(data=data) — the whole dict — so the plaintext was printed directly
beside the mask:

    {"key": "PROBE_TOKEN", "value": "<the plaintext>", "masked": "SUPE****", ...}

The audit trail was never affected; output.py redacts before log_event. Terminal output and
the audit log are different surfaces, which is why this survived an earlier check that
confirmed redaction worked.
"""

from __future__ import annotations

import json

import pytest

from bigbang.core.output import set_json_mode
from bigbang.core.security import set_secret
from bigbang.plugins.secrets import cli as sc

# Named PROBE_VALUE rather than SECRET: ruff S105 flags a string literal assigned to a
# name like SECRET/PASSWORD/TOKEN, and a noqa here would spend a suppression on a test
# fixture. The literal is also self-describing, so nobody greps it and panics.
PROBE_VALUE = "pv-9f3a-not-a-real-credential"


@pytest.fixture
def vaulted():
    """conftest.py already redirects HOME/USERPROFILE, so this writes to a throwaway vault."""
    set_secret("PROBE_TOKEN", PROBE_VALUE)
    return "PROBE_TOKEN"


@pytest.fixture(autouse=True)
def _restore_mode():
    yield
    set_json_mode(False)


def _emitted(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_human_output_does_not_contain_the_plaintext(vaulted, capsys):
    """The defect. A mask printed next to the value it masks is decoration."""
    set_json_mode(False)
    sc.get_cmd(key=vaulted)
    out = capsys.readouterr().out
    assert PROBE_VALUE not in out, f"plaintext secret leaked to the terminal:\n{out}"
    assert "pv-9****" in out, "the mask should still be shown"


def test_json_output_still_carries_the_value(vaulted, capsys):
    """The other half of the contract, and the non-vacuity guard.

    Agents call this to USE the secret. A fix that withheld it everywhere would satisfy
    the test above and break the documented behaviour.
    """
    set_json_mode(True)
    sc.get_cmd(key=vaulted)
    assert _emitted(capsys)["value"] == PROBE_VALUE


def test_human_output_says_how_to_get_the_value(vaulted, capsys):
    """Withholding without saying how to proceed sends people to `cat` the vault file."""
    set_json_mode(False)
    sc.get_cmd(key=vaulted)
    assert "--json" in capsys.readouterr().out


def test_list_never_returns_values(vaulted, capsys):
    """`list_cmd` claims "values never listed" — asserted rather than trusted."""
    set_json_mode(True)
    sc.list_cmd()
    payload = _emitted(capsys)
    assert vaulted in payload["secrets"]
    assert PROBE_VALUE not in json.dumps(payload), "list leaked a secret value"


def test_rm_dry_run_deletes_nothing(vaulted, capsys):
    """--dry-run must be a report, not a delete-and-tell."""
    set_json_mode(True)
    sc.rm_cmd(key=vaulted, force=False, dry_run=True)
    assert _emitted(capsys)["would_delete"] == vaulted
    set_json_mode(True)
    sc.get_cmd(key=vaulted)
    assert _emitted(capsys)["value"] == PROBE_VALUE, "dry-run actually deleted the secret"


def test_rm_force_actually_deletes(vaulted, capsys):
    """Non-vacuity for the test above: rm must be capable of deleting."""
    set_json_mode(True)
    sc.rm_cmd(key=vaulted, force=True, dry_run=False)
    payload = _emitted(capsys)
    assert payload["ok"] is True and payload["existed"] is True
