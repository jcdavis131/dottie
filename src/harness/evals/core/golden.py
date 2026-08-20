from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict

@dataclass
class Golden:
    input: str
    expected: Any = None
    context: List[str] = field(default_factory=list)
    expected_tools: List[str] = field(default_factory=list)
    tags: Dict[str,str] = field(default_factory=dict)
    metadata: Dict[str,Any] = field(default_factory=dict)
    id: str = ""

@dataclass
class Message:
    role: str
    content: str
    tool_calls: List[Any] = field(default_factory=list)
    metadata: Dict[str,Any] = field(default_factory=dict)

@dataclass
class ToolCall:
    name: str
    input: Dict[str,Any] = field(default_factory=dict)
    output: Any = None
    id: str = ""

@dataclass
class EvalCase:
    input: str
    output: str
    expected: Any = None
    context: List[str] = field(default_factory=list)
    messages: List[Message] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    expected_tools: List[str] = field(default_factory=list)
    expected_tool_calls: List[ToolCall] = field(default_factory=list)
    latency_ms: Optional[int] = None
    token_count: Optional[int] = None
    cost_usd: Optional[float] = None
    retry_count: int = 0
    confidence: Optional[float] = None
    tags: Dict[str,str] = field(default_factory=dict)
    metadata: Dict[str,Any] = field(default_factory=dict)
    runs: List[Any] = field(default_factory=list)
    id: str = ""

    @classmethod
    def from_golden(cls, g: Golden, output: str, **kw):
        # golden provides expected_tools etc but kw may override
        data=dict(input=g.input, output=output, expected=g.expected,
                  context=g.context, tags=g.tags, metadata=g.metadata, id=g.id)
        data.update(kw)
        # ensure expected_tools from kw wins over golden if supplied
        if 'expected_tools' not in kw: data['expected_tools']=g.expected_tools
        return cls(**data)
