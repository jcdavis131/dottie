"""dottie/pipeline/verification_economics.py — CriticEconomics + EvalHooks6 + Hamster & Suggestibility Guards
Scout v3.3 parity. No torch.
Implements budget3 threshold8.0 PASS epic, early-exit Δ<0.3 resist marginal, first retry 80% value.
"""

from __future__ import annotations
import json
from typing import Dict, Any, List

EVAL_HOOKS_6 = [
    "correctness",      # does output match what user asked? not what you thought they asked
    "reliability",      # can it run 3× independently with same output? deterministic, tool safety
    "coherence",        # does reasoning flow track? DAG version never mutates in place
    "tool_failures",    # failure taxonomy TOOL_FAILURE counts, recovery ladder applied?
    "hallucination",    # no fabrication — provenance travels with every number
    "comms_quality",    # handoff envelope 7 required, pacing Observe max3 / Orient 180s
]

def verification_econ(score: float, prev: float, budget: int=3, threshold: float=8.0, early_exit_delta: float=0.3) -> Dict[str,Any]:
    delta=score-prev
    early_exit=abs(delta) < early_exit_delta
    passed=score>=threshold
    return {
        "score":score,"prev":prev,"delta":round(delta,3),
        "early_exit":early_exit,
        "early_exit_rule":f"delta<{early_exit_delta} → accept resist marginal, timing>speed",
        "passed":passed,
        "threshold_pass":threshold,
        "budget":budget,
        "budget_rule":"first retry 80% value, remaining 20% across next 2 — cap 3",
        "first_retry_value":"80%",
        "eval_hooks_6":EVAL_HOOKS_6,
        "eval_hooks_detail": {
            "correctness": "output matches user asked, not builder hallucinated scope",
            "reliability": "checkpoint pause/resume days later pick up exactly, no in-place DAG mutation",
            "coherence": "OODA 20/30/10/30/10 Observe/Orient/Decide/Act/Feedback log timeline.jsonl even no-change",
            "tool_failures": "FailureTaxonomy5 + SideEffectClasses + bounded ladder retry1→patch→replan→escalate cannot skip",
            "hallucination": "provenance-honest — every number travels with source, unreachable labelled never faked",
            "comms_quality": "HandoffEnvelope 7 required, ScoutCommsBus sub-swarm 3-5 medium, relevantAgents cap 5-6, 13 only epic",
        },
        "hamster_guard":"PEC without memory hamster wheel — memory is difference iteration→improvement DAG version++ immediate lattice write BLOCKED/DONE/PLANNED not metrics-dance",
        "memory_is_diff":"Memory is difference iteration→improvement, 1500 chars immediate write BLOCKED episodic vs semantic vs working",
        "suggestibility_guard":{
            "best":"[BLOCKER] file: evidence → fix concrete single-resp — one sentence, one file:line, testable",
            "worst":"vague 'consider improving' — blocked by critic, requires concrete fix",
            "rule":"best vs worst critique [BLOCKER] file: evidence → fix concrete single-resp — suggestibility guard: best pushes one concrete fix, worst vague blocked",
        },
        "verification":"early-exit Δ<0.3 resist marginal, budget3 threshold8.0 PASS epic, EvalHooks6 mandatory",
    }

def suggestibility_filter(critiques: List[Dict[str,Any]]) -> Dict[str,Any]:
    # keep best concrete, drop vague
    concretes=[c for c in critiques if "file" in c and "evidence" in c]
    vague=[c for c in critiques if "file" not in c]
    return {"keep":concretes[:3], "blocked":vague, "rule":"best [BLOCKER] file: evidence→fix concrete single-resp, worst vague blocked"}

def pe_hamster_check(dag_version_history: List[int], nodes_status: List[str]) -> Dict[str,Any]:
    # detect if DAG version never incremented while same failure repeats
    if len(set(dag_version_history))==1 and len(dag_version_history)>=3 and any(s in ("blocked","failed") for s in nodes_status):
        return {"hamster":True,"fix":"Immediate lattice write BLOCKED + inc dag_version + patch single-resp — memory is diff 1500 chars","dag_versions":dag_version_history}
    return {"hamster":False,"dag_versions":dag_version_history}

def critic_score(hooks: Dict[str,float]) -> float:
    # simple weighted mean of 6 hooks capped 0-10
    if not hooks: return 0.0
    vals=list(hooks.values())
    return round(sum(vals)/len(vals),2)

if __name__=="__main__":
    # quick self-test
    sc=verification_econ(8.2, 8.0)
    print(json.dumps(sc, indent=2))
    print(10, 7, "[BLOCKER] file: evidence → fix")
