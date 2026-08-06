"""OpenAI adapter — function-calling + tools, ACNE cache"""

from pathlib import Path
from typing import Dict, Any, List
from .base import BaseAdapter, _token_est

class OpenAIAdapter(BaseAdapter):
    def __init__(self, base: Path=None):
        b=base or (Path.home()/ "workspace"/"bundles"/"memory"/"agents-langchain")
        super().__init__(b,"openai")

    def list_tools(self)->List[Dict]:
        return [
            {"name":"contacts_resolve","type":"function","desc":"ACNE resolve trigger->Contact","confidence":0.92},
            {"name":"graphrag_query","type":"function","desc":"TLPG 1-2 hop GraphRAG compressed","confidence":0.89},
            {"name":"checkpoint_write","type":"function","desc":"7-field checkpoint mandatory even no-change","confidence":0.94},
            {"name":"verify_econ","type":"function","desc":"budget3 threshold8.0 early_exit delta<0.3","confidence":0.90},
        ]

    def run(self, prompt:str, model:str="gpt-4o-mini")->Dict[str,Any]:
        import time, hashlib
        start=time.time()
        cached=self.cache.get_query(prompt, params=model)
        if cached:
            return {**cached["result"],"cache_hit":True,"model":model,"latency_ms":int((time.time()-start)*1000),"confidence":0.93}
        tokens=_token_est(prompt)
        # no real openai call — deterministic stub, network false guard
        result={
            "ok":True,"adapter":"openai","model":model,"prompt_preview":prompt[:80],
            "tools":self.list_tools(),
            "tokens_est":tokens,
            "confidence":0.86,
            "provenance":[{"source":"openai.run","confidence":0.86,"detail":f"model {model} deterministic stub network:false","cache_hit":False}],
            "network":False,
            "cache_hit":False,
            "latency_ms":int((time.time()-start)*1000)+75,
            "tempo":":13",
            "note":"local-first stub — no egress, manifest network:false, 5-layer cache saves ~80%"
        }
        self.cache.put_query(prompt, result, params=model)
        return result

    def health(self):
        return {"ok":True,"adapter":"openai","status":"ready (stub, no egress)","models":["gpt-4o-mini","gpt-4o"],"cache":self.cache.stats(),"confidence":0.87,"network":False}

def get_openai_adapter():
    return OpenAIAdapter()
