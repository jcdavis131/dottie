"""
Dottie LLMVM — LLM Virtual Machine layer inspired by Metamate Advanced Auto

Solo personal project, no connection to employer, built with public/free-tier only

Gives Dottie a Python runtime instead of JSON tool-calling loop:
- Persistent notebook namespace
- Async tools (signature = schema)
- Self-modification with audit log
- TMUX interactive terminal
- Skillbooks (docs + code + bootstrap notebook)
- Bidirectional context control

Usage:
    from dottie.llmvm import LLMVMKernel, ToolRegistry, TmuxManager
    kernel = LLMVMKernel()
    await kernel.exec_cell("x = await search_code('S2 hl=300')")
"""

from .kernel import LLMVMKernel, ExecutionResult
from .tool_registry import ToolRegistry, ToolMetadata
from .tmux import TmuxManager, TmuxPane
from .self_modify import SelfModifyManager, AuditEntry
from .skillbook import SkillBook, SkillBookManager
from .context import ContextManager

__all__ = [
    "LLMVMKernel",
    "ExecutionResult",
    "ToolRegistry",
    "ToolMetadata",
    "TmuxManager",
    "TmuxPane",
    "SelfModifyManager",
    "AuditEntry",
    "SkillBook",
    "SkillBookManager",
    "ContextManager",
]

__version__ = "0.1.0-llmvm"
