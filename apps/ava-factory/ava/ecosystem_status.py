"""Read-only snapshot of the surrounding agent ecosystem for /ecosystem.

ava-agi's own dashboard (ava/dashboard_html.py) already covers the training
run in depth. This module answers a different question -- "what is the
state of everything *around* the model": the coding-agent harness
(AgenticOS), the merged skills libraries, the agent-eval scoreboard, and
curriculum-stage progress (TODOS.md).

Everything here reads through the /host_disk read-only bind mount (see
docker-compose.yml's x-host-disk anchor) -- the same mechanism
pipeline_status.py's disk-free probe already uses -- since AgenticOS and
agent-eval are sibling repos outside the ava-agi image, not baked into it.
Every probe is independently guarded: a missing/unreadable checkout
degrades that one card to "not found," it never breaks the rest of the
page or the live dashboard alongside it.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

_HOST_DISK = Path(os.environ.get("AVA_HOST_DISK", "/host_disk"))
# This host's user profile dir -- ava-agi, AgenticOS, and agent-eval are all
# sibling checkouts under it. Override via env if this ever runs elsewhere.
_ECO_HOME = Path(os.environ.get("AVA_ECOSYSTEM_HOME", str(_HOST_DISK / "Users" / "jcdav")))

_AVA_AGI = _ECO_HOME / "ava-agi"
_AGENTICOS = _ECO_HOME / "AgenticOS"
_AGENT_EVAL = _ECO_HOME / "agent-eval"
_DOT_AGENTS_SKILLS = _ECO_HOME / ".agents" / "skills"


def _safe(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception:
        return default


def _count_glob(dir_: Path, pattern: str) -> int:
    if not dir_.is_dir():
        return 0
    return len(list(dir_.glob(pattern)))


def _tail_lines(path: Path, n: int) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return [ln for ln in lines[-n:] if ln.strip()]
    except OSError:
        return []


def _skills_summary() -> dict[str, Any]:
    own = _count_glob(_AGENTICOS / "skills", "*.md")
    cursor = _count_glob(_AGENTICOS / "skills-lib" / "cursor-agent-skills" / "skills", "*/SKILL.md")
    addyosmani = _count_glob(_DOT_AGENTS_SKILLS, "*/SKILL.md")
    return {
        "found": _AGENTICOS.is_dir() or _DOT_AGENTS_SKILLS.is_dir(),
        "agenticos_own": own,
        "cursor_agent_skills": cursor,
        "addyosmani_lifecycle": addyosmani,
        "total": own + cursor + addyosmani,
    }


_HARNESS_FILES = [
    "harness.py", "agentos.py", "guard.py", "autonomy.py",
    "code_tools.py", "web_tools.py", "infra_tools.py", "ava_bridge.py",
]


def _harness_summary() -> dict[str, Any]:
    if not _AGENTICOS.is_dir():
        return {"found": False}
    present = {f: (_AGENTICOS / f).is_file() for f in _HARNESS_FILES}
    return {"found": True, "files": present, "built": sum(present.values()), "total": len(present)}


def _agent_eval_summary() -> dict[str, Any]:
    if not _AGENT_EVAL.is_dir():
        return {"found": False}
    results = []
    results_dir = _AGENT_EVAL / "results"
    if results_dir.is_dir():
        for f in sorted(results_dir.glob("*.json")):
            try:
                rows = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            n = len(rows)
            succ = sum(1 for r in rows if r.get("success"))
            results.append({"model": f.stem, "tasks": n, "success": succ})
    scoreboard_md = None
    sb_path = _AGENT_EVAL / "scoreboard.md"
    if sb_path.is_file():
        try:
            scoreboard_md = sb_path.read_text(encoding="utf-8")
        except OSError:
            scoreboard_md = None
    return {
        "found": True,
        "results": results,
        "scoreboard_md": scoreboard_md,
        "hillclimb_tail": _tail_lines(_AGENT_EVAL / "hillclimb-log.md", 6),
    }


_STAGE_RE = re.compile(r"^## (Stage \d+.*?)\s*$", re.M)
_CHECKBOX_RE = re.compile(r"^- \[( |x)\]", re.M)


def _todos_summary() -> dict[str, Any]:
    path = _AVA_AGI / "TODOS.md"
    if not path.is_file():
        return {"found": False}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"found": False}
    matches = list(_STAGE_RE.finditer(text))
    stages = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        boxes = _CHECKBOX_RE.findall(body)
        done = sum(1 for b in boxes if b == "x")
        stages.append({"name": m.group(1).strip(), "done": done, "total": len(boxes)})
    return {"found": True, "stages": stages}


def collect_ecosystem_status() -> dict[str, Any]:
    return {
        "host_disk_mounted": _HOST_DISK.is_dir(),
        "eco_home": str(_ECO_HOME),
        "agenticos": _safe(_harness_summary, {"found": False}),
        "skills": _safe(_skills_summary, {"found": False}),
        "agent_eval": _safe(_agent_eval_summary, {"found": False}),
        "todos": _safe(_todos_summary, {"found": False}),
        "hillclimb_tail": _safe(lambda: _tail_lines(_AVA_AGI / "tasks" / "hillclimb-log.md", 6), []),
    }
