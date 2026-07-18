import typer
from bigbang.core.output import emit

app = typer.Typer(name="family", help="Family Brain + Life Admin — bookmarks to external brains", no_args_is_help=True)


@app.command("brain")
def brain():
    emit({
        "status": "bookmark — external service, not managed by this CLI",
        "name": "Family Brain",
        "url": "https://agent.meta.ai/s/davis-family-brain-shareable-xri5axxxjxzxatzxj",
    }, command="family brain")


@app.command("bills")
def bills(due: str = typer.Option(None, help="filter")):
    emit({
        "status": "bookmark — no local data store yet",
        "name": "Life Admin tracker",
        "filter": due or "all",
        "planned_tables": ["admin_tasks", "documents"],
    }, command="family bills")


@app.command("list")
def list_items():
    emit({
        "status": "bookmark — external brains, listed for reference only",
        "brains": ["davis-family-brain", "life-admin-brain"],
    }, command="family list")


def register(root):
    root.add_typer(app, name="family")
