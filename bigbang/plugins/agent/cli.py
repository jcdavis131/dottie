import typer
from bigbang.core.output import emit
app = typer.Typer(name="agent", help="Agent runner — NL -> tools", no_args_is_help=True)

@app.command("run")
def run(task: str = typer.Argument(..., help="natural language task")):
    emit({"task": task, "plan": ["Parse intent", "Select bb commands", "Run --json"]})

@app.command("bus")
def bus():
    emit({"message": "Event bus watcher for skills/crons -> propose new tool plugins"})

def register(root):
    root.add_typer(app, name="agent")
