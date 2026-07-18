import platform
import re
import shutil
from pathlib import Path

import typer

from bigbang.core.audit import tail_events
from bigbang.core.output import emit
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
    import os as _os

    def _file_check(name: str, path: Path, require_mode_0600: bool = False):
        """Real check: ok only when the file exists, is readable, and (for the vault) is 0600."""
        if not path.exists():
            return {"check": name, "status": f"{path} missing (not created yet)", "ok": False}
        if not _os.access(path, _os.R_OK):
            return {"check": name, "status": f"{path} exists but not readable", "ok": False}
        if require_mode_0600:
            mode = path.stat().st_mode & 0o777
            if mode != 0o600:
                return {"check": name, "status": f"{path} exists but mode is {oct(mode)} (want 0600)", "ok": False}
            return {"check": name, "status": f"{path} exists, mode 0600", "ok": True}
        return {"check": name, "status": f"{path} exists, readable", "ok": True}

    share = Path.home() / ".local" / "share" / "bigbang"
    checks.append(_file_check("vault", share / "secrets.json", require_mode_0600=True))
    checks.append(_file_check("audit_log", share / "audit.jsonl"))
    checks.append(_file_check("tool_registry", share / "registry.json"))
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
def scaffold_plugin(
    name: str = typer.Argument(..., help="new plugin name"),
    with_manifest: bool = typer.Option(True, help="create manifest.yaml with caps"),
):
    """Scaffold a foundation-shaped plugin (Examples + contract emit + manifest)."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name):
        emit(
            {
                "ok": False,
                "error": "plugin name must be snake_case starting with a letter",
                "example": "scout system scaffold mytool",
            },
            command="system scaffold",
        )
        raise typer.Exit(1)
    base = Path(__file__).parent
    target = base.parent / name
    target.mkdir(parents=True, exist_ok=True)
    cli_file = target / "cli.py"
    (target / "__init__.py").touch(exist_ok=True)
    if cli_file.exists():
        emit(
            {
                "ok": False,
                "warning": f"exists: {cli_file}",
                "example": f"scout --json {name} hello",
            },
            command="system scaffold",
        )
        return
    cli_file.write_text(
        f'''"""{name} plugin — foundation-shaped, capability-declared."""
from pathlib import Path

from bigbang.core.cli_ux import examples_epilog
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit

app = make_plugin_app(
    "{name}",
    "{name} plugin — security-first, capability-declared",
    examples=[
        "scout --json {name} hello",
        "scout {name} --help",
    ],
)


@app.command(
    "hello",
    epilog=examples_epilog(["scout --json {name} hello"]),
)
def hello():
    """Smoke command — prove the plugin loads and respects the foundation contract."""
    mf_path = Path(__file__).parent / "manifest.yaml"
    emit(
        ok(
            {{"message": "Hello from {name}!", "manifest_exists": mf_path.exists()}},
            command="{name} hello",
            example="scout --json {name} hello",
            discover="scout skill show scout",
        ),
        command="{name} hello",
    )


def register(root):
    root.add_typer(app, name="{name}")
'''
    )
    if with_manifest:
        mf = target / "manifest.yaml"
        mf.write_text(
            f"""name: {name}
version: 0.7.0
description: {name} — foundation-shaped Scout plugin
capabilities:
  network:
    enabled: false
    domains: []
  filesystem:
    write: false
    paths: []
  secrets:
    allow: []
"""
        )
    emit(
        {
            "ok": True,
            "created": str(cli_file),
            "manifest": str(target / "manifest.yaml") if with_manifest else "skipped",
            "example": f"scout --json {name} hello",
            "next": f"scout --json {name} hello",
            "teach": "scout skill show scout",
        },
        command="system scaffold",
    )

def register(root):
    root.add_typer(app, name="system")
