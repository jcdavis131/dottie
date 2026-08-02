import os as _os
import platform
import re
import shutil
from pathlib import Path

# Module level, not nested inside doctor(). It was a closure, which meant the vault
# permission rule — the one security-shaped check in this plugin — could not be called or
# monkeypatched by a test at all. A rule nothing can exercise is a rule that rots.

def _file_check(name: str, path: Path, require_mode_0600: bool = False):
    """Real check: ok only when the file exists, is readable, and (for the vault) is 0600."""
    if not path.exists():
        return {
            "check": name,
            "status": f"{path} missing (not created yet)",
            "ok": False,
        }
    if not _os.access(path, _os.R_OK):
        return {
            "check": name,
            "status": f"{path} exists but not readable",
            "ok": False,
        }
    if require_mode_0600:
        mode = path.stat().st_mode & 0o777
        # POSIX mode bits are not the access control mechanism on Windows, so this
        # check could never pass there and doctor was permanently red for a
        # NON-exposure. Measured on this box 2026-08-02:
        #
        #     mode                        0o666
        #     os.chmod(p, 0o600)          before 0o666 -> after 0o666   (no effect)
        #     icacls secrets.json         SYSTEM:(I)(F) Administrators:(I)(F)
        #                                 NUGATRON\jcdav:(I)(F)   <- no Users/Everyone
        #
        # The file IS private, via NTFS ACLs inherited from the user profile. What is
        # not true is that chmod delivered it — security.py writes 0600 and Windows
        # silently ignores everything but the read-only bit.
        #
        # A check that cannot pass on the platform it runs on trains people to skim a
        # red doctor, which is the same failure this repo already names for CI and for
        # tracebacks printed after a green result.
        if _os.name == "nt":
            return {
                "check": name,
                "status": (
                    f"{path} exists; POSIX mode {oct(mode)} not enforced on Windows "
                    "(access is governed by NTFS ACLs inherited from the user profile "
                    "— verify with `icacls`)"
                ),
                "ok": True,
                "caveat": "posix-mode-not-applicable",
            }
        if mode != 0o600:
            return {
                "check": name,
                "status": f"{path} exists but mode is {oct(mode)} (want 0600)",
                "ok": False,
            }
        return {"check": name, "status": f"{path} exists, mode 0600", "ok": True}
    return {"check": name, "status": f"{path} exists, readable", "ok": True}


import typer

from bigbang.core.audit import tail_events
from bigbang.core.output import emit
from bigbang.core.plugin_loader import get_all_manifests

app = typer.Typer(
    name="system",
    help="🖥️ System — doctor, audit, policy, scaffold",
    no_args_is_help=True,
)


def run_doctor():
    from pathlib import Path

    import httpx

    checks = []
    checks.append({"check": "python", "status": platform.python_version(), "ok": True})
    checks.append(
        {
            "check": "git",
            "status": shutil.which("git") or "missing",
            "ok": bool(shutil.which("git")),
        }
    )
    checks.append(
        {
            "check": "docker",
            "status": shutil.which("docker") or "missing",
            "ok": bool(shutil.which("docker")),
        }
    )
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        checks.append({"check": "ollama", "status": f"up {r.status_code}", "ok": True})
    except Exception:
        checks.append(
            {"check": "ollama", "status": "down (expected local)", "ok": False}
        )
    # INFORMATIONAL, not a failure. ~/MEMORY.md is a personal convention, not something the
    # CLI requires or creates — this operator's memory lives under
    # .claude/projects/<slug>/memory/ instead, so doctor reported ok:False forever on a
    # correctly-configured machine. A permanently-red line is how people learn to skim the
    # whole report.
    mem = Path.home() / "MEMORY.md"
    checks.append(
        {
            "check": "MEMORY.md",
            "status": (
                f"{mem} exists"
                if mem.exists()
                else f"{mem} not present (optional convention, not required)"
            ),
            "ok": True,
            "informational": True,
        }
    )

    share = Path.home() / ".local" / "share" / "bigbang"
    checks.append(_file_check("vault", share / "secrets.json", require_mode_0600=True))
    checks.append(_file_check("audit_log", share / "audit.jsonl"))
    checks.append(_file_check("tool_registry", share / "registry.json"))
    emit(
        {
            "message": "doctor complete",
            "checks": checks,
            # 70bfa38 corrected the per-check vault STATUS and left this summary line
            # asserting "vault 0600" unconditionally — on the same platform where that
            # commit had just documented the chmod is a no-op. A summary that contradicts
            # the check below it is worse than either being wrong alone, and it was mine.
            "security": (
                "vault: POSIX 0600 requested; on Windows access is governed by NTFS ACLs "
                "(see the vault check above). policy caps, audit jsonl"
                if _os.name == "nt"
                else "vault 0600, policy caps, audit jsonl"
            ),
        },
        command="system doctor",
    )


@app.command("doctor")
def doctor():
    run_doctor()


@app.command("audit")
def audit_cmd(n: int = typer.Option(20, help="last n events")):
    events = tail_events(n)
    emit(
        {
            "audit_tail": events,
            "count": len(events),
            "file": "~/.local/share/bigbang/audit.jsonl",
        },
        command="system audit",
    )


@app.command("policy")
def policy_cmd():
    manifests = get_all_manifests()
    emit(
        {
            "policies": manifests,
            "note": "each plugin/tool declares capabilities.network, filesystem, secrets — default deny",
        },
        command="system policy",
    )


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
