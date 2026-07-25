# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout flows` — Zapier/Make replacement, fully local (openswap #27).

Automation with the hosted runner deleted: the workflow is a JSON graph in your
repo, the runner is bigbang/core/flows.py on THIS box, steps are free (Zapier
prices the "task", i.e. the step), and nothing is shipped anywhere — the
manifest disables the network axis entirely, so "no payload left the box" is
architectural rather than a promise.

The execution model is the point, and it is deliberately not Zapier's: a hard
step cap on a SHARED budget (a sub-flow spends the same budget, so nesting buys
no extra steps), cycles refused by validation AND a per-node visit cap at
runtime, bounded sub-flow recursion, and DEFAULT-DENY actions — an action runs
only when `--allow <name>` names it, it exists in the catalog, and this surface
injected an effector for it. Anything missing is a recorded refusal that stops
the run and names the node; nothing is ever silently skipped.

This surface owns the real I/O: reading the flow JSON, and the three effectors
(`emit` has no side effect; `write_file` and `append_jsonl` write inside
--out-dir, confined by core resolve_output_path which refuses absolute paths,
drive-qualified paths and any '..' escape). Writes are utf-8 BYTES via
write_bytes / an "ab" handle, never write_text, so a Windows run and a Linux run
produce byte-identical files instead of CRLF-forked ones. The run ledger
(.scout/flows.db — its own file, never the #2 uptime ledger's write lock) is
Zapier's task-history pane as a local table, and it is what a `schedule`
trigger reads to decide "am I due" from recorded data rather than a guess.

Policy: zero network calls anywhere in this plugin. The only capability it
needs is fs_write, enforced with enforce_or_raise at the call site for both the
ledger and the output directory. flowpipe is surfaced by `detect` as the closest
genuinely local open runner; n8n (a server) and the zapier CLI (the paid
platform's own SaaS client) are surfaced for awareness but NEVER executed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from bigbang.core import flows, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib bounded workflow runner is the complete product for this "
    "adapter: JSON trigger->transform->action graphs, a hard shared step cap, "
    "cycle refusal plus a per-node visit cap, bounded sub-flow recursion, "
    "default-deny action allowlisting with every refusal reported by node, "
    "output-path containment, and a sqlite run/step ledger; tier 'fallback' is "
    "the expected steady state (Zapier and Make are SaaS runners and n8n ships "
    "as a server — no local native binary runs THIS graph under THESE bounds)"
)
INSTALL_HINT = (
    "nothing to install — the stdlib runner is complete; flowpipe is an "
    "optional local runner for its own HCL pipelines (a different language, "
    "with none of these caps), so it complements this rather than replacing it"
)

app = make_plugin_app(
    "flows",
    "Bounded JSON workflow graphs (Zapier-class), fully local: hard step cap, "
    "no unbounded loops, default-deny action allowlist, zero egress",
    examples=[
        "scout --json flows actions",
        "scout --json flows plan --example",
        "scout --json flows run --example --payload '{\"severity\":\"error\",\"hosts\":[\"a.com\"]}'",
        "scout --json flows run --flow my-flow.json --allow append_jsonl",
        "scout --json flows runs --limit 5",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only on writes
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # flowpipe is the honest `native` probe: the closest genuinely local, open,
    # no-server workflow CLI. It runs HCL pipelines, not this JSON graph, and
    # enforces none of these bounds, so the stdlib core stays the product either
    # way. n8n (a server) and the zapier CLI (the paid platform's own client,
    # whose whole job is talking to the SaaS — the forbidden network tier) are
    # surfaced for awareness and NEVER executed.
    native = openswap.probe_binary("flowpipe", probe_args=("--version",))
    extras = {
        "n8n": openswap.probe_binary("n8n", probe_args=("--version",)),
        "zapier": openswap.probe_binary("zapier", probe_args=("--version",)),
    }
    return openswap.capability_report(
        "flows",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    return Path(db or os.environ.get("SCOUT_FLOWS_DB") or flows.DB_REL)


def _open_store(db: str | None) -> tuple:
    path = _db_path(db)
    # call-site enforcement: the plugin loader does not check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    return flows.open_store(path), path


def _open_existing(db: str | None, command: str) -> tuple:
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no flow ledger at {path} — run a flow first",
            command=command,
            example="scout --json flows run --example --payload '{\"severity\":\"error\"}'",
        )
    return flows.open_store(path), path


def _ledger_for(db: str | None, record: bool, name: str) -> tuple:
    """(connection, recorded path or None, this flow's real last-run epoch).

    --no-record still opens an in-memory ledger so the pipeline is identical;
    last_run comes from the REAL ledger when there is one, because a schedule
    trigger must decide from recorded history, never from a guessed timestamp.
    """
    conn, path = _open_store(db) if record else (flows.open_store(":memory:"), None)
    return conn, path, flows.last_run_ts(conn, name)


def _read_json(path: str, label: str, command: str) -> dict:
    """Load one JSON object from a file (utf-8-sig: a PowerShell BOM is fine)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        fail_agent(
            f"bad {label} file {path}: {type(exc).__name__}: {exc}",
            command=command,
            example="scout --json flows plan --example",
        )
    if not isinstance(data, dict):
        fail_agent(
            f"{label} file {path} must contain a JSON object",
            command=command,
            example="scout --json flows plan --example",
        )
    return data


def _flow_or_fail(flow: str | None, example: bool, command: str) -> tuple[dict, str]:
    """(graph, source label). --example ships a real runnable graph, not a stub."""
    if example:
        return flows.EXAMPLE_FLOW, "core:EXAMPLE_FLOW"
    if not flow:
        fail_agent(
            "say which workflow: --flow <file.json> or --example",
            command=command,
            example="scout --json flows plan --example",
            discover="scout flows actions",
        )
    return _read_json(flow, "flow", command), Path(flow).as_posix()


def _payload_or_fail(payload: str | None, command: str) -> dict:
    """--payload accepts inline JSON or @file.json; nothing means an empty event."""
    if not payload:
        return {}
    if payload.startswith("@"):
        return _read_json(payload[1:], "payload", command)
    try:
        data = json.loads(payload)
    except ValueError as exc:
        fail_agent(
            f"--payload must be JSON or @file.json: {exc}",
            command=command,
            example='scout --json flows run --example --payload \'{"severity":"error"}\'',
        )
    if not isinstance(data, dict):
        fail_agent(
            "--payload must be a JSON object",
            command=command,
            example='scout --json flows run --example --payload \'{"severity":"error"}\'',
        )
    return data


def _registry_or_fail(sub: list[str] | None, command: str) -> dict:
    """Sub-flow registry keyed by each graph's own `name` — never by filename."""
    out: dict = {}
    for path in sub or []:
        graph = _read_json(path, "sub-flow", command)
        name = str(graph.get("name") or "").strip()
        if not name:
            fail_agent(
                f"sub-flow {path} has no `name` to register it under",
                command=command,
                example="scout --json flows run --flow main.json --sub child.json",
            )
        out[name] = graph
    return out


def _effectors(out_dir: Path) -> dict:
    """The ONE place real effects happen. Each raises on failure, never lies.

    Both file effectors write utf-8 BYTES (write_bytes / an "ab" handle) because
    write_text on Windows translates "\\n" to CRLF and the same flow would then
    produce a file that diffs against its own Linux output.
    """

    def _emit(params: dict, data: dict) -> dict:
        return {"emitted": flows.select_fields(data, params.get("fields"))}

    def _write_file(params: dict, data: dict) -> dict:
        target = flows.resolve_output_path(out_dir, params.get("file"))
        blob = flows.as_text(flows.require_field(data, params.get("from"))).encode("utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        return {"file": target.as_posix(), "bytes": len(blob)}

    def _append_jsonl(params: dict, data: dict) -> dict:
        target = flows.resolve_output_path(out_dir, params.get("file"))
        row = flows.select_fields(data, params.get("fields"))
        blob = (json.dumps(row, sort_keys=True, default=str) + "\n").encode("utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("ab") as fh:
            fh.write(blob)
        return {"file": target.as_posix(), "appended": 1, "bytes": len(blob)}

    return {"emit": _emit, "write_file": _write_file, "append_jsonl": _append_jsonl}


def _fail_on_or_fail(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example=f"scout --json flows {command.split()[-1]} --example --fail-on error",
        )


def _gate(diags: list[dict], fail_on: str | None) -> None:
    """Exit 1 when any diagnostic is at/above the gate — the cron/CI hook."""
    if fail_on is None:
        return
    rank = openswap.severity_rank(fail_on)
    if any(openswap.severity_rank(d["severity"]) <= rank for d in diags):
        raise typer.Exit(code=1)


@app.command("hello", epilog=examples_epilog(["scout --json flows hello"]))
def hello():
    """Smoke check — is the flows surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "flows"},
            command="flows hello",
            example="scout --json flows plan --example",
            discover="scout flows detect",
        ),
        command="flows hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json flows detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    emit(
        ok(
            _capability(),
            command="flows detect",
            example="scout --json flows plan --example",
            discover="scout flows actions",
        ),
        command="flows detect",
    )


@app.command("actions", epilog=examples_epilog(["scout --json flows actions"]))
def actions_cmd():
    """Publish the whole vocabulary: actions, ops, bounds, and a runnable example."""
    emit(
        ok(
            {
                "actions": {
                    name: {
                        "effects": spec["effects"],
                        "required": list(spec["params"]),
                        "optional": list(spec["optional"]),
                        "description": spec["description"],
                    }
                    for name, spec in sorted(flows.ACTIONS.items())
                },
                "default_allowlist": [],
                "allowlist_doctrine": (
                    "default-deny: no action runs unless --allow names it, and a "
                    "refusal stops the run and is reported by node — never skipped"
                ),
                "node_kinds": list(flows.KINDS),
                "transform_ops": list(flows.TRANSFORM_OPS),
                "condition_ops": list(flows.PREDICATE_OPS),
                "triggers": list(flows.TRIGGERS),
                "bounds": {
                    "max_steps": flows.DEFAULT_MAX_STEPS,
                    "max_depth": flows.DEFAULT_MAX_DEPTH,
                    "max_visits": flows.DEFAULT_MAX_VISITS,
                },
                "example_flow": flows.EXAMPLE_FLOW,
            },
            command="flows actions",
            example="scout --json flows plan --example",
            discover="scout flows plan --example",
        ),
        command="flows actions",
    )


@app.command(
    "plan",
    epilog=examples_epilog(
        [
            "scout --json flows plan --example",
            "scout --json flows plan --flow my-flow.json --allow append_jsonl",
            "scout --json flows plan --flow my-flow.json --fail-on error",
        ]
    ),
)
def plan(
    flow: str | None = typer.Option(None, "--flow", help="workflow graph JSON file"),
    example: bool = typer.Option(False, "--example", help="use the built-in example graph"),
    allow: list[str] = typer.Option(
        None, "--allow", help="action to permit, repeatable (default: nothing)"
    ),
    sub: list[str] = typer.Option(
        None, "--sub", help="sub-flow JSON file, repeatable (registered by its `name`)"
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 if any problem is at/above this severity"
    ),
):
    """Validate + report what WOULD run. Executes nothing, writes nothing."""
    _fail_on_or_fail(fail_on, "flows plan")
    graph, source = _flow_or_fail(flow, example, "flows plan")
    registry = _registry_or_fail(sub, "flows plan")
    problems = flows.validate(graph, registry=registry)
    diags = flows.to_diagnostics(source, problems)
    pre = flows.preflight(graph, allow or [])
    emit(
        ok(
            {
                "source": source,
                "flow": graph.get("name"),
                "trigger": (graph.get("trigger") or {}).get("type"),
                "nodes": len(graph.get("nodes") or {}),
                "order": flows.walk_order(graph),
                "subflows": flows.subflow_names(graph),
                "registry": sorted(registry),
                "preflight": pre,
                "valid": not any(p["severity"] == "error" for p in problems),
                "problems": problems,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="flows plan",
            example="scout --json flows run --example --payload '{\"severity\":\"error\"}'",
            discover="scout flows actions",
        ),
        command="flows plan",
    )
    _gate(diags, fail_on)


@app.command(
    "run",
    epilog=examples_epilog(
        [
            "scout --json flows run --example --payload '{\"severity\":\"error\",\"hosts\":[\"a.com\"]}'",
            "scout --json flows run --example --payload @event.json --allow append_jsonl",
            "scout --json flows run --flow main.json --sub child.json --max-steps 20",
            "scout --json flows run --flow main.json --allow emit --fail-on error",
        ]
    ),
)
def run(
    flow: str | None = typer.Option(None, "--flow", help="workflow graph JSON file"),
    example: bool = typer.Option(False, "--example", help="use the built-in example graph"),
    payload: str | None = typer.Option(
        None, "--payload", help="event payload: inline JSON or @file.json"
    ),
    allow: list[str] = typer.Option(
        None, "--allow", help="action to permit, repeatable — DEFAULT-DENY: with "
        "none passed, every action node is refused and reported",
    ),
    sub: list[str] = typer.Option(
        None, "--sub", help="sub-flow JSON file, repeatable (registered by its `name`)"
    ),
    out_dir: str | None = typer.Option(
        None, "--out-dir", help=f"where file actions may write (default {flows.OUT_REL})"
    ),
    db: str | None = typer.Option(
        None, "--db", help=f"run ledger (default {flows.DB_REL} or $SCOUT_FLOWS_DB)"
    ),
    max_steps: int = typer.Option(
        flows.DEFAULT_MAX_STEPS, "--max-steps", help="hard step cap, shared with sub-flows"
    ),
    max_depth: int = typer.Option(
        flows.DEFAULT_MAX_DEPTH, "--max-depth", help="hard sub-flow recursion cap"
    ),
    record: bool = typer.Option(
        True, "--record/--no-record", help="persist the run (off = execute and report only)"
    ),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 if any refusal/failure is at/above this severity"
    ),
):
    """Execute one flow under hard bounds. Real effects, only allowlisted ones."""
    _fail_on_or_fail(fail_on, "flows run")
    graph, source = _flow_or_fail(flow, example, "flows run")
    registry = _registry_or_fail(sub, "flows run")
    event = _payload_or_fail(payload, "flows run")
    out = Path(out_dir or flows.OUT_REL)
    enforce_or_raise(_manifest(), "fs_write_arg", str(out))
    conn, path, last_run = _ledger_for(db, record, str(graph.get("name") or ""))
    res = flows.run_flow(
        graph,
        event,
        allow=allow or [],
        effectors=_effectors(out),
        registry=registry,
        max_steps=max_steps,
        max_depth=max_depth,
        last_run=last_run,
    )
    run_id = flows.record_run(conn, res, source=source) if record else None
    diags = flows.to_diagnostics(source, res["problems"])
    emit(
        ok(
            {
                "db": str(path) if path else None,
                "run_id": run_id,
                "source": source,
                "out_dir": out.as_posix(),
                **res,
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="flows run",
            example="scout --json flows runs --limit 5",
            discover="scout flows runs",
        ),
        command="flows run",
    )
    _gate(diags, fail_on)


@app.command(
    "runs",
    epilog=examples_epilog(
        [
            "scout --json flows runs",
            "scout --json flows runs --flow cert-error-digest --limit 5",
            "scout --json flows runs --run 1",
        ]
    ),
)
def runs_cmd(
    flow: str | None = typer.Option(None, "--flow", help="filter to one flow name"),
    outcome: str | None = typer.Option(None, "--outcome", help=f"filter: {'|'.join(flows.OUTCOMES)}"),
    run_id: int | None = typer.Option(None, "--run", help="one run with its ordered steps"),
    limit: int = typer.Option(20, "--limit", help="max runs returned"),
    db: str | None = typer.Option(None, "--db", help="run ledger path"),
):
    """Run history — Zapier's task pane as a local table. Read-only."""
    conn, path = _open_existing(db, "flows runs")
    if run_id is not None:
        detail = flows.run_detail(conn, run_id)
        if detail is None:
            fail_agent(
                f"no run {run_id} in {path}",
                command="flows runs",
                example="scout --json flows runs --limit 5",
            )
        emit(
            ok(
                {"db": str(path), "run": detail},
                command="flows runs",
                example="scout --json flows runs --limit 5",
                discover="scout flows run --example",
            ),
            command="flows runs",
        )
        return
    emit(
        ok(
            {
                "db": str(path),
                "runs": flows.list_runs(conn, flow=flow, outcome=outcome, limit=limit),
                "by_outcome": flows.outcome_counts(conn, flow=flow),
            },
            command="flows runs",
            example="scout --json flows runs --run 1",
            discover="scout flows run --example",
        ),
        command="flows runs",
    )


def register(root):
    root.add_typer(app, name="flows")
