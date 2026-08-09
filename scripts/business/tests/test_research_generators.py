#!/usr/bin/env python3
"""Self-test for the research-lane playbook generators.

These generators exist to state only what the source files state — quote or
count, never paraphrase, never fill. The tests pin exactly that: absence is
reported as a measured fact (the exact "0 orchestrator reports" sentence),
unparseable inputs are skipped and named rather than invented, sparse records
render "(not recorded)" instead of a fabricated value, and output is
byte-deterministic for a fixed timestamp. Hermetic: every fixture is written
into a TemporaryDirectory by this script; no real apps/ava-factory path and no
other lane's files are read.

    uv run python scripts/business/tests/test_research_generators.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
from pathlib import Path

import yaml

_GEN_DIR = Path(__file__).resolve().parent.parent / "generators"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _GEN_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rb = _load("research_brief")
dc = _load("dataset_card")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    tail = f"  — {detail}" if detail and not cond else ""
    print(f"{'PASS' if cond else 'FAIL'}  {name}{tail}")


def frontmatter(text: str):
    """Parse the YAML block between the leading --- fences; None on failure."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    try:
        return yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


STAMP = "2026-08-09T00:00:00Z"

MINI_SPEC = """\
# LONGCAT2_INSIGHTS_SPEC — mapping an efficiency doctrine onto Dottie

Status per item: **BUILD-NOW** or speced-deferred.

## TL;DR

- The doctrine contributes streaming-aware indexing and hierarchical
  retrieval, mapped onto the free-tier stack.
- One item lands now; two are recorded as **SPECED-DEFERRED** designs.

## 1. Streaming timeline store

**Status: BUILD-NOW.** Priority 1.

## 2. Hierarchical retrieval

Status: **SPECED-DEFERRED**.
"""

ORCH_OK = (
    '{"run_id": "orch-20260808-a", "phases": 3,'
    ' "wall_seconds": 412.6, "status": "complete"}'
)
ORCH_BAD = "not json {"

CORPUS_META = (
    '{"name": "orchestration-corpus", "license": "cc-by-4.0", "sources": ['
    '{"name": "harness-timelines", "path": "bundles/ultra/runs",'
    ' "rows": 1284, "sha256": "ab12cd34"},'
    '{"name": "review-notes", "path": "knowledge/reviews"}]}'
)


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    spec_p = root / "mini_spec.md"
    spec_p.write_text(MINI_SPEC, encoding="utf-8")
    ok_p = root / "orch_report_ok.json"
    ok_p.write_text(ORCH_OK, encoding="utf-8")
    bad_p = root / "orch_report_bad.json"
    bad_p.write_text(ORCH_BAD, encoding="utf-8")
    meta_p = root / "corpus_meta.json"
    meta_p.write_text(CORPUS_META, encoding="utf-8")
    broken_p = root / "corpus_meta_broken.json"
    broken_p.write_text("not json {", encoding="utf-8")

    # -----------------------------------------------------------------------
    # research_brief — happy path: spec plus one parseable report.
    # -----------------------------------------------------------------------
    out = rb.generate(
        {"spec": [spec_p], "orchestrator_reports": [ok_p]}, {}, STAMP
    )
    check("research_brief returns research_brief.md", "research_brief.md" in out)
    brief = out.get("research_brief.md", "")
    fm = frontmatter(brief)
    check("brief frontmatter parses as YAML", isinstance(fm, dict), repr(fm)[:120])
    fm = fm or {}
    check("brief classification is REAL", fm.get("classification") == "REAL")
    check("brief measured flag is true", fm.get("measured") is True)
    check(
        "brief generated_at equals the injected stamp",
        fm.get("generated_at") == STAMP,
        repr(fm.get("generated_at")),
    )
    check(
        "brief cites the spec sha256 and it recomputes",
        _sha256(spec_p) in brief
        and any(s.get("sha256") == _sha256(spec_p) for s in fm.get("sources", [])),
    )
    check(
        "BUILD-NOW marker count is 1 (mechanical count, not prose)",
        "- BUILD-NOW markers: 1" in brief,
    )
    check(
        "SPECED-DEFERRED marker count is 2",
        "- SPECED-DEFERRED markers: 2" in brief,
    )
    check(
        "H1 title is quoted verbatim",
        "# LONGCAT2_INSIGHTS_SPEC — mapping an efficiency doctrine onto Dottie"
        in brief,
    )
    check(
        "numbered H2 headings are listed",
        "  - 1. Streaming timeline store" in brief
        and "  - 2. Hierarchical retrieval" in brief,
    )
    check(
        "TL;DR bullet is reproduced verbatim",
        "- One item lands now; two are recorded as **SPECED-DEFERRED** designs."
        in brief,
    )
    check(
        "report numeric fields appear verbatim",
        "wall_seconds=412.6" in brief and "phases=3" in brief,
    )
    check(
        "report top-level keys are listed",
        "phases, run_id, status, wall_seconds" in brief,
    )

    # Determinism: identical inputs and stamp yield byte-identical output.
    again = rb.generate(
        {"spec": [spec_p], "orchestrator_reports": [ok_p]}, {}, STAMP
    )
    check("brief is byte-deterministic", again["research_brief.md"] == brief)

    # -----------------------------------------------------------------------
    # research_brief — bad-JSON report is skipped and named, never filled.
    # -----------------------------------------------------------------------
    try:
        mixed = rb.generate(
            {"spec": [spec_p], "orchestrator_reports": [ok_p, bad_p]}, {}, STAMP
        )["research_brief.md"]
        check("bad-json report does not raise", True)
    except Exception as exc:  # the test must report the failure, not die on it
        mixed = ""
        check("bad-json report does not raise", False, repr(exc))
    check(
        "bad-json report is listed under Sources skipped",
        "Sources skipped" in mixed and "orch_report_bad.json" in mixed,
    )
    check(
        "skipped report is not cited as a source",
        "orch_report_bad.json" not in "".join(
            s.get("path", "") for s in (frontmatter(mixed) or {}).get("sources", [])
        ),
    )

    # -----------------------------------------------------------------------
    # research_brief — absence is a measured fact; missing spec is an error.
    # -----------------------------------------------------------------------
    empty = rb.generate(
        {"spec": [spec_p], "orchestrator_reports": []}, {}, STAMP
    )["research_brief.md"]
    check(
        "empty report list states the exact absence sentence",
        "0 orchestrator reports were present under "
        "apps/ava-factory/reports/orchestrator/ at generation time." in empty,
    )
    try:
        rb.generate({"spec": [], "orchestrator_reports": []}, {}, STAMP)
        check("empty spec list raises FileNotFoundError", False, "no exception")
    except FileNotFoundError:
        check("empty spec list raises FileNotFoundError", True)

    # -----------------------------------------------------------------------
    # dataset_card — happy path.
    # -----------------------------------------------------------------------
    card = dc.generate({"corpus_meta": [meta_p]}, {}, STAMP)["dataset_card.md"]
    cfm = frontmatter(card) or {}
    check("card frontmatter parses as YAML", isinstance(frontmatter(card), dict))
    check(
        "card carries provenance_classification REAL",
        cfm.get("provenance_classification") == "REAL",
    )
    check("card license comes from the metadata", cfm.get("license") == "cc-by-4.0")
    check("card generated_at equals the injected stamp", cfm.get("generated_at") == STAMP)
    check(
        "card audit sha256 matches recomputation",
        f"- source_sha256: `{_sha256(meta_p)}`" in card
        and any(s.get("sha256") == _sha256(meta_p) for s in cfm.get("sources", [])),
    )
    check(
        "one table row per source record",
        "| harness-timelines | bundles/ultra/runs | (not recorded) | 1284 |"
        " ab12cd34 | (not recorded) |" in card,
    )
    check(
        "sparse record renders (not recorded), never a fabricated value",
        "| review-notes | knowledge/reviews | (not recorded) | (not recorded) |"
        " (not recorded) | (not recorded) |" in card,
    )
    check(
        "summary counts only what the file records",
        # license is top-level only in the fixture, so 0 of 2 RECORDS carry one;
        # only the first record carries rows — measured counts, no fill-in.
        "declares 2 source record(s)" in card
        and "0 of 2 record a license" in card
        and "1 of 2 record a row count" in card,
    )
    check(
        "card is byte-deterministic",
        dc.generate({"corpus_meta": [meta_p]}, {}, STAMP)["dataset_card.md"] == card,
    )

    # -----------------------------------------------------------------------
    # dataset_card — skip semantics, not crashes.
    # -----------------------------------------------------------------------
    try:
        dc.generate({"corpus_meta": []}, {}, STAMP)
        check("missing corpus_meta raises FileNotFoundError", False, "no exception")
    except FileNotFoundError:
        check("missing corpus_meta raises FileNotFoundError", True)
    try:
        dc.generate({"corpus_meta": [broken_p]}, {}, STAMP)
        check("malformed corpus_meta raises FileNotFoundError", False, "no exception")
    except FileNotFoundError as exc:
        check("malformed corpus_meta raises FileNotFoundError", True)
        check(
            "malformed message says unparseable (skip semantics)",
            "unparseable" in str(exc),
            str(exc),
        )


print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
