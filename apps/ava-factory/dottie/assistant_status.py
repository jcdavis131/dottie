"""Capability + telemetry snapshot for the Dottie assistant (spec 15 §5.1).

Served read-only at ``GET /assistant/status`` and published to
``reports/assistant_status.json`` for the arxiviq.com surface to poll via the
same GitHub-raw pipeline the Dottie control plane already uses. Deliberately
exception-swallowing per sub-collector — like every other status collector in
this repo, it must never 500 (the compose healthcheck curls a sibling route).

The published document is the honest "what can this assistant do, and under what
boundaries" contract: the tool catalog, the trust policy (capability-gated,
sandboxed, auth on/off), a rollup of recent telemetry, the curriculum status,
and an **authentic demo transcript** produced by actually running the loop
against the real tools (not hand-authored), so the demo mode on arxiviq shows
real grounding + a real trust denial.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parent.parent


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _trust_summary() -> dict[str, Any]:
    from dottie.trust import default_registry
    reg = default_registry(_REPO)
    caps = list(reg.tools.values())
    return {
        "enforcement": "capability-gated (checked before dispatch)",
        "read_only_tools": sum(1 for c in caps if c.read_only),
        "sandboxed_tools": sum(1 for c in caps if c.sandbox_root is not None),
        "total_tools": len(caps),
        "auth": "on" if os.environ.get("AVA_ASSISTANT_TOKEN") else "off",
        "cors": [o.strip() for o in os.environ.get("AVA_ASSISTANT_CORS", "").split(",") if o.strip()],
        "sandbox_root": str(_REPO),
    }


def _tools() -> list[dict[str, str]]:
    from dottie.trust import default_registry
    return default_registry(_REPO).catalog()


def _telemetry() -> dict[str, Any]:
    from dottie.trust import tail_events
    events = tail_events(60)
    counts: dict[str, int] = {}
    for e in events:
        counts[e.get("action", "?")] = counts.get(e.get("action", "?"), 0) + 1
    return {"recent": events[-12:], "counts": counts, "total_seen": len(events)}


def _engine() -> dict[str, Any]:
    if os.environ.get("AVA_SKIP_ENGINE_BOOT", "0") == "1":
        return {"available": False, "reason": "AVA_SKIP_ENGINE_BOOT=1 (trainer owns the GPU)"}
    try:
        from dottie.serve_engine import get_engine
        st = get_engine().stats()
        return {"available": True, "ckpt": st.get("ckpt"), "params": st.get("params"),
                "vocab": st.get("vocab")}
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}"}


def _curriculum() -> dict[str, Any]:
    return {
        "generator": "tool_use",
        "status": "wired, dormant (weight 0) — flip on at a phase boundary",
        "levels": [
            {"id": "L0", "name": "grounded single", "teaches": "answer from the Observation"},
            {"id": "L1", "name": "multi-step chain", "teaches": "later args from earlier Observations"},
            {"id": "L2", "name": "error & recovery", "teaches": "bad-arg/timeout/empty -> retry or honest give-up"},
            {"id": "L3", "name": "tool selection", "teaches": "pick the right tool from a catalog of many"},
            {"id": "L4", "name": "negative / refuse", "teaches": "answer directly, or refuse a destructive tool"},
            {"id": "L5", "name": "program / parallel", "teaches": "single-shot tool Program: parallel fan-out then reduce (LLM-VM; pairs with think-in-code)"},
        ],
        "format": "plain-text ReAct (frozen-tokenizer-safe), parser-compatible with AgenticOS/ava_bridge.py",
    }


def _demo_transcript() -> dict[str, Any]:
    """Run the real loop against the real tools with a scripted model so the
    published demo is authentic: a grounded arithmetic call, then a refused
    destructive call."""
    from dottie.assistant import run_assistant

    def _script(*responses):
        calls = {"i": 0}

        def _fn(prompt, max_tokens, temperature):
            i = calls["i"]
            calls["i"] += 1
            return responses[min(i, len(responses) - 1)]
        return _fn

    # Route the demo's telemetry to the null device on every platform so polling
    # /assistant/status never pollutes the real audit ledger with demo events.
    # (os.devnull is "nul" on Windows, "/dev/null" on POSIX — both open cleanly.)
    _null = Path(os.devnull)
    grounded = run_assistant(
        [{"role": "user", "content": "What is 19 + 23? Use the calculator."}],
        _script("Thought: I'll use the calculator.\nAction: add(a=19, b=23)", "19 + 23 = 42."),
        sandbox_root=_REPO, audit_path=_null,
    )
    refused = run_assistant(
        [{"role": "user", "content": "Delete all the log files to free space."}],
        _script('Thought: delete_file is destructive.\nAction: delete_file(path="/logs")',
                "I won't run delete_file — it removes data irreversibly and isn't something I "
                "should do autonomously. Confirm explicitly and I'll show the exact call first."),
        sandbox_root=_REPO, audit_path=_null,
    )
    return {
        "grounded": {"prompt": "What is 19 + 23? Use the calculator.", **grounded.as_dict()},
        "refused": {"prompt": "Delete all the log files to free space.", **refused.as_dict()},
    }


def collect_assistant_status() -> dict[str, Any]:
    """Best-effort snapshot; never raises."""
    return {
        "surface": "ava.assistant",
        "persona": "Dottie",
        "generated_at": _utc_now_iso(),
        "engine": _safe(_engine, {"available": False, "reason": "collector error"}),
        "trust": _safe(_trust_summary, {}),
        "tools": _safe(_tools, []),
        "telemetry": _safe(_telemetry, {"recent": [], "counts": {}}),
        "curriculum": _safe(_curriculum, {}),
        "demo": _safe(_demo_transcript, {}),
        "spec": "specs/15_scout_herdr_dottie_tooluse.md",
    }


def publish_assistant_status(out_path: Optional[Path] = None) -> Path:
    """Write the snapshot to ``reports/assistant_status.json`` (or out_path) for
    the arxiviq.com surface to poll. Returns the path written.

    Also best-effort emits a ``source='assistant'`` event into the factory's
    unified telemetry (``dottie/telemetry.py``) when that package is importable
    — i.e. when this runs from the ava-agi-factory-v6-4 checkout whose daemon
    already commits ``reports/`` and pushes to the ``main`` branch arxiviq
    reads. In this feature-branch checkout ``dottie`` is absent, so it no-ops.
    """
    import json
    reports = Path(os.environ.get("AVA_REPORTS_DIR", str(_REPO / "reports")))
    path = out_path or (reports / "assistant_status.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    status = collect_assistant_status()
    path.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    _emit_factory_telemetry(status)
    return path


def _emit_factory_telemetry(status: dict[str, Any]) -> None:
    """Soft integration with the factory's dottie/telemetry.py so 'assistant'
    appears under latest_per_mode/by_mode_counts in dottie_live_status.json with
    zero schema change. Never raises; no-ops when dottie isn't installed."""
    try:
        from dottie.telemetry import log_event  # type: ignore
    except Exception:
        return
    trust = status.get("trust", {})
    tel = status.get("telemetry", {})
    try:
        log_event(
            source="assistant",
            event_type="status",
            message=f"Dottie assistant: {trust.get('total_tools', 0)} tools, "
                    f"{trust.get('sandboxed_tools', 0)} sandboxed, auth {trust.get('auth', 'off')}",
            metrics={
                "total_tools": trust.get("total_tools", 0),
                "read_only_tools": trust.get("read_only_tools", 0),
                "sandboxed_tools": trust.get("sandboxed_tools", 0),
                "telemetry_events": tel.get("total_seen", 0),
                "engine_available": bool(status.get("engine", {}).get("available")),
            },
            level="info",
        )
    except Exception:
        pass


if __name__ == "__main__":
    p = publish_assistant_status()
    print(f"wrote {p}")
