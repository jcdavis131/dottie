import typer
from bigbang.core.output import emit
app = typer.Typer(name="family", help="Family Brain + Life Admin — generic tools", no_args_is_help=True)

@app.command("brain")
def brain():
    emit({"message": "Family Brain", "url": "https://agent.meta.ai/s/davis-family-brain-shareable-xri5axxxjxzxatzxj"})

@app.command("bills")
def bills(due: str = typer.Option(None, help="filter")):
    emit({"message": "Life Admin generic tracker", "filter": due or "all", "tables": ["admin_tasks","documents"]})

@app.command("list")
def list_items():
    emit({"brains": ["davis-family-brain", "life-admin-brain"]})

def register(root):
    root.add_typer(app, name="family")
