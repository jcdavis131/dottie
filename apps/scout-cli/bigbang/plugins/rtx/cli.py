"""
scout rtx — Alienware RTX 4080/4090 offload bridge for autoresearch-rtx custom
Now wired to GitHub releases for dashboard auto-read
Solo personal project, no connection to employer, built with public/free-tier only
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer

from bigbang.core.output import emit

app = typer.Typer(
    name="rtx",
    help="🚀 RTX — offload to Alienware RTX 4080/4090 + scout-rtx releases",
    no_args_is_help=True,
)


def _resolve_custom_root() -> Path:
    """Resolve the scout-rtx working copy.

    Precedence: SCOUT_RTX_ROOT env override, then the dottie monorepo layout
    (DOTTIE_ROOT/apps/scout-rtx, ~/workspace/dottie/apps/scout-rtx), then the
    standalone checkouts (~/workspace/autoresearch-rtx-custom, ~/workspace/scout-rtx).
    Falls back to the legacy default path when nothing exists yet.
    """
    env = os.environ.get("SCOUT_RTX_ROOT")
    if env:
        return Path(env).expanduser()
    candidates = []
    dottie = os.environ.get("DOTTIE_ROOT")
    if dottie:
        candidates.append(Path(dottie).expanduser() / "apps" / "scout-rtx")
    candidates.append(Path.home() / "workspace" / "dottie" / "apps" / "scout-rtx")
    candidates.append(Path.home() / "workspace" / "autoresearch-rtx-custom")
    candidates.append(Path.home() / "workspace" / "scout-rtx")
    for cand in candidates:
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return Path.home() / "workspace" / "autoresearch-rtx-custom"


CUSTOM_ROOT = _resolve_custom_root()
BB_OFFLOAD = CUSTOM_ROOT / "bb-offload"
QUEUE_FILE = BB_OFFLOAD / "queue.json"
RESULTS_FILE = BB_OFFLOAD / "results" / "results.jsonl"
RESULTS_TSV = CUSTOM_ROOT / "results.tsv"

GITHUB_REPO = "jcdavis131/scout-rtx"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"


def _ensure_dirs():
    (BB_OFFLOAD / "results").mkdir(parents=True, exist_ok=True)


def _load_queue():
    if not QUEUE_FILE.exists():
        return {"tasks": []}
    try:
        return json.loads(QUEUE_FILE.read_text())
    except Exception:
        return {"tasks": []}


def _save_queue(q):
    _ensure_dirs()
    QUEUE_FILE.write_text(json.dumps(q, indent=2))


def _load_results_jsonl(n=50):
    if not RESULTS_FILE.exists():
        return []
    lines = RESULTS_FILE.read_text().strip().splitlines()
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


@app.command("status")
def status():
    _ensure_dirs()
    queue = _load_queue()
    results = _load_results_jsonl(10)
    hw_profile = {}
    try:
        if RESULTS_TSV.exists():
            lines = RESULTS_TSV.read_text().strip().splitlines()
            if len(lines) > 1:
                best = None
                for line in lines[1:]:
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        try:
                            bpb = float(parts[1])
                            if best is None or bpb < best[1]:
                                best = (parts[0], bpb, line)
                        except Exception:
                            continue
                if best:
                    hw_profile["best_val_bpb"] = best[1]
                    hw_profile["best_commit"] = best[0]
    except Exception:
        pass

    payload = {
        "custom_root": str(CUSTOM_ROOT),
        "exists": CUSTOM_ROOT.exists(),
        "queue_file": str(QUEUE_FILE),
        "results_file": str(RESULTS_FILE),
        "results_tsv": str(RESULTS_TSV),
        "queue_pending": len(
            [t for t in queue.get("tasks", []) if t.get("status") == "pending"]
        ),
        "queue_total": len(queue.get("tasks", [])),
        "results_count": len(results),
        "best": hw_profile,
        "gpu_hint": "RTX 4080 ada-16gb batch32 / RTX 4090 ada-24gb-plus batch64 BF16 TF32 SDPA torch 2.9.1 cu128 5-min budget",
        "offload_guide": str(CUSTOM_ROOT / "docs" / "OFFLOAD_GUIDE.md"),
        "programs": [str(p) for p in (CUSTOM_ROOT / "programs").glob("*.md")]
        if (CUSTOM_ROOT / "programs").exists()
        else [],
        "github_releases": f"https://api.github.com/repos/{GITHUB_REPO}/releases",
        "github_repo": f"https://github.com/{GITHUB_REPO}",
        "dashboard": "scout rtx dashboard (auto-reads releases every 60s)",
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }
    emit(payload)


@app.command("queue")
def queue_cmd(
    action: str = typer.Argument("list", help="add|list|clear"),
    task: str = typer.Option("", "--task", "-t", help="task description for add"),
    program: str = typer.Option(
        "program-base.md",
        "--program",
        "-p",
        help="program file e.g. programs/program-ava.md",
    ),
):
    _ensure_dirs()
    q = _load_queue()
    if action == "add":
        if not task:
            emit({"error": "need --task text"}, command="scout rtx queue add")
            raise typer.Exit(1)
        entry = {
            "id": datetime.now(UTC).isoformat(),
            "task": task,
            "program": program,
            "status": "pending",
            "created_at": datetime.now(UTC).isoformat(),
        }
        q["tasks"].append(entry)
        _save_queue(q)
        emit(
            {
                "added": entry,
                "queue_file": str(QUEUE_FILE),
                "next_steps": f"Copy queue to Alienware or gh release, then run program {program}",
            }
        )
    elif action == "list":
        emit({"tasks": q.get("tasks", []), "file": str(QUEUE_FILE)})
    elif action == "clear":
        q = {"tasks": []}
        _save_queue(q)
        emit({"cleared": True, "file": str(QUEUE_FILE)})
    else:
        emit({"error": f"unknown action {action}", "valid": ["add", "list", "clear"]})


@app.command("results")
def results(
    n: int = typer.Option(20, "--n", help="last N results"),
    best: bool = typer.Option(False, "--best", help="show best val_bpb only"),
):
    data = _load_results_jsonl(200)
    if not data:
        if RESULTS_TSV.exists():
            tsv = RESULTS_TSV.read_text().strip().splitlines()[: n + 1]
            emit(
                {
                    "source": "results.tsv",
                    "lines": tsv,
                    "count": len(tsv) - 1 if len(tsv) > 0 else 0,
                    "file": str(RESULTS_TSV),
                }
            )
            return
        emit(
            {
                "results": [],
                "message": "No results yet — run in Alienware: .\\scripts\\run-autonomous.ps1",
            }
        )
        return
    if best:
        sorted_data = sorted(
            [
                d
                for d in data
                if isinstance(d.get("val_bpb"), (int, float)) and d["val_bpb"] > 0
            ],
            key=lambda x: x["val_bpb"],
        )
        top = sorted_data[:5] if sorted_data else []
        emit({"best": top, "total": len(data), "file": str(RESULTS_FILE)})
    else:
        emit({"results": data[-n:], "total": len(data), "file": str(RESULTS_FILE)})


@app.command("programs")
def programs():
    prog_dir = CUSTOM_ROOT / "programs"
    if not prog_dir.exists():
        emit({"programs": [], "error": "custom root not found"})
        return
    out = []
    for p in prog_dir.glob("*.md"):
        try:
            head = p.read_text()[:500]
            out.append({"file": p.name, "path": str(p), "preview": head[:200]})
        except Exception:
            out.append({"file": p.name, "path": str(p)})
    emit(
        {
            "programs": out,
            "root": str(CUSTOM_ROOT),
            "hint": "Use: .\\scripts\\run-autonomous.ps1 -Program programs\\program-ava.md",
        }
    )


@app.command("releases")
def releases_cmd(
    action: str = typer.Argument("list", help="list|sync"),
    tag: str = typer.Option("", "--tag", help="tag to sync e.g. v0.6.0-ava-0715"),
):
    """List GitHub releases from scout-rtx repo, auto-read src for dashboard"""
    if action == "list":
        try:
            r = httpx.get(
                f"{GITHUB_API}/releases?per_page=10",
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "scout-cli",
                },
                timeout=10.0,
            )
            if r.status_code != 200:
                emit(
                    {
                        "error": f"GitHub API {r.status_code}",
                        "body": r.text[:500],
                        "repo": GITHUB_REPO,
                    }
                )
                return
            data = r.json()
            slim = [
                {
                    "tag_name": d["tag_name"],
                    "name": d.get("name"),
                    "published_at": d.get("published_at"),
                    "html_url": d.get("html_url"),
                    "assets": [
                        {
                            "name": a["name"],
                            "size": a["size"],
                            "download_url": a["browser_download_url"],
                        }
                        for a in d.get("assets", [])
                    ],
                }
                for d in data
            ]
            emit(
                {
                    "releases": slim,
                    "repo": GITHUB_REPO,
                    "source": f"{GITHUB_API}/releases",
                    "dashboard_auto_read": "every 60s via rtx-offload-dashboard",
                }
            )
        except Exception as e:
            emit({"error": str(e), "repo": GITHUB_REPO})
    elif action == "sync":
        if not tag:
            emit(
                {
                    "error": "need --tag, e.g. scout rtx releases sync --tag v0.6.0-demo-0715"
                }
            )
            raise typer.Exit(1)
        # Download results.tsv asset if exists
        try:
            r = httpx.get(
                f"{GITHUB_API}/releases/tags/{tag}",
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "scout-cli",
                },
                timeout=10.0,
            )
            if r.status_code != 200:
                emit({"error": f"GitHub API {r.status_code}", "body": r.text[:200]})
                return
            rel = r.json()
            assets = rel.get("assets", [])
            downloaded = 0
            for asset in assets:
                name = asset["name"].lower()
                if "results" in name and (
                    name.endswith(".tsv") or name.endswith(".jsonl")
                ):
                    dl = httpx.get(
                        asset["browser_download_url"],
                        timeout=20.0,
                        follow_redirects=True,
                    )
                    if dl.status_code == 200:
                        _ensure_dirs()
                        if name.endswith(".tsv"):
                            (CUSTOM_ROOT / f"results-{tag}.tsv").write_text(dl.text)
                            RESULTS_TSV.write_text(dl.text)  # overwrite latest
                        else:
                            (
                                BB_OFFLOAD / "results" / f"results-{tag}.jsonl"
                            ).write_text(dl.text)
                            # append to main file
                            main = (
                                RESULTS_FILE.read_text()
                                if RESULTS_FILE.exists()
                                else ""
                            )
                            (RESULTS_FILE).write_text(main + "\n" + dl.text)
                        downloaded += 1
            emit(
                {
                    "synced": True,
                    "tag": tag,
                    "downloaded_assets": downloaded,
                    "release": rel.get("html_url"),
                    "next": "scout rtx results --best; scout rtx dashboard",
                }
            )
        except Exception as e:
            emit({"error": str(e)})
    else:
        emit({"error": f"unknown action {action}", "valid": ["list", "sync"]})


@app.command("sync")
def sync_cmd():
    _ensure_dirs()
    results = _load_results_jsonl(50)
    if not results:
        emit(
            {
                "synced": False,
                "reason": "no results.jsonl yet, try scout rtx releases list",
            }
        )
        return
    valid = [r for r in results if r.get("val_bpb") and r["val_bpb"] > 0]
    if not valid:
        emit({"synced": False, "reason": "no valid val_bpb"})
        return
    best = min(valid, key=lambda x: x["val_bpb"])
    payload = {
        "synced": True,
        "best": best,
        "results_count": len(results),
        "github": f"https://github.com/{GITHUB_REPO}/releases",
        "suggestion": f"Best val_bpb {best['val_bpb']} from {best.get('program')} commit {best.get('commit')} → publish via .\\scripts\\publish-release.ps1",
    }
    emit(payload)


@app.command("dashboard")
def dashboard_cmd():
    emit(
        {
            "dashboard": "rtx-offload-dashboard",
            "url": "https://agent.meta.ai -> My Spaces -> RTX Offload Dashboard",
            "github_releases_auto_read": True,
            "repo": f"https://github.com/{GITHUB_REPO}",
            "releases_api": f"{GITHUB_API}/releases",
            "poll_interval": "60s",
            "integration": "dashboard calls listGithubReleases + syncReleaseResults automatically",
        }
    )
