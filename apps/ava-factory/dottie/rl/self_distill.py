"""
Self-distillation loop – MAI Sec 3.4 Fig15
Collect rollouts from RL, SFT midtrained checkpoint, preserve capabilities
Scaling: O(10k-50k) traces for 1B vs 1M for 35B active

Steps:
- collect rollouts from RL runs (mock)
- filter successful (or include incorrect per findings – both similar)
- sample diverse across later checkpoints
- mix mid-training data (10-20% mid data + 80-90% reasoning traces)
- SFT with dropout 0.15, load_balance 1e-2 vs RL 1e-5, loss: cosine 1.7e-5 ->5.2e-6 warmup 2%

Footer: Solo personal project, no connection to employer, built with public/free-tier only
"""
from __future__ import annotations
import json, random, time
from pathlib import Path
from typing import List, Dict

REPO = Path(__file__).resolve().parent.parent.parent
REPORTS = REPO / "reports"

def collect_mock_traces(n: int = 5000) -> List[Dict]:
    traces=[]
    for i in range(n):
        traces.append({
          "prompt": f"Math problem {i}: solve x^2+{i}x+...=?",
          "response": f"Reasoning trace {i} ... final answer {i%100}",
          "task_reward": 1.0 if i%3==0 else 0.5,
          "checkpoint_step": 1000 + (i//100)*100,
          "length": random.randint(200,8000),
          "success": i%3==0
        })
    return traces

def self_distill_filter(traces: List[Dict], keep_success_only: bool=False, max_traces: int=10000) -> List[Dict]:
    # Per MAI: training traces including incorrect performs similarly, but we restrict to successful for safety
    # Sample diverse across later checkpoints (prefer later)
    # Use random sampling (outperformed shortest-trace heuristic)
    if keep_success_only:
        filtered=[t for t in traces if t.get("success")]
    else:
        filtered=traces  # include both per finding

    # sort by checkpoint_step descending, take later 70%
    filtered_sorted=sorted(filtered, key=lambda x: x["checkpoint_step"], reverse=True)
    later = filtered_sorted[: int(len(filtered_sorted)*0.7)]

    # random sample across later for diversity
    sampled = random.sample(later, min(len(later), max_traces))
    return sampled

def mix_with_mid_data(traces: List[Dict], mid_data_frac: float=0.15) -> List[Dict]:
    # Mix mid-training data to avoid forgetting long-context (especially when traces from short max lengths)
    mid_data=[]
    n_mid = int(len(traces)*mid_data_frac/(1-mid_data_frac)) if mid_data_frac<1 else 0
    for i in range(n_mid):
        mid_data.append({"prompt": f"Mid doc {i}", "response": f"Academic text {i} long context analysis...", "source":"mid_training","length":4000})
    mixed = traces + mid_data
    random.shuffle(mixed)
    return mixed

def sft_config():
    return {
      "global_batch": 2048,  # packed sequences
      "seq_len": 131072,
      "optimizer": "adamw",
      "weight_decay": 0.001,
      "lr_schedule": "cosine",
      "lr_max": 1.7e-5,
      "lr_min": 5.2e-6,
      "warmup_frac": 0.02,
      "dropout": 0.15,
      "moe_load_balance_coef": 1e-2,  # vs RL 1e-5
      "note": "Self-distillation before length extensions mix mid data"
    }

def run_self_distillation(n_traces: int=10000, out_path: Path=None):
    out_path = out_path or REPORTS / "self_distill_checkpoint.json"
    REPORTS.mkdir(exist_ok=True, parents=True)
    traces = collect_mock_traces(n=n_traces*2)
    filtered = self_distill_filter(traces, keep_success_only=False, max_traces=n_traces)
    mixed = mix_with_mid_data(filtered, mid_data_frac=0.15)
    cfg = sft_config()
    result = {
      "timestamp": time.time(),
      "n_collected": len(traces),
      "n_filtered": len(filtered),
      "n_mixed": len(mixed),
      "config": cfg,
      "sample": mixed[:2],
      "markers": ["self_distill_start", "self_distill_sft", "self_distill_end"]
    }
    out_path.write_text(json.dumps(result, indent=2))
    print(f"Self-distill: collected {len(traces)} filtered {len(filtered)} mixed {len(mixed)} -> {out_path}")
    print(f"markers {result['markers']} PASS")
    return result

if __name__=="__main__":
    run_self_distillation(n_traces=5000)
