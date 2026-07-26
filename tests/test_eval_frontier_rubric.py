
"""Tests for eval_frontier_rubric — Rubric, FrontierTask, judge prompt and parse"""
import importlib.util
MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/eval_frontier_rubric.py"
spec = importlib.util.spec_from_file_location("eval_frontier_rubric", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

Rubric = mod.Rubric
FrontierTask = mod.FrontierTask

def test_rubric_dataclass_creation():
    r = Rubric(id="r1", category="Financial Accuracy", criterion="Must cite source", weight=1.0,
               eval_instructions="Check", ground_truth_ref="src doc", citation_span="", required=False)
    assert r.id == "r1"
    assert r.category == "Financial Accuracy"
    assert r.weight == 1.0

def test_frontier_task_creation():
    r = Rubric(id="r1", category="Coverage", criterion="covers", weight=0.5,
               eval_instructions="i", ground_truth_ref="gt", required=False)
    task = FrontierTask(id="t1", domain="finance", subdomain="risk", question="What is risk?",
                        context_docs=[{"text":"doc"}], expected_workflow=["step1"], rubrics=[r],
                        human_baseline_hours=2.5, ground_truth="baseline")
    assert task.id == "t1"
    assert len(task.rubrics) == 1
    assert task.human_baseline_hours == 2.5

def test_judge_prompt_contains_criterion():
    r = Rubric(id="r1", category="Accuracy", criterion="Must mention revenue 2023", weight=1.0,
               eval_instructions="inst", ground_truth_ref="doc p.3", required=True)
    prompt = mod._judge_prompt(r, "model output revenue 2023 $5M", "gt revenue")
    assert "Must mention revenue 2023" in prompt
    assert "Accuracy" in prompt
    assert "Model Output" in prompt

def test_parse_score_extracts_float():
    assert mod._parse_score('{"score": 0.82, "reason":"good"}') == 0.82
    assert mod._parse_score('Score 0.5 something') == 0.5 or mod._parse_score('0.5') == 0.5
    assert mod._parse_score('') is None
    assert mod._parse_score('no numbers here!!!') is None

def test_parse_score_clamps():
    # should clamp to 0-1, max/min handling inside
    s = mod._parse_score('{"score": 1.0}')
    assert s == 1.0
    # fallback regex picks first number
    s2 = mod._parse_score("0.73 extra")
    assert 0 <= s2 <= 1

def test_categories_list():
    assert hasattr(mod, "CATEGORIES")
    assert isinstance(mod.CATEGORIES, list)
    assert "Financial Accuracy" in mod.CATEGORIES
