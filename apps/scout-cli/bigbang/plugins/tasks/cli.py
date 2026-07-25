"""
Tasks plugin — Google Tasks wired into BigBang control plane.
Uses hatch_gws_cli (managed OAuth) for all operations, so no secrets in repo.
Real implementation: subprocess to hatch_gws_cli tasks ...

- bb tasks status        -> connection + tasklist count
- bb tasks lists         -> list tasklists
- bb tasks list          -> list tasks in @default or given list
- bb tasks get <id>      -> get one task
- bb tasks add <title>   -> create task
- bb tasks update <id>   -> patch title/notes/due
- bb tasks complete <id> -> mark completed
- bb tasks delete <id>  -> delete with confirm
- bb tasks create-list <title> -> new tasklist
- bb tasks sync-bb       -> import BigBang audit/recent plans as tasks

Security: no network directly, only hatch_gws_cli manages auth; manifest caps network disabled.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer

from bigbang.core.http_utils import sanitize_no_proxy_env
from bigbang.core.output import emit

# Ensure proxy env sanitized (Hatch has IPv6 brackets that break httpx elsewhere, but we use subprocess)
sanitize_no_proxy_env()

app = typer.Typer(
    name="tasks",
    help="✅ Google Tasks — wired into BigBang, lists ↔ bb agent",
    no_args_is_help=True,
)


def _run_gws(args: list[str], json_input: dict | None = None) -> dict:
    """Run hatch_gws_cli tasks ... and return parsed json or raw."""
    cmd = ["hatch_gws_cli", "tasks"] + args
    try:
        if json_input is not None:
            # pass --json with payload
            proc = subprocess.run(
                cmd + ["--json", json.dumps(json_input)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = proc.stdout.strip() or proc.stderr.strip()
        if not out:
            return {"ok": proc.returncode == 0, "raw": ""}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            # Some commands return not json? Try to return as raw
            return {
                "ok": proc.returncode == 0,
                "raw": out,
                "parsed_error": "non-json output",
                "stderr": proc.stderr[:500],
            }
    except subprocess.TimeoutExpired:
        return {"error": "timeout running hatch_gws_cli", "ok": False}
    except FileNotFoundError:
        return {"error": "hatch_gws_cli not found", "ok": False}
    except Exception as e:
        return {"error": str(e), "ok": False}


@app.command("status")
def status_cmd():
    res = _run_gws(["status"])
    # also fetch tasklists count for context
    lists = _run_gws(["tasklists", "list", "--params", json.dumps({"maxResults": 20})])
    count = len(lists.get("items", [])) if isinstance(lists, dict) else 0
    payload = {
        "connection": res,
        "tasklists_count": count,
        "role_in_bigbang": "bb tasks ↔ Google Tasks — source of truth for personal todos, agent can create/complete",
        "next": "bb tasks lists, bb tasks list, bb tasks add 'Ship Turnover Shield fix'",
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }
    emit(payload, command="tasks status")


@app.command("lists")
def lists_cmd():
    res = _run_gws(["tasklists", "list", "--params", json.dumps({"maxResults": 50})])
    items = res.get("items", []) if isinstance(res, dict) else []
    emit(
        {
            "tasklists": items,
            "count": len(items),
            "raw": res,
            "hint": "bb tasks list --tasklist <id> or bb tasks list --tasklist @default",
        },
        command="tasks lists",
    )


@app.command("list")
def list_tasks(
    tasklist: str = typer.Option(
        "@default", "--tasklist", help="tasklist id or @default"
    ),
    show_completed: bool = typer.Option(
        False, "--show-completed", help="include completed"
    ),
    max_results: int = typer.Option(50, "--max", help="max tasks"),
    due_min: str | None = typer.Option(None, help="RFC3339 dueMin filter"),
    due_max: str | None = typer.Option(None, help="RFC3339 dueMax filter"),
):
    params = {
        "tasklist": tasklist,
        "maxResults": max_results,
        "showCompleted": show_completed,
        "showDeleted": False,
    }
    if due_min:
        params["dueMin"] = due_min
    if due_max:
        params["dueMax"] = due_max
    res = _run_gws(["tasks", "list", "--params", json.dumps(params)])
    items = res.get("items", []) if isinstance(res, dict) else []
    emit(
        {"tasklist": tasklist, "tasks": items, "count": len(items), "raw": res},
        command="tasks list",
    )


@app.command("get")
def get_task(
    task_id: str = typer.Argument(..., help="task id"),
    tasklist: str = typer.Option("@default", "--tasklist", help="tasklist id"),
):
    res = _run_gws(
        [
            "tasks",
            "get",
            "--params",
            json.dumps({"tasklist": tasklist, "task": task_id}),
        ]
    )
    emit({"task": res, "tasklist": tasklist}, command="tasks get")


@app.command("add")
def add_task(
    title: str = typer.Argument(..., help="task title"),
    notes: str | None = typer.Option(None, help="notes/body"),
    due: str | None = typer.Option(None, help="RFC3339 due e.g. 2026-07-16T00:00:00Z"),
    tasklist: str = typer.Option("@default", "--tasklist", help="tasklist id"),
):
    body = {"title": title}
    if notes:
        body["notes"] = notes
    if due:
        body["due"] = due
    res = _run_gws(
        ["tasks", "insert", "--params", json.dumps({"tasklist": tasklist})],
        json_input=body,
    )
    emit(
        {
            "created": res,
            "tasklist": tasklist,
            "input": body,
            "next": f"bb tasks list --tasklist {tasklist}",
        },
        command="tasks add",
    )


@app.command("update")
def update_task(
    task_id: str = typer.Argument(..., help="task id"),
    title: str | None = typer.Option(None, help="new title"),
    notes: str | None = typer.Option(None, help="new notes"),
    due: str | None = typer.Option(None, help="new due RFC3339"),
    tasklist: str = typer.Option("@default", "--tasklist", help="tasklist id"),
):
    body = {}
    if title is not None:
        body["title"] = title
    if notes is not None:
        body["notes"] = notes
    if due is not None:
        body["due"] = due
    if not body:
        emit({"error": "no fields to update — use --title/--notes/--due"})
        return
    res = _run_gws(
        [
            "tasks",
            "patch",
            "--params",
            json.dumps({"tasklist": tasklist, "task": task_id}),
        ],
        json_input=body,
    )
    emit({"updated": res, "tasklist": tasklist, "fields": body}, command="tasks update")


@app.command("complete")
def complete_task(
    task_id: str = typer.Argument(..., help="task id"),
    tasklist: str = typer.Option("@default", "--tasklist", help="tasklist id"),
):
    body = {"status": "completed"}
    res = _run_gws(
        [
            "tasks",
            "patch",
            "--params",
            json.dumps({"tasklist": tasklist, "task": task_id}),
        ],
        json_input=body,
    )
    emit(
        {"completed": res, "task_id": task_id, "tasklist": tasklist},
        command="tasks complete",
    )


@app.command("uncomplete")
def uncomplete_task(
    task_id: str = typer.Argument(..., help="task id"),
    tasklist: str = typer.Option("@default", "--tasklist", help="tasklist id"),
):
    body = {"status": "needsAction"}
    res = _run_gws(
        [
            "tasks",
            "patch",
            "--params",
            json.dumps({"tasklist": tasklist, "task": task_id}),
        ],
        json_input=body,
    )
    emit(
        {"uncompleted": res, "task_id": task_id, "tasklist": tasklist},
        command="tasks uncomplete",
    )


@app.command("delete")
def delete_task(
    task_id: str = typer.Argument(..., help="task id"),
    tasklist: str = typer.Option("@default", "--tasklist", help="tasklist id"),
    force: bool = typer.Option(False, "--force", "-f", help="skip confirmation"),
):
    if not force:
        typer.confirm(f"Delete task {task_id} in {tasklist}?", abort=True)
    res = _run_gws(
        [
            "tasks",
            "delete",
            "--params",
            json.dumps({"tasklist": tasklist, "task": task_id}),
        ]
    )
    emit(
        {"deleted": task_id, "tasklist": tasklist, "result": res},
        command="tasks delete",
    )


@app.command("create-list")
def create_list(title: str = typer.Argument(..., help="new tasklist title")):
    res = _run_gws(["tasklists", "insert"], json_input={"title": title})
    emit({"created_list": res, "title": title}, command="tasks create-list")


@app.command("sync-bb")
def sync_bb(
    tasklist: str = typer.Option("@default", "--tasklist", help="target tasklist"),
    from_audit: bool = typer.Option(True, help="import last audit events as tasks"),
):
    """Create BigBang → Google Tasks sync: turn recent bb audit into tasks, and vice versa (future)."""
    created = []
    if from_audit:
        try:
            from bigbang.core.audit import tail_events

            events = tail_events(20)
            # Create 3 recent non-trivial events as tasks if they look like todos
            for ev in events[-5:]:
                cmd = ev.get("command") or ev.get("cmd") or "bb action"
                if "error" in ev or "doctor" in cmd:
                    continue
                title = f"[bb] {cmd} – {str(ev.get('timestamp', ''))[:16]}"
                body = {
                    "title": title[:100],
                    "notes": f"From audit.jsonl: {json.dumps(ev)[:800]}",
                }
                res = _run_gws(
                    ["tasks", "insert", "--params", json.dumps({"tasklist": tasklist})],
                    json_input=body,
                )
                if res.get("id"):
                    created.append(res)
        except Exception as e:
            emit({"error": f"audit sync failed: {e}", "partial": created})
            return

    # Also create starter BigBang wiring tasks
    starters = [
        {
            "title": "Wire Google Tasks into BigBang — bb tasks ↔ Hatch",
            "notes": "Done: tasks plugin with status/lists/list/add/complete. Next: add to ava route and agent bus.",
        },
        {
            "title": "Generate LLM-wiki for BigBang CLI v0.4",
            "notes": "Create docs/llm-wiki/*.md for each plugin with cap-aware docs, then graphify build.",
        },
        {
            "title": "Run graphify build over bigbang-cli → graphify-out",
            "notes": "Use personal-graphify to build graph.json + GRAPH_REPORT.md for token-efficient querying.",
        },
    ]
    for s in starters:
        res = _run_gws(
            ["tasks", "insert", "--params", json.dumps({"tasklist": tasklist})],
            json_input=s,
        )
        if res.get("id"):
            created.append(res)

    emit(
        {
            "synced": len(created),
            "tasks": created,
            "tasklist": tasklist,
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        },
        command="tasks sync-bb",
    )


def _repo_root() -> Path:
    """Find the repo root by searching upward from this file for pyproject.toml."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    # fallback: bigbang package parent (bigbang/plugins/tasks/cli.py -> repo root)
    return here.parents[3]


@app.command("export")
def export_tasks(
    tasklist: str = typer.Option("@default", "--tasklist", help="tasklist id"),
):
    """Export all tasks as JSON for graphify / LLM-wiki ingestion."""
    from bigbang.core.policy import enforce_or_raise, load_manifest

    res = _run_gws(
        [
            "tasks",
            "list",
            "--params",
            json.dumps(
                {"tasklist": tasklist, "maxResults": 100, "showCompleted": False}
            ),
        ]
    )
    root = _repo_root()
    out_path = root / "docs" / "llm-wiki" / f"tasks-{tasklist}.json"
    manifest = load_manifest(Path(__file__).resolve().parent)
    # Stays on the paths-enforcing "fs_write" action: --tasklist names the FILE,
    # so no flag can redirect this write. `base=root` anchors the manifest's
    # relative "docs/llm-wiki" entry to the root resolved above rather than the
    # process CWD — the two diverge whenever the command is invoked from
    # anywhere but the checkout.
    enforce_or_raise(manifest, "fs_write", str(out_path), base=str(root))
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(res, indent=2))
    except OSError as e:
        emit({"error": f"failed to write {out_path}: {e}"}, command="tasks export")
        raise typer.Exit(1)
    emit(
        {
            "exported": str(out_path),
            "count": len(res.get("items", [])) if isinstance(res, dict) else 0,
            "raw": res,
        },
        command="tasks export",
    )


def register(root):
    root.add_typer(app, name="tasks")


# Solo personal project, no connection to employer, built with public/free-tier only
