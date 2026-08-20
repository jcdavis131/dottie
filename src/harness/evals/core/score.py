"""Normalized Score 0.0-1.0 like harness-evals — pass/fail from threshold, no magic."""
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Score:
    name: str
    value: float  # 0.0-1.0
    threshold: float = 0.5
    passed: bool = None
    reason: str = ""
    dimension: str = "correctness"  # correctness|groundedness|safety|trajectory|performance
    latency_ms: Optional[int] = None

    def __post_init__(self):
        v = max(0.0, min(1.0, float(self.value)))
        object.__setattr__(self, "value", v)
        if self.passed is None:
            object.__setattr__(self, "passed", v >= float(self.threshold))

    def to_dict(self):
        return {"name": self.name, "value": self.value, "threshold": self.threshold,
                "passed": self.passed, "dimension": self.dimension, "reason": self.reason}
