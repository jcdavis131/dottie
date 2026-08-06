"""dottie/pipeline/memory_lattice.py — Memory lattice / graph write-back + GARNet
Implements G_workflow (current DAG nodes+edges+status) + G_history (past runs timeline.jsonl patterns)
Immediate lattice write BLOCKED/DONE/PLANNED 1500 chars + People write-back + Scout v5 people resolver
Numpy-only, no torch.
"""

from __future__ import annotations
import json, hashlib, re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

_WORKSPACE = Path.home() / "workspace"
_MEMORY_DIR = _WORKSPACE / "bundles" / "memory"
_GRAPH_DIR = _MEMORY_DIR / "graph"
_LATTICE_DIR = _MEMORY_DIR / "lattice"

def _now_iso(): return datetime.now(timezone.utc).isoformat()
def sha16(s: str): return hashlib.sha1(s.encode()).hexdigest()[:16]

class MemoryLattice:
    """Three memory tiers: episodic (timeline deltas), semantic (pattern→fix), working (1500-char immediate)."""

    def __init__(self, run_id: str):
        self.run_id=run_id
        self.base=_LATTICE_DIR/run_id
        self.base.mkdir(parents=True, exist_ok=True)
        self.episodic_path=self.base/"episodic.jsonl"
        self.semantic_path=_LATTICE_DIR/"semantic.jsonl"
        self.working_path=self.base/"working.jsonl"
        self.graph_path=_GRAPH_DIR/f"{run_id}.jsonl"

    def write_episodic(self, node: Dict[str,Any]):
        entry={"ts":_now_iso(),"runId":self.run_id,"type":"episodic","node":node,"diff":f"{node.get('nodeId')} {node.get('status')} {node.get('errorClass')}"}
        with open(self.episodic_path,"a",encoding="utf-8") as f:
            f.write(json.dumps(entry)+"\n")
        return entry

    def write_semantic(self, pattern: str, fix: str, confidence: float=0.7):
        _LATTICE_DIR.mkdir(parents=True, exist_ok=True)
        entry={"ts":_now_iso(),"pattern":pattern,"fix":fix,"confidence":confidence,"source":self.run_id}
        with open(self.semantic_path,"a",encoding="utf-8") as f:
            f.write(json.dumps(entry)+"\n")
        return entry

    def write_working_immediate(self, status: str, nodeId: str, agentId: str, detail: str):
        self.working_path.parent.mkdir(parents=True, exist_ok=True)
        entry={"ts":_now_iso(),"runId":self.run_id,"type":status,"nodeId":nodeId,"agentId":agentId,"detail":detail[:1500],"1500_chars":detail[:1500]}
        with open(self.working_path,"a",encoding="utf-8") as f:
            f.write(json.dumps(entry)+"\n")
        return entry

    def graph_write_back(self, dag_nodes: List[Dict[str,Any]], edges: List[Dict[str,Any]]):
        _GRAPH_DIR.mkdir(parents=True, exist_ok=True)
        graph={"runId":self.run_id,"ts":_now_iso(),"G_workflow":{"nodes":dag_nodes,"edges":edges,"status":"live"},"G_history_ref":"timeline.jsonl patterns"}
        with open(self.graph_path,"w",encoding="utf-8") as f:
            for n in dag_nodes:
                f.write(json.dumps({"type":"node","runId":self.run_id,**n})+"\n")
            for e in edges:
                f.write(json.dumps({"type":"edge","runId":self.run_id,**e})+"\n")
        # also append to workspace MEMORY.md projection if Launched triple recall requested
        return graph

    def memory_is_diff(self, prev_run_id: Optional[str]=None) -> Dict[str,Any]:
        """PEC without memory hamster wheel guard: memory is difference iteration→improvement"""
        diff={"runId":self.run_id,"prev_runId":prev_run_id,"delta":"memory is difference","rule":"If iteration N+1 repeats failure of N with same DAG version, BLOCKED — must inc dag_version, patch, or semantic fix."}
        self.write_working_immediate("PLANNED","memory-lattice","memory-lattice",json.dumps(diff)[:1500])
        return diff

# People resolver write-back (Scout v5 Prime pattern)
def people_resolve(trigger: str, memory_path: Path|None=None) -> Optional[Dict[str,Any]]:
    memory_path = memory_path or (_WORKSPACE/"MEMORY.md")
    if not memory_path.exists(): return None
    txt=memory_path.read_text()
    # simple trigger search
    for line in txt.splitlines():
        if trigger.lower() in line.lower():
            # parse name <email> trigger
            return {"hit": line.strip(), "confidence":0.88, "source":"MEMORY.md"}
    return None

def people_write_back(name: str, email: str, trigger: str, role: str="", confidence: float=0.88):
    mem=_WORKSPACE/"MEMORY.md"
    line=f"- {name} <{email}> is {role or 'contact'} — trigger \"{trigger}\" confidence {confidence} source manual {datetime.now(timezone.utc).date().isoformat()}"
    with open(mem,"a",encoding="utf-8") as f:
        f.write("\n"+line+"\n")
    return line
