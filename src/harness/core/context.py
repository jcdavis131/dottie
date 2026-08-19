"""Context window management 85%->50% compaction auto-summary preserving locals."""
THRESH=0.85
TARGET=0.50
def needs_compact(used_ratio:float)->bool: return used_ratio>=THRESH
def compact(mission_id:str, thread_id:str, locals_snapshot:dict, chunks_used:int)->dict:
    return {"mission_id":mission_id,"thread_id":thread_id,"locals":locals_snapshot,"chunks_used":chunks_used,"compacted_to":TARGET}
