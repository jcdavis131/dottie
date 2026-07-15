import typer
from bigbang.core.output import emit
app = typer.Typer(name="ava", help="Ava AGI Factory v6.4 local CUDA", no_args_is_help=True)

@app.command("status")
def status():
    emit({"message": "Ava v6.4: 1.17B d2048 48L, YaRN 10k->1M, 4 workspaces, Frontier 11 cats, Docker CUDA, Ollama qwen3:32b judge"})

@app.command("train")
def train(smoke: bool = typer.Option(False), offline: bool = typer.Option(True)):
    emit({"action": "ava train", "smoke": smoke, "offline": offline, "compose": "docker compose --profile cuda up"})

def register(root):
    root.add_typer(app, name="ava")
