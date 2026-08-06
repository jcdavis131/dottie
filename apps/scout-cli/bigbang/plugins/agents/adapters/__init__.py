"""
agents adapters package
"""

from .langchain_adapter import LangChainAdapter, get_langchain_adapter
from .langgraph_adapter import LangGraphAdapter, get_langgraph_adapter
from .crewai_adapter import CrewAIAdapter, get_crewai_adapter
from .openai_adapter import OpenAIAdapter, get_openai_adapter
from .autogen_adapter import AutoGenAdapter, get_autogen_adapter
from .base import TokenCache5, ProvenanceTracker

__all__ = [
    "LangChainAdapter","get_langchain_adapter",
    "LangGraphAdapter","get_langgraph_adapter",
    "CrewAIAdapter","get_crewai_adapter",
    "OpenAIAdapter","get_openai_adapter",
    "AutoGenAdapter","get_autogen_adapter",
    "TokenCache5","ProvenanceTracker",
]

ADAPTERS = {
    "langchain": get_langchain_adapter,
    "langgraph": get_langgraph_adapter,
    "crewai": get_crewai_adapter,
    "openai": get_openai_adapter,
    "autogen": get_autogen_adapter,
}

def list_adapters():
    return list(ADAPTERS.keys())

def get_adapter(name: str):
    fn = ADAPTERS.get(name.lower())
    if not fn:
        raise ValueError(f"Unknown adapter {name}, known {list(ADAPTERS.keys())}")
    return fn()
