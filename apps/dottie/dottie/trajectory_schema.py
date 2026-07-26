# Solo personal project, no connection to employer, built with public/free-tier only
"""Unified trajectory schema — one shape for every rollout, separated from learning.

Distilled from Z.AI's GLM-5.2 "Slime" system (tasks/artifacts/glm52_learnings.md):
treat every diverse interaction (code exec, tool use, validation, repair) as ONE
``{states, actions, tool_calls, feedback}`` trajectory, and keep the *rollout*
producers separate from the *learning* consumers so data feeds consistently.

Today the same shape is emitted four ways with four ad-hoc schemas — CodeAct
traces (engine.py), validation obligation traces (research/validate.py),
agent-eval trajectories (C:\\Users\\jcdav\\agent-eval), and repair transcripts
(scripts/export_repair_transcripts.py) — which already forces two exporters that
cannot share code. This module is the unification: pure adapters map each
rollout's persisted records INTO ``Trajectory``, and one ``to_sft_records``
consumer reads any of them the same way.

THIS FILE: the schema + all FOUR rollout adapters (``from_codeact_trace``,
``from_validation_history``, ``from_repair_rows``, ``from_agent_eval_events``) +
``to_sft_records`` + round-trip serialization. Everything is ADDITIVE — the four
live emitters are NOT rewired. The remaining migration (collapsing the two live
exporters, ``export_repair_transcripts.py`` and agent-eval's
``export_sft_corpus.py``, onto ``to_sft_records`` so one consumer reads every
source) touches working code and is the proposed follow-up.

Honesty guards (deliberate, from the design note):
- ``feedback`` stays polymorphic (a dict): CodeAct carries stdout/error, validation
  carries obligations; do NOT flatten to one field and lose provenance.
- ``outcome.reward`` is whatever the rollout actually recorded. Do NOT invent a
  scalar RL-return here, and do NOT conflate an RL return with a data-quality
  reward — they are different signals (see research/rl naming guard). ``None``
  when the rollout recorded none.
- This module only RESHAPES persisted data. It never feeds training on its own;
  a learning loop must consume ``to_sft_records`` explicitly.

Extension points: add ``from_agent_eval_events`` / ``from_repair_rows`` adapters
(same signature — pure dict -> Trajectory); a future GRPO/PPO batcher can consume
``Trajectory`` objects instead of bespoke tuples (the Slime rollout->learning seam,
ready before the GPU is).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = "traj-1.0.0"


@dataclass(frozen=True)
class Step:
    """One interaction: the state entered, the action taken, any tool calls, the feedback.

    ``tool_calls`` is the shape already used across the codebase: ``[{"tool", "args"}]``.
    ``feedback`` is polymorphic on purpose (see module honesty guards).
    """

    state: str
    action: dict[str, Any]
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    feedback: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Trajectory:
    """A whole rollout as a sequence of steps + a terminal outcome, source-tagged."""

    trajectory_id: str
    source: str  # "codeact" | "agent_eval" | "validation" | "repair"
    task_ref: dict[str, Any]  # {"task_id"} | {"experiment_id"} | {"family","seed"}
    steps: list[Step]
    outcome: dict[str, Any]  # {"status", "reward": {...}|None, "verified_by"}
    schema_version: str = SCHEMA_VERSION


# ---- serialization (round-trips) --------------------------------------------


def to_dict(t: Trajectory) -> dict[str, Any]:
    """Trajectory -> plain JSON-able dict (dataclasses.asdict handles nested Steps)."""
    return asdict(t)


def from_dict(d: dict[str, Any]) -> Trajectory:
    """Plain dict -> Trajectory. Unknown top-level keys are ignored (forward-compat)."""
    steps = [
        s
        if isinstance(s, Step)
        else Step(
            state=s.get("state", ""),
            action=s.get("action") or {},
            tool_calls=s.get("tool_calls") or [],
            feedback=s.get("feedback") or {},
        )
        for s in d.get("steps", [])
    ]
    return Trajectory(
        trajectory_id=d["trajectory_id"],
        source=d["source"],
        task_ref=d.get("task_ref") or {},
        steps=steps,
        outcome=d.get("outcome") or {},
        schema_version=d.get("schema_version", SCHEMA_VERSION),
    )


# ---- adapters: rollout records -> Trajectory (pure, over data we ALREADY persist)


def from_codeact_trace(rec: dict[str, Any]) -> Trajectory:
    """A CodeAct engine trace record (engine.py:242) -> Trajectory.

    Each engine step already carries code (->action), tool_calls (verbatim), and
    ok/stdout/value/error (->feedback). ``state`` is the transcript-so-far: the
    prompt, then each step's code accumulated (an honest approximation of what the
    policy had seen — the engine does not persist the exact rendered context).
    """
    steps: list[Step] = []
    transcript = rec.get("prompt", "") or ""
    for s in rec.get("steps", []):
        code = s.get("code", "") or ""
        steps.append(
            Step(
                state=transcript,
                action={"kind": "code", "payload": code},
                tool_calls=list(s.get("tool_calls") or []),
                feedback={
                    "ok": s.get("ok"),
                    "stdout": s.get("stdout"),
                    "value": s.get("value"),
                    "error": s.get("error"),
                },
            )
        )
        transcript = f"{transcript}\n{code}" if transcript else code
    if rec.get("reached_final"):
        status = "reached_final"
    elif rec.get("terminated"):
        status = "terminated"
    else:
        status = "incomplete"
    return Trajectory(
        trajectory_id=f"codeact:{rec.get('task_id', 'unknown')}:{rec.get('ts', 0)}",
        source="codeact",
        task_ref={"task_id": rec.get("task_id")},
        steps=steps,
        outcome={
            "status": status,
            "reward": rec.get("reward_components"),  # dict of real components, or None
            "verified_by": rec.get("verified_task"),
        },
    )


def from_validation_history(exp: dict[str, Any]) -> Trajectory:
    """A research experiment's validation history (validate.py:1063) -> Trajectory.

    ``exp`` may be the experiment dict (with ``history``) or a ``validation`` dict
    that holds ``history``. Each attempt carries {level(->state), status,
    detail(->feedback), obligations}; validation has no tool calls. The
    failed->discharged obligation transition across attempts is the per-step
    learning signal the unification is meant to surface.
    """
    history = exp.get("history")
    if history is None:
        history = (exp.get("validation") or {}).get("history") or []
    steps: list[Step] = []
    for h in history:
        attempt = h.get("attempt", 0)
        steps.append(
            Step(
                state=f"stage:{h.get('level')}",
                # attempt 0 is the first submission; later attempts are corrector rewrites
                action={"kind": "rewrite" if attempt else "submit", "attempt": attempt},
                tool_calls=[],
                feedback={
                    "ok": h.get("ok"),
                    "status": h.get("status"),
                    "detail": h.get("detail"),
                    "obligations": h.get("obligations"),
                },
            )
        )
    final = history[-1] if history else {}
    return Trajectory(
        trajectory_id=f"validation:{exp.get('experiment_id', 'unknown')}",
        source="validation",
        task_ref={"experiment_id": exp.get("experiment_id")},
        steps=steps,
        outcome={
            "status": "ok" if final.get("ok") else "failed",
            "reward": None,  # validation is a gate, not a graded reward — keep it None honestly
            "verified_by": "validate.py 6-stage",
        },
    )


def from_repair_rows(rows: list[dict[str, Any]]) -> Trajectory:
    """One experiment's repair rows (export_repair_transcripts.py:84) -> Trajectory.

    Pass the rows for a SINGLE experiment (same ``experiment_id``); the exporter
    emits one row per failed attempt that the experiment later recovered from, all
    sharing the final ``corrected_code``. Modelled like the validation trajectory:
    each failure is a step, then one terminal correction step carrying the
    validated code — the failure->fix sequence Slime treats as one trajectory.
    Empty ``rows`` yields a trajectory with no steps (honest), not a crash.
    """
    ordered = sorted(rows, key=lambda r: r.get("failure_seq", 0))
    first = ordered[0] if ordered else {}
    steps: list[Step] = []
    for r in ordered:
        attempt = r.get("attempt", 0)
        steps.append(
            Step(
                state=f"stage:{r.get('level')}",
                action={"kind": "rewrite" if attempt else "submit", "attempt": attempt},
                tool_calls=[],
                feedback={
                    "ok": False,
                    "status": r.get("status"),
                    "detail": r.get("failure_detail"),
                    "repair_hint": r.get("repair_hint"),
                },
            )
        )
    if ordered:
        # terminal step: the validated correction shared by all rows
        steps.append(
            Step(
                state="corrected",
                action={"kind": "rewrite", "payload": first.get("corrected_code")},
                tool_calls=[],
                feedback={"ok": True, "detail": first.get("validated_detail")},
            )
        )
    return Trajectory(
        trajectory_id=f"repair:{first.get('experiment_id', 'unknown')}",
        source="repair",
        task_ref={
            "experiment_id": first.get("experiment_id"),
            "module_name": first.get("module_name"),
        },
        steps=steps,
        outcome={
            "status": "repaired" if ordered else "empty",
            "reward": None,  # a recovered-code corpus, not a graded reward
            "verified_by": first.get("corrected_code_role"),
        },
    )


def from_agent_eval_events(result: dict[str, Any]) -> Trajectory:
    """An agent-eval run result (run_eval.py:150) -> Trajectory.

    agent-eval lives in a separate repo and its per-step events are produced by an
    external agent runner, so the only GUARANTEED event contract is the one
    agent-eval itself relies on: a step event has ``type=="step"`` with ``tool``
    and ``args`` (run_eval.py:117,139). This adapter uses exactly that and passes
    any OTHER event fields through as ``feedback`` verbatim — no schema-guessing,
    so it stays correct as the runner's event shape evolves. ``outcome`` carries
    agent-eval's pass/fail verdict fields; ``reward`` is None (a gate, not graded).
    """
    events = result.get("events") or []
    prompt = result.get("prompt", "") or ""
    steps: list[Step] = []
    for ev in events:
        if ev.get("type") != "step":
            continue
        tool = ev.get("tool")
        args = ev.get("args") or {}
        # honest passthrough: whatever the runner recorded beyond the action contract
        feedback = {k: v for k, v in ev.items() if k not in ("type", "tool", "args")}
        steps.append(
            Step(
                state=prompt,
                action={"kind": "tool", "tool": tool},
                tool_calls=[{"tool": tool, "args": args}],
                feedback=feedback,
            )
        )
    return Trajectory(
        trajectory_id=f"agent_eval:{result.get('task_id', 'unknown')}:{result.get('model', '?')}",
        source="agent_eval",
        task_ref={"task_id": result.get("task_id"), "category": result.get("category")},
        steps=steps,
        outcome={
            "status": result.get("status"),
            "success": result.get("success"),
            "trajectory_ok": result.get(
                "trajectory_ok"
            ),  # None = task declares no trajectory
            "reward": None,
            "verified_by": result.get("check_detail"),
        },
    )


# ---- learning-side consumer (one reader for every source) --------------------


def to_sft_records(t: Trajectory) -> list[dict[str, Any]]:
    """Trajectory -> flat per-step SFT records — the single consumer that replaces
    the two divergent exporters. Source-agnostic: it reads a CodeAct trajectory and
    a validation trajectory identically. The terminal ``outcome`` is attached to the
    LAST step only (so a downstream filter can weight/keep by final status without
    re-joining). Empty-step trajectories yield an empty list, honestly.
    """
    n = len(t.steps)
    records: list[dict[str, Any]] = []
    for i, step in enumerate(t.steps):
        records.append(
            {
                "trajectory_id": t.trajectory_id,
                "source": t.source,
                "task_ref": t.task_ref,
                "step": i,
                "state": step.state,
                "action": step.action,
                "tool_calls": step.tool_calls,
                "feedback": step.feedback,
                "outcome": t.outcome if i == n - 1 else None,
                "schema_version": t.schema_version,
            }
        )
    return records
