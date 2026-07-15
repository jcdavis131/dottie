import typer
from bigbang.core.output import emit
app = typer.Typer(name="agent", help="Agent runner — natural language -> bb tools", no_args_is_help=True)

@app.command("run")
def run(task: str = typer.Argument(..., help="natural language task")):
    emit({
        "message": f"Agent task: {task}",
        "plan": ["Parse intent", "Select bb commands", "Run --json", "Emit"],
        "how": "bb --json finance snapshot, bb vector list, etc."
    })

@app.command("bus")
def bus():
    emit({"message": "Event bus watcher for skills/ + crons -> propose new plugins"})

def register(root):
    root.add_typer(app, name="agent")
