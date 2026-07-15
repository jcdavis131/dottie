import typer
from bigbang.core.output import emit
app = typer.Typer(name="family", help="Davis Family Brain + Life Admin Brain", no_args_is_help=True)
@app.command("brain")
def brain():
    emit({"message": "Davis Family Brain: https://agent.meta.ai/s/davis-family-brain-shareable-xri5axxxjxzxatzxj"})
@app.command("bills")
def bills():
    emit({"message": "Life Admin Brain: 10 tables, bills dup detection, Roth tracker, RSU 444 @ $615.58"})
def register(root):
    root.add_typer(app, name="family")
