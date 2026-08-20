"""Deterministic metrics — no LLM needed. Mirrors harness-evals ExactMatch/Contains/Regex/etc."""
import re, json, difflib
from ..core.metric import BaseMetric
from ..core.score import Score
from ..core.golden import EvalCase

class ExactMatchMetric(BaseMetric):
    name="exact_match"; dimension="correctness"
    def measure(self, ec: EvalCase):
        out=(ec.output or "").strip(); exp=(str(ec.expected or "")).strip() if ec.expected else ""
        v=1.0 if out==exp else 0.0
        return Score(name=self.name, value=v, threshold=self.threshold, dimension=self.dimension, reason="match" if v else f"got:{out[:80]} exp:{exp[:80]}")

class ContainsMetric(BaseMetric):
    name="contains"; dimension="correctness"
    def __init__(self, needle:str, threshold=0.5): super().__init__(threshold=threshold); self.needle=needle
    def measure(self, ec:EvalCase):
        v=1.0 if self.needle in (ec.output or "") else 0.0
        return Score(name=self.name, value=v, threshold=self.threshold, dimension=self.dimension)

class RegexMetric(BaseMetric):
    name="regex"; dimension="correctness"
    def __init__(self, pattern:str, threshold=0.5): super().__init__(threshold=threshold); self.pat=pattern
    def measure(self, ec:EvalCase):
        v=1.0 if re.search(self.pat, ec.output or "", re.M) else 0.0
        return Score(name=self.name, value=v, threshold=self.threshold, dimension=self.dimension)

class JsonDiffMetric(BaseMetric):
    name="json_diff"; dimension="correctness"
    def measure(self, ec:EvalCase):
        try:
            a=json.loads(ec.output) if isinstance(ec.output,str) else ec.output
            b=ec.expected
            if not isinstance(b,dict): return Score(name=self.name,value=0.0,threshold=self.threshold,dimension=self.dimension,reason="expected not dict")
            # simple structural similarity: shared keys / total
            ak=set(a.keys()) if isinstance(a,dict) else set(); bk=set(b.keys())
            if not bk: return Score(name=self.name,value=1.0,threshold=self.threshold,dimension=self.dimension)
            v=len(ak&bk)/len(bk)
            # exact values check
            exact=sum(1 for k in bk if a.get(k)==b.get(k))/len(bk) if isinstance(a,dict) else 0
            v=0.5*v+0.5*exact
            return Score(name=self.name,value=v,threshold=self.threshold,dimension=self.dimension)
        except Exception as e:
            return Score(name=self.name,value=0.0,threshold=self.threshold,dimension=self.dimension,reason=f"parse:{e}")

class SchemaValidationMetric(BaseMetric):
    name="schema_validation"; dimension="correctness"
    def __init__(self, schema:dict, threshold=0.8): super().__init__(threshold=threshold); self.schema=schema
    def measure(self, ec:EvalCase):
        try:
            obj=json.loads(ec.output) if isinstance(ec.output,str) else ec.output
            req=self.schema.get("required",[])
            ok=all(k in obj for k in req) if isinstance(obj,dict) else False
            return Score(name=self.name,value=1.0 if ok else 0.0,threshold=self.threshold,dimension=self.dimension)
        except Exception as e:
            return Score(name=self.name,value=0.0,threshold=self.threshold,dimension=self.dimension,reason=str(e))
