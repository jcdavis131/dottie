"""`scout lab mrr`. 265 loc, no test file until 2026-08-02.

GOAT scored lab 7.17 with D4 0. Reading it found a defect in the revenue number itself.

`current_mrr` was `history[-1].get("mrr")` — the last ENTRY, not the last entry that
carries an mrr. Every field on `lab mrr` is optional, so `--trials 5 --note "..."` appends
a row with mrr=None. Measured on the exact expression:

    history  [{mrr: 420.0, ...}, {mrr: None, trials: 5, ...}]
    current_mrr          None
    remaining_to_1k      1000        <- should be 580
    customers_needed@79  13          <- should be 8

Logging a week of trials wiped the revenue number in a revenue tracker. The old comment had
the reasoning right — "MRR is a point-in-time figure, not a sum" — and the code did not
match it.

SCOUT_LAB_ROOT was added in the same change. The ledger path was hardcoded under
~/workspace/projects, so exercising the append path at all meant writing into the
operator's real mrr.jsonl.
"""

from __future__ import annotations

import json

import pytest

from bigbang.core.output import set_json_mode
from bigbang.plugins.lab import cli as lc


@pytest.fixture(autouse=True)
def lab_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_LAB_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _json_mode():
    set_json_mode(True)
    yield
    set_json_mode(False)


def _emitted(capsys) -> dict:
    payload = json.loads(capsys.readouterr().out)
    return payload.get("data") or payload


def test_a_trials_only_entry_does_not_wipe_current_mrr(capsys):
    """The defect. Two commands, and the second used to report zero revenue."""
    lc.mrr_cmd(trials=None, paid=3, mrr=420.0, churn=None, note="first paying users")
    capsys.readouterr()

    lc.mrr_cmd(trials=5, paid=None, mrr=None, churn=None, note="5 trials this week")
    payload = _emitted(capsys)

    assert payload["current_mrr"] == 420.0, payload
    assert payload["remaining_to_1k"] == 580.0, payload
    assert payload["customers_needed_at_79"] == 7, payload


def test_a_later_real_mrr_still_wins(capsys):
    """Non-vacuity: the fix must not pin to the FIRST mrr it ever saw."""
    lc.mrr_cmd(trials=None, paid=1, mrr=79.0, churn=None, note="")
    capsys.readouterr()
    lc.mrr_cmd(trials=None, paid=None, mrr=None, churn=None, note="quiet week")
    capsys.readouterr()
    lc.mrr_cmd(trials=None, paid=6, mrr=474.0, churn=None, note="growth")
    payload = _emitted(capsys)

    assert payload["current_mrr"] == 474.0, payload


def test_no_history_reports_zero_not_none(capsys):
    """An empty ledger must produce a number the arithmetic below it can use."""
    lc.mrr_cmd(trials=None, paid=None, mrr=None, churn=None, note="")
    payload = _emitted(capsys)
    assert payload["current_mrr"] == 0, payload
    assert payload["remaining_to_1k"] == 1000


def test_an_empty_call_appends_nothing(capsys, lab_root):
    """`lab mrr` with no flags is a READ. It must not write a row of Nones."""
    lc.mrr_cmd(trials=None, paid=None, mrr=None, churn=None, note="")
    capsys.readouterr()
    assert not (lab_root / "files" / "mrr.jsonl").exists()


def test_the_timestamp_is_timezone_aware(capsys, lab_root):
    """utcnow() returned a NAIVE datetime and the code appended "Z" to it — a claim, on a
    financial record. now(UTC) emits a real offset."""
    lc.mrr_cmd(trials=None, paid=1, mrr=79.0, churn=None, note="")
    capsys.readouterr()

    line = (lab_root / "files" / "mrr.jsonl").read_text(encoding="utf-8").strip()
    ts = json.loads(line)["ts"]
    assert ts.endswith("+00:00"), ts
    assert not ts.endswith("ZZ") and not ts.endswith("Z"), ts


def test_ledger_path_honours_scout_lab_root(lab_root):
    assert str(lc._mrr_path()).startswith(str(lab_root))


def test_ledger_path_falls_back_to_the_home_layout(monkeypatch):
    """Non-vacuity for the override: the documented default must still be the default."""
    from pathlib import Path

    monkeypatch.delenv("SCOUT_LAB_ROOT", raising=False)
    assert lc._mrr_path() == (
        Path.home() / "workspace" / "projects" / "first-1k-mo-passive" / "files" / "mrr.jsonl"
    )
