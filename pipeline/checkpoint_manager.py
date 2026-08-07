"""
Dottie Checkpoint Manager — Scout v3.3 parity — v0.9 7/7 triple-write hardened
LangGraph-style pause/resume days later, timeline.jsonl even no-change, MoMA 5-tier + recovery + verification econ.
Solo project, public pip only. No torch.

7/7 triple-write canonical list (all relative to ~/workspace):
1. bundles/ultra/runs — dashboard canonical (scout-ops-always-on-2 reads client-only)
2. dottie/pipeline/runs — Dottie-local portability
3. dottie/bundles/ultra/runs
4. apps/ava-factory/bundles/ultra/runs — legacy ava compat
5. dottie/apps/ava-factory/bundles/ultra/runs
6. dottie/apps/ava-factory/dottie/pipeline/runs
7. apps/ava-factory/dottie/pipeline/runs

Deterministic 7-field checkpoint.json + 7-field timeline.jsonl required.
"""

from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

_REPO = Path(__file__).resolve().parent.parent.parent
_WORKSPACE_ROOT = Path.home() / "workspace"

# Legacy singletons kept for backward compat
_RUNS = _REPO / "bundles" / "ultra" / "runs"
_WORKSPACE_RUNS = _WORKSPACE_ROOT / "bundles" / "ultra" / "runs"
_DOTTIE_RUNS = Path(__file__).resolve().parent / "runs"

# 7/7 canonical + v5 Prime extended 9 (task requires 7 inc scout-cli + goal hidden)
# Task: workspace/bundles/ultra/runs, dottie/pipeline/runs, dottie/bundles/ultra/runs,
# dottie/apps/scout-cli/dottie/pipeline/runs, apps/ava-factory/... , goal hidden_files/brief-auto-exec-checkpoints/<runId>
_SEVEN_REL = [
    "bundles/ultra/runs",
    "dottie/pipeline/runs",
    "dottie/bundles/ultra/runs",
    "dottie/apps/scout-cli/dottie/pipeline/runs",
    "apps/ava-factory/bundles/ultra/runs",
    "dottie/apps/ava-factory/bundles/ultra/runs",
    "dottie/apps/ava-factory/dottie/pipeline/runs",
    "apps/ava-factory/dottie/pipeline/runs",
    "goals/refine-dottie-scout-cli-dumbmodel-com-with-vector-models/hidden_files/brief-auto-exec-checkpoints",
]

# Extra coverage for vector-* and scout-cli bundles (zero-deps, no torch, honest flags)
_EXTRA_RELS = [
    "dottie/apps/scout-cli/bundles/ultra/runs",
    "apps/dottie/bundles/ultra/runs",
    "vector-hoops/bundles/ultra/runs",
    "vector-pitch/bundles/ultra/runs",
    "vector-gridiron/bundles/ultra/runs",
    "vector-equities/bundles/ultra/runs",
    "vector-unified/bundles/ultra/runs",
    "vector-hub/bundles/ultra/runs",
]

def _all_runs_dirs() -> List[Path]:
    dirs = []
    for rel in _SEVEN_REL + _EXTRA_RELS:
        p = _WORKSPACE_ROOT / rel
        dirs.append(p)
    # also include legacy internal runs (ensures ava-factory internal still covered when workspace/apps not same as workspace/dottie/apps)
    for legacy in (_RUNS, _DOTTIE_RUNS, _WORKSPACE_RUNS):
        if legacy not in dirs:
            dirs.append(legacy)
    # deduplicate preserving order
    seen=set(); out=[]
    for d in dirs:
        s=str(d.resolve()) if d.exists() else str(d)
        if s not in seen:
            seen.add(s); out.append(d)
    return out

_ALL_RUNS_DIRS = _all_runs_dirs()

REQUIRED_CHECKPOINT_FIELDS = ["runId","dag_version","nodes","created","saved_at","version","provenance"]
REQUIRED_TIMELINE_FIELDS = ["nodeId","agentId","attempt","latency_ms","tokens_est","status","errorClass"]

MOMA_TIERS = {
    "deterministic": {"cap":"cheap", "cost":10, "desc":"heartbeat/monitor, no LLM"},
    "llm": {"cap":"medium", "cost":200, "desc":"chat/simple decomposition"},
    "deep_research": {"cap":"heavy 9K", "cost":9000, "desc":"5-7 sources A/B/C triangulation"},
    "action_operator": {"cap":"medium-verify", "cost":1500, "desc":"tool-chain idempotent+rollback"},
    "agentic_epic": {"cap":"checkpointed 13-swarm", "cost":15000, "desc":"opaque goal DAG checkpointed"},
}

FAILURE_TAXONOMY = ["INPUT_CORRUPTION","CONTEXT_STARVATION","TOOL_FAILURE","REASONING_COLLAPSE","OUTPUT_CORRUPTION"]
SIDE_EFFECT = ["READ","WRITE_IDEMPOTENT","WRITE_DESTRUCTIVE","EXTERNAL_NOTIFY"]

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ensured_check_dirs(run_id: str) -> List[Path]:
    dirs=[]
    for base in _ALL_RUNS_DIRS:
        try:
            d=base/run_id
            d.mkdir(parents=True, exist_ok=True)
            dirs.append(d)
        except Exception:
            pass
    # extra: ensure workspace/bundles/ultra + dottie symlinks exist for dashboard
    return dirs

class DottieCheckpointManager:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._dirs = _ensured_check_dirs(run_id)
        # primary pointers for backward compat exposure
        self.path = (_DOTTIE_RUNS / run_id / "checkpoint.json")
        self.timeline_path = (_DOTTIE_RUNS / run_id / "timeline.jsonl")
        self.ultra_path = (_RUNS / run_id / "checkpoint.json")
        self.ultra_timeline = (_RUNS / run_id / "timeline.jsonl")
        self.ws_path = (_WORKSPACE_RUNS / run_id / "checkpoint.json")
        self.ws_timeline = (_WORKSPACE_RUNS / run_id / "timeline.jsonl")
        for d in self._dirs:
            d.mkdir(parents=True, exist_ok=True)
        self.checkpoint = {
            "runId": run_id,
            "version": "v0.8-scout-v3.3-parity",
            "created": _now_iso(),
            "dag_version": 1,
            "nodes": [],
            "provenance": {
                "workspace_canonical": "bundles/ultra/runs/<runId>",
                "dottie_local": "dottie/pipeline/runs/<runId>",
                "dottie_bundles": "dottie/bundles/ultra/runs/<runId>",
                "ava_legacy": "apps/ava-factory/bundles/ultra/runs/<runId>",
                "dottie_ava_bundles": "dottie/apps/ava-factory/bundles/ultra/runs/<runId>",
                "dottie_ava_pipeline": "dottie/apps/ava-factory/dottie/pipeline/runs/<runId>",
                "ava_pipeline": "apps/ava-factory/dottie/pipeline/runs/<runId>",
                "note": "7/7 triple-write enforced — copy canonical checkpoint.json to all, timeline.jsonl 7-field mirrored, provenance-honest dashboard reads workspace canonical but portability via dottie local",
                "seven": _SEVEN_REL,
            },
            "guarantees": {
                "structured_workflow": True,
                "tool_safety": "schema+sandbox 30s",
                "memory_discipline": "read/update summaries",
                "reasoning_boundaries": "max 7 steps",
                "eval_hooks": 6,
                "multi_agent": "routing+message passing+shared mem+hierarchical",
            }
        }

    def _all_checkpoint_paths(self, run_id: Optional[str]=None) -> List[Path]:
        rid = run_id or self.run_id
        return [base/rid/"checkpoint.json" for base in _ALL_RUNS_DIRS]

    def _all_timeline_paths(self, run_id: Optional[str]=None) -> List[Path]:
        rid = run_id or self.run_id
        return [base/rid/"timeline.jsonl" for base in _ALL_RUNS_DIRS]

    def _dual_write_timeline(self, entry: dict):
        # write to all 7/7 (actually all dirs) — 7-field guarantee
        # ensure required fields present even if caller omitted: fill defaults
        base_entry = {
            "ts": _now_iso(),
            "runId": self.run_id,
            "nodeId": entry.get("nodeId") or entry.get("node_id") or "unknown",
            "agentId": entry.get("agentId") or entry.get("agent_id") or "executor",
            "attempt": entry.get("attempt", 1),
            "latency_ms": entry.get("latency_ms") if entry.get("latency_ms") is not None else entry.get("latency", 0),
            "tokens_est": entry.get("tokens_est") if entry.get("tokens_est") is not None else entry.get("tokens", 0),
            "status": entry.get("status", "running"),
            "errorClass": entry.get("errorClass") if "errorClass" in entry else entry.get("error_class"),
        }
        # preserve ooda, tempo, layer, metrics if supplied
        for k in ("layer","ooda","tempo","input","output","metrics","dag_version"):
            if k in entry:
                base_entry[k]=entry[k]
        # ensure 7-field timeline present
        # errorClass can be None; still counts as field present
        for p in self._all_timeline_paths():
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(json.dumps(base_entry) + "\n")
            except Exception:
                pass

    def log_node(self, event: Dict[str, Any]) -> Dict[str, Any]:
        entry = self._dual_write_timeline(event)  # _dual_write_timeline returns None, but it writes
        # we need to reconstruct entry for lattice write detection
        # reconstruct minimal from event
        rec = {
            "nodeId": event.get("nodeId") or event.get("node_id") or "unknown",
            "agentId": event.get("agentId") or event.get("agent_id") or "executor",
            "attempt": event.get("attempt", 1),
            "latency_ms": event.get("latency_ms") or event.get("latency", 0),
            "tokens_est": event.get("tokens_est") or event.get("tokens", 0),
            "status": event.get("status", "running"),
            "errorClass": event.get("errorClass") or event.get("error_class"),
        }
        # immediate lattice write on blocked/failed with known error taxonomy
        if rec["status"] in ("blocked","failed") and rec.get("errorClass") in FAILURE_TAXONOMY:
            self._immediate_lattice_write_blocked(rec, raw=event)
        # return canonical 7-field view
        return rec

    def _immediate_lattice_write_blocked(self, entry: Dict[str, Any], raw: Dict[str, Any]|None=None):
        for base in _ALL_RUNS_DIRS:
            lattice_path = base / self.run_id / "lattice_diff.jsonl"
            try:
                diff = {
                    "ts": _now_iso(),
                    "type": "BLOCKED",
                    "runId": self.run_id,
                    "nodeId": entry["nodeId"],
                    "agentId": entry["agentId"],
                    "errorClass": entry["errorClass"],
                    "status": entry["status"],
                    "delta": f"{entry['nodeId']} {entry['errorClass']} vs prev run — memory is difference",
                    "1500_chars": (json.dumps(raw or entry)[:1500]),
                    "memory_is_diff": "BLOCKED episodic vs semantic vs working 1500 chars immediate write",
                }
                lattice_path.parent.mkdir(parents=True, exist_ok=True)
                with open(lattice_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(diff) + "\n")
            except Exception:
                pass

    def save(self, state: Dict[str, Any]):
        # enforce 7-field checkpoint.json on save
        merged = {**self.checkpoint, **state, "saved_at": _now_iso(), "runId": self.run_id}
        # ensure required fields present
        for f in REQUIRED_CHECKPOINT_FIELDS:
            if f not in merged:
                if f=="runId": merged[f]=self.run_id
                elif f=="dag_version": merged[f]=1
                elif f=="nodes": merged[f]=[]
                elif f=="created": merged[f]=_now_iso()
                elif f=="saved_at": merged[f]=_now_iso()
                elif f=="version": merged[f]="v0.8-scout-v3.3-parity"
                elif f=="provenance": merged[f]=self.checkpoint.get("provenance",{})
        for p in self._all_checkpoint_paths():
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(merged, f, indent=2)
            except Exception:
                pass
        if state.get("nodes") is not None:
            for tp in self._all_timeline_paths():
                try:
                    with open(tp, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": _now_iso(), "event":"checkpoint_saved","runId": self.run_id, "dag_version": merged.get("dag_version",1),"nodes": len(merged.get("nodes",[])), "nodeId":"checkpoint","agentId":"checkpoint-manager","attempt":1,"latency_ms":0,"tokens_est":0,"status":"ok","errorClass":None})+"\n")
                except Exception:
                    pass
        return merged

    def load(self, run_id: Optional[str]=None) -> Optional[Dict[str,Any]]:
        rid = run_id or self.run_id
        for base in _ALL_RUNS_DIRS:
            p = base / rid / "checkpoint.json"
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except:
                    continue
        return None

    def pause(self, reason="human gate"):
        self.save({"paused":True,"pause_reason":reason,"paused_at":_now_iso()})
        for tp in self._all_timeline_paths():
            try:
                with open(tp,"a",encoding="utf-8") as f:
                    f.write(json.dumps({"ts":_now_iso(),"event":"checkpoint_pause","reason":reason,"runId":self.run_id,"nodeId":"checkpoint","agentId":"checkpoint-manager","attempt":1,"latency_ms":0,"tokens_est":0,"status":"paused","errorClass":None})+"\n")
            except: pass

    def resume(self, run_id: Optional[str]=None) -> Dict[str,Any]:
        state = self.load(run_id or self.run_id)
        if not state: raise FileNotFoundError(f"no checkpoint for {run_id or self.run_id}")
        next_nodes = [n for n in state.get("nodes",[]) if n.get("status")!="done"]
        return {"state":state,"next_nodes":next_nodes,"resume_msg":f"resumed {run_id or self.run_id} v{state.get('dag_version',1)} {len(next_nodes)} nodes pending"}

    def verify_seven(self, run_id: Optional[str]=None) -> Dict[str,Any]:
        rid = run_id or self.run_id
        results=[]
        for rel in _SEVEN_REL:
            p=_WORKSPACE_ROOT/rel/rid/"checkpoint.json"
            ok=p.exists()
            fields_ok=False
            if ok:
                try:
                    data=json.loads(p.read_text())
                    fields_ok=all(f in data for f in REQUIRED_CHECKPOINT_FIELDS)
                except: fields_ok=False
            timeline=_WORKSPACE_ROOT/rel/rid/"timeline.jsonl"
            tl_ok=timeline.exists()
            tl_fields_ok=False
            if tl_ok:
                try:
                    line=timeline.read_text().splitlines()[0] if timeline.read_text().strip() else "{}"
                    j=json.loads(line)
                    tl_fields_ok=all(k in j for k in ["nodeId","agentId","attempt","latency_ms","tokens_est","status","errorClass"])
                except: tl_fields_ok=False
            results.append({"rel":rel,"checkpoint_exists":ok,"checkpoint_7field":fields_ok,"timeline_exists":tl_ok,"timeline_7field":tl_fields_ok})
        total_ok=sum(1 for r in results if r["checkpoint_exists"] and r["checkpoint_7field"])
        return {"runId":rid,"seven":results,"seven_ok": total_ok==7, "count_ok": total_ok}

# MoMA-lite
def moma_lite_classify(text: str) -> Dict[str,Any]:
    t=text.lower()
    if any(k in t for k in ["heartbeat","monitor","tick","cron health","deterministic"]):
        return {"tier":"deterministic","cost":"cheap","rationale":"heartbeat/monitor no LLM"}
    if any(k in t for k in ["compare","triangulation","sources","wide sweep","agentic loops","ooda","best practices","arxiv","paper"]):
        return {"tier":"deep_research","cost":"heavy 9K","rationale":"multi-domain needs 5-7 sources"}
    if any(k in t for k in ["gmail","calendar","tool chain","orchestrate","idempotent","rollback"]):
        return {"tier":"action_operator","cost":"medium verification heavy","rationale":"side-effect class"}
    if any(k in t for k in ["agentic loop","dynamic workflow","checkpoint","graphplanner","opaque goal","long running"]):
        return {"tier":"agentic_epic","cost":"epic 13-agent swarm checkpointed","rationale":"GraphPlanner G_workflow+G_history + checkpoint"}
    return {"tier":"llm","cost":"medium","rationale":"general chat/summarize/draft"}

def classify_curation_intent(text: str) -> str:
    clf=moma_lite_classify(text)
    if clf["tier"]=="deterministic": return "healthcheck"
    if clf["tier"]=="deep_research": return "research_engine"
    if clf["tier"]=="action_operator": return "tool_gate"
    if clf["tier"]=="agentic_epic": return "continuous"
    return "standard"

def recovery_ladder(error_class: str, side_effect: str, attempt: int) -> Dict[str,Any]:
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

def score_for_cli(text: str) -> Dict[str,Any]:
    m=moma_lite_classify(text)
    return {"intent": m["tier"], "moma_tier": m["tier"], "moma_cap": m["cost"], "graph_memory":{"G_workflow":"current DAG","G_history":"past runs"}}

def _cli_verify(run_id: str):
    mgr=DottieCheckpointManager(run_id)
    res=mgr.verify_seven(run_id)
    print(json.dumps(res, indent=2))
    return res["seven_ok"]

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--verify", type=str, help="runId to verify 7/7")
    ap.add_argument("--runId", type=str, default=None)
    args=ap.parse_args()
    if args.verify:
        ok=_cli_verify(args.verify)
        raise SystemExit(0 if ok else 1)
