"""Offline tests for the skillify stage and the fulltext teacher batches.

No network, no paper_bundle.py: everything tested here is the factory's own
logic (subset selection, state-budget tiers, manifest records, batch format).
paper_bundle.py itself is an approved external tool and is not vendored or
invoked by these tests.

    python3 -m unittest discover -s apps/arxiviq-factory/tests -v
"""

from __future__ import annotations

import gzip
import json
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from arxiviq_factory import skillify
from arxiviq_factory import teacher
from arxiviq_factory.skillify import (
    bundle_name,
    captions_from_text,
    complexity_score,
    manifest_record,
    pdf_url,
    select_key_sections,
    select_papers,
    split_sections,
    state_budget,
)


def paper(aid: str, published: str) -> dict:
    return {"arxiv_id": aid, "version": "1", "title": f"Paper {aid}", "abstract": f"We study {aid}.", "published": published}


SMALL_MD = """# Introduction

We do a small thing.

## Methods

We do it like this.

## Results

It worked. Figure 1 shows the main result.

## Conclusion

Done.
"""

MEDIUM_MD = (
    "# Introduction\n\n" + "Intro prose. " * 2000 + "\n\n"
    "# Methods\n\n" + "Method detail. " * 4000 + "\n\n"
    "# Results\n\n" + "Result detail. Figure 2 plots accuracy. " * 3000 + "\n\n"
    "# Acknowledgments\n\n" + "Thanks. " * 500 + "\n\n"
    "# Discussion\n\n" + "Discussion prose. " * 2000 + "\n"
)

LARGE_MD = (
    "# Introduction\n\n" + "Long intro. " * 12000 + "\n\n"
    "# Methods\n\n" + "Long methods. " * 16000 + "\n\n"
    "# Results\n\n" + "Long results. Figure 9 shows the loss curve. " * 16000 + "\n\n"
    "# References\n\n" + "A reference. " * 4000 + "\n"
)


class SelectPapersTest(unittest.TestCase):
    def test_most_recent_first(self) -> None:
        rows = [paper("2301.00001", "2023-01-01T00:00:00Z"), paper("2609.00002", "2026-09-01T00:00:00Z"), paper("2405.00003", "2024-05-01T00:00:00Z")]
        got = [p["arxiv_id"] for p in select_papers(rows, None, None)]
        self.assertEqual(got, ["2609.00002", "2405.00003", "2301.00001"])

    def test_limit(self) -> None:
        rows = [paper(f"2609.0000{i}", f"2026-09-0{i}T00:00:00Z") for i in range(1, 6)]
        self.assertEqual(len(select_papers(rows, 2, None)), 2)
        self.assertEqual(select_papers(rows, 2, None)[0]["arxiv_id"], "2609.00005")

    def test_since_year(self) -> None:
        rows = [paper("2301.00001", "2023-01-01T00:00:00Z"), paper("2609.00002", "2026-09-01T00:00:00Z")]
        got = [p["arxiv_id"] for p in select_papers(rows, None, 2025)]
        self.assertEqual(got, ["2609.00002"])

    def test_pdf_url_is_version_pinned(self) -> None:
        self.assertEqual(pdf_url("2609.26642", "1"), "https://arxiv.org/pdf/2609.26642v1")
        self.assertEqual(pdf_url("2609.26642", None), "https://arxiv.org/pdf/2609.26642")

    def test_bundle_name_is_skill_slug(self) -> None:
        self.assertEqual(bundle_name("2609.26642"), "2609-26642")
        name = bundle_name("hep-th/9901001")
        self.assertTrue(name and all(c.islower() or c.isdigit() or c == "-" for c in name))
        self.assertLessEqual(len(name), 63)


class StateBudgetTest(unittest.TestCase):
    def test_small_paper_gets_full_text(self) -> None:
        b = state_budget(SMALL_MD, figure_count=1, table_count=0)
        self.assertEqual(b["tier"], "full")
        self.assertIn("We do it like this.", b["state_text"])
        self.assertIn("Figure 1 shows the main result.", b["state_text"])  # captions always travel

    def test_medium_paper_keeps_key_sections(self) -> None:
        b = state_budget(MEDIUM_MD, figure_count=2, table_count=1)
        self.assertEqual(b["tier"], "sections")
        self.assertIn("Method detail.", b["state_text"])
        self.assertIn("Discussion prose.", b["state_text"])
        self.assertIn("Figure 2 plots accuracy.", b["state_text"])
        self.assertNotIn("Thanks.", b["state_text"])  # acknowledgments dropped at this tier

    def test_large_paper_gets_a_window_with_captions(self) -> None:
        b = state_budget(LARGE_MD, figure_count=9, table_count=3)
        self.assertEqual(b["tier"], "window")
        self.assertIn(skillify.TRUNC_MARKER.strip(), b["state_text"])
        self.assertLess(len(b["state_text"]), len(LARGE_MD))
        self.assertIn("Figure 9 shows the loss curve.", b["state_text"])  # captions survive the window

    def test_medium_with_no_matching_headings_keeps_everything(self) -> None:
        md = "# Odd Heading\n\n" + "Body text. " * 9000 + "\n\n# Another Odd Heading\n\n" + "More body. " * 9000 + "\n"
        b = state_budget(md, figure_count=0, table_count=0)
        self.assertEqual(b["tier"], "sections")
        self.assertIn("Body text.", b["state_text"])
        self.assertIn("More body.", b["state_text"])

    def test_complexity_prefers_more_components(self) -> None:
        base = complexity_score(100_000, 8, 0, 0)
        with_figs = complexity_score(100_000, 8, 10, 5)
        self.assertGreater(with_figs, base)


class CaptionsTest(unittest.TestCase):
    def test_extracts_and_dedupes_figure_table_lines(self) -> None:
        md = "Plain line.\nFigure 1 shows the main result.\nTable 2 lists the numbers.\nFigure 1 shows the main result.\n"
        got = captions_from_text(md)
        self.assertEqual(got, ["Figure 1 shows the main result.", "Table 2 lists the numbers."])

    def test_ignores_non_caption_lines(self) -> None:
        got = captions_from_text("# Introduction\n\nNo figures here.\n")
        self.assertEqual(got, [])

    def test_select_key_sections_uses_keywords(self) -> None:
        sections = split_sections(MEDIUM_MD)
        picked = [h for h, _ in select_key_sections(sections)]
        self.assertIn("Methods", picked)
        self.assertIn("Discussion", picked)
        self.assertNotIn("Acknowledgments", picked)


class ManifestRecordTest(unittest.TestCase):
    def test_record_shape_and_reviewed_false(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            pkg = tdp / "2609.00001"
            (pkg / "references").mkdir(parents=True)
            (pkg / "references" / "paper.md").write_text(SMALL_MD, encoding="utf-8")
            (pkg / "assets" / "figure").mkdir(parents=True)
            (pkg / "assets" / "figure" / "fig1.png").write_bytes(b"fake")
            (pkg / "assets" / "table").mkdir(parents=True)
            (pkg / "assets" / "table" / "t1.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            pdf = tdp / "2609.00001.pdf"
            pdf.write_bytes(b"%PDF-1.4 fake")
            p = paper("2609.00001", "2026-09-01T00:00:00Z")
            rec = manifest_record("2609.00001", p, pkg, pdf, verify_status="extracted-ok", review_queue={"items": 3})
            for key in ("arxiv_id", "package_path", "pdf_sha256", "sections", "figure_count", "table_count",
                        "complexity_score", "state_tier", "reviewed", "verification_status", "review_queue", "skillified_at"):
                self.assertIn(key, rec, key)
            self.assertFalse(rec["reviewed"])  # extraction runs never claim review
            self.assertEqual(rec["figure_count"], 1)
            self.assertEqual(rec["table_count"], 1)
            self.assertTrue(rec["pdf_sha256"] and len(rec["pdf_sha256"]) == 64)
            self.assertEqual(rec["package_path"], "sources/paper_skills/2609.00001")


class PrepareFulltextTest(unittest.TestCase):
    def test_batch_rows_carry_package_path_not_abstract(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src, dat = tdp / "sources", tdp / "data"
            (src).mkdir()
            with gzip.open(src / "papers.jsonl.gz", "wt", encoding="utf-8") as f:
                f.write(json.dumps(paper("2609.00001", "2026-09-01T00:00:00Z")) + "\n")
            pkg = tdp / "pkgs" / "2609.00001"
            (pkg / "references").mkdir(parents=True)
            (pkg / "references" / "paper.md").write_text(SMALL_MD, encoding="utf-8")
            with gzip.open(src / "paper_skills.jsonl.gz", "wt", encoding="utf-8") as f:
                f.write(json.dumps({"arxiv_id": "2609.00001", "package_path": "sources/paper_skills/2609.00001"}) + "\n")
            old = (teacher.SOURCES, teacher.DATA, skillify.MANIFEST, skillify.PKG_ROOT)
            teacher.SOURCES, teacher.DATA = src, dat
            skillify.MANIFEST, skillify.PKG_ROOT = src / "paper_skills.jsonl.gz", tdp / "pkgs"
            try:
                paths = teacher.prepare_fulltext(2, None)
            finally:
                teacher.SOURCES, teacher.DATA, skillify.MANIFEST, skillify.PKG_ROOT = old
            self.assertEqual(len(paths), 1)
            rows = [json.loads(l) for l in paths[0].read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            for key in ("arxiv_id", "title", "abstract", "paper_md_path", "captions"):
                self.assertIn(key, row, key)
            self.assertTrue(row["paper_md_path"].endswith("references/paper.md"))
            self.assertTrue(any("Figure 1 shows the main result." in c for c in row["captions"]))
            brief = (dat / "teacher" / "fulltext" / "BRIEF_FULLTEXT.md").read_text(encoding="utf-8")
            self.assertIn("NOT from the abstract alone", brief)
            self.assertIn('"source"', brief)


if __name__ == "__main__":
    unittest.main()
