# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct decode / serving loop (spec 13 T13C.5, GPU-free half).

The loop that turns a *policy* into an agent: the policy emits an assistant turn, the loop extracts
its ```python action, runs it in the T13C.1 `Sandbox`, feeds the Observation back, and repeats until
the policy emits a turn with no code (the FINAL) or the step cap trips. It is the executable half of
`ServeEngine.generate`'s code-act mode and of the T13C.3 real eval's decode driver — both were the
missing piece those modules honestly gated on.

Two honesty properties, both load-bearing:
  • **Pluggable policy.** The loop takes any `Policy = Callable[[str], str]` (transcript → next
    assistant turn). A real model is injected here later; a `TrajectoryReplayPolicy` (replays a
    T13C.2 trajectory's turns) drives the loop end-to-end **without a model**, so the plumbing —
    multi-step execution, observation feedback, FINAL sanitization, trace capture — is testable
    today against the *real* sandbox. `ModelPolicy` refuses to run without a real model (gated).
  • **Sanitized output + captured trace.** Only the FINAL answer reaches the user (the Mem0-style
    thought/answer separation from `docs/RL_INTEGRATION.md`); the full code+observation trace is
    captured separately for debugging and for `ava-skills` memory-mint ingestion — never leaked
    into the user-facing string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ava.rl.codeact_sandbox import Observation, Sandbox

# The transcript markers match ava/datagen/codeact.py::render exactly, so a policy trained on that
# datagen sees at serving time the same format it saw at training time.
USER = "<|user|>"
ASSISTANT = "<|assistant|>"

# A policy maps the running transcript to its next assistant turn. Real models plug in here.
Policy = Callable[[str], str]

_PY_FENCE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)


def extract_action(assistant_turn: str) -> Optional[str]:
    """Return the code of the FIRST ```python fence in the turn, or None if the turn has none.

    No fence ⇒ this turn is the FINAL answer (matches datagen: action turns carry a fenced block,
    the closing turn is prose). Only the first fence is taken — one action per turn, mirroring the
    training format."""
    m = _PY_FENCE.search(assistant_turn)
    if m is None:
        return None
    return m.group(1).strip("\n")


_LABEL = re.compile(r"^\s*(?:FINAL|Answer|Final answer)\s*[:\-]\s*", re.IGNORECASE)


def sanitize_final(assistant_turn: str) -> str:
    """The user-facing answer: the FINAL turn stripped of any leading FINAL:/Answer: label and of a
    leading 'Thought:' preamble. Never contains code or observations (the caller only passes a turn
    with no fence here). Whitespace-trimmed."""
    text = assistant_turn.strip()
    text = re.sub(r"^\s*Thought:\s*", "", text, flags=re.IGNORECASE)
    text = _LABEL.sub("", text)
    return text.strip()


@dataclass(frozen=True)
class CodeActStep:
    """One executed action + its observation — the unit captured for debugging / memory-mint."""
    assistant_turn: str          # the raw turn the policy emitted (thought + code)
    code: str                    # the extracted action
    observation: Observation     # the real sandbox result (stdout / value / error / tool_calls)


@dataclass(frozen=True)
class CodeActResult:
    """Outcome of a code-act episode.

    `final` is the ONLY thing that should reach the user (None if the episode never reached a FINAL
    — step cap hit). `steps` is the full code+observation trace, captured for debugging and for
    memory-mint ingestion; it must never be concatenated into the user-facing string. `terminated`
    ∈ {'final','step_cap','policy_empty'}."""
    final: Optional[str]
    steps: List[CodeActStep]
    terminated: str

    @property
    def observations(self) -> List[Observation]:
        """The Observation sequence — the exact input `codeact_rewards`/`r_exec` consume."""
        return [s.observation for s in self.steps]

    @property
    def reached_final(self) -> bool:
        return self.terminated == "final" and self.final is not None


def _render_observation(obs: Observation) -> str:
    """Render an Observation back into the transcript in the datagen's Observation format, so the
    policy sees at serving time the same Observation shape it was trained on."""
    if obs.error is not None:
        body = obs.error
    else:
        parts: List[str] = []
        if obs.stdout.strip():
            parts.append(obs.stdout.rstrip("\n"))
        if obs.value is not None:
            parts.append(f"=> {obs.value}")
        body = "\n".join(parts) if parts else "(no output)"
    return f"{USER}\nObservation:\n{body}"


def run_code_act(policy: Policy, user_prompt: str, *,
                 tool_sources: Optional[Dict[str, str]] = None,
                 max_steps: int = 8, sandbox_max_steps: int = 16,
                 timeout_s: float = 5.0) -> CodeActResult:
    """Drive `policy` through a code-act episode against the REAL T13C.1 sandbox.

    Loop: emit assistant turn → extract ```python action → `Sandbox.step` → feed Observation back →
    repeat, until the policy emits a turn with no code (FINAL) or `max_steps` actions run. Returns a
    `CodeActResult` whose `final` is sanitized (user-facing) and whose `steps` hold the full trace
    (debug / memory-mint). The sandbox is closed on exit (context manager) even on early return.

    `max_steps` bounds *policy actions* (rollout length); `sandbox_max_steps` is the sandbox's own
    internal cap. An empty policy turn terminates as 'policy_empty' (a degenerate policy, not a
    FINAL) so a broken policy can't masquerade as a finished answer."""
    transcript = f"{USER}\n{user_prompt}"
    steps: List[CodeActStep] = []
    with Sandbox(tool_sources=tool_sources or {}, max_steps=sandbox_max_steps,
                 timeout_s=timeout_s) as vm:
        for _ in range(max_steps):
            turn = policy(transcript)
            if not turn or not turn.strip():
                return CodeActResult(final=None, steps=steps, terminated="policy_empty")
            code = extract_action(turn)
            if code is None:                       # no action → this is the FINAL answer
                return CodeActResult(final=sanitize_final(turn), steps=steps, terminated="final")
            obs = vm.step(code)
            steps.append(CodeActStep(assistant_turn=turn, code=code, observation=obs))
            transcript += f"\n{ASSISTANT}\n{turn}\n{_render_observation(obs)}"
    # Ran out of action budget without a FINAL — honest terminal state, not a fabricated answer.
    return CodeActResult(final=None, steps=steps, terminated="step_cap")


# ─────────────────────────────────────────────────────────────────────────────
# Policies: a GPU-free replay harness (testable today) + the gated real-model policy
# ─────────────────────────────────────────────────────────────────────────────


class TrajectoryReplayPolicy:
    """A **model-free** policy that replays a T13C.2 `Trajectory`'s assistant turns in order, so the
    decode loop can be tested end-to-end against the real sandbox without a model.

    It emits each action turn (Thought + ```python), then the FINAL sentence, then (if asked again)
    nothing. This is a plumbing harness — NOT a capability measurement — but the sandbox execution
    it drives is entirely real, which is exactly what proves the loop runs a multi-step task
    end-to-end and returns only the sanitized FINAL (the T13C.5 serving accept criterion)."""

    def __init__(self, trajectory) -> None:
        turns: List[str] = []
        for turn in trajectory.turns:
            turns.append(f"Thought: {turn.thought}\n```python\n{turn.code}\n```")
        turns.append(trajectory.final_sentence)      # the closing turn has no fence → FINAL
        self._turns = turns
        self._i = 0

    def __call__(self, transcript: str) -> str:      # noqa: ARG002 - replay ignores the transcript
        if self._i >= len(self._turns):
            return ""                                 # exhausted → degenerate empty turn
        turn = self._turns[self._i]
        self._i += 1
        return turn


class ModelPolicyBlockedError(RuntimeError):
    """Raised when the real-model code-act policy is invoked without a loaded model."""


@dataclass
class ModelPolicy:
    """The real policy — INTENTIONALLY GATED. Wrapping a trained model as a `Policy` needs the model
    itself (a branch fine-tune, T9.3/T9.5, which does not exist) and a GPU to decode (BLOCKED_NO_GPU).
    `__call__` refuses rather than emitting a fabricated turn. Swap this in once a checkpoint exists;
    the loop, sandbox, sanitization, and trace capture around it are already built and tested."""

    model: object = None
    tokenizer: object = None
    max_new_tokens: int = 512

    def __call__(self, transcript: str) -> str:      # noqa: ARG002
        raise ModelPolicyBlockedError(
            "This placeholder never decodes — the REAL decode policy now exists: use "
            "ava.rl.codeact_policy.TorchModelPolicy (autoregressive greedy/sampling decode over "
            "any torch LM + tokenizer, seeded, stop-cut; machinery-verified on the real nano "
            "AvaModel and driven through the real sandbox by scripts/rl_smoke_update.py on the "
            "smoke-scale pilot checkpoint). What remains gated is CAPABILITY: a checkpoint whose "
            "emissions actually solve tasks needs the capability-scale climb (T9.3/T9.5 at mini+, "
            "GPU wall-clock — BLOCKED_NO_GPU at that scale). Do not use this class; do not "
            "fabricate capable turns."
        )
