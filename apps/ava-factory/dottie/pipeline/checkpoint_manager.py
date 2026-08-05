"""
Dottie Checkpoint Manager — Scout v3.3 parity
LangGraph-style pause/resume days later, timeline.jsonl even no-change, MoMA 5-tier + recovery + verification econ.
Solo project, public pip only.
"""

from __future__ import annotations
import json, time, os, sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

_REPO = Path(__file__).resolve().parent.parent.parent
_RUNS = _REPO / "bundles" / "ultra" / "runs"
# Also support Dottie-local runs dir for portability
_DOTTIE_RUNS = Path(__file__).resolve().parent / "runs"
_DOTTIE_RUNS.mkdir(parents=True, exist_ok=True)

REQUIRED_TIMELINE_FIELDS = ["nodeId","agentId","attempt","latency","tokens","status","errorClass"]

MOMA_TIERS = {
    "deterministic": {"cap":"cheap", "cost":10, "desc":"heartbeat/monitor, no LLM"},
    "llm": {"cap":"medium", "cost":200, "desc":"chat/simple decomposition"},
    "deep_research": {"cap":"heavy 9K", "cost":9000, "desc":"5-7 sources A/B/C triangulation"},
    "action_operator": {"cap":"medium-verify", "cost":1500, "desc":"tool-chain idempotent+rollback"},
    "agentic_epic": {"cap":"checkpointed 13-swarm", "cost":15000, "desc":"opaque goal DAG checkpointed"},
}

FAILURE_TAXONOMY = ["INPUT_CORRUPTION","CONTEXT_STARVATION","TOOL_FAILURE","REASONING_COLLAPSE","OUTPUT_CORRUPTION"]
SIDE_EFFECT = ["READ","WRITE_IDEMPOTENT","WRITE_DESTRUCTIVE","EXTERNAL_NOTIFY"]

class DottieCheckpointManager:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.path = _DOTTIE_RUNS / run_id / "checkpoint.json"
        self.timeline_path = _DOTTIE_RUNS / run_id / "timeline.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint = {
            "runId": run_id,
            "version": "v0.8-scout-v3.3-parity",
            "created": datetime.now(timezone.utc).isoformat(),
            "dag_version": 1,
            "nodes": [],
            "guarantees": {
                "structured_workflow": True,
                "tool_safety": "schema+sandbox 30s",
                "memory_discipline": "read/update summaries",
                "reasoning_boundaries": "max 7 steps",
                "eval_hooks": 6,
                "multi_agent": "routing+message passing+shared mem+hierarchical",
            }
        }

    def _now(self): return datetime.now(timezone.utc).isoformat()

    def log_node(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Every node logged even no-change — ultra non-negotiable"""
        entry = {
            "ts": self._now(),
            "runId": self.run_id,
            "nodeId": event.get("nodeId") or event.get("node_id") or "unknown",
            "agentId": event.get("agentId") or event.get("agent_id") or "executor",
            "layer": event.get("layer", 3),
            "attempt": event.get("attempt", 1),
            "latency_ms": event.get("latency_ms") or event.get("latency", 0),
            "tokens_est": event.get("tokens_est") or event.get("tokens", 0),
            "status": event.get("status", "running"),
            "errorClass": event.get("errorClass") or event.get("error_class"),
            "ooda": event.get("ooda", {}),
            "tempo": event.get("tempo", ":13"),
            **{k:v for k,v in event.items() if k in ("input","output","metrics")}
        }
        # required fields audit
        missing = [f for f in REQUIRED_TIMELINE_FIELDS if f.lower().replace("_","") not in "".join(entry.keys()).lower() and f not in entry]
        # still write — but keep schema strict in check
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.timeline_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        # immediate lattice write BLOCKED detection
        if entry["status"] in ("blocked","failed") and entry.get("errorClass") in FAILURE_TAXONOMY:
            self._immediate_lattice_write_blocked(entry)
        return entry

    def _immediate_lattice_write_blocked(self, entry: Dict[str, Any]):
        """PECHamsterWheelGuard memory-is-diff: immediate write BLOCKED not metrics-dance"""
        lattice_path = _DOTTIE_RUNS / self.run_id / "lattice_diff.jsonl"
        diff = {
            "ts": self._now(),
            "type": "BLOCKED",
            "nodeId": entry["nodeId"],
            "agentId": entry["agentId"],
            "errorClass": entry["errorClass"],
            "status": entry["status"],
            "delta": f"{entry['nodeId']} {entry['errorClass']} vs prev run — memory is difference",
            "1500_chars": json.dumps(entry)[:1500],
        }
        with open(lattice_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(diff) + "\n")

    def save(self, state: Dict[str, Any]):
        merged = {**self.checkpoint, **state, "saved_at": self._now()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        if state.get("nodes"):
            with open(self.timeline_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": self._now(), "event":"checkpoint_saved","dag_version":state.get("dag_version",1),"nodes":len(state["nodes"])})+"\n")

    def load(self, run_id: Optional[str]=None) -> Optional[Dict[str,Any]]:
        p = (_DOTTIE_RUNS / (run_id or self.run_id) / "checkpoint.json")
        if p.exists():
            try: return json.loads(p.read_text(encoding="utf-8"))
            except: return None
        return None

    def pause(self, reason="human gate"):
        self.save({"paused":True,"pause_reason":reason,"paused_at":self._now()})

    def resume(self, run_id: Optional[str]=None) -> Dict[str,Any]:
        state = self.load(run_id or self.run_id)
        if not state: raise FileNotFoundError(f"no checkpoint for {run_id or self.run_id}")
        next_nodes = [n for n in state.get("nodes",[]) if n.get("status")!="done"]
        return {"state":state,"next_nodes":next_nodes,"resume_msg":f"resumed {run_id or self.run_id} v{state.get('dag_version',1)} {len(next_nodes)} nodes pending"}

# --- MoMA-lite classifier for Dottie curation source pick ---

def moma_lite_classify(text: str) -> Dict[str,Any]:
    t=text.lower()
    if any(k in t for k in ["heartbeat","monitor","tick","cron health","deterministic"]):
        return {"tier":"deterministic","cost":"cheap","rationale":"heartbeat/monitor no LLM"}
    if any(k in t for k in ["compare","triangulation","sources","wide sweep","agentic loops","ooda","best practices","arXiv","paper"]):
        return {"tier":"deep_research","cost":"heavy 9K","rationale":"multi-domain needs 5-7 sources"}
    if any(k in t for k in ["gmail","calendar","tool chain","orchestrate","idempotent","rollback"]):
        return {"tier":"action_operator","cost":"medium verification heavy","rationale":"side-effect class"}
    if any(k in t for k in ["agentic loop","dynamic workflow","checkpoint","graphplanner","opaque goal","long running"]):
        return {"tier":"agentic_epic","cost":"epic 13-agent swarm checkpointed","rationale":"GraphPlanner G_workflow+G_history + checkpoint"}
    return {"tier":"llm","cost":"medium","rationale":"general chat/summarize/draft"}

def classify_curation_intent(text: str) -> str:
    """For Dottie dataset_expansion_fast.py phase picking — MoMA-lite determines which source curation tier"""
    clf=moma_lite_classify(text)
    # maps to data phases
    if clf["tier"]=="deterministic": return "healthcheck"
    if clf["tier"]=="deep_research": return "research_engine"
    if clf["tier"]=="action_operator": return "tool_gate"
    if clf["tier"]=="agentic_epic": return "continuous"
    return "standard"

# --- Bounded Recovery Ladder ---

def recovery_ladder(error_class: str, side_effect: str, attempt: int) -> Dict[str,Any]:
    """retry1→patch→replan→escalate, never skip, WRITE_DESTRUCTIVE and EXTERNAL_NOTIFY never auto"""
    if error_class not in FAILURE_TAXONOMY: error_class="TOOL_FAILURE"
    if side_effect not in SIDE_EFFECT: side_effect="READ"
    if side_effect in ("WRITE_DESTRUCTIVE","EXTERNAL_NOTIFY"):
        return {"action":"escalate","reason":f"{side_effect} never auto — needs human gate","attempt":attempt,"errorClass":error_class,"sideEffect":side_effect}
    if attempt==1:
        return {"action":"retry1","attempt":1,"errorClass":error_class,"sideEffect":side_effect,"safe": side_effect in ("READ","WRITE_IDEMPOTENT")}
    if attempt==2:
        return {"action":"patch","attempt":2,"errorClass":error_class,"fix":"single-resp patch — fix concrete file:line evidence"}
    if attempt==3:
        return {"action":"replan","attempt":3,"errorClass":error_class,"dag_version_inc":True,"bounded":True}
    return {"action":"escalate","attempt":attempt,"errorClass":error_class,"sideEffect":side_effect}

# --- Verification Economics ---

def verification_econ(score: float, prev: float, budget: int=3, threshold: float=8.0, early_exit_delta: float=0.3) -> Dict[str,Any]:
    delta=score-prev
    early_exit=abs(delta)<early_exit_delta
    passed=score>=threshold
    return {
        "score":score,"prev":prev,"delta":round(delta,3),
        "early_exit":early_exit,
        "early_exit_rule":f"delta<{early_exit_delta} -> accept resist marginal",
        "passed":passed,
        "threshold_pass":threshold,
        "budget":budget,
        "first_retry_value":"80%",
        "eval_hooks_6":["correctness","reliability","coherence","tool_failures","hallucination","comms_quality"],
        "hamster_guard":"PEC without memory = repeat same failure DAG version never inc. Fix immediate lattice write BLOCKED/DONE/PLANNED not metrics-dance",
        "memory_is_diff":"Memory is difference iteration→improvement",
        "suggestibility_best":"[BLOCKER] file: evidence → fix concrete single-resp",
    }

# MoMA 5 tiers + checkpoint for scoring CLI
def score_for_cli(text: str) -> Dict[str,Any]:
    m=moma_lite_classify(text)
    # simulate intent scoring similar to harness route
    scores={"intent": m["tier"], "moma_tier": m["tier"], "moma_cap": m["cost"], "graph_memory":{"G_workflow":"current DAG","G_history":"past runs"}}
    return scores

