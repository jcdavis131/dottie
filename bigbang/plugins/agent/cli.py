import typer, json, time
from bigbang.core.output import emit
from bigbang.core.registry import list_tools, search_tools
from bigbang.core.audit import log_event
from pathlib import Path

app = typer.Typer(name="agent", help="🤖 Agent — Ava-native planner that routes to any tool", no_args_is_help=True)

@app.command("run")
def run(task: str = typer.Argument(..., help="natural language e.g. 'summarize my GitHub PRs and post to family brain'")):
    tools = list_tools()
    # Naive intent -> tool matching (Ava would be smarter with local model)
    q = task.lower()
    candidates = []
    for name, m in tools.items():
        if any(word in name or word in m.get("description","").lower() for word in q.split()[:5]):
            candidates.append(name)
    # also check builtins
    builtin_hints = {
        "github": "use bb tools search github + bb auth login github",
        "vector": "bb vector list, bb vector hoops --daily",
        "family": "bb family brain, bb family list",
        "ava": "bb ava status, bb ava train"
    }
    plan = []
    for k,v in builtin_hints.items():
        if k in q:
            plan.append(v)
    if not plan:
        plan = ["bb system doctor", "bb tools list", "bb mcp manifest"]

    # Simulate Ava routing
    emit({
        "task": task,
        "planner": "Ava v6.4 local (stub) — future: Ollama qwen3:32b + Frontier rubric + real router",
        "available_tools": list(tools.keys())[:20],
        "candidate_tools": candidates,
        "plan": plan,
        "execution": "Would run plan step-by-step with policy checks, audit log, --json between steps, and human confirmation for writes",
        "security": "Every step checked against manifest.yaml capabilities, secrets vaulted, audit.jsonl appended"
    }, command="agent run")

@app.command("bus")
def bus():
    emit({
        "message": "Event bus watcher — proposes new tool plugins from recurring patterns",
        "watching": ["~/workspace/*/ (new projects)", "~/.local/share/bigbang/audit.jsonl (recurring commands)", "MCP servers"],
        "proposes": "bb system scaffold <name> when pattern detected 3x, then PR to registry",
        "ava_role": "Ava judges if automation is safe + useful via Frontier rubric"
    }, command="agent bus")

@app.command("teach")
def teach(example: str = typer.Argument(..., help="show agent how to do something once, it learns")):
    emit({"teaching": example, "learned": "Would store as skill in bigbang/skills/<name>.md + as vector for Ava retrieval"}, command="agent teach")

def register(root): root.add_typer(app, name="agent")
