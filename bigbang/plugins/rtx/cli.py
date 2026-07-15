"""
bb rtx — Alienware RTX 4080/4090 offload bridge for autoresearch-win-rtx custom
Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import typer

from bigbang.core.output import emit

app = typer.Typer(name="rtx", help="🚀 RTX — offload to Alienware RTX 4080/4090 local box", no_args_is_help=True)

# Paths — cloud version points to workspace/autoresearch-rtx-custom which is where we built custom fork
CUSTOM_ROOT = Path.home() / "workspace" / "autoresearch-rtx-custom"
BB_OFFLOAD = CUSTOM_ROOT / "bb-offload"
QUEUE_FILE = BB_OFFLOAD / "queue.json"
RESULTS_FILE = BB_OFFLOAD / "results" / "results.jsonl"
RESULTS_TSV = CUSTOM_ROOT / "results.tsv"
MRR_FILE = Path.home() / "workspace" / "projects" / "first-1k-mo-passive" / "files" / "mrr.jsonl"

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
    """Show RTX offload status — queue, results, local profile"""
    _ensure_dirs()
    queue = _load_queue()
    results = _load_results_jsonl(10)

    # Try to read hardware profile from custom docs
    hw_profile = {}
    try:
        # Check if results.tsv exists for best val_bpb
        if RESULTS_TSV.exists():
            lines = RESULTS_TSV.read_text().strip().splitlines()
            if len(lines) > 1:
                # parse TSV
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
        "queue_pending": len([t for t in queue.get("tasks", []) if t.get("status") == "pending"]),
        "queue_total": len(queue.get("tasks", [])),
        "results_count": len(results),
        "best": hw_profile,
        "gpu_hint": "RTX 4080 16GB ada-16gb batch 32 or RTX 4090 24GB ada-24gb-plus batch 64, BF16 TF32 SDPA, torch 2.9.1 cu128, 5-min budget",
        "offload_guide": str(CUSTOM_ROOT / "docs" / "OFFLOAD_GUIDE.md"),
        "programs": [str(p) for p in (CUSTOM_ROOT / "programs").glob("*.md")] if (CUSTOM_ROOT / "programs").exists() else [],
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }
    emit(payload)

@app.command("queue")
def queue_cmd(
    action: str = typer.Argument("list", help="add|list|clear"),
    task: str = typer.Option("", "--task", "-t", help="task description for add"),
    program: str = typer.Option("program-base.md", "--program", "-p", help="program file e.g. programs/program-ava.md"),
):
    """Manage offload queue — queue tasks to Alienware RTX box"""
    _ensure_dirs()
    q = _load_queue()

    if action == "add":
        if not task:
            emit({"error": "need --task text"}, command="bb rtx queue add")
            raise typer.Exit(1)
        entry = {
            "id": datetime.now(timezone.utc).isoformat(),
            "task": task,
            "program": program,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        q["tasks"].append(entry)
        _save_queue(q)
        emit({"added": entry, "queue_file": str(QUEUE_FILE), "next_steps": f"Copy queue to Alienware or run sync script, then run program {program}"})
    elif action == "list":
        emit({"tasks": q.get("tasks", []), "file": str(QUEUE_FILE)})
    elif action == "clear":
        q = {"tasks": []}
        _save_queue(q)
        emit({"cleared": True, "file": str(QUEUE_FILE)})
    else:
        emit({"error": f"unknown action {action}", "valid": ["add","list","clear"]})

@app.command("results")
def results(
    n: int = typer.Option(20, "--n", help="last N results"),
    best: bool = typer.Option(False, "--best", help="show best val_bpb only"),
):
    """Show results from Alienware RTX runs"""
    data = _load_results_jsonl(200)
    if not data:
        # fallback to results.tsv
        if RESULTS_TSV.exists():
            tsv = RESULTS_TSV.read_text().strip().splitlines()[:n+1]
            emit({"source": "results.tsv", "lines": tsv, "count": len(tsv)-1 if len(tsv)>0 else 0, "file": str(RESULTS_TSV)})
            return
        emit({"results": [], "message": "No results yet — run in Alienware: .\\scripts\\run-autonomous.ps1"})
        return

    if best:
        sorted_data = sorted([d for d in data if isinstance(d.get("val_bpb"), (int,float)) and d["val_bpb"]>0], key=lambda x: x["val_bpb"])
        top = sorted_data[:5] if sorted_data else []
        emit({"best": top, "total": len(data), "file": str(RESULTS_FILE)})
    else:
        emit({"results": data[-n:], "total": len(data), "file": str(RESULTS_FILE)})

@app.command("programs")
def programs():
    """List custom programs for RTX offload"""
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
    emit({"programs": out, "root": str(CUSTOM_ROOT), "hint": "Use: .\\scripts\\run-autonomous.ps1 -Program programs\\program-ava.md -Tag ava-jul15"})

@app.command("sync")
def sync_cmd():
    """Sync results to First $1k/mo passive MRR log + brain"""
    _ensure_dirs()
    results = _load_results_jsonl(50)
    if not results:
        emit({"synced": False, "reason": "no results.jsonl yet"})
        return

    # Find best
    valid = [r for r in results if r.get("val_bpb") and r["val_bpb"]>0]
    if not valid:
        emit({"synced": False, "reason": "no valid val_bpb"})
        return
    best = min(valid, key=lambda x: x["val_bpb"])

    # Append to mrr jsonl as note if Turnover track
    payload = {
        "synced": True,
        "best": best,
        "results_count": len(results),
        "suggestion": f"Best val_bpb {best['val_bpb']} from {best.get('program')} commit {best.get('commit')} → promote to {'Ava v6.4' if 'ava' in str(best.get('program','')) else 'Turnover Shield' if 'turnover' in str(best.get('program','')) else 'write plugin'}",
        "next": [
            f"Review CUSTOM_ROOT/docs/OFFLOAD_GUIDE.md",
            f"Promote win: copy train.py diff to appropriate repo",
            f"bb brain daily \"RTX results: best val_bpb {best['val_bpb']} from {best.get('program')}\"",
            f"bb lab mrr --trials 1 --note \"RTX overnight best {best['val_bpb']}\"",
        ],
    }
    emit(payload)

@app.command("dashboard")
def dashboard():
    """Show instructions to open RTX dashboard"""
    web_path = CUSTOM_ROOT / "bigbang-bridge" / "dashboard.json"
    payload = {
        "message": "RTX dashboard — open via BigBang web artifact or check docs",
        "custom_root": str(CUSTOM_ROOT),
        "offload_guide": str(CUSTOM_ROOT / "docs" / "OFFLOAD_GUIDE.md"),
        "hardware_profile": str(CUSTOM_ROOT / "docs" / "HARDWARE_PROFILE.md"),
        "programs": [str(p) for p in (CUSTOM_ROOT / "programs").glob("*.md")] if (CUSTOM_ROOT / "programs").exists() else [],
        "queue_file": str(QUEUE_FILE),
        "results_file": str(RESULTS_FILE),
        "results_tsv": str(RESULTS_TSV),
        "hint": "To visualize: bb --json rtx results --best + bb --json rtx status → feed to web artifact",
        "next_steps_local": [
            "cd C:\\Users\\jcdav\\workspace\\autoresearch-rtx-custom",
            ".\\scripts\\setup-win.ps1 -Program programs\\program-base.md",
            ".\\scripts\\run-autonomous.ps1 -Program programs\\program-ava.md -Tag ava-jul15",
            "Start Claude Code: 'Hi have a look at program.md and let's kick off a new experiment!'",
            ".\\scripts\\sync-to-hatch.ps1 -Watch",
        ],
        "disclaimer": "Solo personal project, no connection to employer",
    }
    emit(payload)

def register(root):
    root.add_typer(app, name="rtx")
