"""Think-in-code pretrain arm: reason → execute → answer (computed truths).

Research brief / Phase 4.4: expose the model to traces where solution work is
done by short, sandboxed Python rather than only by free-form CoT. Every final
answer is produced by exec(), never templated as a literal.

Also covers the LLM-VM bridge: short programs that *schedule* tool-like
syscalls (a frozen ``tools`` object in the sandbox) — parallel fan-out vs
sequential dependency — pairing with ``tool_curriculum`` L5 ReAct programs.

Weight: see ``synth_think_code`` in ``configs/sources.yaml``.
"""

from __future__ import annotations

from typing import Any, Iterator

from dottie.datagen.base import Generator
from dottie.datagen.code_gen import SAFE_BUILTINS, FORBIDDEN_TOKENS, _run_with_timeout


def _sandbox_eval(code: str, call: str, extras: dict[str, Any] | None = None) -> str | None:
    """Exec ``code`` then eval ``call``; return repr(result) or None on failure."""
    if any(tok in code for tok in FORBIDDEN_TOKENS) or any(
        tok in call for tok in FORBIDDEN_TOKENS
    ):
        return None

    def work():
        ns = {"__builtins__": SAFE_BUILTINS, "__name__": "ava_think_in_code"}
        if extras:
            ns.update(extras)
        exec(code, ns)
        return repr(eval(call, ns))

    try:
        return _run_with_timeout(work, timeout_s=2)
    except Exception:
        return None


class _ToolVM:
    """Minimal LLM-VM syscall table for think-in-code tool-schedule problems.

    Methods are pure lookups into a frozen table — they stand in for real tools
    so the *schedule* (parallel vs sequential) is what the model practices.
    """

    def __init__(self, table: dict[str, Any]):
        self._table = table

    def word_count(self, path: str) -> int:
        return int(self._table[("word_count", path)])

    def read_int(self, path: str, key: str) -> int:
        return int(self._table[("read_int", path, key)])

    def multiply(self, a: int, b: int) -> int:
        return int(a) * int(b)

    def add(self, a: int, b: int) -> int:
        return int(a) + int(b)


def _problem_gcd(rng) -> tuple[str, str, str, str, str] | None:
    a = rng.randint(12, 220)
    b = rng.randint(8, 180)
    code = (
        "def gcd(x, y):\n"
        "    while y:\n"
        "        x, y = y, x % y\n"
        "    return x\n"
    )
    call = f"gcd({a}, {b})"
    out = _sandbox_eval(code, call)
    if out is None:
        return None
    prompt = f"Find gcd({a}, {b}) by writing and running a short program."
    reason = (
        "1. Euclid's algorithm repeatedly replaces (x, y) with (y, x % y).\n"
        "2. When y becomes 0, x is the gcd.\n"
        "3. I implement that, then execute it on the given pair."
    )
    return prompt, reason, code, call, out


def _problem_modpow(rng) -> tuple[str, str, str, str, str] | None:
    base = rng.randint(2, 9)
    exp = rng.randint(2, 6)
    mod = rng.choice([7, 11, 13, 17, 19])
    code = (
        "def modpow(b, e, m):\n"
        "    r = 1\n"
        "    b = b % m\n"
        "    while e > 0:\n"
        "        if e % 2 == 1:\n"
        "            r = (r * b) % m\n"
        "        b = (b * b) % m\n"
        "        e = e // 2\n"
        "    return r\n"
    )
    call = f"modpow({base}, {exp}, {mod})"
    out = _sandbox_eval(code, call)
    if out is None:
        return None
    prompt = f"Compute {base}^{exp} mod {mod} using modular exponentiation in code."
    reason = (
        "1. Squaring reduces the exponent by half each loop.\n"
        "2. Multiply into the accumulator only when the current exponent bit is set.\n"
        "3. All multiplies stay mod m to keep intermediates small."
    )
    return prompt, reason, code, call, out


def _problem_sum_divisible(rng) -> tuple[str, str, str, str, str] | None:
    n = rng.randint(20, 80)
    k = rng.choice([3, 4, 5, 6, 7])
    code = (
        "def sum_divisible(n, k):\n"
        "    total = 0\n"
        "    for i in range(1, n + 1):\n"
        "        if i % k == 0:\n"
        "            total = total + i\n"
        "    return total\n"
    )
    call = f"sum_divisible({n}, {k})"
    out = _sandbox_eval(code, call)
    if out is None:
        return None
    prompt = f"Sum every integer from 1 to {n} that is divisible by {k}."
    reason = (
        f"1. Scan 1..{n} and keep only values where i % {k} == 0.\n"
        "2. Accumulate those values in a running total.\n"
        "3. Execute the loop rather than guessing the closed form."
    )
    return prompt, reason, code, call, out


def _problem_is_palindrome_int(rng) -> tuple[str, str, str, str, str] | None:
    # Build true palindromes and near-misses via digit choices.
    if rng.random() < 0.55:
        left = rng.randint(10, 99)
        n = left * 100 + int(str(left)[::-1])
    else:
        n = rng.randint(1000, 9999)
    code = (
        "def is_palindrome_int(n):\n"
        "    s = str(n)\n"
        "    return s == s[::-1]\n"
    )
    call = f"is_palindrome_int({n})"
    out = _sandbox_eval(code, call)
    if out is None:
        return None
    prompt = f"Is {n} a palindrome when written in base 10? Answer True or False."
    reason = (
        "1. Convert the integer to its decimal string.\n"
        "2. Compare the string to its reverse.\n"
        "3. Return the boolean from an executed check, not a hand count."
    )
    return prompt, reason, code, call, out


def _problem_parallel_tool_fanout(rng) -> tuple[str, str, str, str, str] | None:
    """Parallel tool schedule: two independent word_counts, then add."""
    f1, f2 = rng.sample(
        ["a.py", "b.py", "utils.py", "core.py", "notes.txt", "data.csv"], 2
    )
    w1, w2 = rng.randint(11, 90), rng.randint(11, 90)
    tools = _ToolVM({
        ("word_count", f1): w1,
        ("word_count", f2): w2,
    })
    code = (
        "def combined_word_count(tools, f1, f2):\n"
        "    # Independent syscalls — safe to schedule in parallel.\n"
        "    r0 = tools.word_count(f1)\n"
        "    r1 = tools.word_count(f2)\n"
        "    return tools.add(r0, r1)\n"
    )
    call = f"combined_word_count(tools, {f1!r}, {f2!r})"
    out = _sandbox_eval(code, call, extras={"tools": tools})
    if out is None:
        return None
    prompt = (
        f"Using a tool VM, get the combined word count of {f1} and {f2}. "
        f"The two counts are independent — schedule a parallel fan-out, then reduce."
    )
    reason = (
        "1. Treat tools as LLM-VM syscalls, not free-form guesses.\n"
        "2. word_count(f1) and word_count(f2) share no data dependency → parallel.\n"
        "3. add reduces the two registers; execute the schedule rather than mental math."
    )
    return prompt, reason, code, call, out


def _problem_sequential_tool_dep(rng) -> tuple[str, str, str, str, str] | None:
    """Sequential tool schedule: read then multiply (dependent)."""
    path = rng.choice(["config.py", "manifest.yaml", "trainer.py"])
    key = rng.choice(["batch_size", "num_workers", "n_layers"])
    base = rng.randint(4, 48)
    factor = rng.randint(2, 11)
    tools = _ToolVM({("read_int", path, key): base})
    code = (
        "def scale_config(tools, path, key, factor):\n"
        "    # Dependent: multiply needs the read result — sequential only.\n"
        "    v = tools.read_int(path, key)\n"
        "    return tools.multiply(v, factor)\n"
    )
    call = f"scale_config(tools, {path!r}, {key!r}, {factor})"
    out = _sandbox_eval(code, call, extras={"tools": tools})
    if out is None:
        return None
    prompt = (
        f"Using a tool VM, read {key} from {path} and multiply by {factor}. "
        f"Do not pretend the multiply is parallel with the read."
    )
    reason = (
        "1. Dependency analysis: multiply's args come from the read Observation.\n"
        "2. Schedule is sequential — parallel fan-out would be incorrect here.\n"
        "3. Execute read_int then multiply as syscalls; answer from the return value."
    )
    return prompt, reason, code, call, out


_PROBLEMS = (
    _problem_gcd,
    _problem_modpow,
    _problem_sum_divisible,
    _problem_is_palindrome_int,
)

_TOOL_SCHEDULE_PROBLEMS = (
    _problem_parallel_tool_fanout,
    _problem_sequential_tool_dep,
)


def render_think_in_code(
    prompt: str,
    reason: str,
    code: str,
    call: str,
    result_repr: str,
) -> str:
    """Canonical reason → code → execution → Final answer dialect."""
    answer = result_repr
    # Prefer unquoted bools/ints when repr is already canonical for them.
    return (
        f"Problem: {prompt}\n\n"
        f"Reasoning:\n{reason}\n\n"
        f"```python\n{code.rstrip()}\nprint({call})\n```\n\n"
        f"Execution:\n```\n{result_repr}\n```\n\n"
        f"Final answer: {answer}\n"
    )


class ThinkInCodeGenerator(Generator):
    """P3/P5 deliberate arm: classic code-mediated solutions (live mixture)."""

    name = "think_code"
    phases = (3, 5)

    def generate(self, target_bytes: int) -> Iterator[dict]:
        produced = 0
        while produced < target_bytes:
            fn = self.rng.choice(_PROBLEMS)
            got = None
            for _ in range(8):
                got = fn(self.rng)
                if got is not None:
                    break
            if got is None:
                continue
            prompt, reason, code, call, out = got
            text = render_think_in_code(prompt, reason, code, call, out)
            phase = 3 if self.rng.random() < 0.7 else 5
            doc = self.doc(
                text=text,
                task_type="deliberate",
                concept="think_in_code",
                phase=phase,
                source="synth_think_code",
            )
            produced += len(doc["text"].encode("utf-8"))
            yield doc


class ThinkToolsGenerator(Generator):
    """LLM-VM tool schedules in think-in-code dialect (parallel vs sequential).

    Spec 15: enters ``sources.yaml`` at weight 0 so the live mini diet is
    untouched. Activate with ``synth_tool_use`` post-mini for transfer.
    """

    name = "think_tools"
    phases = (3, 4, 5)

    def generate(self, target_bytes: int) -> Iterator[dict]:
        produced = 0
        while produced < target_bytes:
            fn = self.rng.choice(_TOOL_SCHEDULE_PROBLEMS)
            got = None
            for _ in range(8):
                got = fn(self.rng)
                if got is not None:
                    break
            if got is None:
                continue
            prompt, reason, code, call, out = got
            text = render_think_in_code(prompt, reason, code, call, out)
            # p3 heavy (schedule skill), p4 long-context adjacency, p5 anneal.
            r = self.rng.random()
            phase = 3 if r < 0.55 else (4 if r < 0.80 else 5)
            doc = self.doc(
                text=text,
                task_type="tool_selection",
                concept="think_tools",
                phase=phase,
                source="synth_think_tools",
            )
            produced += len(doc["text"].encode("utf-8"))
            yield doc
