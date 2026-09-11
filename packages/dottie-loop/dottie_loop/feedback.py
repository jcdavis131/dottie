"""Real feedback from every surface (spec §16 "Capture requirements", §35 gap 02).

One recorder behind the CLI, the API, Slack and the ``scout loop`` plugin so a
signal means the same thing wherever it was emitted: it is bound to ONE captured
run, appended as a superseding record (the trace file stays append-only), and the
reward is recomputed from the record with the signal as evidence. A surface that
cannot name the run it answers records nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dottie_loop.capture import FEEDBACK_SIGNALS, SURFACES
from dottie_loop.errors import BlockedError, InvalidInputError
from dottie_loop.hashing import now_iso
from dottie_loop.reward import RewardInputs, compute_reward

#: Slack reaction name -> signal (the operator can extend this as data)
SLACK_REACTIONS: dict[str, str] = {
    "white_check_mark": "accept",
    "heavy_check_mark": "accept",
    "x": "reject",
    "negative_squared_cross_mark": "reject",
    "pencil2": "edit",
    "memo": "edit",
    "rocket": "apply",
    "no_entry_sign": "dismiss",
    "wastebasket": "dismiss",
}


def load_traces(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def record_feedback(store: Path, *, run_id: str, signal: str, surface: str, edit_fraction: float | None = None, subject: str | None = None) -> dict[str, Any]:
    """Attach ``signal`` to the captured run ``run_id`` under ``store`` and recompute its reward."""
    if signal not in FEEDBACK_SIGNALS:
        raise InvalidInputError(f"signal must be one of {sorted(FEEDBACK_SIGNALS)}", field="signal")
    if surface not in SURFACES:
        raise InvalidInputError("unknown surface", field="surface")
    if edit_fraction is not None and not 0.0 <= edit_fraction <= 1.0:
        raise InvalidInputError("edit_fraction must be in [0, 1]", field="edit_fraction")
    if not run_id or not isinstance(run_id, str):
        raise InvalidInputError("run_id is required", field="run_id")
    traces_path = Path(store) / "traces" / "pair.jsonl"
    if not traces_path.exists():
        raise BlockedError("no captured traces for this store (capture is opt-in)", "capture")
    match = [t for t in load_traces(traces_path) if t.get("session_id") == run_id or t.get("trace_id") == run_id]
    if not match:
        raise InvalidInputError(f"no trace for run {run_id}", field="run_id")
    rec = match[-1]
    entry = {"signal": signal, "edit_fraction": edit_fraction, "surface": surface, "subject": subject, "at": now_iso()}
    rec.setdefault("feedback", []).append(entry)
    with traces_path.open("a", encoding="utf-8") as f:  # superseding record; never rewrite history
        f.write(json.dumps({**rec, "supersedes_trace": rec.get("trace_id")}, sort_keys=True) + "\n")
    reward = compute_reward(RewardInputs(trace_id=rec["trace_id"], task_ok=rec.get("outcome", {}).get("task_ok"), feedback=signal, edit_fraction=edit_fraction, evidence=[f"feedback:{signal}:{surface}"]))
    (Path(store) / "traces" / f"reward-{rec['trace_id']}.json").write_text(json.dumps(reward, indent=1, sort_keys=True), encoding="utf-8")
    return {"trace_id": rec["trace_id"], "feedback": entry, "reward": reward}


def signal_from_text(text: str) -> str | None:
    """A thread reply whose FIRST word is a signal name is feedback; anything else is conversation."""
    words = text.strip().lower().replace(":", " ").split()
    if not words:
        return None
    first = words[0].strip("!.,")
    return first if first in FEEDBACK_SIGNALS else None
