import typer
from bigbang.core.output import emit
app = typer.Typer(name="vector", help="Vector Hoops/Pitch/Gridiron MTNN", no_args_is_help=True)
@app.command("list")
def list_sites():
    emit({"sites": [
        {"name": "hoops", "rows": 12966, "domain": "hoops.dumbmodel.com", "mode": "Guess The Player"},
        {"name": "pitch", "rows": 633, "domain": "pitch.dumbmodel.com"},
        {"name": "gridiron", "MAE": 4.268, "domain": "gridiron.dumbmodel.com"},
    ]})
@app.command("hoops")
def hoops(daily: bool = typer.Option(False), mode: str = typer.Option("guess")):
    emit({"message": f"Vector Hoops rebuild --{'quick' if daily else 'full'} --leakfree mode={mode}"})
def register(root):
    root.add_typer(app, name="vector")
