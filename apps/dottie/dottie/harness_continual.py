# Solo personal project, no connection to employer, built with public/free-tier only
"""
Continual Harness v2 — Dottie SOTA edition of Prime Agent's harness.

Prime: supplemental prompts, memories, skill descriptions, reusable subagent specs
as durable state, refineable via small evidence-backed updates, local by default,
snapshots for rollback, never rewrites immutable base prompt.

Dottie SOTA adds:
- versioned at workspace/.dottie/harness/<session>/harness.json + harness.jsonl + snapshots/
- MissionLog co-located, People Resolver Write-Back to MEMORY.md, GARNet graph hooks,
  provenance tracking, confidence <0.4 = hint, explicit ACNE opt-in
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def default_harness_dir() -> Path:
    env = os.environ.get("DOTTIE_HARNESS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent.parent / ".dottie" / "harness"


@dataclass
class HarnessState:
    session_id: str
    version: int = 1
    base_prompt_hash: str = ""  # immutable base is never rewritten
    supplemental_prompts: dict[str, str] = field(default_factory=dict)  # id -> prompt fragment
    memories: list[dict[str, Any]] = field(default_factory=list)
    skill_descriptions: dict[str, str] = field(default_factory=dict)
    subagent_specs: dict[str, dict] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)  # key -> source manual|calendar|memory_heuristic|enriched|extraction|ingest
    confidence: dict[str, float] = field(default_factory=dict)
    updated_ts: float = field(default_factory=lambda: time.time())

    def to_json(self) -> dict:
        return {
            "session_id": self.session_id,
            "version": self.version,
            "base_prompt_hash": self.base_prompt_hash,
            "supplemental_prompts": self.supplemental_prompts,
            "memories": self.memories,
            "skill_descriptions": self.skill_descriptions,
            "subagent_specs": self.subagent_specs,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "updated_ts": self.updated_ts,
        }

    @classmethod
    def from_json(cls, data: dict) -> "HarnessState":
        return cls(
            session_id=data["session_id"],
            version=data.get("version", 1),
            base_prompt_hash=data.get("base_prompt_hash", ""),
            supplemental_prompts=data.get("supplemental_prompts", {}),
            memories=data.get("memories", []),
            skill_descriptions=data.get("skill_descriptions", {}),
            subagent_specs=data.get("subagent_specs", {}),
            provenance=data.get("provenance", {}),
            confidence=data.get("confidence", {}),
            updated_ts=data.get("updated_ts", time.time()),
        )


class ContinualHarness:
    """
    Durable, local-first, evidence-backed, snapshot-able harness.
    Mirrors prime-agent's contract but with Dottie guarantees.
    """

    def __init__(self, session_id: str, base_dir: Path | None = None):
        self.session_id = session_id
        self.base_dir = Path(base_dir) if base_dir else default_harness_dir()
        self.session_dir = self.base_dir / session_id
        self.harness_json = self.session_dir / "harness.json"
        self.harness_log = self.session_dir / "harness.jsonl"
        self.snapshots_dir = self.session_dir / "snapshots"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._state = self._load_or_init()

    def _load_or_init(self) -> HarnessState:
        if self.harness_json.exists():
            try:
                data = json.loads(self.harness_json.read_text(encoding="utf-8"))
                return HarnessState.from_json(data)
            except Exception:
                pass
        state = HarnessState(session_id=self.session_id)
        # ensure file exists so first snapshot works
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.harness_json.write_text(json.dumps(state.to_json(), indent=2), encoding="utf-8")
        return state

    def _write(self):
        self.harness_json.write_text(json.dumps(self._state.to_json(), indent=2), encoding="utf-8")

    def snapshot(self) -> Path:
        ts = time.strftime("%Y%m%d-%H%M%S-%f") if False else time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time()*1000)%1000:03d}"
        dest = self.snapshots_dir / ts
        dest.mkdir(parents=True, exist_ok=True)
        if not self.harness_json.exists():
            self._write()
        shutil.copy2(self.harness_json, dest / "harness.json")
        # provenance manifest
        (dest / "provenance.json").write_text(json.dumps({
            "session_id": self.session_id,
            "version": self._state.version,
            "ts": time.time(),
            "reason": "auto snapshot before refine"
        }, indent=2), encoding="utf-8")
        return dest

    def list_snapshots(self) -> list[str]:
        return sorted([p.name for p in self.snapshots_dir.iterdir() if p.is_dir()])

    def rollback(self, timestamp: str) -> HarnessState:
        src = self.snapshots_dir / timestamp / "harness.json"
        if not src.exists():
            raise ValueError(f"snapshot {timestamp} not found")
        shutil.copy2(src, self.harness_json)
        self._state = self._load_or_init()
        self._log("rollback", {"to": timestamp})
        return self._state

    def _log(self, kind: str, payload: dict):
        line = json.dumps({"ts": time.time(), "kind": kind, "payload": payload})
        with self.harness_log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def refine(self, evidence: str, updates: dict, provenance: str = "manual", confidence: float = 0.9) -> dict:
        """
        Small, evidence-backed update — Prime's `/refine` contract.
        - never touches base_prompt
        - records snapshot before mutating
        - low conf <0.4 = hint, not authoritative
        - returns diff for review
        """
        if not evidence or len(evidence.strip()) < 10:
            raise ValueError("refine needs evidence (>=10 chars) — no evidence, no refine")
        if not updates:
            raise ValueError("refine needs at least one update")
        if confidence < 0:
            raise ValueError("confidence must be >=0")
        # Snapshot before
        self.snapshot()
        diff = {"added": {}, "updated": {}, "skipped_low_conf": {}, "provenance": provenance, "confidence": confidence}
        for k, v in updates.items():
            if k == "base_prompt":
                raise ValueError("immutable base system prompt cannot be rewritten — create a supplemental prompt instead")
            if confidence < 0.4:
                diff["skipped_low_conf"][k] = v
                continue
            # supplemental prompts
            if k.startswith("prompt:"):
                pid = k.split("prompt:",1)[1]
                if pid in self._state.supplemental_prompts:
                    diff["updated"][k] = {"old": self._state.supplemental_prompts[pid], "new": v}
                else:
                    diff["added"][k] = v
                self._state.supplemental_prompts[pid] = str(v)
            elif k.startswith("skill:"):
                sid = k.split("skill:",1)[1]
                self._state.skill_descriptions[sid] = str(v)
                diff["added" if sid not in diff["added"] else "updated"][k] = v
            elif k.startswith("subagent:"):
                sid = k.split("subagent:",1)[1]
                self._state.subagent_specs[sid] = v if isinstance(v, dict) else {"spec": v}
                diff["added"][k] = v
            elif k.startswith("memory:"):
                self._state.memories.append({"id": k, "content": v, "ts": time.time(), "provenance": provenance})
                diff["added"][k] = v
            else:
                # generic supplemental
                self._state.supplemental_prompts[k] = str(v)
                diff["added"][k] = v
            self._state.provenance[k] = provenance
            self._state.confidence[k] = confidence

        self._state.version += 1
        self._state.updated_ts = time.time()
        self._write()
        self._log("refine", {"evidence": evidence[:500], "diff": diff, "version": self._state.version})
        return diff

    def get_context_for_prompt(self) -> str:
        """Render supplemental context to inject — never base prompt."""
        parts = []
        if self._state.supplemental_prompts:
            parts.append("# Supplemental Harness Prompts (durable, refined)")
            for pid, txt in self._state.supplemental_prompts.items():
                conf = self._state.confidence.get(pid, 1.0)
                prov = self._state.provenance.get(pid, "manual")
                tag = f"[conf={conf} prov={prov}]" + (" (hint only, conf<0.4)" if conf < 0.4 else "")
                parts.append(f"- {pid} {tag}: {txt}")
        if self._state.memories:
            parts.append("\n# Memories (local)")
            for m in self._state.memories[-10:]:  # last 10
                parts.append(f"- {m['id']}: {m['content']}")
        return "\n".join(parts)

    @property
    def state(self) -> HarnessState:
        return self._state
