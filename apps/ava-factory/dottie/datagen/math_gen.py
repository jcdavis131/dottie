"""Phase-1 (arithmetic curriculum) and phase-3 (multi-step reasoning +
temporal workflow logs) synthetic math corpus. Every number in every doc is
computed by Python -- worked "steps" are rendered from the same computation
that produces the final answer, never guessed or templated as literal text.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Iterator

from dottie.datagen.base import Generator

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def fmt_frac(fr: Fraction) -> str:
    if fr.denominator == 1:
        return str(fr.numerator)
    return f"{fr.numerator}/{fr.denominator}"


def fmt2(x: float) -> str:
    return f"{x:.2f}"


def base_str(x: int) -> str:
    """Render a number for use as the base of a ^ expression, parenthesizing
    negatives so e.g. (-3)^6 is never ambiguously written as -3^6."""
    return f"({x})" if x < 0 else str(x)


# ---------------------------------------------------------------------------
# P1(a): column arithmetic
# ---------------------------------------------------------------------------

def _column_add(a: int, b: int) -> tuple[list[str], int]:
    sa, sb = str(a), str(b)
    n = max(len(sa), len(sb))
    sa, sb = sa.zfill(n), sb.zfill(n)
    carry = 0
    digits = []
    steps = []
    for i in range(n - 1, -1, -1):
        da, db = int(sa[i]), int(sb[i])
        total = da + db + carry
        digit = total % 10
        newcarry = total // 10
        col = n - i
        steps.append(f"  column {col} (from the right): {da} + {db} + carry {carry} = {total} -> write {digit}, carry {newcarry}")
        digits.append(str(digit))
        carry = newcarry
    if carry:
        digits.append(str(carry))
    result = int("".join(reversed(digits)))
    assert result == a + b
    return steps, result


def _column_sub(a: int, b: int) -> tuple[list[str], int]:
    """a - b, a >= b (caller ensures this)."""
    sa, sb = str(a), str(b)
    n = max(len(sa), len(sb))
    sa, sb = sa.zfill(n), sb.zfill(n)
    borrow_in = 0
    digits = []
    steps = []
    for i in range(n - 1, -1, -1):
        da_raw = int(sa[i]) - borrow_in
        db = int(sb[i])
        col = n - i
        if da_raw < db:
            digit = da_raw + 10 - db
            steps.append(
                f"  column {col} (from the right): {da_raw} - {db} is negative, so borrow 10 from the "
                f"next column: {da_raw + 10} - {db} = {digit}"
            )
            borrow_in = 1
        else:
            digit = da_raw - db
            steps.append(f"  column {col} (from the right): {da_raw} - {db} = {digit}")
            borrow_in = 0
        digits.append(str(digit))
    result = int("".join(reversed(digits)))
    assert result == a - b, (a, b, result)
    return steps, result


def _column_mul(a: int, b: int) -> tuple[list[str], int]:
    sb = str(b)
    n = len(sb)
    partials = []
    steps = []
    total = 0
    for i, ch in enumerate(reversed(sb)):
        digit = int(ch)
        partial = a * digit * (10 ** i)
        steps.append(f"  {a} x {digit} (digit at position {i}, place value {10 ** i}) = {a * digit}, shifted -> {partial}")
        partials.append(partial)
        total += partial
    steps.append(f"  sum of partial products: {' + '.join(str(p) for p in partials)} = {total}")
    assert total == a * b
    return steps, total


def _arith_doc(rng) -> tuple[str, str, str]:
    op = rng.choice(["add", "sub", "mul"])
    d1 = rng.randint(1, 3)
    d2 = rng.randint(1, 3)
    a = rng.randint(10 ** (d1 - 1) if d1 > 1 else 0, 10 ** d1 - 1)
    b = rng.randint(10 ** (d2 - 1) if d2 > 1 else 0, 10 ** d2 - 1)
    a = max(a, 1 if d1 == 1 else a)
    trivial = d1 == 1 and d2 == 1
    if op == "add":
        steps, result = _column_add(a, b)
        prompt = f"Compute {a} + {b} using column addition."
        concept = "addition"
    elif op == "sub":
        if a < b:
            a, b = b, a
        steps, result = _column_sub(a, b)
        prompt = f"Compute {a} - {b} using column subtraction."
        concept = "subtraction"
    else:
        steps, result = _column_mul(a, b)
        prompt = f"Compute {a} x {b} using the standard (partial products) algorithm."
        concept = "multiplication"
    text = prompt + "\n\nWorked steps:\n" + "\n".join(steps) + f"\n\nFinal answer: {result}"
    task_type = "automatic" if trivial else "deliberate"
    return text, task_type, concept


# ---------------------------------------------------------------------------
# P1(b): linear equations
# ---------------------------------------------------------------------------

def _linear_eq_doc(rng) -> tuple[str, str, str]:
    a = rng.choice([n for n in range(-20, 21) if n != 0])
    b = rng.randint(-30, 30)
    c = rng.randint(-30, 30)
    x = Fraction(c - b, a)
    text = (
        f"Solve for x: {a}x + {b} = {c}\n\n"
        "Step 1 -- isolate the term with x:\n"
        f"  {a}x = {c} - ({b}) = {c - b}\n"
        "Step 2 -- divide both sides by the coefficient of x:\n"
        f"  x = {c - b} / {a} = {fmt_frac(x)}\n\n"
        f"Check: {a} * ({fmt_frac(x)}) + {b} = {fmt_frac(a * x + b)} (should equal {c})\n"
        f"Final answer: x = {fmt_frac(x)}"
    )
    assert a * x + b == c
    return text, "deliberate", "linear_equation"


# ---------------------------------------------------------------------------
# P1(c): geometry
# ---------------------------------------------------------------------------

def _geometry_doc(rng) -> tuple[str, str, str]:
    shape = rng.choice(["rectangle", "triangle", "circle"])
    if shape == "rectangle":
        l = rng.randint(2, 40)
        w = rng.randint(2, 40)
        perimeter = 2 * (l + w)
        area = l * w
        text = (
            f"A rectangle has length {l} and width {w}.\n"
            f"Perimeter = 2 x (length + width) = 2 x ({l} + {w}) = 2 x {l + w} = {perimeter}\n"
            f"Area = length x width = {l} x {w} = {area}\n"
            f"Final answer: perimeter = {perimeter}, area = {area}"
        )
        concept = "geometry_rectangle"
    elif shape == "triangle":
        base = rng.randint(2, 40)
        height = rng.randint(2, 40)
        area = Fraction(base * height, 2)
        text = (
            f"A triangle has base {base} and height {height}.\n"
            f"Area = (base x height) / 2 = ({base} x {height}) / 2 = {base * height} / 2 = {fmt_frac(area)}\n"
            f"Final answer: area = {fmt_frac(area)}"
        )
        concept = "geometry_triangle"
    else:
        r = rng.randint(1, 30)
        circumference_approx = 2 * math.pi * r
        area_approx = math.pi * r * r
        text = (
            f"A circle has radius {r}.\n"
            f"Circumference = 2 x pi x r = 2 x pi x {r} = {2 * r}*pi ~= {fmt2(circumference_approx)}\n"
            f"Area = pi x r^2 = pi x {r}^2 = pi x {r * r} = {r * r}*pi ~= {fmt2(area_approx)}\n"
            f"Final answer: circumference ~= {fmt2(circumference_approx)}, area ~= {fmt2(area_approx)} "
            f"(exact: {2 * r}*pi and {r * r}*pi respectively)"
        )
        concept = "geometry_circle"
    return text, "deliberate", concept


# ---------------------------------------------------------------------------
# P1(d): modular arithmetic
# ---------------------------------------------------------------------------

def _modular_doc(rng) -> tuple[str, str, str]:
    m = rng.randint(3, 12)
    if rng.random() < 0.5:
        a = rng.randint(m + 1, 9 * m)
        r = a % m
        q = a // m
        text = (
            f"Compute {a} mod {m}.\n"
            f"{a} = {q} x {m} + {r}   (since {q} x {m} = {q * m} and {a} - {q * m} = {r})\n"
            f"Final answer: {a} mod {m} = {r}"
        )
        return text, "deliberate", "modular_arithmetic"
    else:
        coeff = rng.randint(1, m - 1)
        target = rng.randint(0, m - 1)
        solutions = sorted(x for x in range(m) if (coeff * x) % m == target)
        lines = [f"  x={x}: {coeff} x {x} mod {m} = {(coeff * x) % m}" for x in range(m)]
        if solutions:
            verdict = f"Solutions in {{0, ..., {m - 1}}}: {', '.join(str(s) for s in solutions)}"
        else:
            verdict = f"No solution exists in {{0, ..., {m - 1}}} (gcd({coeff}, {m}) = {math.gcd(coeff, m)} does not divide {target})"
        text = (
            f"Solve the congruence {coeff}x ≡ {target} (mod {m}) by checking every residue:\n"
            + "\n".join(lines)
            + f"\n\n{verdict}"
        )
        return text, "deliberate", "modular_arithmetic"


# ---------------------------------------------------------------------------
# P1(e): sequences
# ---------------------------------------------------------------------------

def _sequence_doc(rng) -> tuple[str, str, str]:
    kind = rng.choice(["arithmetic", "geometric"])
    n = rng.randint(5, 12)
    if kind == "arithmetic":
        a1 = rng.randint(-20, 20)
        d = rng.randint(-9, 9) or 1
        terms = [a1 + i * d for i in range(min(n, 6))]
        nth = a1 + (n - 1) * d
        total = Fraction(n, 2) * (2 * a1 + (n - 1) * d)
        text = (
            f"Arithmetic sequence: first term a1={a1}, common difference d={d}.\n"
            f"First terms: {', '.join(str(t) for t in terms)}, ...\n"
            f"nth term formula: a_n = a1 + (n-1)d. For n={n}: a_{n} = {a1} + ({n}-1)x{d} = {a1} + {(n - 1) * d} = {nth}\n"
            f"Sum formula: S_n = n/2 x (2a1 + (n-1)d). For n={n}: "
            f"S_{n} = {n}/2 x (2x{a1} + {(n - 1) * d}) = {n}/2 x {2 * a1 + (n - 1) * d} = {fmt_frac(total)}\n"
            f"Final answer: a_{n} = {nth}, S_{n} = {fmt_frac(total)}"
        )
        concept = "sequence_arithmetic"
    else:
        a1 = rng.randint(1, 6)
        r = rng.choice([n for n in range(-3, 4) if n not in (0, 1)])
        n = rng.randint(4, 8)  # keep geometric growth bounded
        terms = [a1 * (r ** i) for i in range(min(n, 6))]
        nth = a1 * (r ** (n - 1))
        total = Fraction(a1) * (Fraction(r) ** n - 1) / (Fraction(r) - 1)
        text = (
            f"Geometric sequence: first term a1={a1}, common ratio r={r}.\n"
            f"First terms: {', '.join(str(t) for t in terms)}, ...\n"
            f"nth term formula: a_n = a1 x r^(n-1). For n={n}: a_{n} = {a1} x {base_str(r)}^{n - 1} = {nth}\n"
            f"Sum formula: S_n = a1 x (r^n - 1) / (r - 1). For n={n}: "
            f"S_{n} = {a1} x ({base_str(r)}^{n} - 1) / ({base_str(r)} - 1) = {a1} x ({r ** n} - 1) / {r - 1} = {fmt_frac(total)}\n"
            f"Final answer: a_{n} = {nth}, S_{n} = {fmt_frac(total)}"
        )
        concept = "sequence_geometric"
    return text, "deliberate", concept


# ---------------------------------------------------------------------------
# P1(f): probability word problems
# ---------------------------------------------------------------------------

def _probability_doc(rng) -> tuple[str, str, str]:
    kind = rng.choice(["dice", "coins", "urn"])
    if kind == "dice":
        target_sum = rng.randint(2, 12)
        outcomes = [(i, j) for i in range(1, 7) for j in range(1, 7) if i + j == target_sum]
        favorable = len(outcomes)
        prob = Fraction(favorable, 36)
        text = (
            f"Two fair six-sided dice are rolled. What is the probability that the sum is {target_sum}?\n"
            f"Sample space size: 6 x 6 = 36 equally likely outcomes.\n"
            f"Outcomes summing to {target_sum}: {outcomes} -> {favorable} outcome(s).\n"
            f"P(sum = {target_sum}) = {favorable}/36 = {fmt_frac(prob)}\n"
            f"Final answer: {fmt_frac(prob)}"
        )
        concept = "probability"
    elif kind == "coins":
        n = rng.randint(2, 8)
        k = rng.randint(0, n)
        ways = math.comb(n, k)
        prob = Fraction(ways, 2 ** n)
        text = (
            f"A fair coin is flipped {n} times. What is the probability of exactly {k} heads?\n"
            f"Number of ways to choose which {k} of the {n} flips are heads: C({n},{k}) = {ways}.\n"
            f"Total equally likely outcomes: 2^{n} = {2 ** n}.\n"
            f"P(exactly {k} heads) = {ways}/{2 ** n} = {fmt_frac(prob)}\n"
            f"Final answer: {fmt_frac(prob)}"
        )
        concept = "probability"
    else:
        red = rng.randint(2, 8)
        blue = rng.randint(2, 8)
        total = red + blue
        draw = rng.randint(1, min(total, 4))
        want_red = rng.randint(0, draw)
        if want_red > red:
            want_red = red
        ways_favorable = math.comb(red, want_red) * math.comb(blue, draw - want_red) if draw - want_red <= blue else 0
        ways_total = math.comb(total, draw)
        prob = Fraction(ways_favorable, ways_total) if ways_total else Fraction(0)
        text = (
            f"An urn has {red} red balls and {blue} blue balls ({total} total). {draw} balls are drawn "
            f"without replacement. What is the probability that exactly {want_red} of them are red?\n"
            f"Ways to choose {want_red} red from {red}: C({red},{want_red}) = {math.comb(red, want_red)}.\n"
            f"Ways to choose {draw - want_red} blue from {blue}: C({blue},{draw - want_red}) = "
            f"{math.comb(blue, draw - want_red) if draw - want_red <= blue else 0}.\n"
            f"Total ways to choose {draw} from {total}: C({total},{draw}) = {ways_total}.\n"
            f"P(exactly {want_red} red) = {ways_favorable}/{ways_total} = {fmt_frac(prob)}\n"
            f"Final answer: {fmt_frac(prob)}"
        )
        concept = "probability"
    return text, "deliberate", concept


_P1_FAMILIES = [_arith_doc, _linear_eq_doc, _geometry_doc, _modular_doc, _sequence_doc, _probability_doc]


# ---------------------------------------------------------------------------
# P3: multi-step word problems
# ---------------------------------------------------------------------------

_UNIT_CONVERSIONS = [
    ("kilometers", "meters", 1000),
    ("meters", "centimeters", 100),
    ("hours", "minutes", 60),
    ("minutes", "seconds", 60),
    ("dollars", "cents", 100),
    ("kilograms", "grams", 1000),
]


def _word_problem_doc(rng) -> tuple[str, str, str]:
    kind = rng.choice(["rate_time_distance", "unit_conversion", "multi_step_totals"])
    if kind == "rate_time_distance":
        speed1 = rng.randint(20, 90)
        time1 = rng.randint(1, 5)
        speed2 = rng.randint(20, 90)
        time2 = rng.randint(1, 5)
        dist1 = speed1 * time1
        dist2 = speed2 * time2
        total_dist = dist1 + dist2
        total_time = time1 + time2
        avg_speed = Fraction(total_dist, total_time)
        text = (
            f"A car travels at {speed1} km/h for {time1} hours, then at {speed2} km/h for {time2} more hours.\n"
            "Step 1: distance of the first leg = speed x time = "
            f"{speed1} x {time1} = {dist1} km.\n"
            f"Step 2: distance of the second leg = {speed2} x {time2} = {dist2} km.\n"
            f"Step 3: total distance = {dist1} + {dist2} = {total_dist} km.\n"
            f"Step 4: total time = {time1} + {time2} = {total_time} hours.\n"
            f"Step 5: average speed = total distance / total time = {total_dist}/{total_time} = {fmt_frac(avg_speed)} km/h.\n"
            f"Final answer: total distance = {total_dist} km, average speed = {fmt_frac(avg_speed)} km/h"
        )
        concept = "rate_time_distance"
    elif kind == "unit_conversion":
        from_unit, to_unit, factor = rng.choice(_UNIT_CONVERSIONS)
        amount = rng.randint(2, 500)
        converted = amount * factor
        extra = rng.randint(1, factor - 1)
        combined = converted + extra
        text = (
            f"Convert {amount} {from_unit} to {to_unit}, then add {extra} {to_unit}.\n"
            f"Step 1: 1 {from_unit} = {factor} {to_unit}, so {amount} {from_unit} = {amount} x {factor} = {converted} {to_unit}.\n"
            f"Step 2: {converted} + {extra} = {combined} {to_unit}.\n"
            f"Final answer: {combined} {to_unit}"
        )
        concept = "unit_conversion"
    else:
        items = rng.randint(2, 4)
        prices = [rng.randint(1, 50) for _ in range(items)]
        quantities = [rng.randint(1, 10) for _ in range(items)]
        subtotals = [p * q for p, q in zip(prices, quantities)]
        total = sum(subtotals)
        discount_pct = rng.choice([0, 5, 10, 15, 20])
        discount_amt = Fraction(total * discount_pct, 100)
        final = Fraction(total) - discount_amt
        lines = [f"Step {i + 1}: item {i + 1} costs {prices[i]} x {quantities[i]} = {subtotals[i]}." for i in range(items)]
        text = (
            f"A shopper buys {items} kinds of items:\n"
            + "\n".join(lines)
            + f"\nStep {items + 1}: subtotal = {' + '.join(str(s) for s in subtotals)} = {total}.\n"
            f"Step {items + 2}: a {discount_pct}% discount is applied: {total} x {discount_pct}/100 = {fmt_frac(discount_amt)}.\n"
            f"Step {items + 3}: final total = {total} - {fmt_frac(discount_amt)} = {fmt_frac(final)}.\n"
            f"Final answer: {fmt_frac(final)}"
        )
        concept = "multi_step_totals"
    return text, "deliberate", concept


# ---------------------------------------------------------------------------
# P3: temporal workflow logs
# ---------------------------------------------------------------------------

_WORKER_NAMES = ["Worker-A", "Worker-B", "Worker-C"]
_TASK_NOUNS = sorted([
    "data ingest", "schema migration", "model training run", "eval sweep", "report draft",
    "code review", "deploy staging", "load test", "index rebuild", "backup verification",
])
_DELAY_EVENTS = [
    "a server outage",
    "an upstream dependency failure",
    "a blocked code review",
    "an unavailable teammate",
    "a data quality issue",
    "a hardware failure",
]


def _temporal_workflow_doc(rng, n_tasks: int | None = None) -> tuple[str, str, str]:
    n_tasks = n_tasks or rng.randint(3, 6)
    task_names = rng.sample(_TASK_NOUNS, min(n_tasks, len(_TASK_NOUNS)))
    while len(task_names) < n_tasks:
        task_names.append(rng.choice(_TASK_NOUNS))
    workers = [_WORKER_NAMES[i % len(_WORKER_NAMES)] for i in range(n_tasks)]
    durations = [rng.randint(1, 5) for _ in range(n_tasks)]
    deadlines = []

    # sequential schedule per worker track
    track_end = {w: 0 for w in set(workers)}
    starts = []
    ends = []
    for name, worker, dur in zip(task_names, workers, durations):
        start = track_end[worker]
        end = start + dur
        starts.append(start)
        ends.append(end)
        track_end[worker] = end

    lines = ["Project plan (day 0 = kickoff):"]
    for i, name in enumerate(task_names):
        deadline = ends[i] + rng.randint(0, 3)
        deadlines.append(deadline)
        lines.append(
            f"  Task '{name}' -> {workers[i]}, duration {durations[i]}d, "
            f"scheduled day {starts[i]}-{ends[i]}, deadline day {deadline}."
        )

    # inject a delay event on a random task
    delay_idx = rng.randrange(n_tasks)
    delay_days = rng.randint(1, 4)
    event = rng.choice(_DELAY_EVENTS)
    event_day = rng.randint(0, ends[delay_idx])
    lines.append("")
    lines.append(f"Day {event_day}: {event} delays '{task_names[delay_idx]}' by {delay_days} day(s).")

    # recompute: shift the delayed task and every later task on the same worker track
    new_ends = list(ends)
    new_starts = list(starts)
    new_ends[delay_idx] += delay_days
    worker = workers[delay_idx]
    shift = delay_days
    for i in range(n_tasks):
        if i == delay_idx:
            continue
        if workers[i] == worker and starts[i] >= ends[delay_idx]:
            new_starts[i] += shift
            new_ends[i] += shift

    lines.append("")
    lines.append("Recomputed schedule:")
    missed = []
    for i, name in enumerate(task_names):
        status = "ON TIME" if new_ends[i] <= deadlines[i] else "MISSES DEADLINE"
        if status == "MISSES DEADLINE":
            missed.append(name)
        lines.append(
            f"  Task '{name}' -> {workers[i]}, new schedule day {new_starts[i]}-{new_ends[i]}, "
            f"deadline day {deadlines[i]}: {status}"
        )
    if missed:
        lines.append(f"\nSummary: {len(missed)} task(s) now miss their deadline: {', '.join(missed)}.")
    else:
        lines.append("\nSummary: all tasks remain on schedule after the delay.")

    text = "\n".join(lines)
    concept = rng.choice(["deadline", "schedule", "delay"])
    return text, "temporal", concept


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class MathGenerator(Generator):
    name = "math"
    phases = (1, 3, 4)

    P1_FRACTION = 0.70  # ~28MB of 40MB default target
    LONG_P3_FRACTION = 0.10

    def generate(self, target_bytes: int) -> Iterator[dict]:
        p1_budget = int(target_bytes * self.P1_FRACTION)
        p3_budget = target_bytes - p1_budget

        yield from self._generate_p1(p1_budget)
        yield from self._generate_p3(p3_budget)

    def _generate_p1(self, budget: int) -> Iterator[dict]:
        produced = 0
        # staged curriculum: walk each family in order, giving each an equal
        # slice of the P1 budget, before moving to the next family.
        per_family = max(1, budget // len(_P1_FAMILIES))
        for builder in _P1_FAMILIES:
            family_produced = 0
            while family_produced < per_family and produced < budget:
                text, task_type, concept = builder(self.rng)
                source = f"math/p1_{builder.__name__.strip('_').replace('_doc', '')}"
                d = self.doc(text=text, task_type=task_type, concept=concept, phase=1, source=source)
                n = len(d["text"].encode("utf-8"))
                family_produced += n
                produced += n
                yield d
        # if rounding left the budget short, top up with arithmetic drills
        while produced < budget:
            text, task_type, concept = _arith_doc(self.rng)
            d = self.doc(text=text, task_type=task_type, concept=concept, phase=1, source="math/p1_arith")
            produced += len(d["text"].encode("utf-8"))
            yield d

    def _generate_p3(self, budget: int) -> Iterator[dict]:
        produced = 0
        while produced < budget:
            long_form = self.rng.random() < self.LONG_P3_FRACTION
            temporal = self.rng.random() < 0.35
            if temporal:
                n_tasks = self.rng.randint(6, 10) if long_form else None
                text, task_type, concept = _temporal_workflow_doc(self.rng, n_tasks=n_tasks)
                source = "math/p3_temporal"
            else:
                if long_form:
                    parts = []
                    n_problems = self.rng.randint(6, 10)
                    for _ in range(n_problems):
                        t, _, _ = _word_problem_doc(self.rng)
                        parts.append(t)
                    text = "Multi-problem practice set:\n\n" + "\n\n---\n\n".join(parts)
                    task_type = "deliberate"
                    concept = "word_problem"
                else:
                    text, task_type, concept = _word_problem_doc(self.rng)
                source = "math/p3_word_problem"
            phase = 4 if long_form else 3
            d = self.doc(text=text, task_type=task_type, concept=concept, phase=phase, source=source)
            produced += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":
    from dottie.datagen.base import run_cli

    run_cli(MathGenerator)
