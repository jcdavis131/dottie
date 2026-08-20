"""Agent/Tool metrics like harness-evals ToolCorrectness, PlanAdherence etc."""
from ..core.metric import BaseMetric
from ..core.score import Score

class ToolCorrectnessMetric(BaseMetric):
    name="tool_correctness"; dimension="trajectory"
    def __init__(self, mode="at_least_one", threshold=0.7): super().__init__(threshold=threshold); self.mode=mode
    def measure(self, ec):
        got=set(t.name for t in (ec.tool_calls or []))
        exp=set(ec.expected_tools or [])
        if not exp: return Score(name=self.name,value=1.0,threshold=self.threshold,dimension=self.dimension,reason="no expected")
        if self.mode=="exact": v=1.0 if got==exp else 0.0
        elif self.mode=="at_least_one": v=1.0 if got&exp else 0.0
        else: v=len(got&exp)/len(exp) if exp else 1.0
        return Score(name=self.name,value=v,threshold=self.threshold,dimension=self.dimension,reason=f"got {got} exp {exp}")

class ToolArgumentMatchMetric(BaseMetric):
    name="tool_arg_match"; dimension="trajectory"
    def __init__(self, arg_match="subset", ignore_keys=None, threshold=0.7):
        super().__init__(threshold=threshold); self.arg_match=arg_match; self.ignore=set(ignore_keys or [])
    def measure(self, ec):
        exp=ec.expected_tool_calls or []
        got=ec.tool_calls or []
        if not exp: return Score(name=self.name,value=1.0,threshold=self.threshold,dimension=self.dimension)
        # simple: first exp must match first got on non-ignored keys subset
        if not got: return Score(name=self.name,value=0.0,threshold=self.threshold,dimension=self.dimension,reason="no tool_calls")
        g=got[0].input; e=exp[0].input if hasattr(exp[0],'input') else exp[0].get('input',{})
        g={k:v for k,v in g.items() if k not in self.ignore}
        e={k:v for k,v in e.items() if k not in self.ignore}
        if self.arg_match=="subset": ok=all(g.get(k)==v for k,v in e.items())
        else: ok=g==e
        return Score(name=self.name,value=1.0 if ok else 0.0,threshold=self.threshold,dimension=self.dimension,reason=f"got {g} exp {e}")

class StepEfficiencyMetric(BaseMetric):
    name="step_efficiency"; dimension="trajectory"
    def __init__(self, optimal_steps=5, threshold=0.6): super().__init__(threshold=threshold); self.optimal=optimal_steps
    def measure(self, ec):
        steps=len(ec.tool_calls or []) or 1
        v=self.optimal/steps if steps>=self.optimal else 1.0
        return Score(name=self.name,value=min(1.0,v),threshold=self.threshold,dimension=self.dimension,reason=f"{steps} steps")
