"""RFT ETL — audit.jsonl (canonical workflow-trace substrate) -> structured RFT dataset.

Solo personal project, no connection to employer, built with public/free-tier only

Implements the RFT-on-your-own-workflow-traces pattern from the MAI-Thinking-1 review
(docs/llm-wiki/research-mai-thinking-1.md): every `emit()` in scout-cli is audited to
`~/.local/share/bigbang/audit.jsonl`; this module segments that stream into episodes,
redacts secrets, annotates reward *components* (never final scalar rewards — weighting
belongs to the training config, which keeps the dataset forward-compatible), and writes
versioned JSONL records ready for a PyTorch Dataset in ava-agi-factory-v6-4.

Reward-component conventions follow the factory's spec 12 naming guard: keys are
`r_*` components under `reward_components`, and this file never uses the bare word
"reward" as a data-quality score.

Schema stability contract: RFT_SCHEMA_VERSION is semver. Additive fields bump minor;
breaking renames bump major; consumers must check `schema_version` before training.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

RFT_SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Redaction — audit args can contain live secrets; redaction is NOT optional.
# ---------------------------------------------------------------------------

_SECRET_KEY_RE = re.compile(
    r"(secret|token|password|passwd|api[-_]?key|auth|credential|bearer|cookie)", re.IGNORECASE
)
_SECRET_VALUE_RE = re.compile(
    r"^(sk-[A-Za-z0-9_\-]{8,}|ghp_[A-Za-z0-9]{8,}|gho_[A-Za-z0-9]{8,}|xox[a-z]-[A-Za-z0-9\-]{8,}"
    r"|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}\..*)$"
)
REDACTED = "[REDACTED]"


def redact(value: Any, _key: str = "") -> Any:
    """Recursively mask secret-shaped values by key name or value pattern."""
    if isinstance(value, dict):
        return {k: redact(v, _key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, _key=_key) for v in value]
    if isinstance(value, str):
        if _SECRET_KEY_RE.search(_key) or _SECRET_VALUE_RE.match(value.strip()):
            return REDACTED
    return value


# ---------------------------------------------------------------------------
# Parsing + episode segmentation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RftStep:
    """One tool invocation inside an episode. Mirrors an audit.jsonl entry, redacted."""

    t: int                      # 0-based index within the episode
    command: str
    args: Dict[str, Any]
    status: str                 # "ok" | anything else = failure
    duration_ms: int
    ts: float                   # epoch seconds (UTC)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class RftEpisode:
    """A contiguous burst of tool activity treated as one workflow trajectory."""

    episode_id: str
    steps: List[RftStep]
    start_ts: float
    end_ts: float


def _parse_ts(raw: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def parse_audit_lines(lines: Iterable[str]) -> List[Dict[str, Any]]:
    """Parse raw audit.jsonl lines into normalized dicts; malformed lines are skipped
    (the audit writer itself is best-effort append, so partial lines are expected)."""
    events: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = _parse_ts(row.get("ts", ""))
        if ts is None or "command" not in row:
            continue
        events.append({
            "ts": ts,
            "command": str(row["command"]),
            "args": redact(row.get("args") or {}),
            "status": str(row.get("status", "ok")),
            "duration_ms": int(row.get("duration_ms") or 0),
        })
    events.sort(key=lambda e: e["ts"])
    return events


def segment_episodes(events: List[Dict[str, Any]], gap_seconds: float = 300.0) -> List[RftEpisode]:
    """Group time-ordered events into episodes split on idle gaps > gap_seconds.

    audit.jsonl has no session key, so temporal contiguity is the segmentation signal:
    a human-or-agent working session produces a dense burst; a gap means a new task.
    """
    episodes: List[RftEpisode] = []
    current: List[Dict[str, Any]] = []
    for event in events:
        if current and (event["ts"] - current[-1]["ts"]) > gap_seconds:
            episodes.append(_finalize(current))
            current = []
        current.append(event)
    if current:
        episodes.append(_finalize(current))
    return episodes


def _finalize(events: List[Dict[str, Any]]) -> RftEpisode:
    steps = [
        RftStep(t=i, command=e["command"], args=e["args"], status=e["status"],
                duration_ms=e["duration_ms"], ts=e["ts"])
        for i, e in enumerate(events)
    ]
    fingerprint = json.dumps(
        [events[0]["ts"]] + [e["command"] for e in events], sort_keys=True
    ).encode("utf-8")
    return RftEpisode(
        episode_id=hashlib.sha256(fingerprint).hexdigest()[:16],
        steps=steps,
        start_ts=events[0]["ts"],
        end_ts=events[-1]["ts"],
    )


# ---------------------------------------------------------------------------
# Reward components (measurements, not weighted scalars)
# ---------------------------------------------------------------------------

def reward_components(episode: RftEpisode) -> Dict[str, Any]:
    """Annotate the trajectory with the measurements a trainer weights later.

    - r_task_terminal_ok: did the episode end in a successful call (binary task signal)
    - fraction_ok: robustness of the whole trajectory
    - redundant_steps: consecutive identical (command, args) calls — the MAI finding
      penalizes redundant/duplicated tool calls; we count them, the trainer prices them
    - num_steps / total_duration_ms: raw length signals for a difficulty-scaled length
      penalty (factory spec 12 R_len) — stored raw so the penalty stays a training knob
    """
    steps = episode.steps
    redundant = sum(
        1 for a, b in zip(steps, steps[1:])
        if a.command == b.command and a.args == b.args
    )
    return {
        "r_task_terminal_ok": 1.0 if (steps and steps[-1].ok) else 0.0,
        "fraction_ok": round(sum(1 for s in steps if s.ok) / len(steps), 4) if steps else 0.0,
        "redundant_steps": redundant,
        "num_steps": len(steps),
        "total_duration_ms": sum(s.duration_ms for s in steps),
    }


# ---------------------------------------------------------------------------
# Record assembly + validation
# ---------------------------------------------------------------------------

RFT_RECORD_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "scout-cli RFT workflow-trace record",
    "type": "object",
    "required": ["schema_version", "episode_id", "steps", "outcome", "reward_components", "meta"],
    "properties": {
        "schema_version": {"type": "string"},
        "episode_id": {"type": "string", "minLength": 16, "maxLength": 16},
        "start_ts": {"type": "number"},
        "end_ts": {"type": "number"},
        "steps": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "required": ["t", "command", "args", "status", "duration_ms", "ts"],
                "properties": {
                    "t": {"type": "integer", "minimum": 0},
                    "command": {"type": "string"},
                    "args": {"type": "object"},
                    "status": {"type": "string"},
                    "duration_ms": {"type": "integer", "minimum": 0},
                    "ts": {"type": "number"},
                },
            },
        },
        "outcome": {
            "type": "object",
            "required": ["terminal_ok"],
            "properties": {"terminal_ok": {"type": "boolean"}},
        },
        "reward_components": {
            "type": "object",
            "required": ["r_task_terminal_ok", "fraction_ok", "redundant_steps",
                          "num_steps", "total_duration_ms"],
        },
        "meta": {
            "type": "object",
            "required": ["source", "redacted"],
        },
    },
}


def to_rft_record(episode: RftEpisode) -> Dict[str, Any]:
    components = reward_components(episode)
    return {
        "schema_version": RFT_SCHEMA_VERSION,
        "episode_id": episode.episode_id,
        "start_ts": episode.start_ts,
        "end_ts": episode.end_ts,
        "steps": [asdict(s) for s in episode.steps],
        "outcome": {"terminal_ok": bool(components["r_task_terminal_ok"])},
        "reward_components": components,
        "meta": {"source": "scout-cli audit.jsonl", "redacted": True},
    }


def validate_record(record: Dict[str, Any]) -> List[str]:
    """Dependency-free structural validation against RFT_RECORD_SCHEMA's required shape.

    Returns a list of problems (empty = valid). Deliberately not a full JSON-Schema
    engine — scout-cli stays stdlib-first; the factory's torch loader may re-validate
    with jsonschema if installed.
    """
    problems: List[str] = []
    for key in RFT_RECORD_SCHEMA["required"]:
        if key not in record:
            problems.append(f"missing top-level key: {key}")
    if record.get("schema_version") != RFT_SCHEMA_VERSION:
        problems.append(f"schema_version {record.get('schema_version')!r} != {RFT_SCHEMA_VERSION}")
    steps = record.get("steps") or []
    if not steps:
        problems.append("steps is empty")
    for i, step in enumerate(steps):
        for key in ("t", "command", "args", "status", "duration_ms", "ts"):
            if key not in step:
                problems.append(f"steps[{i}] missing {key}")
    rc = record.get("reward_components") or {}
    for key in RFT_RECORD_SCHEMA["properties"]["reward_components"]["required"]:
        if key not in rc:
            problems.append(f"reward_components missing {key}")
    if _contains_secret(record):
        problems.append("unredacted secret-shaped value present")
    return problems


def _contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_secret(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_secret(v) for v in value)
    return isinstance(value, str) and bool(_SECRET_VALUE_RE.match(value.strip()))


# ---------------------------------------------------------------------------
# End-to-end export
# ---------------------------------------------------------------------------

def export_dataset(
    audit_path: Path,
    out_path: Path,
    gap_seconds: float = 300.0,
    min_steps: int = 1,
) -> Dict[str, Any]:
    """audit.jsonl -> rft_dataset.jsonl. Returns a summary dict (counts, drops, output path)."""
    lines = audit_path.read_text(encoding="utf-8").splitlines() if audit_path.exists() else []
    events = parse_audit_lines(lines)
    episodes = segment_episodes(events, gap_seconds=gap_seconds)
    kept, dropped_short, dropped_invalid = [], 0, 0
    for ep in episodes:
        if len(ep.steps) < min_steps:
            dropped_short += 1
            continue
        record = to_rft_record(ep)
        problems = validate_record(record)
        if problems:
            dropped_invalid += 1
            continue
        kept.append(record)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for record in kept:
            f.write(json.dumps(record) + "\n")
    return {
        "schema_version": RFT_SCHEMA_VERSION,
        "audit_events": len(events),
        "episodes": len(episodes),
        "records_written": len(kept),
        "dropped_short": dropped_short,
        "dropped_invalid": dropped_invalid,
        "out": str(out_path),
    }


def iter_records(dataset_path: Path) -> Iterator[Dict[str, Any]]:
    """Stream a written dataset; the factory's torch Dataset wraps exactly this."""
    with dataset_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
