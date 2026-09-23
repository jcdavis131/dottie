"""Offline tests for arxiviq-factory: no network, tiny in-memory corpus.

    python3 -m unittest discover -s apps/arxiviq-factory/tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from arxiviq_factory import SCHEMA_ID
from arxiviq_factory.curate import label_summary, load_validator, split_by_paper
from arxiviq_factory.enrich import norm_name, parse_html_affiliations
from arxiviq_factory.families import NIMBLE_MAX_WORDS, Corpus, build, impact_level
from arxiviq_factory.harvest import parse_atom
from arxiviq_factory.teacher import check

NOW = datetime(2026, 9, 23, tzinfo=UTC)

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
 <entry>
  <id>http://arxiv.org/abs/2301.08243v3</id>
  <published>2023-01-19T18:59:01Z</published><updated>2023-04-13T18:00:00Z</updated>
  <title>Self-Supervised Learning from Images with a
   Joint-Embedding Predictive Architecture</title>
  <summary>  This paper demonstrates an approach for learning highly semantic image representations. </summary>
  <author><name>Mahmoud Assran</name></author>
  <author><name>Yann LeCun</name><arxiv:affiliation>NYU</arxiv:affiliation></author>
  <arxiv:comment>CVPR 2023</arxiv:comment>
  <arxiv:primary_category term="cs.CV"/>
  <category term="cs.CV"/><category term="cs.AI"/><category term="cs.LG"/>
 </entry>
</feed>"""

HTML = """<div class="ltx_authors">
<span class="ltx_creator ltx_role_author">
<span class="ltx_personname">Mahmoud Assran
</span><span class="ltx_author_notes"><span class="ltx_author_notes_content">
<span class="ltx_contact ltx_role_affiliation"><span class="ltx_contact_name">Affiliation: </span>Meta AI (FAIR)
</span>
<span class="ltx_contact ltx_role_affiliation"><span class="ltx_contact_name">Affiliation: </span> Mila, Quebec AI Institute
</span></span></span></span>
<span class="ltx_author_before">  </span><span class="ltx_creator ltx_role_author">
<span class="ltx_personname">Somebody Else
</span><span class="ltx_author_notes"><span class="ltx_author_notes_content">
<span class="ltx_contact ltx_role_affiliation"><span class="ltx_contact_name">Affiliation: </span>Elsewhere University
</span></span></span></span>
</div><div class="ltx_abstract">"""


def paper(aid: str, topics: list[str], cats: list[str], authors: list[str], published: str = "2023-01-19T00:00:00Z") -> dict:
    return {
        "arxiv_id": aid,
        "title": f"Paper {aid} on world models",
        "abstract": f"We study {aid} and learn a predictive representation of the world.",
        "authors": [{"name": a, "arxiv_affiliations": []} for a in authors],
        "published": published,
        "primary_category": cats[0],
        "categories": cats,
        "journal_ref": "",
        "topics": topics,
    }


def corpus() -> Corpus:
    papers = [
        paper("2301.00001", ["world_models"], ["cs.LG", "cs.AI"], ["Ada Lovelace", "Alan Turing"]),
        paper("2301.00002", ["world_models"], ["cs.CV", "cs.LG"], ["Grace Hopper", "Alan Turing"]),
        paper("2301.00003", ["jepa"], ["cs.CV"], ["Yann LeCun", "Ada Lovelace"]),
        paper("2301.00004", ["jepa", "world_models"], ["cs.RO", "cs.LG"], ["Grace Hopper"]),
        paper("2609.00005", ["jepa"], ["cs.LG"], ["Claude Shannon"], published="2026-09-01T00:00:00Z"),
    ]
    enrich = [
        {"arxiv_id": "2301.00001", "authors": [{"name": "Ada Lovelace", "affiliations": ["Meta AI (FAIR)"]}, {"name": "Alan Turing", "affiliations": ["McGill University"]}], "s2": {"citation_count": 400, "venue_type": "conference", "venue_name": "NeurIPS"}},
        {"arxiv_id": "2301.00002", "authors": [{"name": "Grace Hopper", "affiliations": ["McGill University"]}, {"name": "Alan Turing", "affiliations": []}], "s2": {"citation_count": 3, "venue_type": None, "venue_name": None}},
        {"arxiv_id": "2301.00003", "authors": [{"name": "Yann LeCun", "affiliations": ["NYU"]}, {"name": "Ada Lovelace", "affiliations": []}], "s2": None},
    ]
    ror = [
        {"affiliation": "Meta AI (FAIR)", "match": {"ror": "https://ror.org/meta", "name": "Meta (United States)", "types": ["company"], "country": "US", "country_name": "United States"}},
        {"affiliation": "McGill University", "match": {"ror": "https://ror.org/mcgill", "name": "McGill University", "types": ["education"], "country": "CA", "country_name": "Canada"}},
        {"affiliation": "NYU", "match": {"ror": "https://ror.org/nyu", "name": "New York University", "types": ["education"], "country": "US", "country_name": "United States"}},
    ]
    teacher = [
        {
            "arxiv_id": "2301.00001",
            "questions": [
                {"prompt": "What does the paper learn?", "options": {"A": "A predictive representation", "B": "A reward model", "C": "A tokenizer", "D": "A compiler"}, "answer": "A"},
                {"prompt": "What is being studied?", "options": {"A": "Graphs", "B": "The paper's own subject", "C": "Proteins", "D": "Markets"}, "answer": "B"},
            ],
            "contribution": "method",
            "code_release": 0,
            "teacher": "claude-test",
        }
    ]
    return Corpus(papers, enrich, ror, teacher, now=NOW)


class HarvestTest(unittest.TestCase):
    def test_parse_atom(self) -> None:
        [p] = parse_atom(ATOM)
        self.assertEqual(p["arxiv_id"], "2301.08243")
        self.assertEqual(p["version"], "3")
        self.assertEqual(p["title"], "Self-Supervised Learning from Images with a Joint-Embedding Predictive Architecture")
        self.assertEqual(p["primary_category"], "cs.CV")
        self.assertEqual(p["categories"], ["cs.CV", "cs.AI", "cs.LG"])
        self.assertEqual(p["authors"][1], {"name": "Yann LeCun", "arxiv_affiliations": ["NYU"]})
        self.assertEqual(p["comment"], "CVPR 2023")


class EnrichTest(unittest.TestCase):
    def test_html_affiliations_only_for_named_authors(self) -> None:
        got = parse_html_affiliations(HTML, ["Mahmoud Assran", "Yann LeCun"])
        self.assertEqual(got, {"Mahmoud Assran": ["Meta AI (FAIR)", "Mila, Quebec AI Institute"]})
        self.assertEqual(norm_name("José  Álvarez-Ruiz"), "jose alvarez ruiz")


class TeacherTest(unittest.TestCase):
    good: ClassVar[dict] = {
        "arxiv_id": "x",
        "questions": [{"prompt": "What does it propose?", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "answer": "C"}] * 2,
        "contribution": "method",
        "code_release": 1,
    }

    def test_accepts_sound_records(self) -> None:
        self.assertIsNone(check(self.good, {"x"}))

    def test_rejects_rather_than_repairs(self) -> None:
        self.assertEqual(check({**self.good, "arxiv_id": "y"}, {"x"}), "unknown arxiv_id")
        self.assertEqual(check({**self.good, "questions": self.good["questions"][:1]}, {"x"}), "needs exactly two questions")
        dup = {**self.good["questions"][0], "options": {"A": "a", "B": "a", "C": "c", "D": "d"}}
        self.assertEqual(check({**self.good, "questions": [dup, dup]}, {"x"}), "empty, overlong or duplicate option")
        bad = {**self.good["questions"][0], "answer": "E"}
        self.assertEqual(check({**self.good, "questions": [bad, bad]}, {"x"}), "answer outside A-D")
        self.assertEqual(check({**self.good, "contribution": "novel"}, {"x"}), "contribution outside the closed set")


class FamiliesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = build(corpus(), seed=7)
        self.io = load_validator()

    def fam(self, name: str) -> list[dict]:
        return [r for r in self.rows if r["meta"]["family"] == name]

    def test_every_row_is_a_valid_jev_record(self) -> None:
        self.assertGreater(len(self.rows), 10)
        for r in self.rows:
            self.assertEqual(r["record"]["schema"], SCHEMA_ID)
            self.io.validate_record(r["record"])
            self.assertEqual(set(r["record"]), {"schema", "id", "state", "questions", "labels"})

    def test_states_never_carry_their_answer(self) -> None:
        for r in self.rows:
            state = json.dumps(r["record"]["state"])
            self.assertNotIn("primary_category", state)
            self.assertNotIn("affiliation", state)
            fam = r["meta"]["family"]
            if fam in ("author_of", "topic", "category", "teacher_quiz", "impact", "peer_reviewed"):
                self.assertNotIn("authors", r["record"]["state"], fam)

    def test_topic_skips_multi_topic_papers(self) -> None:
        ids = {r["meta"]["arxiv_id"] for r in self.fam("topic")}
        self.assertNotIn("2301.00004", ids)

    def test_outcomes_need_time(self) -> None:
        for f in ("impact", "peer_reviewed"):
            self.assertNotIn("2609.00005", {r["meta"]["arxiv_id"] for r in self.fam(f)})
        [imp] = [r for r in self.fam("impact") if r["meta"]["arxiv_id"] == "2301.00001"]
        self.assertEqual(imp["record"]["labels"]["impact"]["score"], 4.0)  # 400 cites / 3.7 years > 100/yr
        self.assertEqual(impact_level(3, 3.0), 1)

    def test_industry_from_ror_types(self) -> None:
        by = {r["meta"]["arxiv_id"]: r["record"]["labels"]["industry"]["noul"] for r in self.fam("industry")}
        self.assertEqual(by["2301.00001"], 1.0)
        self.assertEqual(by.get("2301.00003"), None)  # half the authors unknown: not labelled no

    def test_teacher_rows_are_marked(self) -> None:
        quiz = self.fam("teacher_quiz")
        self.assertEqual(len(quiz), 2)
        self.assertTrue(all(r["meta"]["label_source"] == "llm-teacher:claude-test" for r in quiz))
        self.assertEqual(set(quiz[0]["record"]["questions"]["answer"]["criteria"]), {"A", "B", "C", "D"})

    def test_nimble_pairs_flip_on_one_short_candidate(self) -> None:
        pairs: dict[str, list[dict]] = {}
        for r in self.rows:
            if r["meta"]["pair_id"]:
                pairs.setdefault(r["meta"]["pair_id"], []).append(r)
        self.assertTrue(pairs)
        for pid, (a, b) in pairs.items():
            self.assertEqual(a["record"]["state"], b["record"]["state"], pid)
            qa = next(iter(a["record"]["questions"].values()))["instructions"]
            qb = next(iter(b["record"]["questions"].values()))["instructions"]
            self.assertNotEqual(qa, qb)
            la = next(iter(a["record"]["labels"].values()))["noul"]
            lb = next(iter(b["record"]["labels"].values()))["noul"]
            self.assertEqual({la, lb}, {0.0, 1.0})
            diff = set(qa.split()) ^ set(qb.split())
            self.assertLessEqual(len(diff), 2 * NIMBLE_MAX_WORDS)

    def test_author_negatives_are_real_same_topic_authors(self) -> None:
        names = {a["name"] for p in corpus().papers for a in p["authors"]}
        for r in self.fam("author_of"):
            q = r["record"]["questions"]["author_of"]["instructions"]
            cand = q.removeprefix("Is ").removesuffix(" one of the authors of this paper?")
            self.assertIn(cand, names)


class CurateTest(unittest.TestCase):
    def test_holdout_is_whole_papers_and_at_least_a_fifth(self) -> None:
        rows = build(corpus(), seed=7)
        held = split_by_paper(rows, seed=1)
        n_hold = sum(1 for r in rows if r["meta"]["arxiv_id"] in held)
        self.assertGreaterEqual(n_hold / len(rows), 0.2)
        for r in rows:
            if r["meta"]["pair_id"]:
                mates = [x for x in rows if x["meta"]["pair_id"] == r["meta"]["pair_id"]]
                self.assertEqual(len({x["meta"]["arxiv_id"] in held for x in mates}), 1)

    def test_label_summary(self) -> None:
        s = label_summary(build(corpus(), seed=7))
        self.assertEqual(s["topic"]["type"], "choice")
        self.assertIn("positive_rate", s["author_of"])
        self.assertEqual(s["author_of"]["positive_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
