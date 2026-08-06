"""AutoGen adapter — multi-agent conversational, ACNE provenance"""

from pathlib import Path
from typing import Dict, Any, List
from .base import BaseAdapter, _token_est

class AutoGenAdapter(BaseAdapter):
    def __init__(self, base: Path=None):
        b=base or (Path.home()/ "workspace"/"bundles"/"memory"/"agents-langchain")
        super().__init__(b,"autogen")

    def list_agents(self)->List[Dict]:
        return [
            {"id":"researcher","role":"Researcher, fast-facts OODA Observe","confidence":0.88},
            {"id":"coder","role":"Coder/Builder, self-contained artifact","confidence":0.91},
            {"id":"critic","role":"Critic, verify econ budget3","confidence":0.90},
            {"id":"operator","role":"Operator, Always-On watcher :13 pacing","confidence":0.87},
            {"id":"communicator","role":"Communicator, human-in-loop gate","confidence":0.86},
        ]

    def run_conversation(self, goal:str, max_rounds:int=3)->Dict[str,Any]:
        import time
        start=time.time()
        cached=self.cache.get_query(goal, params=f"autogen-{max_rounds}")
        if cached:
            return {**cached["result"],"cache_hit":True,"latency_ms":int((time.time()-start)*1000),"confidence":0.92}
        agents=self.list_agents()
        turns=[]
        for i in range(max_rounds):
            agent=agents[i%len(agents)]
            turns.append({"round":i+1,"speaker":agent["id"],"msg":f"[{agent['id']}] round {i+1} on '{goal[:40]}' — {agent['role'][:60]}","confidence":agent["confidence"]})
        tokens=_token_est(goal)*max_rounds
        result={
            "ok":True,"adapter":"autogen","goal":goal,"agents":agents,"turns":turns,"rounds":max_rounds,
            "tokens_est":tokens,
            "confidence":0.85,
            "provenance":[{"source":"autogen.conversation","confidence":0.85,"detail":f"{max_rounds} rounds {len(agents)} agents","cache_hit":False}],
            "tempo":":13","cache_hit":False,"latency_ms":int((time.time()-start)*1000)+100
        }
        self.cache.put_query(goal,result,params=f"autogen-{max_rounds}")
        return result

    def health(self):
        return {"ok":True,"adapter":"autogen","status":"ready","agents":5,"max_rounds_safe":4,"cache":self.cache.stats(),"confidence":0.87}

def get_autogen_adapter():
    return AutoGenAdapter()
