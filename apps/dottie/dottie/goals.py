# Solo personal project, no connection to employer, built with public/free-tier only
"""
Persistent Goals — prime's /goal that keeps objective active across turns
until completed/paused/cleared, plus Dottie's measured climb tie-in.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


def default_goals_path() -> Path:
    env = os.environ.get("DOTTIE_GOALS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent.parent / ".dottie" / "goals.jsonl"


@dataclass
class GoalRecord:
    goal_id: str
    objective: str
    status: str  # active | paused | completed | cleared
    progress: str
    created_ts: float
    updated_ts: float
    mission_id: str | None = None
    provenance: str = "manual"

    def to_jsonl(self): return json.dumps(asdict(self))


class GoalStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_goals_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def set(self, objective: str, mission_id: str | None = None, goal_id: str | None = None) -> GoalRecord:
        rec = GoalRecord(
            goal_id=goal_id or uuid.uuid4().hex[:8],
            objective=objective,
            status="active",
            progress="init",
            created_ts=time.time(),
            updated_ts=time.time(),
            mission_id=mission_id,
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(rec.to_jsonl() + "\n")
        return rec

    def update_progress(self, goal_id: str, progress: str, status: str | None = None) -> dict | None:
        # append new version; last wins
        records = list(self.iter_all())
        target = None
        for r in records:
            if r["goal_id"] == goal_id:
                target = r
        if not target:
            return None
        new = dict(target)
        new["progress"] = progress
        new["updated_ts"] = time.time()
        if status:
            new["status"] = status
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(new) + "\n")
        return new

    def iter_all(self):
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue

    def active(self) -> list[dict]:
        latest: dict[str, dict] = {}
        for r in self.iter_all():
            latest[r["goal_id"]] = r
        return [v for v in latest.values() if v["status"] == "active"]

    def clear(self, goal_id: str):
        return self.update_progress(goal_id, "cleared", status="cleared")
