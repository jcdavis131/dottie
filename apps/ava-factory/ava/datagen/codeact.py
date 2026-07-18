"""CodeAct datagen (spec 13 T13C.2) — executable trajectories where the model *thinks in code*.

Solo personal project, no connection to employer, built with public/free-tier only

Unlike react_tools.py (which teaches the plain-text Thought/Action/Observation *shape*, nothing
executes), every trajectory here is **real executable Python**: the answer is computed by running
the code, and the emitted code re-executes under the T13C.1 CodeActSandbox to the same labeled
answer. Inherits react_tools' grounding-over-syntax bias — a floor share of trajectories teach
*the program's output contradicted my assumption; say so and re-plan*, not *I ran code, therefore
I succeeded*.

Equivalence guarantee: the emitted code contains **no randomness and no wall-clock** — the private
`rng` only picks parameters at *generation* time, and time comes from the sandbox's frozen
`get_clock()`. So the in-process executor here and the subprocess sandbox produce byte-identical
observations, which the test verifies by re-running trajectories through the real Sandbox.

Families:
  * codeact_compute   (deliberate): the answer must come from a run expression, not mental math.
  * codeact_tool      (deliberate): a bound tool returns a value the program must actually consume;
                       a grounding variant returns "unknown" and the model must say so, not guess.
  * codeact_multistep (temporal):   run → inspect the Observation → run again with the observed value.
  * codeact_recover   (deliberate, grounding): the first block errors on a wrong assumption; the
                       Observation shows the failure; the model debugs it and computes the answer.
"""

from __future__ import annotations

import ast
import io
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from ava.datagen.base import Generator, run_cli
# Import the sandbox's constants so the in-process executor stays in lockstep by construction
# (not by a hand-maintained comment): frozen clock, value cap, and stdout cap must all match.
from ava.rl.codeact_sandbox import DEFAULT_FREEZE_EPOCH as FREEZE_EPOCH, STDOUT_CAP, VALUE_CAP

USER = "<|user|>"
ASSISTANT = "<|assistant|>"

GROUNDING_FLOOR_DEFAULT = 0.35


# ---------------------------------------------------------------------------
# In-process executor — mirrors CodeActSandbox exec + last-expression semantics
# exactly (used to COMPUTE the labeled answer and render real observations).
# ---------------------------------------------------------------------------

def _safe_repr(x, cap: int = VALUE_CAP) -> str:
    try:
        r = repr(x)
    except Exception as e:  # pragma: no cover - defensive; generated values are simple
        r = f"<unreprable: {e}>"
    return r if len(r) <= cap else r[:cap] + "...<truncated>"


def _run_block(ns: dict, code: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Exec a block in `ns`; return (stdout, value_repr_or_None, error_or_None).

    Same ast last-expression split as the sandbox worker: pop a trailing Expr, exec the rest,
    then eval the expression for its value. `ns` persists across blocks (the LLM-VM namespace)."""
    buf = io.StringIO()
    value: Optional[str] = None
    error: Optional[str] = None
    import contextlib
    try:
        tree = ast.parse(code, mode="exec")
        last_expr = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = tree.body.pop()
        with contextlib.redirect_stdout(buf):
            exec(compile(tree, "<codeact>", "exec"), ns)
            if last_expr is not None:
                v = eval(compile(ast.Expression(last_expr.value), "<codeact>", "eval"), ns)
                if v is not None:
                    value = _safe_repr(v)
    except BaseException as e:  # noqa: BLE001 - mirror the sandbox: report, don't raise
        error = "".join(traceback.format_exception_only(type(e), e)).strip()
    out = buf.getvalue()
    if len(out) > STDOUT_CAP:                    # mirror the sandbox's stdout truncation exactly
        out = out[:STDOUT_CAP] + "...<truncated>"
    return out, value, error


def _fresh_ns() -> dict:
    return {"__name__": "ava_codeact_datagen", "get_clock": lambda: FREEZE_EPOCH}


def _render_obs(stdout: str, value: Optional[str], error: Optional[str]) -> str:
    if error is not None:
        return error
    parts: List[str] = []
    if stdout.strip():
        parts.append(stdout.rstrip("\n"))
    if value is not None:
        parts.append(f"=> {value}")
    return "\n".join(parts) if parts else "(no output)"


# ---------------------------------------------------------------------------
# Trajectory model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Turn:
    thought: str
    code: str
    obs: str            # rendered Observation (real execution output)


@dataclass(frozen=True)
class Trajectory:
    user: str
    turns: List[Turn]
    answer: str                          # labeled final answer (a computed value's repr / derived)
    final_sentence: str                  # the assistant's grounded closing turn
    task_type: str
    concept: str
    grounding: bool
    blocks: List[str] = field(default_factory=list)         # code blocks, for sandbox re-exec
    tool_sources: Dict[str, str] = field(default_factory=dict)


def render(traj: Trajectory) -> str:
    """Render a trajectory to the chat transcript format (matches react_tools' markers)."""
    parts: List[str] = [f"{USER}\n{traj.user}"]
    for turn in traj.turns:
        parts.append(f"{ASSISTANT}\nThought: {turn.thought}\n```python\n{turn.code}\n```")
        parts.append(f"{USER}\nObservation:\n{turn.obs}")
    parts.append(f"{ASSISTANT}\n{traj.final_sentence}")
    return "\n".join(parts)


class _Leakage(Exception):
    """Raised internally when a candidate trajectory leaks its answer into the prompt."""


def _guard_no_leak(user: str, answer: str) -> None:
    # The prompt must never contain the answer string (the model must COMPUTE it, not copy it).
    if answer and answer in user:
        raise _Leakage(answer)


# ---------------------------------------------------------------------------
# Families — each returns a Trajectory whose answer is computed by _run_block.
# rng is used ONLY to pick parameters; emitted code is deterministic + pure.
# ---------------------------------------------------------------------------

def _compute(rng) -> Trajectory:
    n = rng.randint(3, 6)
    nums = [rng.randint(2, 40) for _ in range(n)]
    code = f"nums = {nums}\nsum(x * x for x in nums)"
    ns = _fresh_ns()
    stdout, value, error = _run_block(ns, code)
    assert error is None and value is not None
    user = (f"Compute the sum of squares of these numbers: {nums}. "
            f"Don't do it in your head — run the code and read the result.")
    _guard_no_leak(user, value)
    turn = Turn("I'll compute this by running code rather than trusting mental arithmetic.",
                code, _render_obs(stdout, value, error))
    return Trajectory(
        user=user, turns=[turn], answer=value,
        final_sentence=f"The sum of squares is {value} (from the executed result, not estimated).",
        task_type="deliberate", concept="codeact_compute", grounding=False, blocks=[code],
    )


_ORDER_STATUS = {
    "A100": "shipped", "B205": "processing", "C310": "delivered",
    "D415": "cancelled", "E520": "returned",
}
_TOOL_LOOKUP_SRC = (
    "def lookup(order_id):\n"
    "    table = " + repr(_ORDER_STATUS) + "\n"
    "    return table.get(order_id, 'unknown')\n"
)


def _tool(rng, grounding: bool) -> Trajectory:
    if grounding:
        order = rng.choice(["Z999", "Q000", "X123", "NOPE1"])  # not in the table → 'unknown'
    else:
        order = rng.choice(list(_ORDER_STATUS))
    code = f"lookup({order!r})"
    ns = _fresh_ns()
    exec(_TOOL_LOOKUP_SRC, ns)
    stdout, value, error = _run_block(ns, code)
    assert error is None and value is not None
    status = value.strip("'\"")
    user = (f"What is the status of order {order}? Use the lookup tool and answer from what it "
            f"returns — do not assume.")
    _guard_no_leak(user, value)
    _guard_no_leak(user, status)
    if grounding:
        final = (f"The lookup returned 'unknown' for order {order}, so I have no record of its "
                 f"status — I won't guess a plausible-sounding one.")
        concept = "codeact_tool_grounding"
    else:
        final = f"Order {order} is '{status}', per the lookup tool's result."
        concept = "codeact_tool"
    turn = Turn("I'll query the lookup tool rather than assume the order's status.",
                code, _render_obs(stdout, value, error))
    return Trajectory(
        user=user, turns=[turn], answer=value, final_sentence=final,
        task_type="deliberate", concept=concept, grounding=grounding,
        blocks=[code], tool_sources={"lookup": _TOOL_LOOKUP_SRC},
    )


def _multistep(rng) -> Trajectory:
    words = [rng.choice(["alpha", "beta", "gamma", "delta", "omega", "sigma", "theta"])
             for _ in range(rng.randint(3, 5))]
    block1 = f"words = {words}\nlengths = [len(w) for w in words]\ntotal = sum(lengths)\ntotal"
    block2 = "total * 2"
    ns = _fresh_ns()
    o1 = _run_block(ns, block1)
    o2 = _run_block(ns, block2)                      # uses `total` from block1's namespace
    assert o1[2] is None and o2[2] is None and o2[1] is not None
    user = (f"Take these words: {words}. Sum their character lengths, then double that sum. "
            f"Work step by step in code, using each result in the next step.")
    answer = o2[1]
    _guard_no_leak(user, answer)
    turns = [
        Turn("First, sum the word lengths.", block1, _render_obs(*o1)),
        Turn("The observed total is in scope; now double it.", block2, _render_obs(*o2)),
    ]
    return Trajectory(
        user=user, turns=turns, answer=answer,
        final_sentence=f"Doubling the observed total gives {answer}.",
        task_type="temporal", concept="codeact_multistep", grounding=False,
        blocks=[block1, block2],
    )


def _recover(rng) -> Trajectory:
    values = [rng.randint(5, 30) for _ in range(rng.randint(3, 5))]
    setup = f"record = {{'id': {rng.randint(100, 999)}, 'values': {values}}}"
    block1 = f"{setup}\nrecord['total']"             # wrong assumption: no precomputed 'total'
    block2 = "sum(record['values'])"                 # compute it from what's actually there
    ns = _fresh_ns()
    o1 = _run_block(ns, block1)                       # errors (KeyError), record still in ns
    o2 = _run_block(ns, block2)
    assert o1[2] is not None and "KeyError" in o1[2] and o2[2] is None and o2[1] is not None
    user = (f"The record has an 'id' and a 'values' list {values}. Give me the total of the values. "
            f"Run code to get it.")
    answer = o2[1]
    _guard_no_leak(user, answer)
    turns = [
        Turn("I'll assume the total is precomputed under record['total'].", block1, _render_obs(*o1)),
        Turn("That raised KeyError — my assumption was wrong, there's no 'total' key. I'll compute "
             "it from record['values'] instead.", block2, _render_obs(*o2)),
    ]
    return Trajectory(
        user=user, turns=turns, answer=answer,
        final_sentence=f"My first assumption failed (no 'total' key); computing from 'values' gives {answer}.",
        task_type="deliberate", concept="codeact_recover", grounding=True,
        blocks=[block1, block2],
    )


# ordered so selection is deterministic; grounding families flagged.
_FAMILIES: List[Tuple[str, Callable, bool]] = [
    ("codeact_compute", lambda rng: _compute(rng), False),
    ("codeact_tool", lambda rng: _tool(rng, grounding=False), False),
    ("codeact_multistep", lambda rng: _multistep(rng), False),
    ("codeact_tool_grounding", lambda rng: _tool(rng, grounding=True), True),
    ("codeact_recover", lambda rng: _recover(rng), True),
]


def _build(rng, want_grounding: bool) -> Trajectory:
    """Pick a family (grounding or not) and build a leak-free trajectory (bounded redraw)."""
    pool = [f for f in _FAMILIES if f[2] == want_grounding]
    for _ in range(8):  # deterministic bounded retry on the rare answer-leak coincidence
        _, fn, _ = pool[rng.randrange(len(pool))]
        try:
            return fn(rng)
        except _Leakage:
            continue
    # extremely unlikely (8 consecutive answer-leak coincidences). Honor want_grounding so a
    # forced-grounding slot can't silently emit a non-grounding trajectory and undercut the floor.
    return _recover(rng) if want_grounding else _compute(rng)


def iter_trajectories(seed: int, n: int, grounding_floor: float = GROUNDING_FLOOR_DEFAULT
                      ) -> Iterator[Trajectory]:
    """Yield `n` trajectories. A running-share scheduler guarantees the grounding family share
    never dips below `grounding_floor` (exposed for tests + for `generate`)."""
    import random as _r
    rng = _r.Random(seed)
    produced = 0
    grounded = 0
    for _ in range(n):
        # Force grounding whenever the PROJECTED post-emission share would fall below the floor
        # (checking the pre-item share let the tail undershoot: n=3 gave 1/3 < 0.35).
        want_grounding = grounded / (produced + 1) < grounding_floor
        traj = _build(rng, want_grounding)
        produced += 1
        grounded += int(traj.grounding)
        yield traj


class CodeActGenerator(Generator):
    """Streams executable CodeAct trajectories as schema-conformant docs."""

    name = "codeact"
    phases = (2, 3, 5)

    def __init__(self, seed: int, grounding_floor: float = GROUNDING_FLOOR_DEFAULT):
        super().__init__(seed)
        self.grounding_floor = grounding_floor

    def generate(self, target_bytes: int) -> Iterator[dict]:
        # Self-limit to ~target_bytes (the Generator contract) — stream, don't loop forever.
        produced = 0
        grounded = 0
        produced_bytes = 0
        while produced_bytes < target_bytes:
            want_grounding = grounded / (produced + 1) < self.grounding_floor
            traj = _build(self.rng, want_grounding)
            produced += 1
            grounded += int(traj.grounding)
            text = render(traj)
            phase = self.phases[self.rng.randrange(len(self.phases))]
            d = self.doc(text=text, task_type=traj.task_type, concept=traj.concept,
                         phase=phase, source=self.name)
            produced_bytes += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":  # pragma: no cover
    run_cli(CodeActGenerator)
