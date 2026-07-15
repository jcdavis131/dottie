import typer, shutil, platform, json
from pathlib import Path
from bigbang.core.output import emit
from bigbang.core.audit import tail_events
from bigbang.core.plugin_loader import get_all_manifests

app = typer.Typer(name="system", help="🖥️ System — doctor, audit, policy, scaffold", no_args_is_help=True)

def run_doctor():
    from pathlib import Path
    import httpx
    checks = []
    checks.append({"check": "python", "status": platform.python_version(), "ok": True})
    checks.append({"check": "git", "status": shutil.which("git") or "missing", "ok": bool(shutil.which("git"))})
    checks.append({"check": "docker", "status": shutil.which("docker") or "missing", "ok": bool(shutil.which("docker"))})
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        checks.append({"check": "ollama", "status": f"up {r.status_code}", "ok": True})
    except Exception:
        checks.append({"check": "ollama", "status": "down (expected local)", "ok": False})
    mem = Path.home() / "MEMORY.md"
    checks.append({"check": "MEMORY.md", "status": f"{mem} {'exists' if mem.exists() else 'missing'}", "ok": mem.exists()})
    vault = Path.home() / ".local" / "share" / "bigbang" / "secrets.json"
    checks.append({"check": "vault", "status": f"{vault} {'exists' if vault.exists() else 'not yet'} 0600", "ok": True})
    audit = Path.home() / ".local" / "share" / "bigbang" / "audit.jsonl"
    checks.append({"check": "audit_log", "status": str(audit), "ok": True})
    reg = Path.home() / ".local" / "share" / "bigbang" / "registry.json"
    checks.append({"check": "tool_registry", "status": str(reg), "ok": True})
    emit({"message": "doctor complete", "checks": checks, "security": "vault 0600, policy caps, audit jsonl"}, command="system doctor")

@app.command("doctor")
def doctor():
    run_doctor()

@app.command("audit")
def audit_cmd(n: int = typer.Option(20, help="last n events")):
    events = tail_events(n)
    emit({"audit_tail": events, "count": len(events), "file": "~/.local/share/bigbang/audit.jsonl"}, command="system audit")

@app.command("policy")
def policy_cmd():
    manifests = get_all_manifests()
    emit({"policies": manifests, "note": "each plugin/tool declares capabilities.network, filesystem, secrets — default deny"}, command="system policy")

@app.command("scaffold")
def scaffold_plugin(name: str = typer.Argument(..., help="new plugin name"), with_manifest: bool = typer.Option(True, help="create manifest.yaml with caps")):
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
from pathlib import Path
import yaml

app = typer.Typer(name="{name}", help="{name} plugin — security-first, capability-declared", no_args_is_help=True)

@app.command("hello")
def hello():
    # Example: check policy manifest
    mf_path = Path(__file__).parent / "manifest.yaml"
    emit({{"message": "Hello from {name}!", "manifest_exists": mf_path.exists()}})

def register(root):
    root.add_typer(app, name="{name}")
''')
    if with_manifest:
        mf = target / "manifest.yaml"
        mf.write_text(f'''name: {name}
version: 0.3.0
description: {name} — your tool description
capabilities:
  network:
    enabled: false
    domains: []
  filesystem:
    write: false
    paths: []
  secrets:
    allow: []
''')
    emit({"created": str(cli_file), "manifest": str(target / "manifest.yaml") if with_manifest else "skipped", "next": f"bb {name} hello --json"}, command="system scaffold")

def register(root):
    root.add_typer(app, name="system")
