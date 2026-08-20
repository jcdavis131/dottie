"""Dottie harness-evals — zero-deps port of harness/harness-evals best ideas."""
from .core.golden import Golden, EvalCase, Message, ToolCall
from .core.score import Score
from .core.metric import BaseMetric, ReliabilityMetric, SafetyMetric, evaluate, assert_test, evaluate_cases
from .baseline import JsonBaselineStore, compare_to_baseline
__all__=["Golden","EvalCase","Message","ToolCall","Score","BaseMetric","ReliabilityMetric","SafetyMetric","evaluate","assert_test","evaluate_cases","JsonBaselineStore","compare_to_baseline"]
