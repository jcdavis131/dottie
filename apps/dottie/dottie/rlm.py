# Solo personal project, no connection to employer, built with public/free-tier only
"""
Dottie RLM v2 — SOTA edition of Prime Agent's Recursive Language Model.

Prime's insight: treat context as variables (prompt-as-variable) and tools
like recursive subagents as function calls inside a persistent REPL.

Dottie SOTA adds:
- MissionLog at workspace/.scout/missions/<id>/timeline.jsonl (pause Monday resume Thursday)
- StuckDetector → ONE lateral lens (SCAMPER/SixHats/Inversion/Provocation/Random/Analogy)
- Verifier with budget that ships (score 1-10, fix once if <8, max 2)
- Typed harness integration, provenance tracking

Usage inside Dottie REPL:
    query = "compare stripe vs lemonsqueezy aug 2026"
    results = rlm("research that", sources=[...], model_tier="deep_research")
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable


def default_missions_dir() -> Path:
    env = os.environ.get("DOTTIE_MISSIONS_DIR") or os.environ.get("SCOUT_MISSIONS_DIR")
    if env:
        return Path(env)
    # Scout v5 Prime contract: workspace/.scout/missions/<id>/timeline.jsonl
    return Path(__file__).resolve().parent.parent.parent.parent / ".scout" / "missions"


@dataclass
class MissionEvent:
    ts: float
    type: str  # turn | tool_call | subagent_spawn | subagent_result | refine | verifier | heartbeat
    agent_id: str
    node_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: str = "manual"  # manual|memory_heuristic|enriched|extraction|ingest|tool

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self))


class MissionLog:
    """Pause/Resume durable log — Scout v5 Prime contract."""

    def __init__(self, mission_id: str | Path | None = None, base_dir: Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else default_missions_dir()
        if mission_id and "/" in str(mission_id):
            # allow passing full path
            self.mission_dir = Path(mission_id)
            self.mission_id = self.mission_dir.name
        else:
            self.mission_id = mission_id or uuid.uuid4().hex[:10]
            self.mission_dir = self.base_dir / self.mission_id
        self.timeline_path = self.mission_dir / "timeline.jsonl"
        self.mission_dir.mkdir(parents=True, exist_ok=True)
        if not self.timeline_path.exists():
            self.timeline_path.write_text("", encoding="utf-8")

    def append(self, event: MissionEvent) -> None:
        with self.timeline_path.open("a", encoding="utf-8") as f:
            f.write(event.to_jsonl() + "\n")

    def iter_events(self):
        if not self.timeline_path.exists():
            return
        with self.timeline_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def count(self) -> int:
        return sum(1 for _ in self.iter_events())


@dataclass
class RLMSubagentSpec:
    prompt: str
    model_tier: str = "llm_medium"  # deterministic cheap / llm_medium / deep_research heavy 9K / action_operator / agentic_epic
    sources: list[str] = field(default_factory=list)
    require: list[str] = field(default_factory=list)
    parent_mission_id: str | None = None
    subagent_id: str = field(default_factory=lambda: f"rlm-{uuid.uuid4().hex[:6]}")


class StuckDetector:
    """
    Scout v5 Prime Stuck Detector — same query 2x / 2 fails / 0 hits / conf<0.4 / 'hmm'
    → ONE lateral lens showing abandoned.
    """

    def __init__(self):
        self.recent_queries: list[str] = []
        self.fail_count = 0
        self.zero_hit_count = 0

    def observe_query(self, q: str) -> bool:
        self.recent_queries.append(q.lower().strip())
        if len(self.recent_queries) > 5:
            self.recent_queries.pop(0)
        # 2x same
        if len(self.recent_queries) >= 2 and self.recent_queries[-1] == self.recent_queries[-2]:
            return True
        return False

    def observe_fail(self) -> bool:
        self.fail_count += 1
        return self.fail_count >= 2

    def observe_zero_hits(self) -> bool:
        self.zero_hit_count += 1
        return self.zero_hit_count >= 1

    def observe_conf(self, conf: float) -> bool:
        return conf < 0.4

    def should_trigger_lens(self, query_same=False, fail=False, zero=False, low_conf=False) -> bool:
        return any([query_same, fail, zero, low_conf])


# Lateral lenses on-demand — from bundles/skills/lateral/README.md
LATERAL_LENSES = {
    "scamper": "Substitute/Combine/Adapt/Modify/Put to other use/Eliminate/Reverse",
    "six_hats": "White facts / Red gut / Black caution / Yellow benefits / Green creativity / Blue process",
    "inversion": "Invert the goal; what guarantees failure? Do opposite.",
    "provocation": "Introduce a deliberate falsehood PO -> see what breaks",
    "random_entry": "Pick random unrelated domain and force analogy",
    "analogy": "Map structure from adjacent domain (biology, economics, etc.)",
    "concept_fan": "Fan out: purpose -> broader concepts -> alternative implementations",
    "worst_idea": "Intentionally worst idea → invert to good",
}


def pick_lateral_lens(trigger_reason: str) -> tuple[str, str]:
    # simple deterministic pick for reproducibility
    mapping = {
        "same_query": "inversion",
        "fail": "scamper",
        "zero_hits": "analogy",
        "low_conf": "concept_fan",
        "hmm": "six_hats",
    }
    name = mapping.get(trigger_reason, "scamper")
    return name, LATERAL_LENSES[name]


class VerifierWithBudget:
    """
    Verifier That Ships — score 1-10, fix biggest gap once if <8, max 2 loops.
    From Scout v5 Prime.
    """

    def __init__(self, threshold: float = 8.0, max_loops: int = 2):
        self.threshold = threshold
        self.max_loops = max_loops
        self.loops = 0

    def score(self, result: Any, rubric: dict | None = None) -> dict:
        # Simple heuristic scorer; real impl would call LLM critic.
        # Dottie provenance-honest: this is heuristic unless LLM provides score.
        score = 7.5  # baseline honest: needs improvement
        issues: list[str] = []
        if isinstance(result, dict):
            if not result.get("sources"):
                issues.append("missing sources")
                score -= 1.0
            if not result.get("evidence"):
                issues.append("no evidence-backed claims")
                score -= 0.5
        if isinstance(result, str) and len(result) < 30:
            issues.append("shallow output")
            score -= 1.5
        score = max(1.0, min(10.0, score))
        return {"score": round(score,1), "issues": issues, "pass": score >= self.threshold}

    def should_fix(self, score_report: dict) -> bool:
        return not score_report["pass"] and self.loops < self.max_loops

    def fix_once(self, result: Any, score_report: dict, fix_fn: Callable[[Any, list[str]], Any] | None = None) -> Any:
        self.loops += 1
        if fix_fn:
            return fix_fn(result, score_report["issues"])
        # default: annotate biggest gap
        if isinstance(result, dict):
            result["_fix_attempt"] = self.loops
            result["_gap"] = score_report["issues"][0] if score_report["issues"] else "general"
            return result
        return f"{result}\n\n[FIX attempt {self.loops} addressing: {', '.join(score_report['issues'])}]"


# REPL factory — now with llmvm helpers wired in (9600dev/llmvm)

def make_rlm_environment(mission: MissionLog | None = None, policy=None) -> dict[str, Any]:
    """
    Build the vars available inside the persistent IPython REPL.
    `rlm` spawns subagents programmatically (Prime's core pattern).

    Now also exposes llmvm helpers (llm_call, llm_list_bind, llm_bind, guard, result)
    so recipes can interleave NL + code like llmvm does.
    """

    def rlm(prompt: str, model_tier="llm_medium", sources=None, require=None, background=False) -> dict:
        spec = RLMSubagentSpec(
            prompt=prompt,
            model_tier=model_tier,
            sources=sources or [],
            require=require or [],
            parent_mission_id=mission.mission_id if mission else None,
        )
        event = MissionEvent(
            ts=time.time(),
            type="subagent_spawn",
            agent_id=spec.subagent_id,
            payload={"prompt": prompt, "tier": model_tier, "require": require, "sources": sources, "background": background},
        )
        if mission:
            mission.append(event)
        # In production this would dispatch to scout-prime/researcher; here we return a structured intent
        # so the calling REPL can await it or continue.
        return {
            "subagent_id": spec.subagent_id,
            "status": "spawned",
            "prompt": prompt,
            "tier": model_tier,
            "mission_id": spec.parent_mission_id,
            "note": "Dottie SOTA: this would dispatch to scout-prime->researcher->builder pipeline with checkpoint per node",
        }

    def refine_harness(evidence: str, small_update: dict):
        if mission:
            mission.append(MissionEvent(ts=time.time(), type="refine", agent_id="repl", payload={"evidence": evidence, "update": small_update}))
        return {"refined": True, "evidence_len": len(evidence)}

    env = {
        "rlm": rlm,
        "mission": mission,
        "MissionLog": MissionLog,
        "StuckDetector": StuckDetector,
        "VerifierWithBudget": VerifierWithBudget,
        "pick_lateral_lens": pick_lateral_lens,
        "refine_harness": refine_harness,
    }

    # llmvm integration — optional but auto-wired if policy available
    try:
        from dottie.llmvm import make_llmvm_environment
        llmvm_env = make_llmvm_environment(mission=mission, policy=policy)
        # merge, rlm stays canonical
        for k, v in llmvm_env.items():
            if k not in env:
                env[k] = v
        # keep llmvm composite too
        env["llmvm_env"] = llmvm_env
    except Exception:
        # graceful degrade — Dottie works standalone
        pass

    return env

