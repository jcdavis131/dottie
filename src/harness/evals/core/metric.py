"""BaseMetric like harness-evals — single measure() method, never raises in evaluate()."""
from typing import Optional
from .score import Score
from .golden import EvalCase

class BaseMetric:
    name: str
    dimension: str = "correctness"  # correctness|groundedness|safety|trajectory|performance
    threshold: float = 0.5
    def __init__(self, name: str = None, threshold: float = 0.5, dimension: str = None):
        self.name = name or self.__class__.__name__.lower().replace("metric","")
        self.threshold = threshold
        if dimension: self.dimension = dimension
    def measure(self, ec: EvalCase) -> Optional[Score]: raise NotImplementedError
    def a_measure(self, ec: EvalCase) -> Optional[Score]: return self.measure(ec)

class ReliabilityMetric(BaseMetric):
    dimension = "trajectory"
class SafetyMetric(BaseMetric):
    dimension = "safety"

def evaluate(ec: EvalCase, metrics: list) -> list[Score]:
    """Never raises — returns all scores including failures like harness-evals."""
    out=[]
    for m in metrics:
        try:
            s = m.measure(ec)
            if s is not None: out.append(s)
        except Exception as e:
            out.append(Score(name=m.name, value=0.0, threshold=m.threshold, passed=False, reason=f"error:{e}", dimension=getattr(m,'dimension','correctness')))
    return out

def assert_test(ec: EvalCase, metrics: list):
    scores = evaluate(ec, metrics)
    fails = [s for s in scores if not s.passed]
    if fails:
        raise AssertionError(f"Fails: {[(s.name,s.value,s.reason) for s in fails]}")
    return scores

def evaluate_cases(cases: list[EvalCase], metrics: list, sinks=None) -> list[list[Score]]:
    all_scores=[]
    for ec in cases:
        scores = evaluate(ec, metrics)
        if sinks:
            for sink in sinks: sink.write(scores, ec)
        all_scores.append(scores)
    return all_scores
