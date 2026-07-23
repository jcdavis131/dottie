"""evals/probe_items/tool_selection.jsonl — additive tool-selection probe breadth.

This file is ADDITIVE: evals/probes.py deliberately does not score it yet, so
the existing 6-set probe suite stays byte-identical for A/B comparability.
These tests pin the new set's contract: schema parity with the existing probe
items, gold answers drawn from the trained tool inventory (tool_curriculum's
L3 catalog), and a surface form distinct from the training templates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_ITEMS = (
    Path(__file__).resolve().parent.parent
    / "evals"
    / "probe_items"
    / "tool_selection.jsonl"
)

# Mirror of dottie/datagen/tool_curriculum.py _CATALOG_POOL names (the L3
# tool-selection catalog the model trains on). test_catalog_parity below
# cross-checks this copy against the source when the data stack is present.
CATALOG = {
    "get_clock",
    "word_count",
    "char_count",
    "repo_grep",
    "repo_read_file",
    "list_dir",
    "multiply",
    "add",
    "sum",
    "currency_convert",
    "summarize",
    "translate",
    "weather",
    "db_query",
    "send_email",
    "web_search",
    "delete_file",
}
NO_TOOL = "no tool"


def _rows() -> list[dict]:
    return [
        json.loads(line)
        for line in _ITEMS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_schema_matches_existing_probe_sets():
    rows = _rows()
    assert len(rows) == 20
    for row in rows:
        assert set(row) == {"prompt", "answer"}
        assert row["prompt"].strip() and row["answer"].strip()


def test_prompts_unique():
    prompts = [r["prompt"] for r in _rows()]
    assert len(prompts) == len(set(prompts))


def test_answers_in_trained_inventory():
    for row in _rows():
        assert row["answer"] in CATALOG | {NO_TOOL}, row["answer"]
    # destructive tool is distractor-only (the curriculum teaches refusing it)
    assert all(r["answer"] != "delete_file" for r in _rows())
    # breadth: most of the catalog appears as a gold at least once
    golds = {r["answer"] for r in _rows()} - {NO_TOOL}
    assert len(golds) >= 14


def test_gold_tool_listed_in_its_own_menu():
    for row in _rows():
        if row["answer"] == NO_TOOL:
            continue
        menu = row["prompt"].split(".", 1)[0]
        assert row["answer"] in menu, row["prompt"]


def test_surface_form_differs_from_training_templates():
    """Decontamination discipline (evals/eval_sets.py): the probe surface-form
    must not coincide with tool_curriculum's training templates."""
    text = _ITEMS.read_text(encoding="utf-8")
    for training_marker in (
        "Available tools (choose",
        "Thought:",
        "Action:",
        "Observation:",
    ):
        assert training_marker not in text, training_marker


def test_byte_hygiene_lf_only():
    """Same contract as probe_items_gen._write_jsonl: LF-only, trailing LF —
    keeps the file byte-stable across platforms."""
    data = _ITEMS.read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"\n")


def test_catalog_parity():
    """Cross-check the CATALOG mirror against the real _CATALOG_POOL. Skips on
    images without the data stack (base.py imports zstandard — see conftest)."""
    pytest.importorskip("zstandard")
    from dottie.datagen.tool_curriculum import _CATALOG_POOL

    assert CATALOG == {name for name, _, _ in _CATALOG_POOL}
