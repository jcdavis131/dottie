"""
Specialists + consolidation – MAI Fig12
Train 3 RL specialists from stable ckpt using different prompt distributions,
then SFT combine traces into consolidated model, then final RL light.
"""
import json, time
from pathlib import Path
from dataclasses import dataclass

REPO = Path(__file__).resolve().parent.parent.parent
REPORTS = REPO/"reports"

@dataclass
class SpecialistConfig:
    name: str
    prompt_mix: dict
    reward_type: str
    steps: int

SPECIALISTS = [
    SpecialistConfig(name="stem_reasoning", prompt_mix={"math":0.585,"physics":0.132,"chem":0.109,"other":0.174}, reward_type="mcq_proof_open", steps=1000),
    SpecialistConfig(name="agentic_code", prompt_mix={"code":0.6,"tool_use":0.3,"temporal":0.1}, reward_type="tool_success", steps=1000),
    SpecialistConfig(name="helpfulness_safety", prompt_mix={"chat":0.5,"safety":0.3,"delegation":0.2}, reward_type="safety_score", steps=800),
]

def train_specialist(cfg: SpecialistConfig, base_ckpt: str):
    # mock training loop
    print(f"Training specialist {cfg.name} from {base_ckpt} mix {cfg.prompt_mix}")
    time.sleep(0.1)
    return {"name": cfg.name, "ckpt": f"{cfg.name}_final.pt", "steps": cfg.steps, "status":"done"}

def consolidate(specialist_ckpts: list[str], out: Path):
    # collect traces from all specialists, SFT
    print(f"Consolidating {specialist_ckpts} -> {out}")
    data={"specialists":specialist_ckpts,"method":"trace_distillation_sft","timestamp":time.time()}
    out.write_text(json.dumps(data,indent=2))
    return out

def final_rl_light(consolidated_ckpt: Path):
    print(f"Final RL light climb from {consolidated_ckpt}")
    return {"ckpt": "mai-thinking-1-dottie-final.pt", "stage":"final_rl"}

if __name__=="__main__":
    REPORTS.mkdir(exist_ok=True, parents=True)
    results=[]
    for spec in SPECIALISTS:
        r=train_specialist(spec, "dottie_nano_v66_stable.pt")
        results.append(r)
    cons_path=REPORTS/"consolidated_sft.json"
    consolidate([r["ckpt"] for r in results], cons_path)
    final=final_rl_light(cons_path)
    print(f"SPECIALISTS DONE {final}")
