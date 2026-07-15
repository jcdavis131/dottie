import typer
from bigbang.core.output import emit
app = typer.Typer(name="vector", help="Vector Hoops/Pitch/Gridiron MTNN control", no_args_is_help=True)

@app.command("list")
def list_sites():
    emit({"sites": [
        {"name": "hoops", "rows": 12966, "domain": "hoops.dumbmodel.com", "mode": "Guess The Player"},
        {"name": "pitch", "rows": 633, "domain": "pitch.dumbmodel.com"},
        {"name": "gridiron", "MAE": 4.268, "domain": "gridiron.dumbmodel.com"},
    ]})

@app.command("hoops")
def hoops(daily: bool = typer.Option(False), mode: str = typer.Option("guess"), leakfree: bool = typer.Option(True)):
    emit({"action": "rebuild hoops", "daily": daily, "mode": mode, "leakfree": leakfree, "cmd": "pipeline/rebuild_all.py --quick --leakfree" if daily else "pipeline/rebuild_all.py --full"})

@app.command("verify")
def verify():
    emit({"action": "verify_accuracy.py", "datasets": ["hoops","pitch","gridiron"]})

def register(root):
    root.add_typer(app, name="vector")
