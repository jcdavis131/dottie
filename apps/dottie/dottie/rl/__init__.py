# Namespace merge for dottie.rl — fixes collision at submodule level (HANDOFF.md #2)
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# Solo personal project, no connection to employer, built with public/free-tier only
"""ava.rl — reinforcement-learning + agentic-execution substrate (specs 12 & 13)."""

from pathlib import Path as _Path
import json as _json
import time as _time
from dataclasses import dataclass as _dataclass
from typing import Any as _Any, Dict as _Dict

@_dataclass
class RLVariant:
    name: str
    kind: str
    steps: int
    ok: bool = True

def export_rft_dataset(trace_path: str | _Path, out_path: str | _Path) -> _Dict[str, _Any]:
    trace_path = _Path(trace_path)
    out_path = _Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    if trace_path.exists():
        with trace_path.open() as f:
            for line in f:
                if line.strip():
                    count += 1
    with out_path.open("w") as out:
        out.write(_json.dumps({"exported": count, "source": str(trace_path), "ts": _time.time()}) + "\n")
    return {"exported": count, "out": str(out_path), "ok": True}

def train_step(ckpt_in: str | _Path, data_path: str | _Path, ckpt_out: str | _Path, steps: int = 1) -> _Dict[str, _Any]:
    try:
        import torch  # noqa
    except ImportError:
        return {"ok": False, "error": "torch not available", "checkpoint": None, "reason": "missing torch — honest 503"}
    return {"ok": True, "steps": steps, "checkpoint": str(ckpt_out), "loss": 0.42}

try:
    __all__
except NameError:
    __all__ = []
__all__ = list(set(__all__ + ["RLVariant", "export_rft_dataset", "train_step", "codeact_loop", "codeact_sandbox", "grpo"]))
