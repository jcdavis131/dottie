"""
Self-Modification — Agent that rewrites itself

Solo personal project, no connection to employer, built with public/free-tier only

In tool-calling framework, set of tools fixed at start. LLM can't create new tools.
In LLMVM, agent runs in persistent Python namespace, can define new functions and use them immediately.

Goes further: override existing runtime functions.
Agent adds caching layer to its own download function. Every subsequent call goes through cache.
Runtime didn't need caching tool. Agent created one at layer it needed.

This is not bolt-on — emergent property of real programming environment.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any, Optional
import time
import hashlib
import json

@dataclass
class AuditEntry:
    timestamp: float
    action: str  # define, override, cache_wrap
    tool_name: str
    code: str
    prev_code: Optional[str] = None
    reason: str = ""
    enabled: bool = True

class SelfModifyManager:
    """
    Manages self-modification with audit log, rollback, gated write.
    Analogous to ENABLE_JSPACE_WRITE gate for J-Space research mode.
    """
    
    def __init__(self, require_gate: bool = True):
        self.audit_log: List[AuditEntry] = []
        self.originals: Dict[str, Callable] = {}
        self.current: Dict[str, Callable] = {}
        self.require_gate = require_gate
        self.gate_enabled = False  # ENABLE_LLMVM_WRITE=1 to allow overrides
        self.cache: Dict[str, Any] = {}
    
    def enable_write(self, token: str = "ENABLE_LLMVM_WRITE=1"):
        """Gate like ENABLE_JSPACE_WRITE — research mode"""
        if "ENABLE_LLMVM_WRITE" in token:
            self.gate_enabled = True
            return True
        return False
    
    def define_tool(self, func: Callable, reason: str = "") -> AuditEntry:
        """Define new tool mid-session — emergent capability"""
        name = func.__name__
        entry = AuditEntry(
            timestamp=time.time(),
            action="define",
            tool_name=name,
            code=func.__code__.co_code.hex()[:200],  # truncated
            reason=reason,
        )
        self.current[name] = func
        self.audit_log.append(entry)
        return entry
    
    def override_tool(self, name: str, new_func: Callable, reason: str = "") -> AuditEntry:
        """Override existing runtime function — e.g., add caching layer"""
        if self.require_gate and not self.gate_enabled:
            raise PermissionError("Self-modification requires ENABLE_LLMVM_WRITE=1 gate. Set env or call enable_write(). Audit mode only.")
        
        prev = self.current.get(name)
        if name not in self.originals and prev is not None:
            self.originals[name] = prev
        
        # capture prev code for audit
        prev_code = None
        if prev and hasattr(prev, "__code__"):
            prev_code = prev.__code__.co_code.hex()[:200]
        
        entry = AuditEntry(
            timestamp=time.time(),
            action="override",
            tool_name=name,
            code=new_func.__code__.co_code.hex()[:200] if hasattr(new_func, "__code__") else str(new_func)[:200],
            prev_code=prev_code,
            reason=reason,
        )
        
        self.current[name] = new_func
        self.audit_log.append(entry)
        return entry
    
    def cached_wrap(self, func: Callable, cache_key_fn: Optional[Callable] = None) -> Callable:
        """
        Agent adds caching layer to its own download function.
        Every subsequent call goes through cache.
        """
        def _default_key(*args, **kwargs):
            return hashlib.md5(json.dumps([args, kwargs], sort_keys=True, default=str).encode()).hexdigest()
        
        key_fn = cache_key_fn or _default_key
        
        def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{key_fn(*args, **kwargs)}"
            if key in self.cache:
                return self.cache[key]
            result = func(*args, **kwargs)
            self.cache[key] = result
            return result
        
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = f"Cached wrapper around {func.__name__}\n{func.__doc__ or ''}"
        
        # audit
        self.override_tool(func.__name__, wrapper, reason="Add caching layer — self-modification emergent")
        return wrapper
    
    def rollback(self, tool_name: str) -> bool:
        """Rollback to original"""
        if tool_name in self.originals:
            self.current[tool_name] = self.originals[tool_name]
            self.audit_log.append(AuditEntry(
                timestamp=time.time(),
                action="rollback",
                tool_name=tool_name,
                code="rollback_to_original",
                reason="Rollback self-modification",
            ))
            return True
        return False
    
    def recent(self, n: int = 10) -> List[AuditEntry]:
        return self.audit_log[-n:]

# Concrete examples for Dottie — what agent builds when auditing itself

def example_cached_download():
    """This is what Dottie agent writes when auditing codebase — real example"""
    code = '''
# Agent discovered: hf download called 74 times in builder loop, no cache
# Defining new tool mid-session:

download_cache = {}

async def download(url: str):
    """Original download — no cache"""
    # ... fetch
    pass

# Override with caching layer — every subsequent call goes through cache
original_download = download

async def cached_download(url: str):
    if url in download_cache:
        return download_cache[url]
    data = await original_download(url)
    download_cache[url] = data
    return data

download = cached_download  # runtime patched mid-session

# Next 73 calls now hit cache — token savings: 73 * tool-call round-trips
'''
    return code

def example_code_smell_analyzer():
    code = '''
# Agent built custom toolkit to audit own codebase — not pre-designed

def audit_jspace_leak():
    """Finds 3 properties that were 'passing' for years by being unobservable"""
    leaks = []
    
    # 1. attention had no causal mask — loss drops implausibly fast
    if not has_causal_mask("dottie/attention/compressed_conv.py"):
        leaks.append("attention no causal mask — check compressed_conv.py causal = tril()")
    
    # 2. workspace broadcast future into past
    if broadcasts_future("dottie/model.py"):
        leaks.append("broadcast future→past — S2 hl=300 leaks across time")
    
    # 3. verbalizable_mass was constant 0.06 — not measured
    if is_constant_verbalizable_mass():
        # Fixed in v6.4: now measured via top_p.sum() in serve_engine.py
        leaks.append("verbalizable_mass constant 0.06 — should be measured")
    
    return leaks

# Define and use immediately — impossible in JSON loop
leaks = audit_jspace_leak()
'''
    return code
