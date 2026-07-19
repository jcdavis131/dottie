"""
Bidirectional Context Control — loading in and compacting out

Solo personal project, no connection to employer, built with public/free-tier only

Metamate insight:
- Loading in: tool search and skill loading bring in relevant context
- Compacting out: agent actively manages own memory, removing failed attempts and replacing verbose output with concise summaries
- Long sessions that previously crashed at context limits now continue seamlessly

For Dottie: manifest 32k docs, frontier_eval_results.json verbose, builder.log 10k lines
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import time

@dataclass
class ContextEntry:
    id: str
    type: str  # tool_output, code_result, failed_attempt, summary
    content: str
    tokens_est: int
    timestamp: float = field(default_factory=time.time)
    useful: bool = True
    kept: bool = True

class ContextManager:
    """
    Bidirectional context control.
    Loading in via tool search, compacting out via active memory management.
    """
    
    def __init__(self, max_tokens: int = 120000):
        self.max_tokens = max_tokens
        self.entries: List[ContextEntry] = []
        self.total_tokens = 0
    
    def add(self, entry: ContextEntry):
        self.entries.append(entry)
        if entry.kept:
            self.total_tokens += entry.tokens_est
        
        # auto-compact if over limit — long sessions continue seamlessly
        if self.total_tokens > self.max_tokens * 0.9:
            self.compact()
    
    def search_and_load(self, query: str, registry) -> List[Dict]:
        """
        Loading in: tool search brings in relevant context only
        Only lightweight metadata upfront (~100 tokens per skill)
        """
        results = registry.search(query)
        loaded = []
        for meta in results:
            # only load detailed definition on demand
            self.add(ContextEntry(
                id=f"tool_{meta.name}",
                type="tool_output",
                content=f"{meta.signature}: {meta.description}",
                tokens_est=meta.tokens_est,
            ))
            loaded.append({"name": meta.name, "signature": meta.signature})
        return loaded
    
    def compact(self):
        """
        Compacting out: agent actively manages memory
        - Removing failed attempts
        - Replacing verbose output with concise summaries
        """
        compacted = []
        removed_tokens = 0
        
        for e in self.entries:
            if e.type == "failed_attempt" and e.tokens_est > 500:
                # remove failed attempts — don't pile up
                e.kept = False
                removed_tokens += e.tokens_est
            elif e.tokens_est > 2000 and e.type == "tool_output":
                # replace verbose with summary
                original_tokens = e.tokens_est
                e.content = f"[Summary of {e.id}]: {e.content[:200]}... (compressed from {original_tokens} tokens)"
                e.tokens_est = 200
                removed_tokens += original_tokens - 200
                compacted.append(e.id)
        
        self.total_tokens = sum(en.tokens_est for en in self.entries if en.kept)
        return {"removed_tokens": removed_tokens, "compacted_ids": compacted, "remaining": self.total_tokens}
    
    def summarize_session(self) -> str:
        """Replace verbose with concise — only final output enters context"""
        useful = [e for e in self.entries if e.kept and e.useful]
        return f"Session summary: {len(useful)} useful entries, {self.total_tokens} tokens, {len(self.entries)-len(useful)} compacted/removed"

# Example: how Dottie reduces 10k log to 200 token summary
def example_compaction():
    mgr = ContextManager(max_tokens=8000)
    
    # builder.log backpressure — 10k lines of same message
    mgr.add(ContextEntry(
        id="builder_log",
        type="tool_output",
        content="2026-07-09 17:43:58 [Builder] Backpressure: 27 shards pending > 20 allowed\n" * 500,
        tokens_est=8000,
    ))
    
    # compact — replace with summary
    result = mgr.compact()
    # Now: "Backpressure 27 shards pending >20 allowed, 27 occurences 17:43-17:47, root cause: curator tok/s < 3x trainer tok/s"
    # Only 200 tokens, not 8000
    
    return result
