import typer
from pathlib import Path
from bigbang.core.output import emit

app = typer.Typer(name="vector", help="Vector Hoops/Pitch/Gridiron MTNN control", no_args_is_help=True)

WORKSPACE = Path.home() / "workspace"
SITES = {
    "hoops": "hoops.dumbmodel.com",
    "pitch": "pitch.dumbmodel.com",
    "gridiron": "gridiron.dumbmodel.com",
}


def _count_csv_rows(repo: Path, max_files: int = 50) -> int:
    """Sum data rows (lines minus header) across CSVs in the repo. Real counts only."""
    total = 0
    for i, f in enumerate(sorted(repo.rglob("*.csv"))):
        if i >= max_files:
            break
        try:
            lines = sum(1 for _ in f.open("r", errors="ignore"))
            total += max(lines - 1, 0)
        except OSError:
            continue
    return total


def _site_status(name: str) -> dict:
    repo = WORKSPACE / f"vector-{name}"
    info = {"name": name, "domain": SITES[name], "repo": str(repo)}
    if not repo.exists():
        info["status"] = "bookmark — repo not present"
        return info
    info["status"] = "repo present"
    info["csv_rows"] = _count_csv_rows(repo)
    return info


@app.command("list")
def list_sites():
    emit({"sites": [_site_status(n) for n in SITES]}, command="vector list")


@app.command("hoops")
def hoops(daily: bool = typer.Option(False), mode: str = typer.Option("guess"), leakfree: bool = typer.Option(True)):
    repo = WORKSPACE / "vector-hoops"
    if not repo.exists():
        emit({"status": "bookmark — repo not present", "repo": str(repo),
              "would_run": "pipeline/rebuild_all.py --quick --leakfree" if daily else "pipeline/rebuild_all.py --full"},
             command="vector hoops")
        return
    emit({"action": "rebuild hoops", "repo": str(repo), "daily": daily, "mode": mode,
          "leakfree": leakfree,
          "cmd": "pipeline/rebuild_all.py --quick --leakfree" if daily else "pipeline/rebuild_all.py --full"},
         command="vector hoops")


@app.command("verify")
def verify():
    present = [n for n in SITES if (WORKSPACE / f"vector-{n}").exists()]
    missing = [n for n in SITES if n not in present]
    emit({"action": "verify_accuracy.py", "repos_present": present,
          "repos_missing": missing,
          "note": "runs only against locally cloned vector-* repos — no invented metrics"},
         command="vector verify")


def register(root):
    root.add_typer(app, name="vector")
