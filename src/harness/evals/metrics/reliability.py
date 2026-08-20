"""Reliability — OutcomeConsistency etc. multi-run like harness-evals example."""
from ..core.metric import ReliabilityMetric
from ..core.score import Score
from collections import Counter

class OutcomeConsistencyMetric(ReliabilityMetric):
    name="outcome_consistency"; dimension="trajectory"
    def measure(self, ec):
        runs=ec.runs or []
        if len(runs)<2: return Score(name=self.name,value=1.0,threshold=self.threshold,dimension=self.dimension,reason="single run")
        outs=[(r.output if hasattr(r,'output') else str(r)).strip() for r in runs]
        cnt=Counter(outs)
        most=cnt.most_common(1)[0][1]
        v=most/len(outs)
        return Score(name=self.name,value=v,threshold=self.threshold,dimension=self.dimension,reason=f"{most}/{len(outs)} consistent")
