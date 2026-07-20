"""Skill plugin — teach agents (Dottie-claw first) how to drive Scout."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
import yaml

from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import ok
from bigbang.core.output import emit

app = typer.Typer(
    name="skill",
    help="📚 Skill — teach Dottie-claw / Claude / Cursor / OpenClaw to drive Scout",
    no_args_is_help=True,
    epilog=examples_epilog(
        [
            "scout skill list",
            "scout skill show scout",
            "scout skill install scout --target dottie",
            "scout skill install --all --target dottie",
            "scout skill teach --target dottie   # alias: install --all",
        ]
    ),
)

# Packaged skills live next to plugins: bigbang/skills/
SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"

TARGETS: dict[str, Path] = {
    "dottie": Path.home() / ".dottie-claw" / "skills",
    "openclaw": Path.home() / ".openclaw" / "skills",
    "claude": Path.home() / ".claude" / "skills",
    "cursor": Path.home() / ".cursor" / "skills",
}


def _iter_skills() -> list[dict[str, str]]:
    """Discover packaged skills (dir/SKILL.md or flat name.md)."""
    found: list[dict[str, str]] = []
    if not SKILLS_ROOT.exists():
        return found
    for path in sorted(SKILLS_ROOT.iterdir()):
        if path.name.startswith(".") or path.name == "__init__.py":
            continue
        if path.is_dir():
            skill_md = path / "SKILL.md"
            if skill_md.exists():
                meta = _frontmatter(skill_md)
                found.append(
                    {
                        "name": meta.get("name") or path.name,
                        "path": str(skill_md),
                        "description": meta.get("description", ""),
                        "layout": "dir",
                    }
                )
        elif path.suffix == ".md":
            meta = _frontmatter(path)
            found.append(
                {
                    "name": meta.get("name") or path.stem,
                    "path": str(path),
                    "description": meta.get("description", ""),
                    "layout": "file",
                }
            )
    return found


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    # normalize description to single line for list view
    out: dict[str, str] = {}
    for k, v in data.items():
        if v is None:
            continue
        out[str(k)] = " ".join(str(v).split())
    return out


def _resolve_skill(name: str) -> dict[str, str] | None:
    key = name.strip().lower().removesuffix(".md")
    for s in _iter_skills():
        if s["name"].lower() == key or Path(s["path"]).stem.lower() == key:
            return s
        if Path(s["path"]).parent.name.lower() == key and s["layout"] == "dir":
            return s
    return None


def _target_dirs(target: str) -> list[Path]:
    t = target.lower().strip()
    if t == "all":
        return list(TARGETS.values())
    if t not in TARGETS:
        fail_agent(
            f"unknown target {target}",
            command="skill install",
            example="scout skill install scout --target dottie",
            discover="scout skill list",
        )
    return [TARGETS[t]]


def _install_one(
    skill: dict[str, str], dest_root: Path, *, force: bool
) -> dict[str, str]:
    name = skill["name"]
    src = Path(skill["path"])
    dest_dir = dest_root / name
    dest_file = dest_dir / "SKILL.md"
    if dest_file.exists() and not force:
        return {
            "name": name,
            "dest": str(dest_file),
            "status": "exists",
            "ok": True,
            "skipped": True,
        }
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_file)
    return {
        "name": name,
        "dest": str(dest_file),
        "status": "installed",
        "ok": True,
        "skipped": False,
    }


@app.command(
    "list",
    epilog=examples_epilog(["scout --json skill list", "scout skill show scout"]),
)
def list_cmd():
    """List packaged Scout skills available to install for agents."""
    skills = _iter_skills()
    emit(
        ok(
            {"skills": skills, "count": len(skills), "root": str(SKILLS_ROOT)},
            command="skill list",
            example="scout skill install scout --target dottie",
            discover="scout skill show scout",
            targets=sorted(TARGETS.keys()),
        ),
        command="skill list",
    )


@app.command(
    "show",
    epilog=examples_epilog(
        ["scout skill show scout", "scout --json skill show scout-herd"]
    ),
)
def show_cmd(
    name: str = typer.Argument("scout", help="skill name e.g. scout, scout-herd"),
    path_only: bool = typer.Option(False, "--path", help="print path only in data"),
):
    """Show a packaged skill (path + preview). Default: scout (Dottie curriculum)."""
    skill = _resolve_skill(name)
    if not skill:
        fail_agent(
            f"skill not found: {name}",
            command="skill show",
            example="scout skill list",
            discover="scout skill list",
        )
    text = Path(skill["path"]).read_text(encoding="utf-8", errors="replace")
    preview = text if len(text) <= 4000 else text[:4000] + "\n… [truncated]"
    emit(
        ok(
            {
                "skill": skill
                if path_only
                else {**skill, "preview": preview, "chars": len(text)},
            },
            command="skill show",
            example=f"scout skill install {skill['name']} --target dottie",
        ),
        command="skill show",
    )


@app.command(
    "install",
    epilog=examples_epilog(
        [
            "scout skill install scout --target dottie",
            "scout skill install scout-herd --target dottie",
            "scout skill install --all --target dottie",
            "scout skill install scout --target claude --force",
        ]
    ),
)
def install_cmd(
    name: str | None = typer.Argument(None, help="skill name (omit with --all)"),
    target: str = typer.Option(
        "dottie",
        "--target",
        "-t",
        help="dottie|openclaw|claude|cursor|all",
    ),
    all_skills: bool = typer.Option(
        False, "--all", help="install every packaged skill"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="overwrite existing SKILL.md"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="show destinations only"),
):
    """Install skill(s) into an agent skill directory (Dottie-claw default)."""
    if not all_skills and not name:
        fail_agent(
            "Provide a skill name or --all",
            command="skill install",
            example="scout skill install scout --target dottie",
        )
    skills = _iter_skills() if all_skills else []
    if name:
        one = _resolve_skill(name)
        if not one:
            fail_agent(
                f"skill not found: {name}",
                command="skill install",
                example="scout skill list",
            )
        skills = [one]
    dests = _target_dirs(target)
    results = []
    for dest_root in dests:
        for skill in skills:
            if dry_run:
                results.append(
                    {
                        "name": skill["name"],
                        "dest": str(dest_root / skill["name"] / "SKILL.md"),
                        "status": "would_install",
                        "dry_run": True,
                        "ok": True,
                    }
                )
            else:
                results.append(_install_one(skill, dest_root, force=force))
    emit(
        ok(
            {
                "installed": results,
                "count": len(results),
                "target": target,
                "note": "Dottie-claw / Claude / Cursor should pick up SKILL.md on next session",
            },
            command="skill install",
            example="scout skill show scout",
            discover="scout --json herd status",
        ),
        command="skill install",
    )


@app.command(
    "teach",
    epilog=examples_epilog(
        [
            "scout skill teach --target dottie",
            "scout skill teach --target claude --force",
        ]
    ),
)
def teach_cmd(
    target: str = typer.Option(
        "dottie",
        "--target",
        "-t",
        help="dottie|openclaw|claude|cursor|all",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="overwrite existing"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Teach an agent Scout — installs all packaged skills (Dottie-claw default)."""
    # Reuse install --all
    install_cmd(name=None, target=target, all_skills=True, force=force, dry_run=dry_run)


@app.command("targets")
def targets_cmd():
    """Show skill install target directories."""
    emit(
        ok(
            {
                "targets": {k: str(v) for k, v in TARGETS.items()},
                "example": "scout skill teach --target dottie",
            },
            command="skill targets",
        ),
        command="skill targets",
    )


def register(root):
    root.add_typer(app, name="skill")
