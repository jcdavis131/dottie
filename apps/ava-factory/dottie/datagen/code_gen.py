"""Phase-2 code corpus: small Python functions/classes with doctests whose
expected output is produced by actually exec()-ing the snippet inside a
restricted sandbox, never guessed. Any candidate that raises or times out is
discarded and a new one is drawn from the same seeded RNG stream (so
determinism is preserved -- the discard/retry loop is itself deterministic).
"""

from __future__ import annotations

import builtins as _builtins_module
from typing import Iterator

from dottie.datagen.base import Generator

try:
    import signal as _signal
    _HAS_ALARM = hasattr(_signal, "SIGALRM")
except ImportError:  # pragma: no cover
    _signal = None
    _HAS_ALARM = False

# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

SAFE_NAMES = [
    "abs", "min", "max", "sum", "len", "range", "enumerate", "zip", "sorted",
    "reversed", "int", "float", "str", "bool", "list", "dict", "set", "tuple",
    "print", "isinstance", "ValueError", "TypeError",
]
SAFE_BUILTINS = {name: getattr(_builtins_module, name) for name in SAFE_NAMES}
# __build_class__ is the interpreter's internal primitive for the `class`
# statement -- without it, exec() cannot run ANY class definition at all
# under a restricted __builtins__, which would make "simple classes"
# (explicitly required content) impossible to sandbox. It is not itself a
# capability leak (unlike open/__import__/eval/exec/compile, which stay
# excluded below), so it is added here deliberately.
SAFE_BUILTINS["__build_class__"] = _builtins_module.__build_class__

FORBIDDEN_TOKENS = ("import ", "__import__", "open(", "eval(", "exec(", "compile(")


class _CodeGenTimeout(Exception):
    pass


def _run_with_timeout(fn, timeout_s: int = 2):
    if _HAS_ALARM:
        def _handler(signum, frame):
            raise _CodeGenTimeout("sandboxed execution timed out")

        old_handler = _signal.signal(_signal.SIGALRM, _handler)
        _signal.alarm(timeout_s)
        try:
            return fn()
        finally:
            _signal.alarm(0)
            _signal.signal(_signal.SIGALRM, old_handler)
    else:
        # Non-POSIX dev machines (e.g. Windows) have no SIGALRM; run
        # best-effort without a hard wall-clock cutoff. Production data
        # generation always runs inside the Linux container where the
        # alarm-based timeout is active.
        return fn()


def run_sandboxed(code: str, steps: list[tuple[str, bool]]):
    """Executes `code` (a function/class definition) then replays `steps`
    (source, is_expr) in the same namespace. is_expr=True steps are eval'd
    and their repr() captured; is_expr=False steps are exec'd for side
    effect only. Returns a list of (source, repr_or_None) on success, or
    None if anything raises or the 2s timeout fires."""
    if any(tok in code for tok in FORBIDDEN_TOKENS):
        return None
    for src, _ in steps:
        if any(tok in src for tok in FORBIDDEN_TOKENS):
            return None

    def work():
        # __name__ is required by the interpreter's class-creation machinery
        # (it becomes the class's __module__); it is plumbing, not a
        # capability, so it is safe to seed here.
        ns = {"__builtins__": SAFE_BUILTINS, "__name__": "dottie_datagen_sandbox"}
        exec(code, ns)
        rendered = []
        for src, is_expr in steps:
            if is_expr:
                val = eval(src, ns)
                rendered.append((src, repr(val)))
            else:
                exec(src, ns)
                rendered.append((src, None))
        return rendered

    try:
        return _run_with_timeout(work, timeout_s=2)
    except Exception:
        return None


def render_snippet(code: str, description: str, rendered_steps: list[tuple[str, str | None]]) -> str:
    doc_lines = [f'    """{description}', "", "    Examples:"]
    for src, expected in rendered_steps:
        doc_lines.append(f"    >>> {src}")
        if expected is not None:
            doc_lines.append(f"    {expected}")
    doc_lines.append('    """')
    docstring = "\n".join(doc_lines)

    lines = code.rstrip("\n").split("\n")
    # insert the docstring as the first line of the first def/class body
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.lstrip().startswith(("def ", "class ")) and line.rstrip().endswith(":"):
            out.append(docstring)
            inserted = True
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Templates -- each returns (code, steps, concept, description)
# ---------------------------------------------------------------------------

_WORDS = sorted(["python", "hello", "level", "radar", "banana", "apple", "kayak", "noon", "rotor",
                  "widget", "gadget", "october", "zebra", "yellow", "orange", "purple", "civic", "matter"])


def _tmpl_factorial(rng):
    code = (
        "def factorial(n):\n"
        "    result = 1\n"
        "    for i in range(1, n + 1):\n"
        "        result = result * i\n"
        "    return result\n"
    )
    ns = sorted(rng.sample(range(0, 9), 3))
    steps = [(f"factorial({n})", True) for n in ns]
    return code, steps, "factorial", "Computes n! (the factorial of n) iteratively."


def _tmpl_fibonacci(rng):
    code = (
        "def fibonacci(n):\n"
        "    a, b = 0, 1\n"
        "    for _ in range(n):\n"
        "        a, b = b, a + b\n"
        "    return a\n"
    )
    ns = sorted(rng.sample(range(0, 15), 3))
    steps = [(f"fibonacci({n})", True) for n in ns]
    return code, steps, "fibonacci", "Returns the nth Fibonacci number (0-indexed, fibonacci(0) == 0)."


def _tmpl_is_prime(rng):
    code = (
        "def is_prime(n):\n"
        "    if n < 2:\n"
        "        return False\n"
        "    i = 2\n"
        "    while i * i <= n:\n"
        "        if n % i == 0:\n"
        "            return False\n"
        "        i = i + 1\n"
        "    return True\n"
    )
    ns = sorted(rng.sample(range(0, 30), 4))
    steps = [(f"is_prime({n})", True) for n in ns]
    return code, steps, "is_prime", "Checks primality of n by trial division."


def _tmpl_gcd(rng):
    code = (
        "def gcd(a, b):\n"
        "    while b:\n"
        "        a, b = b, a % b\n"
        "    return a\n"
    )
    pairs = [(rng.randint(1, 100), rng.randint(1, 100)) for _ in range(3)]
    steps = [(f"gcd({a}, {b})", True) for a, b in pairs]
    return code, steps, "gcd", "Computes the greatest common divisor of a and b via the Euclidean algorithm."


def _tmpl_reverse_string(rng):
    code = (
        "def reverse_string(s):\n"
        "    return s[::-1]\n"
    )
    words = rng.sample(_WORDS, 3)
    steps = [(f"reverse_string({w!r})", True) for w in words]
    return code, steps, "reverse_string", "Reverses a string using slicing."


def _tmpl_is_palindrome(rng):
    code = (
        "def is_palindrome(s):\n"
        "    cleaned = s.lower()\n"
        "    return cleaned == cleaned[::-1]\n"
    )
    words = list(rng.sample(_WORDS, 2)) + ["level", "Racecar"]
    steps = [(f"is_palindrome({w!r})", True) for w in words]
    return code, steps, "is_palindrome", "Checks whether a string reads the same forwards and backwards (case-insensitive)."


def _tmpl_sum_list(rng):
    code = (
        "def sum_list(nums):\n"
        "    total = 0\n"
        "    for x in nums:\n"
        "        total = total + x\n"
        "    return total\n"
    )
    lists = [[rng.randint(-20, 20) for _ in range(rng.randint(1, 6))] for _ in range(3)]
    steps = [(f"sum_list({lst!r})", True) for lst in lists]
    return code, steps, "sum_list", "Sums the numbers in a list by accumulation."


def _tmpl_max_list(rng):
    code = (
        "def max_list(nums):\n"
        "    best = nums[0]\n"
        "    for x in nums[1:]:\n"
        "        if x > best:\n"
        "            best = x\n"
        "    return best\n"
    )
    lists = [[rng.randint(-20, 20) for _ in range(rng.randint(1, 6))] for _ in range(3)]
    steps = [(f"max_list({lst!r})", True) for lst in lists]
    return code, steps, "max_list", "Finds the largest element of a non-empty list by scanning."


def _tmpl_count_vowels(rng):
    code = (
        "def count_vowels(s):\n"
        "    vowels = 'aeiouAEIOU'\n"
        "    count = 0\n"
        "    for ch in s:\n"
        "        if ch in vowels:\n"
        "            count = count + 1\n"
        "    return count\n"
    )
    words = rng.sample(_WORDS, 3)
    steps = [(f"count_vowels({w!r})", True) for w in words]
    return code, steps, "count_vowels", "Counts vowel characters in a string."


def _tmpl_dedup(rng):
    code = (
        "def dedup_preserve_order(items):\n"
        "    seen = []\n"
        "    result = []\n"
        "    for x in items:\n"
        "        if x not in seen:\n"
        "            seen.append(x)\n"
        "            result.append(x)\n"
        "    return result\n"
    )
    base = [rng.randint(0, 5) for _ in range(rng.randint(4, 9))]
    steps = [("dedup_preserve_order(" + repr(base) + ")", True)]
    base2 = [rng.randint(0, 5) for _ in range(rng.randint(4, 9))]
    steps.append(("dedup_preserve_order(" + repr(base2) + ")", True))
    return code, steps, "dedup", "Removes duplicate elements while preserving first-seen order."


def _tmpl_bubble_sort(rng):
    code = (
        "def bubble_sort(nums):\n"
        "    arr = list(nums)\n"
        "    n = len(arr)\n"
        "    for i in range(n):\n"
        "        for j in range(0, n - i - 1):\n"
        "            if arr[j] > arr[j + 1]:\n"
        "                arr[j], arr[j + 1] = arr[j + 1], arr[j]\n"
        "    return arr\n"
    )
    lists = [[rng.randint(-20, 20) for _ in range(rng.randint(2, 7))] for _ in range(2)]
    steps = [(f"bubble_sort({lst!r})", True) for lst in lists]
    return code, steps, "bubble_sort", "Sorts a list ascending using the bubble sort algorithm."


def _tmpl_linear_search(rng):
    code = (
        "def linear_search(nums, target):\n"
        "    for i, x in enumerate(nums):\n"
        "        if x == target:\n"
        "            return i\n"
        "    return -1\n"
    )
    lst = [rng.randint(0, 9) for _ in range(rng.randint(3, 8))]
    present = rng.choice(lst)
    absent = 99
    steps = [(f"linear_search({lst!r}, {present!r})", True), (f"linear_search({lst!r}, {absent!r})", True)]
    return code, steps, "linear_search", "Finds the index of target in nums, or -1 if not present."


def _tmpl_sum_digits(rng):
    code = (
        "def sum_digits(n):\n"
        "    n = abs(n)\n"
        "    total = 0\n"
        "    while n > 0:\n"
        "        total = total + n % 10\n"
        "        n = n // 10\n"
        "    return total\n"
    )
    ns = [rng.randint(0, 999999) for _ in range(3)]
    steps = [(f"sum_digits({n})", True) for n in ns]
    return code, steps, "sum_digits", "Sums the decimal digits of an integer."


def _tmpl_running_total(rng):
    code = (
        "def running_total(nums):\n"
        "    result = []\n"
        "    total = 0\n"
        "    for x in nums:\n"
        "        total = total + x\n"
        "        result.append(total)\n"
        "    return result\n"
    )
    lst = [rng.randint(-10, 10) for _ in range(rng.randint(2, 7))]
    steps = [(f"running_total({lst!r})", True)]
    return code, steps, "running_total", "Returns the running (cumulative) sum of a list of numbers."


def _tmpl_flatten(rng):
    code = (
        "def flatten_2level(nested):\n"
        "    result = []\n"
        "    for sub in nested:\n"
        "        for x in sub:\n"
        "            result.append(x)\n"
        "    return result\n"
    )
    nested = [[rng.randint(0, 9) for _ in range(rng.randint(1, 3))] for _ in range(rng.randint(2, 4))]
    steps = [(f"flatten_2level({nested!r})", True)]
    return code, steps, "flatten", "Flattens a list of lists by one level."


def _tmpl_matrix_transpose(rng):
    code = (
        "def matrix_transpose(matrix):\n"
        "    rows = len(matrix)\n"
        "    cols = len(matrix[0])\n"
        "    result = []\n"
        "    for c in range(cols):\n"
        "        new_row = []\n"
        "        for r in range(rows):\n"
        "            new_row.append(matrix[r][c])\n"
        "        result.append(new_row)\n"
        "    return result\n"
    )
    rows, cols = rng.randint(2, 3), rng.randint(2, 3)
    matrix = [[rng.randint(0, 9) for _ in range(cols)] for _ in range(rows)]
    steps = [(f"matrix_transpose({matrix!r})", True)]
    return code, steps, "matrix_transpose", "Transposes a rectangular matrix represented as a list of row-lists."


def _tmpl_second_largest(rng):
    code = (
        "def second_largest(nums):\n"
        "    uniq = sorted(set(nums), reverse=True)\n"
        "    return uniq[1]\n"
    )
    base = list(rng.sample(range(0, 30), rng.randint(4, 8)))
    steps = [(f"second_largest({base!r})", True)]
    return code, steps, "second_largest", "Finds the second-largest distinct value in a list."


def _tmpl_merge_sorted(rng):
    code = (
        "def merge_sorted(a, b):\n"
        "    result = []\n"
        "    i = 0\n"
        "    j = 0\n"
        "    while i < len(a) and j < len(b):\n"
        "        if a[i] <= b[j]:\n"
        "            result.append(a[i])\n"
        "            i = i + 1\n"
        "        else:\n"
        "            result.append(b[j])\n"
        "            j = j + 1\n"
        "    result.extend(a[i:])\n"
        "    result.extend(b[j:])\n"
        "    return result\n"
    )
    a = sorted(rng.sample(range(0, 20), rng.randint(2, 5)))
    b = sorted(rng.sample(range(0, 20), rng.randint(2, 5)))
    steps = [(f"merge_sorted({a!r}, {b!r})", True)]
    return code, steps, "merge_sorted", "Merges two already-sorted lists into one sorted list."


def _tmpl_rotate_list(rng):
    code = (
        "def rotate_list(nums, k):\n"
        "    n = len(nums)\n"
        "    if n == 0:\n"
        "        return list(nums)\n"
        "    k = k % n\n"
        "    return nums[k:] + nums[:k]\n"
    )
    lst = [rng.randint(0, 9) for _ in range(rng.randint(3, 7))]
    k = rng.randint(0, 10)
    steps = [(f"rotate_list({lst!r}, {k})", True)]
    return code, steps, "rotate_list", "Rotates a list left by k positions."


def _tmpl_char_frequency(rng):
    code = (
        "def char_frequency(s):\n"
        "    freq = {}\n"
        "    for ch in s:\n"
        "        if ch in freq:\n"
        "            freq[ch] = freq[ch] + 1\n"
        "        else:\n"
        "            freq[ch] = 1\n"
        "    return freq\n"
    )
    word = rng.choice(_WORDS)
    steps = [(f"char_frequency({word!r})", True)]
    return code, steps, "char_frequency", "Counts occurrences of each character in a string."


def _tmpl_stack_class(rng):
    code = (
        "class Stack:\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "\n"
        "    def push(self, x):\n"
        "        self.items.append(x)\n"
        "\n"
        "    def pop(self):\n"
        "        return self.items.pop()\n"
        "\n"
        "    def peek(self):\n"
        "        return self.items[-1]\n"
        "\n"
        "    def is_empty(self):\n"
        "        return len(self.items) == 0\n"
        "\n"
        "    def size(self):\n"
        "        return len(self.items)\n"
    )
    vals = [rng.randint(0, 9) for _ in range(3)]
    steps = [
        ("s = Stack()", False),
        (f"s.push({vals[0]})", False),
        (f"s.push({vals[1]})", False),
        (f"s.push({vals[2]})", False),
        ("s.pop()", True),
        ("s.size()", True),
        ("s.is_empty()", True),
    ]
    return code, steps, "stack", "A simple last-in-first-out Stack class backed by a Python list."


def _tmpl_point_class(rng):
    code = (
        "class Point:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "        self.y = y\n"
        "\n"
        "    def distance_squared(self, other):\n"
        "        dx = self.x - other.x\n"
        "        dy = self.y - other.y\n"
        "        return dx * dx + dy * dy\n"
        "\n"
        "    def translate(self, dx, dy):\n"
        "        return Point(self.x + dx, self.y + dy)\n"
        "\n"
        "    def __repr__(self):\n"
        "        return 'Point(' + str(self.x) + ', ' + str(self.y) + ')'\n"
    )
    x1, y1 = rng.randint(-5, 5), rng.randint(-5, 5)
    x2, y2 = rng.randint(-5, 5), rng.randint(-5, 5)
    dx, dy = rng.randint(-5, 5), rng.randint(-5, 5)
    steps = [
        (f"p1 = Point({x1}, {y1})", False),
        (f"p2 = Point({x2}, {y2})", False),
        ("p1.distance_squared(p2)", True),
        (f"p1.translate({dx}, {dy})", True),
    ]
    return code, steps, "point_class", "A 2D Point class with squared distance and translation."


def _tmpl_word_counter_class(rng):
    code = (
        "class WordCounter:\n"
        "    def __init__(self):\n"
        "        self.counts = {}\n"
        "\n"
        "    def add(self, word):\n"
        "        if word in self.counts:\n"
        "            self.counts[word] = self.counts[word] + 1\n"
        "        else:\n"
        "            self.counts[word] = 1\n"
        "\n"
        "    def count_of(self, word):\n"
        "        if word in self.counts:\n"
        "            return self.counts[word]\n"
        "        return 0\n"
        "\n"
        "    def total(self):\n"
        "        return sum(self.counts.values())\n"
    )
    w1, w2 = rng.sample(_WORDS, 2)
    steps = [
        ("c = WordCounter()", False),
        (f"c.add({w1!r})", False),
        (f"c.add({w2!r})", False),
        (f"c.add({w1!r})", False),
        (f"c.count_of({w1!r})", True),
        (f"c.count_of({w2!r})", True),
        ("c.total()", True),
    ]
    return code, steps, "word_counter", "A simple word-frequency counter class backed by a dict."


_TEMPLATES = [
    _tmpl_factorial, _tmpl_fibonacci, _tmpl_is_prime, _tmpl_gcd, _tmpl_reverse_string,
    _tmpl_is_palindrome, _tmpl_sum_list, _tmpl_max_list, _tmpl_count_vowels, _tmpl_dedup,
    _tmpl_bubble_sort, _tmpl_linear_search, _tmpl_sum_digits, _tmpl_running_total,
    _tmpl_flatten, _tmpl_matrix_transpose, _tmpl_second_largest, _tmpl_merge_sorted,
    _tmpl_rotate_list, _tmpl_char_frequency, _tmpl_stack_class, _tmpl_point_class,
    _tmpl_word_counter_class,
]


def build_candidate(rng) -> tuple[str, str] | None:
    """Draws one template + params from rng, sandbox-executes it, and
    returns (rendered_doc_text, concept) on success or None on failure
    (caller should regenerate -- the RNG stream has already advanced
    deterministically, so retries stay deterministic)."""
    template = rng.choice(_TEMPLATES)
    code, steps, concept, description = template(rng)
    result = run_sandboxed(code, steps)
    if result is None:
        return None
    text = render_snippet(code, description, result)
    return text, concept


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class CodeGenGenerator(Generator):
    name = "code"
    phases = (2,)

    def generate(self, target_bytes: int) -> Iterator[dict]:
        produced = 0
        attempts_since_success = 0
        while produced < target_bytes:
            candidate = build_candidate(self.rng)
            if candidate is None:
                attempts_since_success += 1
                if attempts_since_success > 10000:
                    raise RuntimeError("code_gen: too many consecutive sandbox failures")
                continue
            attempts_since_success = 0
            text, concept = candidate
            d = self.doc(text=text, task_type="deliberate", concept=concept, phase=2, source="code/pyfunc")
            produced += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":
    from dottie.datagen.base import run_cli

    run_cli(CodeGenGenerator)
