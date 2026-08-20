"""JsonBaselineStore + compare like harness-evals — detects regressions."""
import json, pathlib, time
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class BaselineDiff:
    regressions: List[str]
    improvements: List[str]
    unchanged: List[str]
    tolerance: float
    @property
    def has_regressions(self): return bool(self.regressions)
    def summary(self): return f"regress:{len(self.regressions)} improv:{len(self.improvements)} same:{len(self.unchanged)} tol:{self.tolerance}"

class JsonBaselineStore:
    def __init__(self, baseline_dir=".evals/baselines"):
        self.dir=pathlib.Path(baseline_dir); self.dir.mkdir(parents=True, exist_ok=True)
    def save(self, run_id: str, scores_by_name: Dict[str,float]):
        p=self.dir/f"{run_id}.json"
        p.write_text(json.dumps({"run_id":run_id,"ts":time.time(),"scores":scores_by_name}, indent=2))
        # also latest
        (self.dir/"latest.json").write_text(json.dumps(scores_by_name, indent=2))
    def load(self, run_id: str=None) -> Dict[str,float]:
        if run_id:
            return json.loads((self.dir/f"{run_id}.json").read_text())["scores"]
        return json.loads((self.dir/"latest.json").read_text()) if (self.dir/"latest.json").exists() else {}

def compare_to_baseline(current: Dict[str,float], baseline: Dict[str,float], tolerance=0.05) -> BaselineDiff:
    regs=[]; improv=[]; same=[]
    for k,v in current.items():
        b=baseline.get(k)
        if b is None: continue
        if v < b - tolerance: regs.append(f"{k}:{b:.2f}->{v:.2f}")
        elif v > b + tolerance: improv.append(f"{k}:{b:.2f}->{v:.2f}")
        else: same.append(k)
    return BaselineDiff(regs, improv, same, tolerance)
