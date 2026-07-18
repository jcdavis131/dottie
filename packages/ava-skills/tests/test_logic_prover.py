# Solo personal project, no connection to employer, built with public/free-tier only
"""logic-prover: real mode writes valid JSONL for truth tables (incl. IMPLIES) and
syllogisms; n is honored beyond 100; byte/record counts are real."""

import json

from conftest import load_skill_module

lp = load_skill_module("logic-prover")


class TestGenerators:
    def test_truth_tables_include_implies(self):
        recs = lp.gen_truth_tables(9)
        exprs = {r["expr"] for r in recs}
        assert "P IMPLIES Q" in exprs
        assert "P AND Q" in exprs and "P OR Q" in exprs

    def test_truth_table_rows_are_verified(self):
        for rec in lp.gen_truth_tables(6):
            assert rec["type"] == "truth_table"
            assert len(rec["rows"]) == 4  # all P/Q assignments
            assert rec["valid"] is True
            for row in rec["rows"]:
                assert row["value"] == lp.OPS[rec["expr"].split()[1]](row["P"], row["Q"])

    def test_implies_semantics(self):
        implies = next(r for r in lp.gen_truth_tables(3) if r["expr"] == "P IMPLIES Q")
        table = {(row["P"], row["Q"]): row["value"] for row in implies["rows"]}
        assert table == {(True, True): True, (True, False): False,
                         (False, True): True, (False, False): True}

    def test_syllogisms_have_premises_conclusion_valid(self):
        for rec in lp.gen_syllogisms(10):
            assert rec["type"] == "syllogism"
            assert len(rec["premises"]) == 2
            assert rec["conclusion"].startswith("Therefore")
            assert rec["valid"] is True
            assert rec["form"] in {"Barbara", "ModusPonens", "Ferio"}


class TestRealModeJsonl:
    def test_writes_valid_jsonl_honoring_n_beyond_100(self, tmp_path):
        n = 150
        r = lp.run(mode="real", n=n, out_dir=str(tmp_path), seed=3)
        assert r["pass"] is True
        m = r["measured"]
        assert m["records_written"] == 2 * n
        assert m["truth_tables"] == n and m["syllogisms"] == n

        out = tmp_path / "logic_corpus.jsonl"
        assert str(out) == m["out_file"]
        raw = out.read_bytes()
        assert len(raw) == m["bytes_written"]  # reported bytes are the real file size

        lines = raw.decode("utf-8").splitlines()
        assert len(lines) == 2 * n
        records = [json.loads(line) for line in lines]  # every line is valid JSON
        types = {rec["type"] for rec in records}
        assert types == {"truth_table", "syllogism"}
        assert any(rec.get("expr") == "P IMPLIES Q" for rec in records)
        for rec in records:
            if rec["type"] == "truth_table":
                assert {"expr", "rows", "valid"} <= set(rec)
            else:
                assert {"premises", "conclusion", "valid"} <= set(rec)

    def test_mock_mode_counts_only(self):
        r = lp.run(mode="mock", n=200)
        assert r["pass"] is True
        assert r["measured"]["n_generated"] == 40  # mock caps at 20+20 by design
        assert "target_tokens" not in r["measured"]  # no invented 50B claim
