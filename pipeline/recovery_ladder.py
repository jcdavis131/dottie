"""dottie/pipeline/recovery_ladder.py — Bounded Recovery Ladder + Failure Taxonomy + SideEffectClasses
Scout v3.3 parity, solo project, no torch.
Implements retry1→patch→replan→escalate cannot skip, WRITE_DESTRUCTIVE/EXTERNAL_NOTIFY never auto.
"""

from __future__ import annotations
from typing import Dict, Any

FAILURE_TAXONOMY = ["INPUT_CORRUPTION","CONTEXT_STARVATION","TOOL_FAILURE","REASONING_COLLAPSE","OUTPUT_CORRUPTION"]
SIDE_EFFECT_CLASSES = {
    "READ": {"idempotent": True, "auto": True, "description": "safe unlimited, schema+sandbox 30s"},
    "WRITE_IDEMPOTENT": {"idempotent": True, "auto": "1x check", "description": "idempotent re-write allowed once, then re-read to confirm"},
    "WRITE_DESTRUCTIVE": {"idempotent": False, "auto": False, "description": "never auto — needs human gate, bio-map Remodeling"},
    "EXTERNAL_NOTIFY": {"idempotent": False, "auto": False, "description": "never speculative — requires explicit user approval"},
}

def recovery_ladder(error_class: str, side_effect: str, attempt: int) -> Dict[str,Any]:
    if error_class not in FAILURE_TAXONOMY:
        error_class="TOOL_FAILURE"
    if side_effect not in SIDE_EFFECT_CLASSES:
        side_effect="READ"
    # hard gate
    if side_effect in ("WRITE_DESTRUCTIVE","EXTERNAL_NOTIFY"):
        return {"action":"escalate","reason":f"{side_effect} never auto — needs human gate","attempt":attempt,"errorClass":error_class,"sideEffect":side_effect,"bounded":True,"bio_map":"Remodeling — human gate, parallel true"}
    if attempt==1:
        return {"action":"retry1","attempt":1,"errorClass":error_class,"sideEffect":side_effect,"safe":side_effect in ("READ","WRITE_IDEMPOTENT"),"bio":"Hemostasis — stop bleeding, retry exact","next_if_fail":"patch"}
    if attempt==2:
        return {"action":"patch","attempt":2,"errorClass":error_class,"sideEffect":side_effect,"fix":"single-resp patch — fix concrete file:line evidence, no reformat ocean","bio":"Inflammation — narrow scope, one file, one resp","next_if_fail":"replan"}
    if attempt==3:
        return {"action":"replan","attempt":3,"errorClass":error_class,"sideEffect":side_effect,"dag_version_inc":True,"bounded":True,"bio":"Proliferation — pure-function DAG re-plan, version++ never mutate in place","next_if_fail":"escalate"}
    return {"action":"escalate","attempt":attempt,"errorClass":error_class,"sideEffect":side_effect,"bounded":True,"bio":"Remodeling — human gate, visible abandonment","reason":"3 attempts exhausted — escalate with evidence packet"}

def contextual_recovery_table() -> Dict[str, Dict[str,str]]:
    return {
        "INPUT_CORRUPTION": {"retry1":"validate schema, coerce missing, fallback default","patch":"add guard clause, file:line evidence","replan":"change node input type to require validated dict"},
        "CONTEXT_STARVATION": {"retry1":"re-read MEMORY.md + lattice 1-2 hops","patch":"inject curated context pack","replan":"split node — Observe fresh imperfect snapshot 20%"},
        "TOOL_FAILURE": {"retry1":"tool retry with backoff 30s×2","patch":"switch tool adapter (openai→anthropic)","replan":"pure-function invocation wrapper"},
        "REASONING_COLLAPSE": {"retry1":"add 7-step bound, Orient lattice+culture+exp","patch":"lateral lens ONE only — inversion","replan":"strategist 3-lens optimistic/pessimistic/strange"},
        "OUTPUT_CORRUPTION": {"retry1":"validate output json schema","patch":"add missing required field","replan":"builder self-contained artifact check"},
    }

def explain_ladder(error_class: str, side_effect: str, attempt: int) -> str:
    ladder=recovery_ladder(error_class, side_effect, attempt)
    table=contextual_recovery_table().get(error_class,{})
    return f"Ladder {attempt} {error_class}/{side_effect} → {ladder['action']}: {table.get(ladder['action'], ladder.get('reason',''))}"
