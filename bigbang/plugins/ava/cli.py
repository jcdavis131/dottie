import typer
from bigbang.core.output import emit
from pathlib import Path
import json

app = typer.Typer(name="ava", help="🧠 Ava AGI Factory — brain of BigBang, local CUDA + Frontier eval", no_args_is_help=True)

FACTORY = Path.home() / "workspace" / "ava-agi-factory-v6-4"

@app.command("status")
def status():
    compose = FACTORY / "docker-compose.yml"
    emit({
        "factory": str(FACTORY),
        "exists": FACTORY.exists(),
        "compose": str(compose),
        "model": "1.17B d2048 48L YaRN 10k->1M, 4 workspaces, Frontier 11 cats",
        "judges": ["qwen3:32b via Ollama", "LocalHFJudge", "CriteriaJudge"],
        "role_in_bigbang": "Router + planner for bb agent run, evaluates if new tool automation is safe/useful",
        "next": "bb ava train --smoke, bb ava eval --frontier"
    }, command="ava status")

@app.command("train")
def train(smoke: bool = typer.Option(False), offline: bool = typer.Option(True), steps: int = typer.Option(1000)):
    emit({
        "action": "ava train",
        "smoke": smoke,
        "offline": offline,
        "steps": steps,
        "cmd": f"docker compose --profile cuda up -d && python train_1b_deepspeed.py --smoke={smoke}",
        "audit": "Training logs -> ~/workspace/ava-agi-factory-v6-4/logs/, eval via Frontier rubric"
    }, command="ava train")

@app.command("eval")
def eval_cmd(frontier: bool = typer.Option(False, help="run Frontier 11-cat rubric")):
    emit({
        "eval": "frontier" if frontier else "branch-harness",
        "harness": "eval_branch_harness.py + eval_frontier_rubric.py",
        "judge": "Ollama qwen3:32b",
        "bigbang_use": "Ava scores if a new tool/skill is worth promoting to core"
    }, command="ava eval")

@app.command("route")
def route(task: str = typer.Argument(..., help="task to route via Ava")):
    # Future: actual Ollama call to qwen3:32b
    emit({
        "task": task,
        "ava_router_stub": "Would call Ollama http://host.docker.internal:11434/api/chat with router prompt",
        "returns": {"tool": "vector", "confidence": 0.87, "reason": "task mentions hoops"}
    }, command="ava route")

def register(root): root.add_typer(app, name="ava")
