"""ConversationGolden modes SIMULATE/REPLAY/SCRIPTED/GRAPH like harness-evals."""
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from ..core.golden import Message

class ConversationMode(str, Enum):
    SIMULATE="simulate"; REPLAY="replay"; SCRIPTED="scripted"; GRAPH="graph"

@dataclass
class ConversationGolden:
    scenario: str
    expected_outcome: str = ""
    turns: List[Message] = field(default_factory=list)  # pre-scripted user turns for SCRIPTED/REPLAY
    mode: ConversationMode = ConversationMode.SCRIPTED
    max_turns: int = 8
    user_persona: str = "helpful analyst"
    initial_prompt: str = ""
    graph_config: Optional[Dict[str,Any]] = None
    id: str = ""
