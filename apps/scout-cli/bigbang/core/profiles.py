# Solo personal project, no connection to employer, built with public/free-tier only
"""Dynamic execution profiles — the Hermes / OpenClaw runtime loops.

A profile shapes how the agent runtime behaves around the Single CLI Doctrine (the LLM
has exactly ONE tool: scout). Hermes is the self-improving loop: solve, then isolate the
routine into a reusable forge tool so the next session starts stronger. OpenClaw is the
context-persistence loop: re-enter every step with deep session state and discover
existing capabilities before writing new code.

The J-Space state store (packages/ava-skills, skills.state_store) is the persistence
substrate for both: Hermes registers refined tools into `skills_library`; OpenClaw reads
and writes `session_context`. It is imported lazily and its absence degrades honestly —
profiles still shape prompts, and the caller is told persistence is off.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

HERMES_SYSTEM_ROLE = (
    "System Role: You are the Hermes runtime loop within Dottie. Execute tasks "
    "proactively using `scout`. After every successful execution, isolate the underlying "
    "routine, write/refine a reusable Python tool via `scout forge forge`, and update "
    "your local J-Space skills registry."
)

OPENCLAW_SYSTEM_ROLE = (
    "System Role: You are the OpenClaw orchestration loop within Dottie. Maintain high "
    "situational awareness and deep state context across execution loops using the "
    "`session_context` memory store. Coordinate complex cross-domain tasks by "
    "discovering existing capability manifests via `scout --json forge list` before "
    "attempting to write raw execution code."
)


@dataclass(frozen=True)
class Profile:
    name: str
    system_role: str
    # behavioural switches the agent runtime honours
    persist_context: bool = False  # load/store session_context around each run
    refine_after_success: bool = False  # Hermes: register the routine as a skill
    discover_first: tuple = field(default_factory=tuple)  # commands to surface pre-plan


PROFILES: dict[str, Profile] = {
    "hermes": Profile(
        name="hermes",
        system_role=HERMES_SYSTEM_ROLE,
        refine_after_success=True,
    ),
    "openclaw": Profile(
        name="openclaw",
        system_role=OPENCLAW_SYSTEM_ROLE,
        persist_context=True,
        discover_first=("scout --json forge list",),
    ),
}


def get_profile(name: str | None = None) -> Profile | None:
    """Resolve by explicit name, then DOTTIE_PROFILE env; None means plain runtime."""
    key = (name or os.environ.get("DOTTIE_PROFILE") or "").strip().lower()
    if not key:
        return None
    if key not in PROFILES:
        raise KeyError(f"unknown profile {key!r}; available: {sorted(PROFILES)}")
    return PROFILES[key]


def _state_store():
    """Lazy J-Space store import — ava-skills is a sibling workspace member and may be
    absent in a standalone scout install. Honest None, never a stub."""
    try:
        from skills.state_store import JSpaceStateStore

        return JSpaceStateStore()
    except ImportError:
        return None


def build_system_prompt(
    profile: Profile, *, session_id: str = "scout"
) -> dict[str, Any]:
    """The profile's system role plus (OpenClaw) the persisted session snapshot.

    Returns {"system": str, "context": dict|None, "persistence": "on"|"unavailable"}
    so callers can surface exactly what state the loop re-entered with."""
    context = None
    persistence = "off"
    if profile.persist_context:
        store = _state_store()
        if store is None:
            persistence = "unavailable"
        else:
            with store:
                context = store.session_snapshot(session_id)
            persistence = "on"
    system = profile.system_role
    if context:
        system += f"\n\nPersistent session context ({session_id}): {context}"
    if profile.discover_first:
        system += "\n\nBefore planning, discover existing capabilities: " + "; ".join(
            profile.discover_first
        )
    return {"system": system, "context": context, "persistence": persistence}


def after_run(
    profile: Profile,
    *,
    session_id: str,
    task: str,
    outcome: str,
    plan: list | None = None,
) -> dict[str, Any]:
    """Post-run hook: log the task; Hermes registers the successful routine into
    skills_library as a forge-refinement candidate; OpenClaw persists the last
    outcome as re-entry state. Every write is real or reported unavailable."""
    store = _state_store()
    if store is None:
        return {"persistence": "unavailable"}
    result: dict[str, Any] = {"persistence": "on"}
    with store:
        store.log_task(
            session_id, task, outcome, trace={"plan": plan} if plan else None
        )
        if profile.persist_context:
            # channel "cli": scout is the CLI surface of the shared store (the dottie
            # engine writes "engine"/"arxiviq"); session_snapshot reads ALL channels,
            # so cross-surface visibility is by session_id, not by channel.
            store.set_context(session_id, "last_task", task, channel="cli")
            store.set_context(session_id, "last_outcome", outcome, channel="cli")
            result["context_updated"] = ["last_task", "last_outcome"]
            result["channel"] = "cli"
        if profile.refine_after_success and outcome == "ok" and plan:
            name = f"routine_{abs(hash(task)) % 10**8:08d}"
            version = store.register_skill(
                name,
                _forge_tool_code(name, task, plan),
                capabilities="",
                source="hermes",
            )
            result["skill_registered_version"] = version
            # Hermes PROPOSES the refinement; a human confirms by running the commands
            # (same gate philosophy as research promotion bundles — nothing self-installs).
            result["forge_proposal"] = [
                f'scout --json forge new {name} --description "{task[:60]}"',
                f"scout --json forge edit {name} --code-file <skills_library:{name}>",
                f"scout --json forge test {name}",
            ]
    return result


def _forge_tool_code(name: str, task: str, plan: list) -> str:
    """A contract-compliant plugin draft wrapping the routine's steps: ``run`` replays
    the plan via subprocess scout calls and reports each step's REAL exit code. Stored
    in skills_library as the ready-to-forge artifact behind the human-gated proposal."""
    steps = ",\n    ".join(repr(str(s)) for s in plan)
    header = "# Solo personal project, no connection to employer, built with public/free-tier only"
    return f'''{header}
"""{name} — Hermes-refined routine for: {task}"""
import shlex
import subprocess
import sys
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.cli_ux import examples_epilog

app = make_plugin_app("{name}", "Hermes routine: {task[:70]}")

STEPS = [
    {steps},
]


@app.command("hello", epilog=examples_epilog(["scout --json {name} hello"]))
def hello():
    emit(ok({{"plugin": "{name}", "steps": len(STEPS)}}, command="{name} hello",
            example="scout --json {name} run"), command="{name} hello")


@app.command("run", epilog=examples_epilog(["scout --json {name} run"]))
def run():
    results = []
    for step in STEPS:
        argv = [sys.executable, "-m", "bigbang.cli", "--json"] + shlex.split(step)[1:]
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        results.append({{"step": step, "exit": p.returncode}})
    emit(ok({{"results": results}}, command="{name} run",
            example="scout --json {name} run"), command="{name} run")


def register(root):
    root.add_typer(app, name="{name}")
'''
