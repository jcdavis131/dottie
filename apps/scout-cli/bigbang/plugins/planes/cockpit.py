"""Gather five-plane cockpit data — Trust, World, Herd, Judgment, Memory."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from bigbang.core.audit import AUDIT_FILE, tail_events
from bigbang.core.plugin_loader import get_all_manifests, list_plugin_names
from bigbang.core.registry import list_tools
from bigbang.core.security import list_secrets
from bigbang.plugins.herd import store as herd_store

SHARE = Path.home() / ".local" / "share" / "bigbang"
THESIS = "Most agent managers are multiplexers. Scout is a judgment plane."
TAGLINES = [
    "Scout — the judgment plane for personal agents.",
    "Where agents decide. (Herdr is where they live.)",
    "Vaulted. Audited. Teachable. Local.",
]


def _file_ok(path: Path, *, mode_0600: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "ok": False, "status": "missing"}
    st = path.stat()
    mode = st.st_mode & 0o777
    if mode_0600 and mode != 0o600:
        return {
            "path": str(path),
            "ok": False,
            "status": f"mode {oct(mode)} (want 0600)",
        }
    return {"path": str(path), "ok": True, "status": "ready", "mode": oct(mode)}


def trust_plane() -> dict[str, Any]:
    vault = _file_ok(SHARE / "secrets.json", mode_0600=True)
    audit = _file_ok(AUDIT_FILE)
    keys = list_secrets()
    manifests = get_all_manifests()
    capped = sum(
        1 for m in manifests.values() if isinstance(m, dict) and m.get("capabilities")
    )
    return {
        "id": "trust",
        "title": "Trust",
        "question": "May this agent do that — and does anything leave without consent?",
        "ok": True,
        "healthy": bool(vault["ok"] and audit["ok"]),
        "signals": {
            "vault": vault,
            "audit_log": audit,
            "secret_keys": len(keys),
            "plugins_with_manifest_caps": capped,
            "plugins_total": len(list_plugin_names()),
            # Invariant: local audit ∈ Trust; product telemetry ∉ Trust (see docs/DIFFERENTIATION.md)
            "local_audit": True,
            "product_telemetry": False,
            "phone_home": False,
        },
        "commands": [
            "scout --json system doctor",
            "scout --json system policy",
            "scout secrets list",
        ],
    }


def world_plane() -> dict[str, Any]:
    tools = list_tools()
    return {
        "id": "world",
        "title": "World",
        "question": "What internet tools exist?",
        "ok": True,
        "signals": {
            "registered_tools": len(tools),
            "mcp_serve": "scout mcp serve",
            "tool_names": sorted(tools.keys())[:20],
        },
        "commands": [
            "scout --json tools list",
            "scout mcp manifest",
            "scout auth status",
        ],
    }


def herd_plane() -> dict[str, Any]:
    summary = herd_store.summary()
    herdr = herd_store.herdr_available()
    return {
        "id": "herd",
        "title": "Herd",
        "question": "What’s running / blocked / done?",
        "ok": True,
        "signals": {
            "sessions": summary.get("count", 0),
            "by_status": summary.get("by_status", {}),
            "herdr_installed": herdr.get("installed"),
            "note": "Scout herd is a JSON ledger — Herdr owns real PTY panes",
        },
        "commands": [
            "scout --json herd status",
            "scout --json herd wait <label> --status done --timeout 120",
            "scout herd herdr",
        ],
    }


def judgment_plane() -> dict[str, Any]:
    ollama = bool(shutil.which("ollama"))
    # lightweight: don't network-probe Ollama here (doctor does that)
    return {
        "id": "judgment",
        "title": "Judgment",
        "question": "What should we do next?",
        "ok": True,
        "signals": {
            "ava_plugin": "ava" in list_plugin_names(),
            "agent_plugin": "agent" in list_plugin_names(),
            "ollama_binary": ollama,
            "plan_default": "scout agent run …  # plan only; pass --execute to run",
        },
        "commands": [
            'scout --json ava route "check draft for ai slop"',
            'scout --json agent run "list my tools"',
            "scout --json agent bus",
        ],
    }


def memory_plane() -> dict[str, Any]:
    rft_default = Path.home() / ".local" / "share" / "bigbang" / "rft" / "dataset.jsonl"
    # rft plugin default may differ — signal audit richness instead
    events = tail_events(5)
    graph = Path("graphify-out/graph.json")
    memory_md = Path.home() / "MEMORY.md"
    return {
        "id": "memory",
        "title": "Memory",
        "question": "What do we know / learn?",
        "ok": True,
        "signals": {
            "recent_audit_events": len(events),
            "memory_md": memory_md.exists(),
            "graphify_out": graph.exists(),
            "rft_dataset_hint": str(rft_default),
            "flywheel": "act → audit.jsonl → rft export → ava train/eval → better routes",
        },
        "commands": [
            "scout --json brain sync",
            "scout --json graphify status",
            "scout --json rft stats",
        ],
    }


def all_planes() -> list[dict[str, Any]]:
    return [
        trust_plane(),
        world_plane(),
        herd_plane(),
        judgment_plane(),
        memory_plane(),
    ]


def cockpit_status() -> dict[str, Any]:
    planes = all_planes()
    return {
        "thesis": THESIS,
        "taglines": TAGLINES,
        "planes": planes,
        "plane_ids": [p["id"] for p in planes],
        "pairing": {
            "herdr": "WHERE agents live (PTY multiplexer)",
            "scout": "HOW agents decide (judgment plane)",
            "dottie": "scout skill teach --target dottie",
        },
        "docs": [
            "docs/DIFFERENTIATION.md",
            "docs/FOUNDATION.md",
            "docs/herdr-inspired.md",
        ],
        "disclaimer": (
            "Solo personal project, no connection to employer, built with public/free-tier only"
        ),
    }


def compare_matrix() -> dict[str, Any]:
    """Honest matrix — Scout wins on judgment/trust/memory, not on PTY attach."""
    rows = [
        {
            "capability": "Runs inside your terminal",
            "tmux": True,
            "agent_apps": False,
            "herdr": True,
            "scout": True,
            "scout_note": "CLI + MCP, not a TUI multiplexer",
        },
        {
            "capability": "Persistent PTY sessions",
            "tmux": True,
            "agent_apps": "limited",
            "herdr": True,
            "scout": False,
            "scout_note": "Pair with Herdr — deliberate omission",
        },
        {
            "capability": "Remote SSH / thin-client attach",
            "tmux": True,
            "agent_apps": "limited",
            "herdr": True,
            "scout": False,
            "scout_note": "Pair with Herdr",
        },
        {
            "capability": "Semantic pane state",
            "tmux": False,
            "agent_apps": "partial",
            "herdr": True,
            "scout": "ledger",
            "scout_note": "herd JSON status, not PTY sidebar",
        },
        {
            "capability": "Capability-gated world tools",
            "tmux": False,
            "agent_apps": "partial",
            "herdr": False,
            "scout": True,
            "scout_note": "tools + mcp + policy manifests",
        },
        {
            "capability": "Vault + default-deny policy + local audit",
            "tmux": False,
            "agent_apps": "varies",
            "herdr": False,
            "scout": True,
            "scout_note": "Trust plane (audit stays on your disk)",
        },
        {
            "capability": "No product telemetry / no phone-home",
            "tmux": True,
            "agent_apps": "often no",
            "herdr": True,
            "scout": True,
            "scout_note": "Shared value with Herdr; telemetry is a Trust boundary, not a feature",
        },
        {
            "capability": "Audit → RFT training loop",
            "tmux": False,
            "agent_apps": False,
            "herdr": False,
            "scout": True,
            "scout_note": "Memory plane flywheel",
        },
        {
            "capability": "Local brain routing (Ava)",
            "tmux": False,
            "agent_apps": False,
            "herdr": False,
            "scout": True,
            "scout_note": "Judgment plane",
        },
        {
            "capability": "Personal knowledge graph",
            "tmux": False,
            "agent_apps": False,
            "herdr": False,
            "scout": True,
            "scout_note": "graphify",
        },
        {
            "capability": "Installable agent curriculum",
            "tmux": False,
            "agent_apps": "partial",
            "herdr": "skill",
            "scout": True,
            "scout_note": "scout skill teach --target dottie",
        },
        {
            "capability": "Agents can orchestrate it",
            "tmux": "scriptable",
            "agent_apps": "partial",
            "herdr": True,
            "scout": True,
            "scout_note": "JSON CLI + scout_* MCP tools",
        },
        {
            "capability": "No browser dashboard / no account",
            "tmux": True,
            "agent_apps": False,
            "herdr": True,
            "scout": True,
            "scout_note": "Shared value with Herdr",
        },
    ]
    return {
        "thesis": THESIS,
        "headline": "Most agent managers are multiplexers. Scout is a judgment plane.",
        "rows": rows,
        "win_column": "scout",
        "refuse": [
            "Building a Herdr/tmux TUI clone",
            "Competing on SSH thin-client attach",
            "Marketing 'tmux for AI agents'",
        ],
        "embrace": [
            "Trust plane (vault/policy/audit)",
            "World plane (tools/MCP)",
            "Judgment plane (Ava/agent)",
            "Memory plane (brain/graphify/rft)",
            "Teach Dottie-claw via skills",
        ],
        "docs": "docs/DIFFERENTIATION.md",
    }


def loop_health() -> dict[str, Any]:
    """Flywheel: act → audit → rft → ava → better routes."""
    events = tail_events(50)
    commands = [e.get("command") for e in events if e.get("command")]
    herd = herd_store.summary()
    stages = [
        {
            "stage": "act",
            "ok": True,
            "detail": "tools / herd / agent --execute",
            "example": 'scout herd start job --cmd "pytest -q"',
        },
        {
            "stage": "audit",
            "ok": AUDIT_FILE.exists(),
            "detail": f"{len(events)} recent events sampled",
            "example": "scout --json system audit --n 20",
            "top_commands": _top(commands, 8),
        },
        {
            "stage": "rft",
            "ok": "rft" in list_plugin_names(),
            "detail": "export audit traces to training JSONL",
            "example": "scout --json rft export",
        },
        {
            "stage": "judge",
            "ok": "ava" in list_plugin_names(),
            "detail": "Ava route + agent plan",
            "example": 'scout --json ava route "what next"',
        },
        {
            "stage": "remember",
            "ok": True,
            "detail": "brain sync + graphify",
            "example": "scout --json brain sync",
        },
        {
            "stage": "herd",
            "ok": True,
            "detail": f"{herd.get('count', 0)} sessions in ledger",
            "example": "scout --json herd status",
        },
    ]
    return {
        "thesis": THESIS,
        "flywheel": "act → audit.jsonl → rft export → ava → brain/graphify → better routes",
        "stages": stages,
        "herdr_boundary": (
            "Herdr keeps PTYs alive across attach/detach. "
            "Scout turns those actions into trusted, learnable orchestration."
        ),
        "next": [
            "scout skill teach --target dottie",
            "scout --json planes status",
            "scout --json herd status",
        ],
    }


def _top(items: list[str], n: int) -> list[dict[str, Any]]:
    from collections import Counter

    c = Counter(items)
    return [{"command": k, "count": v} for k, v in c.most_common(n)]
