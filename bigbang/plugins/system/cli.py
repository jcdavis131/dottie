import typer, shutil, platform
from pathlib import Path
from bigbang.core.output import emit

app = typer.Typer(name="system", help="System health, updates, scaffolding", no_args_is_help=True)

def run_doctor():
    from pathlib import Path
    checks = []
    checks.append({"check": "python", "status": platform.python_version(), "ok": True})
    checks.append({"check": "git", "status": shutil.which("git") or "missing", "ok": bool(shutil.which("git"))})
    checks.append({"check": "docker", "status": shutil.which("docker") or "missing", "ok": bool(shutil.which("docker"))})
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        checks.append({"check": "ollama", "status": f"up {r.status_code}", "ok": True})
    except Exception:
        checks.append({"check": "ollama", "status": "down (expected)", "ok": False})
    mem = Path.home() / "MEMORY.md"
    checks.append({"check": "MEMORY.md", "status": f"{mem} {'exists' if mem.exists() else 'missing'}", "ok": mem.exists()})
    ws = Path.home() / "workspace" / "bigbang-cli"
    checks.append({"check": "repo", "status": str(ws), "ok": ws.exists()})
    emit({"message": "doctor complete", "checks": checks})

@app.command("doctor")
def doctor():
    run_doctor()

@app.command("scaffold")
def scaffold_plugin(name: str = typer.Argument(..., help="new plugin name")):
    base = Path(__file__).parent
    target = base.parent / name
    target.mkdir(parents=True, exist_ok=True)
    cli_file = target / "cli.py"
    (target / "__init__.py").touch(exist_ok=True)
    if cli_file.exists():
        emit({"warning": f"exists: {cli_file}"})
        return
    cli_file.write_text(f'''import typer
from bigbang.core.output import emit
app = typer.Typer(name="{name}", help="{name} plugin", no_args_is_help=True)
@app.command("hello")
def hello():
    emit({{"message": "Hello from {name}!"}})
def register(root):
    root.add_typer(app, name="{name}")
''')
    emit({"created": str(cli_file)})

def register(root):
    root.add_typer(app, name="system")
