# Solo personal project, no connection to employer, built with public/free-tier only
"""VerifiedTaskProvider — assistant-realistic task families with deterministic verifiers.

Closes Dottie's training-signal gap: today every engine trace records ``r_task=null``
("unscored, no verifier"). This module supplies task families where the verifier is
deterministic Python computed from the SAME values rendered into the prompt — the factory's
spec-12 T12R.1 verified-return pattern (see ``apps/ava-factory/ava/datagen/codeact.py``):
answers are COMPUTED at build time, never templated into the prompt as literal text.

Families (all deterministic per ``(family, seed)``):
  * ``compute``    — multi-step arithmetic reduction over a rendered list; verify exact integer.
  * ``extract``    — a small generated inventory document is embedded in the prompt; the task is
                     a filtered aggregate per spec; verify the computed aggregate.
  * ``tool_chain`` — the needed data lives ONLY inside two bound sandbox tools (never in the
                     prompt); the task composes their outputs; verify the provider-side
                     composition AND that both tools were really called (from the REAL
                     observations' recorded tool_calls).
  * ``file_ops``   — write a derived file under the sandbox scratch dir (its cwd), read it back,
                     and report a content digest; verify by re-deriving the exact expected bytes.
                     HONEST LIMIT: the sandbox scratch dir is ephemeral and inaccessible to the
                     parent after the run, so the verifier proves the derived CONTENT (digest),
                     not the write syscall itself.
  * ``constraint`` — produce text meeting CHECKABLE constraints (a must-include token COMPUTED
                     from prompt values, a forbidden word, a word-count band). HONEST LIMIT:
                     only the constraints are verified — prose QUALITY is not scored, and the
                     verifier says so. Graded partial credit (documented below).

Grading contract: ``task.verify(final_text, observations) -> r_task`` in ``[0.0, 1.0]``.
Binary families return exactly 0.0 or 1.0. ``constraint`` is the one graded family: credit is
GATED on the computed token (no token -> 0.0, because without it there is no evidence the
values were engaged), then r_task = satisfied_constraints / 3.

No answer leakage: every build runs the same token matcher the verifier uses against the
prompt and redraws (bounded, deterministic) on a collision — so a policy that merely echoes
the prompt can NEVER score (the property the echo-backend test asserts). Naming guard: the
task-success scalar is ``r_task``; "reward" stays reserved for data-quality filter scores.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

FAMILIES: tuple[str, ...] = (
    "compute",
    "extract",
    "tool_chain",
    "file_ops",
    "constraint",
)

_MAX_REDRAWS = 8  # deterministic bounded retry on the rare answer-leak coincidence


class TaskBuildError(RuntimeError):
    """A family/seed could not produce a leak-free task within the redraw bound (honest failure)."""


# ---------------------------------------------------------------------------
# Token matching — shared by the verifiers AND the no-leakage guard, so the
# guarantee is exact: "the token that scores cannot be scored off the prompt".
# ---------------------------------------------------------------------------


def answer_token_present(token: str, text: str, *, ignore_case: bool = False) -> bool:
    """True iff ``token`` appears in ``text`` as a standalone token.

    Boundary guards keep '4' from matching inside '42', '-53' inside '12-53', and '42'
    inside '42.5' — while a sentence-ending period ('the result is 42.') still matches.
    This exact matcher is used both to grade finals and to guard prompts."""
    if not token or not text:
        return False
    pattern = r"(?<![\w.\-])" + re.escape(token) + r"(?!\w)(?!\.\d)"
    return re.search(pattern, text, re.IGNORECASE if ignore_case else 0) is not None


def _called_tools(observations: Sequence[Any]) -> set:
    """Tool names actually called on SUCCESSFUL steps, from real observations.

    Accepts factory ``Observation`` objects or trace-round-tripped dicts."""
    names: set = set()
    for o in observations or ():
        if isinstance(o, dict):
            ok, calls = o.get("ok", o.get("error") is None), o.get("tool_calls", [])
        else:
            ok, calls = getattr(o, "ok", False), getattr(o, "tool_calls", [])
        if not ok:
            continue
        for c in calls:
            names.add(c.get("tool"))
    return names


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedTask:
    """One buildable, verifiable task instance. ``verify`` is deterministic Python whose
    expectation was computed from the same values rendered into ``prompt``."""

    task_id: str
    family_id: str
    seed: int
    prompt: str
    verify_fn: Callable[[str, Sequence[Any]], float]
    tool_names: tuple[str, ...] = ()  # display signatures, e.g. "part_lookup(part_id)"
    tool_sources: dict[str, str] = field(default_factory=dict)
    expected: str = ""  # canonical answer token (provider-side truth)
    grading: str = "binary"  # "binary" | "graded"
    verifier_note: str = ""

    def verify(self, final_text: str, observations: Sequence[Any]) -> float:
        return self.verify_fn(final_text or "", observations or [])

    def verifier_detail(self) -> dict[str, Any]:
        """Server-side verifier description for traces/API (never shown to the policy)."""
        return {
            "family": self.family_id,
            "seed": self.seed,
            "expected": self.expected,
            "grading": self.grading,
            "note": self.verifier_note,
        }


def _binary_token_verify(
    expected: str, *, ignore_case: bool = False
) -> Callable[[str, Sequence[Any]], float]:
    def verify(final_text: str, observations: Sequence[Any]) -> float:
        return (
            1.0
            if answer_token_present(expected, final_text, ignore_case=ignore_case)
            else 0.0
        )

    return verify


# ---------------------------------------------------------------------------
# Families — every expected value is COMPUTED here from the values that go
# into the prompt; the prompt never carries the expectation as literal text.
# ---------------------------------------------------------------------------

_ITEM_WORDS = (
    "bolt",
    "washer",
    "gasket",
    "spring",
    "bearing",
    "clamp",
    "valve",
    "rotor",
    "flange",
    "socket",
    "bracket",
    "pin",
)
_LINE_WORDS = (
    "alpha",
    "bravo",
    "canyon",
    "delta",
    "ember",
    "falcon",
    "granite",
    "harbor",
)
_FORBIDDEN_WORDS = ("obviously", "basically", "literally", "essentially")


def _build_compute(rng: random.Random, seed: int) -> VerifiedTask:
    nums = [rng.randint(3, 97) for _ in range(6)]
    evens = [x for x in nums if x % 2 == 0]
    odds = [x for x in nums if x % 2 == 1]
    expected = sum(x * x for x in evens) - sum(odds)  # computed, never templated
    prompt = (
        f"Data list: {nums}. Compute (the sum of the squares of the even numbers) minus "
        "(the sum of the odd numbers). Do the arithmetic in the sandbox, not in your head. "
        "Report the result in your final answer as a plain integer (may be negative, no "
        "thousands separators)."
    )
    return VerifiedTask(
        task_id=f"compute-{seed}",
        family_id="compute",
        seed=seed,
        prompt=prompt,
        expected=str(expected),
        verify_fn=_binary_token_verify(str(expected)),
        verifier_note="binary: exact computed integer must appear as a standalone token in the FINAL",
    )


def _build_extract(rng: random.Random, seed: int) -> VerifiedTask:
    n = rng.randint(5, 8)
    names = rng.sample(_ITEM_WORDS, n)
    items = [(name, rng.randint(1, 40), rng.randint(2, 99)) for name in names]
    threshold = rng.randint(5, 20)
    expected = sum(q * p for _, q, p in items if q >= threshold)  # computed aggregate
    doc = "\n".join(f"- {name}: qty={q} unit_price_cents={p}" for name, q, p in items)
    prompt = (
        "Here is an inventory document:\n"
        f"{doc}\n"
        f"Compute the total value in cents (qty * unit_price_cents, summed) of the items whose "
        f"qty is at least {threshold}. Use the sandbox to extract and aggregate. Report the "
        "total in your final answer as a plain integer."
    )
    return VerifiedTask(
        task_id=f"extract-{seed}",
        family_id="extract",
        seed=seed,
        prompt=prompt,
        expected=str(expected),
        verify_fn=_binary_token_verify(str(expected)),
        verifier_note="binary: computed filtered aggregate must appear as a standalone token in the FINAL",
    )


def _build_tool_chain(rng: random.Random, seed: int) -> VerifiedTask:
    part_ids = [f"P{rng.randint(10, 99)}{c}" for c in ("A", "B", "C", "D")]
    bins = ("north", "south", "east", "west")
    table = {
        pid: {"weight_g": rng.randint(50, 900), "bin": rng.choice(bins)}
        for pid in part_ids
    }
    rates = {b: rng.randint(2, 9) for b in bins}
    queried = rng.sample(part_ids, 2)
    # Provider-side composition of the two tools' outputs — the verified expectation.
    expected = sum(table[p]["weight_g"] * rates[table[p]["bin"]] for p in queried)
    part_lookup_src = (
        "def part_lookup(part_id):\n"
        f"    table = {table!r}\n"
        "    return table.get(part_id)\n"
    )
    bin_rate_src = (
        "def bin_rate(bin_name):\n"
        f"    rates = {rates!r}\n"
        "    return rates.get(bin_name)\n"
    )
    prompt = (
        f"For parts {queried[0]} and {queried[1]}: call part_lookup(part_id) to get each part's "
        "weight_g and bin, then call bin_rate(bin_name) for each part's bin. The shipping score "
        "is the sum over both parts of weight_g * rate. The part data exists ONLY inside these "
        "tools — you must call them. Report the shipping score in your final answer as a plain "
        "integer."
    )
    expected_s = str(expected)

    def verify(final_text: str, observations: Sequence[Any]) -> float:
        called = _called_tools(observations)
        if not {"part_lookup", "bin_rate"} <= called:
            # The data is unreachable without the tools; a "correct" number without both real
            # tool calls would be a guess/leak, so it earns 0.0 (documented, binary).
            return 0.0
        return 1.0 if answer_token_present(expected_s, final_text) else 0.0

    return VerifiedTask(
        task_id=f"tool_chain-{seed}",
        family_id="tool_chain",
        seed=seed,
        prompt=prompt,
        expected=expected_s,
        verify_fn=verify,
        tool_names=("part_lookup(part_id)", "bin_rate(bin_name)"),
        tool_sources={"part_lookup": part_lookup_src, "bin_rate": bin_rate_src},
        verifier_note=(
            "binary: computed tool-output composition must appear in the FINAL AND both "
            "tools must show real recorded calls in the observations"
        ),
    )


def _build_file_ops(rng: random.Random, seed: int) -> VerifiedTask:
    k = rng.randint(4, 7)
    lines = [f"{rng.choice(_LINE_WORDS)} {rng.randint(10, 999)}" for _ in range(k)]
    # Exact expected file bytes, re-derived provider-side (the digest verifies the content).
    content = "\n".join(line.upper() for line in lines) + "\n"
    digest12 = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    doc = "\n".join(lines)
    prompt = (
        "In the sandbox, take these lines:\n"
        f"{doc}\n"
        "Write them to a file named report.txt in the current directory (the sandbox scratch "
        "dir), each line UPPERCASED, joined with '\\n', with a single trailing newline. Then "
        "read the file back as bytes and compute its SHA-256 hex digest. Report in your final "
        "answer the first 12 hex characters of that digest."
    )
    return VerifiedTask(
        task_id=f"file_ops-{seed}",
        family_id="file_ops",
        seed=seed,
        prompt=prompt,
        expected=digest12,
        verify_fn=_binary_token_verify(digest12, ignore_case=True),
        verifier_note=(
            "binary: sha256[:12] of the re-derived expected file bytes must appear in "
            "the FINAL. Limit (honest): proves the derived content, not the write "
            "syscall — the sandbox scratch dir is destroyed before the parent could "
            "inspect it."
        ),
    )


def _build_constraint(rng: random.Random, seed: int) -> VerifiedTask:
    a, b, c = rng.randint(3, 30), rng.randint(3, 30), rng.randint(3, 30)
    k = (a * b + c) % 89
    token = f"TAG-{k:02d}"  # computed from prompt values; digits never rendered
    forbidden = rng.choice(_FORBIDDEN_WORDS)
    lo = rng.randint(30, 50)
    hi = lo + 40
    prompt = (
        f"Write a short note (between {lo} and {hi} words) about keeping a tidy workshop. "
        f"Compute k = (a*b + c) mod 89 where a={a}, b={b}, c={c}, and include somewhere in the "
        "note the exact token TAG-<k> with k zero-padded to two digits (e.g. the k=5 token "
        f"would be written with digits 05). Do not use the word '{forbidden}'. Only these "
        "mechanical constraints are checked; the quality of the prose is NOT scored."
    )

    def verify(final_text: str, observations: Sequence[Any]) -> float:
        text = final_text or ""
        if not answer_token_present(token, text):
            return 0.0  # credit is gated on the COMPUTED token — without it, no evidence of work
        wc_ok = lo <= len(text.split()) <= hi
        forb_ok = re.search(rf"\b{re.escape(forbidden)}\b", text, re.IGNORECASE) is None
        return round((1 + int(wc_ok) + int(forb_ok)) / 3, 4)

    return VerifiedTask(
        task_id=f"constraint-{seed}",
        family_id="constraint",
        seed=seed,
        prompt=prompt,
        expected=token,
        verify_fn=verify,
        grading="graded",
        verifier_note=(
            "graded [0,1]: credit gated on the computed token (absent -> 0.0), then "
            "satisfied/3 over {token, word-count band, forbidden word}. HONEST LIMIT: "
            "only constraints are verified, never prose quality."
        ),
    )


_BUILDERS: dict[str, Callable[[random.Random, int], VerifiedTask]] = {
    "compute": _build_compute,
    "extract": _build_extract,
    "tool_chain": _build_tool_chain,
    "file_ops": _build_file_ops,
    "constraint": _build_constraint,
}


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class VerifiedTaskProvider:
    """Deterministic (family, seed) -> VerifiedTask with a built-in no-leakage guard."""

    families: tuple[str, ...] = FAMILIES

    def build(self, family: str, seed: int) -> VerifiedTask:
        if family not in _BUILDERS:
            raise ValueError(
                f"unknown task family {family!r}; choices: {', '.join(FAMILIES)}"
            )
        builder = _BUILDERS[family]
        for attempt in range(_MAX_REDRAWS):
            # str seeds hash via sha512 in random.Random — stable across runs and processes.
            rng = random.Random(f"dottie-task:{family}:{seed}:{attempt}")
            task = builder(rng, seed)
            if not answer_token_present(task.expected, task.prompt, ignore_case=True):
                return task
        raise TaskBuildError(  # pragma: no cover - needs 8 consecutive leak coincidences
            f"could not build a leak-free {family!r} task for seed {seed} in "
            f"{_MAX_REDRAWS} redraws; refusing to emit a leaking prompt"
        )

    def batch_seeds(
        self, family: str, n: int, seeds: Sequence[int] | None = None
    ) -> list[tuple[str, int]]:
        """(family, seed) pairs for a climb batch. ``family='mixed'`` cycles all families
        deterministically. Default seeds are 0..n-1."""
        use = list(seeds) if seeds is not None else list(range(n))
        if len(use) != n:
            raise ValueError(f"seeds length {len(use)} != n {n}")
        if family == "mixed":
            return [(FAMILIES[i % len(FAMILIES)], s) for i, s in enumerate(use)]
        if family not in _BUILDERS:
            raise ValueError(
                f"unknown task family {family!r}; choices: "
                f"{', '.join(FAMILIES)} or 'mixed'"
            )
        return [(family, s) for s in use]
