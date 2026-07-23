"""scripts/probe_error_analysis.py — classifier, inventory, dry-run plumbing.

Torch-free (host-side post-run tool). The fixture rows each carry an ``expect``
label; the classifier must agree with every one — dry-run enforces the same
contract at runtime, so fixture and classifier cannot drift silently.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "probe_error_analysis.py"
_FIXTURES = _SCRIPT.parent / "fixtures" / "probe_error_analysis"

_spec = importlib.util.spec_from_file_location("probe_error_analysis", _SCRIPT)
pea = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pea)


def _fixture_rows() -> list[dict]:
    return pea.load_jsonl(_FIXTURES / "generations.jsonl")


def test_fixture_covers_every_failure_mode():
    expects = {r["expect"] for r in _fixture_rows()}
    assert expects == {"correct", *pea.FAILURE_MODES}


def test_classifier_matches_fixture_expectations():
    rows = _fixture_rows()
    inventory = pea.build_inventory(rows)
    for row in rows:
        label, detail = pea.classify(row, inventory)
        assert label == row["expect"], (
            f"gold={row['answer']!r} gen={row['generation']!r}: "
            f"expected {row['expect']}, got {label} ({detail})"
        )


def test_inventory_from_menu_and_golds():
    rows = [
        {
            "set": "tool_selection",
            "prompt": "Toolbox: add, weather, translate. Pick one; "
            "the single right tool for this is",
            "answer": "weather",
            "generation": "",
        },
        # numeric gold must NOT enter the inventory; "no tool" must not either
        {"set": "arithmetic", "prompt": "1 + 1 =", "answer": "2", "generation": ""},
        {"set": "tool_selection", "prompt": "no menu here", "answer": "no tool",
         "generation": ""},
        # identifier-shaped golds of NON-tool sets must stay out (facts' Paris)
        {"set": "facts", "prompt": "The capital of France is", "answer": "Paris",
         "generation": ""},
    ]
    inv = pea.build_inventory(rows)
    assert inv == {"add", "weather", "translate"}


def test_no_tool_gold_flags_any_tool_reach():
    inv = {"translate", "get_clock"}
    row = {"answer": "no tool", "generation": "get_clock()"}
    assert pea.classify(row, inv)[0] == "wrong_tool"
    row = {"answer": "no tool", "generation": "no tool needed here"}
    assert pea.classify(row, inv)[0] == "correct"


def test_dry_run_exits_zero_and_reports(capsys):
    rc = pea.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry-run OK" in out
    assert "per-set failure modes" in out
    # aggregate context from the fixture report is printed too
    assert "aggregate probe results" in out


def test_report_only_mode_is_honest(capsys):
    rc = pea.main(["--report", str(_FIXTURES / "report.json")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "UNMEASURED" in out  # never fabricates per-item data


def test_out_writes_full_analysis(tmp_path, capsys):
    out_path = tmp_path / "analysis.json"
    rc = pea.main(
        ["--generations", str(_FIXTURES / "generations.jsonl"), "--out", str(out_path)]
    )
    assert rc == 0
    blob = json.loads(out_path.read_text(encoding="utf-8"))
    assert set(blob) == {"inventory", "sets", "rows"}
    assert len(blob["rows"]) == len(_fixture_rows())
    assert all("class" in r and "detail" in r for r in blob["rows"])
