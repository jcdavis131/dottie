"""Tests for logic_textbook_pipeline — gen_textbook and quality filter"""

import importlib.util

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/logic_textbook_pipeline.py"
spec = importlib.util.spec_from_file_location("logic_textbook_pipeline", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_gen_textbook_contains_topic():
    txt = mod.gen_textbook("induction")
    assert "induction" in txt.lower()
    assert "Definition" in txt or "Theorem" in txt


def test_heuristic_quality_score_deterministic():
    s1 = mod.heuristic_quality_score("Theorem Definition Proof Example " + "word " * 10)
    s2 = mod.heuristic_quality_score("Theorem Definition Proof Example " + "word " * 10)
    assert s1 == s2
    assert 0 <= s1 <= 1


def test_heuristic_quality_score_penalizes_short():
    short = "hi"
    long_good = "Theorem Definition Proof Example " + "unique words " * 20
    assert mod.heuristic_quality_score(long_good) >= mod.heuristic_quality_score(short)


def test_gen_jsonl_example_structure():
    ex = mod.gen_jsonl_example("propositional logic")
    assert "text" in ex
    assert "source" in ex
    assert "task_type" in ex
    assert "reward_heuristic" in ex
    assert 0 <= ex["reward_heuristic"] <= 1


def test_topics_constants():
    assert hasattr(mod, "TOPICS_LOGIC")
    assert hasattr(mod, "TOPICS_MATH")
    assert len(mod.TOPICS_LOGIC) >= 3
    assert len(mod.TOPICS_MATH) >= 3
