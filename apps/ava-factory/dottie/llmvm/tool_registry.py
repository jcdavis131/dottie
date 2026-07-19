"""
Tool Registry — defer-loaded 1000+ tools without context blowup

Solo personal project, no connection to employer, built with public/free-tier only

Metamate insight:
- Almost everything defer-loaded. Only lightweight metadata upfront (~100 tokens per skill)
- Agent searches for and loads detailed definitions on demand
- Signature is schema, docstring is description. Schema tax = 0.
- Massive toolset creates resilience — multiple paths to goal

For Dottie: HF datasets, code search, logs, OpenWiki, Ollama judges, W&B, etc.
"""

import inspect
from dataclasses import dataclass, asdict
from typing import Dict, List, Callable, Optional
import json

@dataclass
class ToolMetadata:
    name: str
    description: str
    signature: str  # the function signature IS the schema
    params: List[Dict]
    tokens_est: int  # ~100 tokens per skill metadata
    namespace: str
    loaded: bool = False

class ToolRegistry:
    """
    Defer-loaded registry. Upfront: ~100 tokens per skill.
    Detailed definition loaded on demand via search.
    """
    
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._metadata: Dict[str, ToolMetadata] = {}
        self._search_index: Dict[str, List[str]] = {}  # keyword -> tool names
    
    def register(self, func: Callable, namespace: str = "ava", description: Optional[str] = None):
        """Register tool — signature is schema, docstring is description"""
        sig = inspect.signature(func)
        doc = description or (func.__doc__ or "").strip().split("\n")[0]
        
        params = []
        for name, param in sig.parameters.items():
            params.append({
                "name": name,
                "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "any",
                "required": param.default == inspect.Parameter.empty,
            })
        
        meta = ToolMetadata(
            name=func.__name__,
            description=doc,
            signature=f"{func.__name__}{sig}",
            params=params,
            tokens_est=~100,  # lightweight metadata
            namespace=namespace,
            loaded=True,
        )
        
        self._tools[func.__name__] = func
        self._metadata[func.__name__] = meta
        
        # build search index for tool discovery (agent searches for tools)
        keywords = f"{func.__name__} {doc} {namespace}".lower().split()
        for kw in keywords:
            self._search_index.setdefault(kw, []).append(func.__name__)
        
        return func
    
    def search(self, query: str, top_k: int = 10) -> List[ToolMetadata]:
        """Agent searches for and loads detailed tool definitions on demand"""
        query = query.lower()
        candidates = set()
        for kw, tools in self._search_index.items():
            if kw in query or query in kw:
                candidates.update(tools)
        
        # also fuzzy match description
        for name, meta in self._metadata.items():
            if query in meta.description.lower() or query in name.lower():
                candidates.add(name)
        
        results = [self._metadata[name] for name in candidates][:top_k]
        return results
    
    def load(self, name: str) -> Optional[Callable]:
        """Load detailed definition on demand — only now does token cost hit"""
        return self._tools.get(name)
    
    def list_lightweight(self) -> List[Dict]:
        """Upfront metadata: ~100 tokens per skill — no context blowup"""
        return [
            {"name": m.name, "desc": m.description[:80], "tokens": m.tokens_est, "ns": m.namespace}
            for m in self._metadata.values()
        ]
    
    def total_tokens_if_all_loaded(self) -> int:
        return len(self._metadata) * 100
    
    def total_tokens_detailed(self) -> int:
        # if all tools loaded with full schema, would blow up
        return len(self._metadata) * 800  # 8x blowup estimate

# Pre-populate with Dottie's actual tool surface (free-tier only)
def create_dottie_registry() -> ToolRegistry:
    reg = ToolRegistry()
    
    # These will be async functions in real runtime
    async def search_code(pattern: str, top_k: int = 10): 
        """Search codebase for pattern with ripgrep"""
        pass
    async def search_logs(pattern: str, hours: int = 24):
        """Search builder.log and training logs"""
        pass
    async def read_manifest(): 
        """Read data manifest concurrency-safe"""
        pass
    async def analyze_jspace(text: str):
        """Run J-Space inspector hl estimation"""
        pass
    async def run_eval(branch: str = "all", mode: str = "mock"):
        """Run branch harness eval"""
        pass
    async def openwiki_search(query: str):
        """Search ~/.openwiki/wiki for S2 knowledge"""
        pass
    async def hf_dataset_search(query: str):
        """Search HF datasets for candidates"""
        pass
    async def download_cached(url: str):
        """Download with caching layer — self-moddable"""
        pass
    
    for fn in [search_code, search_logs, read_manifest, analyze_jspace, run_eval, openwiki_search, hf_dataset_search, download_cached]:
        reg.register(fn)
    
    return reg


# Backward compat alias
def create_ava_registry(*args, **kwargs):
    return create_dottie_registry(*args, **kwargs)
