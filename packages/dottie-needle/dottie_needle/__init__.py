"""dottie_needle — native grammar-constrained function calling for Dottie.

Tier 1 of the native Needle rewrite: tool schemas compiled into a fail-closed
grammar, so a malformed tool call is rejected at the gate instead of reaching
the tool plane. Stdlib only. This package never executes or authorizes calls.
"""

from dottie_needle.engine import GuidedCaller, NoValidCallError, retrieve_tools
from dottie_needle.grammar import CompiledGrammar, GrammarError, ToolSpec

__all__ = [
    "CompiledGrammar",
    "GrammarError",
    "GuidedCaller",
    "NoValidCallError",
    "ToolSpec",
    "retrieve_tools",
]

__version__ = "0.1.0"
