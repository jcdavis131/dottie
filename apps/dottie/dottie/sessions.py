# Solo personal project, no connection to employer, built with public/free-tier only
"""
Dottie Sessions — daemon-backed, reattachable, agent-to-agent messaging.

Prime: daemon-backed agents keep running when terminal disconnects, reattachable,
agent-to-agent discovery + messaging, schedules, heartbeats, autonomous mode.

Dottie SOTA adds: MissionLog timeline.jsonl, climb gates, HEARTBEAT.md checklist,
provenance-honest status, local registry at workspace/.dottie/registry.json
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


def default_registry_path() -> Path:
    env = os.environ.get("DOTTIE_REGISTRY")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent.parent / ".dottie" / "registry.json"


@dataclass
class SessionRecord:
    session_id: str
    created_ts: float
    last_seen_ts: float
    status: str  # running | idle | stopped
    mission_id: str | None = None
    harness_session_id: str | None = None
    pid: int | None = None
    model: str | None = None
    goal: str | None = None

    def to_json(self): return asdict(self)


class SessionRegistry:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_registry_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict):
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register(self, record: SessionRecord) -> None:
        data = self._load()
        data[record.session_id] = record.to_json()
        self._save(data)

    def heartbeat(self, session_id: str):
        data = self._load()
        if session_id in data:
            data[session_id]["last_seen_ts"] = time.time()
            data[session_id]["status"] = "running"
            self._save(data)

    def list(self) -> list[dict]:
        return list(self._load().values())

    def get(self, session_id: str) -> dict | None:
        return self._load().get(session_id)

    def stop(self, session_id: str):
        data = self._load()
        if session_id in data:
            data[session_id]["status"] = "stopped"
            data[session_id]["last_seen_ts"] = time.time()
            self._save(data)

    def set_goal(self, session_id: str, goal: str):
        data = self._load()
        if session_id not in data:
            # auto-register minimal
            data[session_id] = SessionRecord(session_id=session_id, created_ts=time.time(), last_seen_ts=time.time(), status="running", goal=goal).to_json()
        else:
            data[session_id]["goal"] = goal
        self._save(data)
        return data[session_id]


# Simple file-based inbox for agent-to-agent messaging
def inbox_path(session_id: str) -> Path:
    base = Path(__file__).resolve().parent.parent.parent.parent / ".dottie" / "inbox" / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base / "messages.jsonl"


def send_message(to_session_id: str, from_session_id: str, msg: str, kind: str = "chat") -> dict:
    p = inbox_path(to_session_id)
    entry = {"ts": time.time(), "from": from_session_id, "to": to_session_id, "kind": kind, "msg": msg, "id": uuid.uuid4().hex[:8]}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def read_inbox(session_id: str, limit: int = 50) -> list[dict]:
    p = inbox_path(session_id)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().split("\n")
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# Heartbeat + schedule helpers

def default_heartbeat_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "HEARTBEAT.md"


def add_heartbeat_check(line: str, heartbeat_file: Path | None = None) -> None:
    hb = heartbeat_file or default_heartbeat_path()
    current = hb.read_text(encoding="utf-8") if hb.exists() else ""
    if line not in current:
        with hb.open("a", encoding="utf-8") as f:
            f.write(f"\n- {line}\n")
