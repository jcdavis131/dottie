# Solo personal project, no connection to employer, built with public/free-tier only
"""brain — goals, memory and daily notes, read from the operator's own files.

Replaces opening ~/MEMORY.md, ~/memory/<date>.md and ~/workspace/projects/*/PROJECT.md by
hand when briefing an assistant. Read-mostly: only `daily` and `sync` write, and both say
where.

PATHS ARE OVERRIDABLE. Every location derives from `_brain_root()`, which honours
SCOUT_BRAIN_ROOT and falls back to the home layout this was written against. Before
2026-08-02 the layout was hardcoded in five places, so on any other machine `brain goals`
returned `count: 0` without saying where it had looked — indistinguishable from having no
goals.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import typer

from bigbang.core.output import emit

app = typer.Typer(
    name="brain",
    help="🧠 Hatch brain — goals, memory, daily notes for Ava co-dev",
    no_args_is_help=True,
)

READ_LIMIT = 8000


def _brain_root() -> Path:
    """Base for every path here. SCOUT_BRAIN_ROOT, else the home layout.

    Resolved per CALL, never at import. A module-level default is bound before a test
    harness can redirect HOME, which is the exact failure this repo hit in
    apps/ava-factory/dottie/telemetry.py (fixed 53c5c60) — and `sync --out` had the same
    shape here, a typer.Option default containing Path.home() evaluated at import time.
    """
    override = os.environ.get("SCOUT_BRAIN_ROOT")
    return Path(override).expanduser() if override else Path.home()


def _projects_root() -> Path:
    return _brain_root() / "workspace" / "projects"


def _memory_file() -> Path:
    return _brain_root() / "MEMORY.md"


def _daily_file() -> Path:
    return _brain_root() / "memory" / f"{datetime.now().strftime('%Y-%m-%d')}.md"


def _read_if_exists(p: Path, limit: int = READ_LIMIT, tail: bool = False) -> str | None:
    """Read a capped slice. `tail=True` takes it from the END, which is not the same thing.

    It used to always return `text[:8000]`, and `memory_cmd` then did `.splitlines()[-n:]`
    on that — so "the last n lines of MEMORY.md" was the last n lines of the FIRST 8000
    characters. Measured on a 400-line, 11,199-char file:

        true last line     : line 0399
        what brain showed  : line 0285      (and cut mid-word)

    Silently wrong rather than truncated-and-obvious: the output looks like a tail, is
    labelled a tail, and is 114 lines short of one. MEMORY.md is a file designed to grow,
    so this gets worse with use.

    A tail can start mid-line, so the first partial line is dropped rather than reported as
    a whole one.
    """
    try:
        if not p.exists():
            return None
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    if len(text) <= limit:
        return text
    if not tail:
        return text[:limit]
    clipped = text[-limit:]
    return clipped.split("\n", 1)[1] if "\n" in clipped else clipped


@app.command("memory")
def memory_cmd(
    query: str = typer.Option("", "--query", help="filter lines containing"),
    n: int = typer.Option(30, "--n", help="last n lines from MEMORY.md + today daily"),
):
    mem_path = _memory_file()
    today = _daily_file()
    # tail=True: this field is called a tail, so it has to be one.
    mem = _read_if_exists(mem_path, tail=True) or ""
    lines = mem.splitlines()[-n:]
    if query:
        lines = [l for l in lines if query.lower() in l.lower()]
    daily = _read_if_exists(today)
    emit(
        {
            "MEMORY.md_tail": lines,
            "memory_path": str(mem_path),
            "memory_exists": mem_path.exists(),
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
    proj_root = _projects_root()
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
            # A bare count: 0 cannot be told apart from "the layout is different and I
            # found nothing". Both facts are reported so the caller can tell.
            "projects_root": str(proj_root),
            "projects_root_exists": proj_root.exists(),
            "hint": "bb brain goal <slug> for detail, bb brain sync to export for Ava"
            if proj_root.exists()
            else f"no projects root at {proj_root} — set SCOUT_BRAIN_ROOT to your layout",
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        },
        command="brain goals",
    )


@app.command("goal")
def goal_detail(
    slug: str = typer.Argument(..., help="project slug e.g. first-1k-mo-passive"),
):
    p = _projects_root() / slug
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
    out: Path | None = typer.Option(
        # None, not a Path.home() expression: a typer.Option default is evaluated at
        # IMPORT time, so the old default froze the operator's home before any test
        # harness or SCOUT_BRAIN_ROOT could redirect it.
        None,
        "--out",
        help="Output file (default: <brain root>/workspace/your_files/brain-sync.json)",
    ),
):
    """Export token-efficient brain snapshot for Ava / LLM-wiki ingestion"""
    out = out or (_brain_root() / "workspace" / "your_files" / "brain-sync.json")
    mem_path = _memory_file()
    mem = _read_if_exists(mem_path, tail=True) or ""
    goals_root = _projects_root()
    goals = []
    if goals_root.exists():
        for g in goals_root.iterdir():
            if g.is_dir() and (g / "PROJECT.md").exists():
                goals.append(g.name)
    data = {
        # utcnow() is deprecated in 3.12 and returns a NAIVE datetime, so the "Z" was a
        # claim rather than a fact. now(UTC) is aware and the rest of this repo uses it.
        "ts": datetime.now(UTC).isoformat(),
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
    today_path = _daily_file()
    today_path.parent.mkdir(parents=True, exist_ok=True)
    with today_path.open("a", encoding="utf-8") as f:
        f.write(f"\n- {datetime.now().strftime('%H:%M')} bb brain: {note}\n")
    emit({"appended": str(today_path), "note": note}, command="brain daily")


def register(root):
    root.add_typer(app, name="brain")


# Solo personal project, no connection to employer, built with public/free-tier only
