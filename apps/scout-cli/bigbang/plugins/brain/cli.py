# Solo personal project, no connection to employer, built with public/free-tier only
import json
from datetime import datetime
from pathlib import Path

import typer

from bigbang.core.output import emit

app = typer.Typer(
    name="brain",
    help="🧠 Hatch brain — goals, memory, daily notes for Ava co-dev",
    no_args_is_help=True,
)


def _read_if_exists(p: Path) -> str | None:
    try:
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")[:8000]
    except Exception:
        return None
    return None


@app.command("memory")
def memory_cmd(
    query: str = typer.Option("", "--query", help="filter lines containing"),
    n: int = typer.Option(30, "--n", help="last n lines from MEMORY.md + today daily"),
):
    mem_path = Path.home() / "MEMORY.md"
    today = Path.home() / f"memory/{datetime.now().strftime('%Y-%m-%d')}.md"
    mem = _read_if_exists(mem_path) or ""
    lines = mem.splitlines()[-n:]
    if query:
        lines = [l for l in lines if query.lower() in l.lower()]
    daily = _read_if_exists(today)
    emit(
        {
            "MEMORY.md_tail": lines,
            "today_note": daily[:2000] if daily else None,
            "today_path": str(today),
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        },
        command="brain memory",
    )


@app.command("goals")
def goals_cmd(
    active_only: bool = typer.Option(True, "--active/--all"),
    search: str = typer.Option("", "--search", help="filter goal titles"),
):
    proj_root = Path.home() / "workspace" / "projects"
    goals = []
    if proj_root.exists():
        for p in proj_root.iterdir():
            if not p.is_dir():
                continue
            proj_md = p / "PROJECT.md"
            if not proj_md.exists():
                continue
            content = _read_if_exists(proj_md) or ""
            # crude active filter: if mentions archived skip
            if active_only and "archived" in content.lower()[:500]:
                continue
            title = p.name
            # first line of PROJECT.md
            if content:
                first = content.splitlines()[0][:120]
                title = first.replace("#", "").strip()
            if (
                search
                and search.lower() not in title.lower()
                and search.lower() not in content.lower()
            ):
                continue
            # progress entries
            files_dir = p / "files"
            briefs_dir = p / "briefs"
            goals.append(
                {
                    "slug": p.name,
                    "title": title,
                    "has_PROJECT": True,
                    "files_count": len(list(files_dir.iterdir()))
                    if files_dir.exists()
                    else 0,
                    "briefs_count": len(list(briefs_dir.iterdir()))
                    if briefs_dir.exists()
                    else 0,
                    "path": str(p),
                }
            )
    emit(
        {
            "goals": goals,
            "count": len(goals),
            "hint": "bb brain goal <slug> for detail, bb brain sync to export for Ava",
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        },
        command="brain goals",
    )


@app.command("goal")
def goal_detail(
    slug: str = typer.Argument(..., help="project slug e.g. first-1k-mo-passive"),
):
    p = Path.home() / "workspace" / "projects" / slug
    if not p.exists():
        emit({"error": f"not found {slug}", "path": str(p)})
        return
    proj_md = _read_if_exists(p / "PROJECT.md")
    files = []
    if (p / "files").exists():
        files = [str(f.name) for f in (p / "files").iterdir()][:20]
    briefs = []
    if (p / "briefs").exists():
        briefs = [str(f.name) for f in (p / "briefs").iterdir()][:20]
    emit(
        {
            "slug": slug,
            "PROJECT.md": proj_md[:6000] if proj_md else None,
            "files": files,
            "briefs": briefs,
            "path": str(p),
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        },
        command="brain goal",
    )


@app.command("sync")
def sync_cmd(
    out: Path = typer.Option(
        Path.home() / "workspace" / "your_files" / "brain-sync.json", "--out"
    ),
):
    """Export token-efficient brain snapshot for Ava / LLM-wiki ingestion"""
    mem_path = Path.home() / "MEMORY.md"
    mem = _read_if_exists(mem_path) or ""
    goals_root = Path.home() / "workspace" / "projects"
    goals = []
    if goals_root.exists():
        for g in goals_root.iterdir():
            if g.is_dir() and (g / "PROJECT.md").exists():
                goals.append(g.name)
    data = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "memory_lines": len(mem.splitlines()),
        "memory_tail": mem.splitlines()[-20:],
        "goals": goals,
        "goals_count": len(goals),
        "source": "bb brain sync — local-first, no secrets",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    emit(
        {"synced": str(out), "goals": goals, "memory_tail": data["memory_tail"][:10]},
        command="brain sync",
    )


@app.command("daily")
def daily_cmd(
    note: str = typer.Argument(..., help="Append to today's daily memory note"),
):
    today_path = Path.home() / f"memory/{datetime.now().strftime('%Y-%m-%d')}.md"
    today_path.parent.mkdir(parents=True, exist_ok=True)
    with today_path.open("a", encoding="utf-8") as f:
        f.write(f"\n- {datetime.now().strftime('%H:%M')} bb brain: {note}\n")
    emit({"appended": str(today_path), "note": note}, command="brain daily")


def register(root):
    root.add_typer(app, name="brain")


# Solo personal project, no connection to employer, built with public/free-tier only
