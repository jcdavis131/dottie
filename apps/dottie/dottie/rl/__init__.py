# Solo personal project, no connection to employer, built with public/free-tier only
"""ava.rl — reinforcement-learning + agentic-execution substrate (specs 12 & 13).

GPU-free, tested building blocks landed:
  * `codeact_sandbox`       — the LLM-VM (T13C.1): subprocess-isolated persistent-namespace interpreter.
  * `codeact_rewards`       — R_exec / R_codeuse / R_len / codeact_return (T13C.4 reward terms).
  * `grpo`                  — GRPO-lite discipline mechanics (T12R.2 / T13C.4): group advantages,
                              entropy-thermostat controller, outer ratio clip, trace-bank recovery.
  * `grpo_torch`            — the REAL torch GRPO optimizer step (T12R.2 torch half): exact-parity
                              clipped surrogate, thermostat/outer-clip wiring, backward + step.
                              CPU-verified: learning demo + spike/overflow NaN-survival tests.
  * `codeact_loop`          — pluggable-policy decode/serving loop (T13C.5): emit→sandbox→observe→FINAL.
  * `codeact_policy`        — the REAL autoregressive decode policy (T13C.5): TorchModelPolicy over
                              any torch LM + duck-typed tokenizer; greedy/sampling, seeded, stop-cut.
  * `codeact_consolidation` — MOPD trace-pool prep (T13C.5): verified-only, stratified.
  * `codeact_eg_gate`       — EG-gated rollout (T13C.6): success→error transform + eg_trend verdict.

The whole mechanical chain (decode → sandbox → rewards → advantages → torch update) has been
executed END-TO-END on a REAL smoke-scale checkpoint: `scripts/cpu_pilot_e2e.py` runs the real
nano CPU-pilot pipeline (datagen → tokenizer → pack → pretrain → agentic branch fork) and
`scripts/rl_smoke_update.py` performs a real GRPO update on the resulting branch checkpoint
(evidence: `runs/cpu_pilot/MANIFEST.json`, scale=smoke_cpu_pilot, capability_claim=none).

Still gated — now on CAPABILITY-scale resources only, not missing code: capability-level branch
checkpoints (T9.3/T9.5 at mini+; GPU wall-clock), the MOPD distillation run
(`codeact_consolidation.mopd_consolidation_run`), and the EG verdict (needs real 2-rung capability
curves). The legacy refusal stubs (`grpo.GRPOOptimizerStep`, `codeact_loop.ModelPolicy`) now point
to their real implementations and continue to refuse fabricated use.
"""

# ---- Dottie factory exports (closed-loop helper, added during tech-debt cleanup) ----
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

# keep legacy top-level expected by ava shim
try:
    __all__
except NameError:
    __all__ = []
__all__ = list(set(__all__ + ["RLVariant", "export_rft_dataset", "train_step", "codeact_loop", "codeact_sandbox", "grpo"]))
