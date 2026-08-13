# Solo personal project, no connection to employer, built with public/free-tier only
"""
Dottie Background Orchestrator — autonomous llmvm + RLM loops for long projects.

Goal: run LLMVMRuntime loops for long projects autonomously, reading GOAL.md files,
spawning rlm/llmvm continuations, writing mission logs with 7-field timeline entry
even no-change per Scout v5 Prime.

Zero_deps: pure python stdlib + dottie.policy + dottie.rlm + dottie.llmvm

Pipeline:
  - scan_goals(root=~/workspace/goals) : find */GOAL.md or GOAL.md style
  - For each goal, create/get MissionLog at workspace/.scout/missions/<goal_slug>-<date>
  - Run LLMVMRuntime.run(query from goal) in background continuation
  - Write timeline.jsonl with mandatory 7 fields: nodeId, agentId, attempt, latency_ms, tokens_est, status, errorClass
  - Supports pause/resume days later via resume_mission_log + saved locals snapshot
  - Triple-write checkpoint: mirrors same entry to:
      1) workspace/.scout/missions/<id>/timeline.jsonl
      2) workspace/goals/<slug>/hidden_files/cron_health.jsonl (light)
      3) workspace/.scout/missions/_cron/timeline.jsonl aggregate

Usage autonomous:
    from dottie.background_orchestrator import BackgroundOrchestrator
    orch = BackgroundOrchestrator()
    results = orch.sweep_all_goals(max_goals=3, max_continuations=6)

Daemon mode (if called via cron):
    orch = BackgroundOrchestrator.from_env()
    orch.run_once(log_even_no_change=True)

Feeds goal_ec4f28c2bfbf (refine Dottie) — logs to:
  - dottie/apps/dottie/data/traces/
  - goals/refine-dottie-*/hidden_files/
  - .scout/missions/_cron/timeline.jsonl
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

def _default_workspace() -> Path:
    return Path.home() / "workspace"

def _default_missions_dir() -> Path:
    env = os.environ.get("DOTTIE_MISSIONS_DIR") or os.environ.get("SCOUT_MISSIONS_DIR")
    if env:
        return Path(env)
    return _default_workspace() / ".scout" / "missions"

def _default_goals_dir() -> Path:
    return _default_workspace() / "goals"

# ---------------------------------------------------------------------------
# 7-field checkpoint writer (even no-change)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _make_7field(
    nodeId: str,
    agentId: str,
    attempt: int = 1,
    latency_ms: int = 0,
    tokens_est: int = 0,
    status: str = "ok",
    errorClass: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base = {
        "ts": _now_iso(),
        "nodeId": nodeId,
        "agentId": agentId,
        "attempt": attempt,
        "latency_ms": latency_ms,
        "tokens_est": tokens_est,
        "status": status,
        "errorClass": errorClass,
    }
    if extra:
        base.update(extra)
    return base

def _triple_write_timeline(
    mission_dir: Path,
    entry: Dict[str, Any],
    goal_hidden_dir: Optional[Path] = None,
):
    """
    Triple-write per checkpoint-manager spec:
      1) mission_dir/timeline.jsonl
      2) goals/<slug>/hidden_files/cron_health.jsonl (or goals-aggregate)
      3) .scout/missions/_cron/timeline.jsonl (operator aggregate)
    Always logs even no-change.
    """
    mission_dir.mkdir(parents=True, exist_ok=True)
    timeline = mission_dir / "timeline.jsonl"
    try:
        with timeline.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

    # aggregate cron
    try:
        agg_dir = _default_missions_dir() / "_cron"
        agg_dir.mkdir(parents=True, exist_ok=True)
        agg_file = agg_dir / "timeline.jsonl"
        with agg_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**entry, "mission_dir": str(mission_dir)}) + "\n")
    except Exception:
        pass

    # goal hidden mirror if provided
    if goal_hidden_dir:
        try:
            goal_hidden_dir.mkdir(parents=True, exist_ok=True)
            hf = goal_hidden_dir / "cron_health.jsonl"
            with hf.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Goal scanning
# ---------------------------------------------------------------------------

def _is_goal_dir(p: Path) -> bool:
    if not p.is_dir():
        return False
    # Common patterns: GOAL.md, goal.md, or files/GOAL.md exists
    if (p / "GOAL.md").exists() or (p / "goal.md").exists():
        return True
    # some repos store under files/
    if (p / "files" / "GOAL.md").exists():
        return True
    return False

def scan_goals(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    root = root or _default_goals_dir()
    if not root.exists():
        return []
    goals = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        # Skip hidden or archives
        if child.name.startswith(".") or child.name.startswith("_"):
            continue
        goal_path = None
        content = ""
        if (child / "GOAL.md").exists():
            goal_path = child / "GOAL.md"
        elif (child / "goal.md").exists():
            goal_path = child / "goal.md"
        elif (child / "files" / "GOAL.md").exists():
            goal_path = child / "files" / "GOAL.md"

        if goal_path:
            try:
                content = goal_path.read_text(encoding="utf-8", errors="ignore")[:6000]
            except Exception:
                content = ""
            goals.append({
                "slug": child.name,
                "dir": str(child),
                "goal_path": str(goal_path),
                "title": content.splitlines()[0][:200] if content else child.name,
                "content": content,
            })
    return goals

# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

class BackgroundOrchestrator:
    """
    Background orchestrator for Dottie llmvm long projects.

    Reads workspace/goals/*/GOAL.md, spawns llmvm continuations,
    writes mission logs with 7-field entries, supports pause/resume.
    """

    def __init__(
        self,
        goals_dir: Optional[Path] = None,
        missions_dir: Optional[Path] = None,
        policy_backend: Optional[str] = None,
    ):
        self.goals_dir = Path(goals_dir) if goals_dir else _default_goals_dir()
        self.missions_dir = Path(missions_dir) if missions_dir else _default_missions_dir()
        self.policy_backend = policy_backend or os.environ.get("DOTTIE_POLICY", "ollama")
        self.missions_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "BackgroundOrchestrator":
        return cls()

    # -- mission log resume helpers -----------------------------------------
    def resume_mission(self, mission_id: str) -> Any:
        """Resume mission log days later — delegated to llmvm resume helper."""
        try:
            from dottie.llmvm import resume_mission_log
            mission, events = resume_mission_log(mission_id, base_dir=self.missions_dir)
            return mission, events
        except Exception:
            # Fallback: try rlm MissionLog
            try:
                from dottie.rlm import MissionLog
                m = MissionLog(mission_id=mission_id, base_dir=self.missions_dir)
                evs = list(m.iter_events())
                return m, evs
            except Exception as e:
                return None, [f"resume failed {e}"]

    def _get_policy(self):
        try:
            from dottie.policy import get_policy
            p = get_policy(self.policy_backend)
            return p
        except Exception as e:
            # Echo fallback for CI
            def echo_pol(transcript: str) -> str:
                return (
                    "<helpers>\n"
                    "result('echo fallback: ' + str(globals().get('query',''))) \n"
                    "</helpers>"
                )
            echo_pol.__name__ = "EchoPolicyFallback"
            return echo_pol

    def run_one_goal(
        self,
        goal: Dict[str, Any],
        max_continuations: int = 6,
        log_even_no_change: bool = True,
    ) -> Dict[str, Any]:
        """
        Run one goal through llmvm + rlm, write checkpoints.

        Returns result dict with mission_id, status, llmvm result if any.
        """
        slug = goal["slug"]
        content = goal.get("content","")[:4000]
        goal_dir = Path(goal["dir"])
        hidden_dir = goal_dir / "hidden_files"

        mission_id = f"dottie-{slug}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        t0 = time.monotonic()

        # 1) Try to resume if timeline exists
        existing_events = []
        try:
            from dottie.llmvm import latest_mission_state
            state = latest_mission_state(mission_id, base_dir=self.missions_dir)
            if state["event_count"] > 0:
                existing_events = [state]
        except Exception:
            pass

        # 2) MissionLog creation (or resume)
        try:
            from dottie.rlm import MissionLog, MissionEvent
            mission = MissionLog(mission_id=mission_id, base_dir=self.missions_dir)
        except Exception:
            # Fallback dir structure even without MissionLog
            mission = None

        # 3) Prompt composition from GOAL.md
        prompt = (
            f"You are Dottie background worker continuing long project.\n"
            f"Goal slug: {slug}\n"
            f"Goal doc:\n{content[:3500]}\n\n"
            f"Existing history events: {len(existing_events)} — {'resumed' if existing_events else 'new spawn'}\n\n"
            f"Task: break this goal into next concrete milestone, then attempt it using helpers.\n"
            f"Use <helpers> blocks: llm_call, llm_list_bind, guard, scout() forge plugins.\n"
            f"Forge plugins now discoverable via list_forge_plugins().\n"
            f"When milestone achieved, call result(milestone_summary). End with FINAL.\n"
        )

        policy = self._get_policy()

        entry_pre = _make_7field(
            nodeId=f"background-{slug}",
            agentId="background-orchestrator",
            attempt=1,
            latency_ms=int((time.monotonic()-t0)*1000),
            tokens_est=len(prompt)//4,
            status="running",
            errorClass=None,
            extra={
                "ts_cdt": datetime.now().isoformat(),
                "mission_id": mission_id,
                "goal_slug": slug,
                "phase": "spawn",
                "event_count_prior": len(existing_events),
                "policy_backend": self.policy_backend,
                "max_continuations": max_continuations,
            }
        )
        _triple_write_timeline(self.missions_dir / mission_id, entry_pre, hidden_dir)

        # 4) llmvm execution
        llmvm_result: Dict[str, Any] = {}
        status = "ok"
        error_class = None
        try:
            from dottie.llmvm import LLMVMRuntime
            rt = LLMVMRuntime(policy=policy, mission=mission)
            t_llmvm = time.monotonic()
            llmvm_result = rt.run(prompt, max_continuations=max_continuations)
            latency = int((time.monotonic()-t_llmvm)*1000)
            entry_llmvm = _make_7field(
                nodeId=f"llmvm-{slug}",
                agentId="llmvm-rt",
                attempt=1,
                latency_ms=latency,
                tokens_est=sum(len(str(x))//4 for x in llmvm_result.get("turns",[])[:3]),
                status="ok" if llmvm_result.get("final") else "no-final",
                errorClass=None,
                extra={
                    "mission_id": mission_id,
                    "goal_slug": slug,
                    "final_present": bool(llmvm_result.get("final")),
                    "n_steps": llmvm_result.get("n_steps",0),
                    "answers": len(llmvm_result.get("answers",[])),
                    "forge_plugins": llmvm_result.get("forge_plugins_discovered",0),
                    "chunks_used": llmvm_result.get("chunks_used",[]),
                }
            )
            _triple_write_timeline(self.missions_dir / mission_id, entry_llmvm, hidden_dir)
        except Exception as e:
            status = "failed"
            error_class = type(e).__name__
            latency = int((time.monotonic()-t0)*1000)
            entry_fail = _make_7field(
                nodeId=f"llmvm-{slug}",
                agentId="background-orchestrator",
                attempt=1,
                latency_ms=latency,
                tokens_est=0,
                status="failed",
                errorClass=error_class,
                extra={"mission_id": mission_id, "goal_slug": slug, "error": str(e)[:800]}
            )
            _triple_write_timeline(self.missions_dir / mission_id, entry_fail, hidden_dir)
            llmvm_result = {"error": str(e), "final": None}

        # 5) Ensure even when no-change we logged
        if log_even_no_change:
            t_total = int((time.monotonic()-t0)*1000)
            entry_post = _make_7field(
                nodeId=f"orchestrator-tick",
                agentId="background-orchestrator",
                attempt=1,
                latency_ms=t_total,
                tokens_est=llmvm_result.get("n_steps",0)*400,
                status=status,
                errorClass=error_class,
                extra={
                    "mission_id": mission_id,
                    "goal_slug": slug,
                    "total_ms": t_total,
                    "final_len": len(str(llmvm_result.get("final",""))),
                    "no_change": status=="ok" and not llmvm_result.get("final"),
                    "log_even_no_change": True,
                }
            )
            _triple_write_timeline(self.missions_dir / mission_id, entry_post, hidden_dir)

        # 6) Persist resume snapshot to hidden_files for quick resume
        try:
            hidden_dir.mkdir(parents=True, exist_ok=True)
            snap_path = hidden_dir / f"llmvm_resume_{slug}.json"
            snap = {
                "mission_id": mission_id,
                "slug": slug,
                "ts": _now_iso(),
                "mission_dir": str(self.missions_dir / mission_id),
                "timeline_exists": (self.missions_dir / mission_id / "timeline.jsonl").exists(),
                "event_count": 0,
                "final": str(llmvm_result.get("final",""))[:1200] if llmvm_result.get("final") else None,
                "answers": llmvm_result.get("answers",[])[:2],
            }
            try:
                from dottie.rlm import MissionLog
                m = MissionLog(mission_id=mission_id, base_dir=self.missions_dir)
                snap["event_count"] = m.count()
            except Exception:
                pass
            snap_path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        except Exception:
            pass

        return {
            "slug": slug,
            "mission_id": mission_id,
            "mission_dir": str(self.missions_dir / mission_id),
            "status": status,
            "errorClass": error_class,
            "final_present": bool(llmvm_result.get("final")),
            "llmvm": llmvm_result,
            "no_change": status=="ok" and not llmvm_result.get("final"),
        }

    def sweep_all_goals(
        self,
        max_goals: int = 5,
        max_continuations: int = 6,
        shuffle: bool = True,
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        goals = scan_goals(self.goals_dir)
        if shuffle:
            # Prioritize newest modified mtime, but still shuffle a bit for fairness
            try:
                goals.sort(key=lambda g: os.path.getmtime(g["goal_path"]), reverse=True)
            except Exception:
                pass
            if len(goals) > max_goals:
                # Take top half by mtime + random sample remainder
                top_n = max_goals // 2
                head = goals[:top_n]
                rest = goals[top_n:]
                random.shuffle(rest)
                goals = head + rest[:max_goals-top_n]
                goals = goals[:max_goals]
            else:
                if shuffle and len(goals) > 1:
                    # Keep mtime-sorted but still allow a little jitter
                    pass

        goals = goals[:max_goals]

        results = []
        for g in goals:
            try:
                r = self.run_one_goal(g, max_continuations=max_continuations)
                results.append(r)
            except Exception as e:
                results.append({"slug": g["slug"], "status": "orch-failed", "error": str(e)[:500]})

        # Aggregate checkpoint even if 0 goals (no-change guarantee)
        agg_entry = _make_7field(
            nodeId="background-sweep",
            agentId="background-orchestrator",
            attempt=1,
            latency_ms=int((time.monotonic()-t0)*1000),
            tokens_est=sum(r.get("llmvm", {}).get("n_steps", 0) * 200 for r in results),
            status="ok" if results else "no-goals",
            errorClass=None,
            extra={
                "goals_scanned": len(goals),
                "goals_run": len(results),
                "goals_ok": sum(1 for r in results if r.get("status")=="ok"),
                "ts_cdt": datetime.now().isoformat(),
                "hidden_files_dir": "workspace/goals/*/hidden_files",
            }
        )
        # Write to _cron aggregate explicitly
        try:
            agg_dir = self.missions_dir / "_cron"
            agg_dir.mkdir(parents=True, exist_ok=True)
            with (agg_dir / "timeline.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(agg_entry) + "\n")
        except Exception:
            pass

        return {
            "goals_scanned": len(goals),
            "results": results,
            "aggregate": agg_entry,
            "missions_dir": str(self.missions_dir),
        }

    # -- daemon entrypoints -----------------------------------------------
    def run_once(self, log_even_no_change: bool = True) -> Dict[str, Any]:
        return self.sweep_all_goals(max_goals=3, max_continuations=4)

    @staticmethod
    def ensure_cron_entry(cron_dir: str = "~/workspace/bundles/cron.d") -> str:
        """
        Ensure a cron.d JSON exists for always-on background orchestrator.
        Returns path created.
        """
        cron_path = Path(cron_dir).expanduser()
        cron_path.mkdir(parents=True, exist_ok=True)
        json_path = cron_path / "background_llmvm_orchestrator.json"
        content = {
            "id": "background_llmvm_orchestrator",
            "enabled": True,
            "owner": "goal:goal_ec4f28c2bfbf",
            "schedule": {"kind": "interval", "seconds": 300},
            "description": "Dottie background llmvm orchestrator — scans goals/*/GOAL.md, runs llmvm continuations, triple-checkpoint 7-field even no-change",
            "command": "python3 -c \"from dottie.background_orchestrator import BackgroundOrchestrator; BackgroundOrchestrator().run_once()\"",
            "env": {"PYTHONPATH": "dottie/apps/dottie"},
            "logging": {"required_fields": ["nodeId","agentId","attempt","latency_ms","tokens_est","status","errorClass"]},
            "version": "1.0.0",
            "tags": ["always-on","operator","dottie","llmvm","background"],
        }
        json_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        return str(json_path)


# ---------------------------------------------------------------------------
# CLI quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    orch = BackgroundOrchestrator.from_env()
    out = orch.run_once()
    print(json.dumps(out, indent=2)[:4000])

