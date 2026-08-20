"""Operational — latency/token/cost. Typed fields like harness-evals."""
from ..core.metric import BaseMetric
from ..core.score import Score

class LatencyMetric(BaseMetric):
    name="latency"; dimension="performance"
    def __init__(self, max_ms=2000, threshold=0.5):
        super().__init__(threshold=threshold); self.max_ms=max_ms
    def measure(self, ec):
        ms=ec.latency_ms or 0
        # score 1 at 0ms, 0 at max_ms, linear 0..1 clipped
        if ms<=0: v=1.0
        elif ms>=self.max_ms: v=0.0
        else: v=1.0 - ms/self.max_ms
        return Score(name=self.name,value=v,threshold=self.threshold,dimension=self.dimension,reason=f"{ms}ms",latency_ms=ms)

class TokenCostMetric(BaseMetric):
    name="token_cost"; dimension="performance"
    def __init__(self, max_tokens=2000, threshold=0.5): super().__init__(threshold=threshold); self.max_tokens=max_tokens
    def measure(self, ec):
        n=ec.token_count or 0
        v=1.0 if n<=self.max_tokens else max(0.0,1.0 - (n-self.max_tokens)/self.max_tokens)
        return Score(name=self.name,value=v,threshold=self.threshold,dimension=self.dimension,reason=f"{n}tok")

class CostEfficiencyMetric(BaseMetric):
    name="cost_efficiency"; dimension="performance"
    def __init__(self, max_usd=0.05, threshold=0.5): super().__init__(threshold=threshold); self.max_usd=max_usd
    def measure(self, ec):
        c=ec.cost_usd or 0
        v=1.0 if c<=self.max_usd else max(0.0,1.0 - c/self.max_usd)
        return Score(name=self.name,value=v,threshold=self.threshold,dimension=self.dimension,reason=f"${c:.4f}")
