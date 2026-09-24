"""The deterministic tier: local Python solvers and allowlisted read-only scout commands.

No model, no network. A goal is parsed by the first solver whose pattern
matches it; the solver computes the answer with plain Python. When no solver
matches, the tier raises :class:`NotApplicable`: deterministic execution could
not attempt the goal, which is exactly the observation the tier probe needs.

Arithmetic goes through an AST whitelist (numbers, + - * / // % **, unary
minus, parentheses; exponents bounded), never ``eval``. The only subprocess is
an allowlisted, read-only ``scout --json <cmd>`` (:data:`SCOUT_READONLY`).
"""

from __future__ import annotations

import ast
import calendar
import datetime as dt
import hashlib
import json
import math
import operator
import re
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any

from bigbang.plugins.harness.executors.base import ExecResult, NotApplicable

if TYPE_CHECKING:
    from collections.abc import Callable

_NUM = r"-?\d+(?:\.\d+)?"
_OPS: dict[type, Callable[..., Any]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}


def _fmt(x: float) -> str:
    """Integers without a trailing .0; floats to 6 significant decimals."""
    if isinstance(x, int) or (isinstance(x, float) and x.is_integer() and abs(x) < 1e15):
        return str(int(x))
    return f"{x:.6f}".rstrip("0").rstrip(".")


def safe_eval(expr: str) -> float:
    """Evaluate an arithmetic expression through an AST whitelist."""

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 64:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](left, right)
        raise ValueError(f"not arithmetic: {type(node).__name__}")

    return ev(ast.parse(expr.replace("^", "**").replace("×", "*").replace("÷", "/"), mode="eval"))


def s_arithmetic(goal: str) -> str | None:
    m = re.search(r"(?:what is|what's|compute|calculate|evaluate)\s*:?\s*([-+*/%^().\d\s×÷]+?)\s*[?.=]*$", goal, re.I)
    if not m or not re.search(r"\d", m.group(1)) or not re.search(r"[-+*/%^×÷]", m.group(1).strip().lstrip("-")):
        return None
    return _fmt(safe_eval(m.group(1)))


def s_percent(goal: str) -> str | None:
    m = re.search(rf"({_NUM})\s*(?:%|percent)\s+of\s+({_NUM})", goal, re.I)
    return _fmt(float(m.group(1)) * float(m.group(2)) / 100.0) if m else None


def s_sqrt(goal: str) -> str | None:
    m = re.search(rf"square root of\s+({_NUM})", goal, re.I)
    return _fmt(math.sqrt(float(m.group(1)))) if m else None


# unit -> (dimension, factor to the base unit)
_UNITS: dict[str, tuple[str, float]] = {
    "mm": ("len", 0.001), "millimeters": ("len", 0.001), "cm": ("len", 0.01), "centimeters": ("len", 0.01),
    "m": ("len", 1.0), "meters": ("len", 1.0), "km": ("len", 1000.0), "kilometers": ("len", 1000.0),
    "in": ("len", 0.0254), "inches": ("len", 0.0254), "ft": ("len", 0.3048), "feet": ("len", 0.3048),
    "yd": ("len", 0.9144), "yards": ("len", 0.9144), "mi": ("len", 1609.344), "miles": ("len", 1609.344),
    "mg": ("mass", 1e-6), "g": ("mass", 0.001), "grams": ("mass", 0.001), "kg": ("mass", 1.0),
    "kilograms": ("mass", 1.0), "lb": ("mass", 0.45359237), "lbs": ("mass", 0.45359237),
    "pounds": ("mass", 0.45359237), "oz": ("mass", 0.028349523125), "ounces": ("mass", 0.028349523125),
    "ml": ("vol", 0.001), "milliliters": ("vol", 0.001), "l": ("vol", 1.0), "liters": ("vol", 1.0),
    "gal": ("vol", 3.785411784), "gallons": ("vol", 3.785411784),
    "s": ("time", 1.0), "seconds": ("time", 1.0), "min": ("time", 60.0), "minutes": ("time", 60.0),
    "h": ("time", 3600.0), "hours": ("time", 3600.0), "days": ("time", 86400.0), "weeks": ("time", 604800.0),
    "b": ("data", 1.0), "bytes": ("data", 1.0), "kb": ("data", 1e3), "mb": ("data", 1e6), "gb": ("data", 1e9),
    "kib": ("data", 1024.0), "mib": ("data", 1024.0**2), "gib": ("data", 1024.0**3),
}
_TEMPS = {"c": "c", "celsius": "c", "f": "f", "fahrenheit": "f", "k": "k", "kelvin": "k"}


def _unit(u: str) -> str:
    u = u.lower().strip(".").replace("°", "")
    return u if u in _UNITS or u in _TEMPS else (u[:-1] if u.endswith("s") and u[:-1] in _UNITS else u)


def _temp(v: float, a: str, b: str) -> float:
    c = v if a == "c" else (v - 32) * 5 / 9 if a == "f" else v - 273.15
    return c if b == "c" else c * 9 / 5 + 32 if b == "f" else c + 273.15


def s_units(goal: str) -> str | None:
    m = re.search(rf"convert\s+({_NUM})\s*°?\s*([a-z]+)\.?\s+(?:to|into)\s+°?([a-z]+)", goal, re.I)
    if not m:
        m2 = re.search(rf"how many\s+([a-z]+)\s+(?:are )?in\s+({_NUM})\s*°?([a-z]+)", goal, re.I)
        if not m2:
            return None
        v, a, b = float(m2.group(2)), _unit(m2.group(3)), _unit(m2.group(1))
    else:
        v, a, b = float(m.group(1)), _unit(m.group(2)), _unit(m.group(3))
    if a in _TEMPS and b in _TEMPS:
        return _fmt(round(_temp(v, _TEMPS[a], _TEMPS[b]), 6))
    if a in _UNITS and b in _UNITS and _UNITS[a][0] == _UNITS[b][0]:
        return _fmt(round(v * _UNITS[a][1] / _UNITS[b][1], 6))
    return None


def s_base(goal: str) -> str | None:
    m = re.search(r"convert\s+(?:the )?(?:decimal )?(?:number )?(\d+)\s+to\s+(binary|hexadecimal|hex|octal)", goal, re.I)
    if m:
        n, base = int(m.group(1)), m.group(2).lower()
        return format(n, "b" if base == "binary" else "o" if base == "octal" else "x")
    m = re.search(r"(?:convert\s+)?(?:the )?(binary|hexadecimal|hex|octal)\s+(?:number\s+)?([0-9a-fA-Fx]+)\s+to\s+decimal", goal, re.I)
    if m:
        base = {"binary": 2, "octal": 8}.get(m.group(1).lower(), 16)
        return str(int(m.group(2).lower().removeprefix("0x"), base))
    return None


def s_hash(goal: str) -> str | None:
    m = re.search(r"(sha-?256|sha-?1|md5)\s+(?:hash|digest|hex digest)?\s*of\s+(?:the string\s+)?['\"](.*?)['\"]", goal, re.I)
    if not m:
        return None
    algo = m.group(1).lower().replace("-", "")
    return hashlib.new(algo, m.group(2).encode("utf-8")).hexdigest()


def s_count(goal: str) -> str | None:
    m = re.search(r"how many (words|characters|letters|vowels)\s+(?:are )?(?:there )?in\s+(?:the (?:text|string|sentence)\s+)?['\"](.*?)['\"]", goal, re.I)
    if not m:
        return None
    kind, text = m.group(1).lower(), m.group(2)
    if kind == "words":
        return str(len(text.split()))
    if kind == "characters":
        return str(len(text))
    if kind == "letters":
        return str(sum(ch.isalpha() for ch in text))
    return str(sum(ch.lower() in "aeiou" for ch in text))


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def s_dates(goal: str) -> str | None:
    m = re.search(r"how many days (?:are there )?between (\d{4}-\d{2}-\d{2}) and (\d{4}-\d{2}-\d{2})", goal, re.I)
    if m:
        return str(abs((_date(m.group(2)) - _date(m.group(1))).days))
    m = re.search(r"what day of the week (?:was|is|will be|falls on) (\d{4}-\d{2}-\d{2})", goal, re.I)
    if m:
        return calendar.day_name[_date(m.group(1)).weekday()]
    m = re.search(r"is (\d{4}) a leap year", goal, re.I)
    if m:
        return "yes" if calendar.isleap(int(m.group(1))) else "no"
    return None


_ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
          (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def s_roman(goal: str) -> str | None:
    m = re.search(r"convert (\d+) to roman numerals?", goal, re.I)
    if m:
        n, out = int(m.group(1)), []
        for v, sym in _ROMAN:
            while n >= v:
                out.append(sym)
                n -= v
        return "".join(out)
    m = re.search(r"roman numeral\s+([MDCLXVI]+)\s+(?:to|as|in)\s+(?:an? )?(?:integer|arabic|decimal|number)", goal, re.I)
    if m:
        vals = {s: v for v, s in _ROMAN if len(s) == 1}
        r = m.group(1).upper()
        return str(sum(-vals[c] if i + 1 < len(r) and vals[c] < vals[r[i + 1]] else vals[c] for i, c in enumerate(r)))
    return None


def s_number_theory(goal: str) -> str | None:
    m = re.search(r"(greatest common divisor|gcd|least common multiple|lcm) of (\d+) and (\d+)", goal, re.I)
    if m:
        a, b = int(m.group(2)), int(m.group(3))
        return str(math.gcd(a, b) if m.group(1).lower() in ("gcd", "greatest common divisor") else math.lcm(a, b))
    m = re.search(r"is (\d+) (?:a )?prime", goal, re.I)
    if m:
        n = int(m.group(1))
        return "yes" if n > 1 and all(n % d for d in range(2, math.isqrt(n) + 1)) else "no"
    m = re.search(r"factorial of (\d+)|(\d+) factorial", goal, re.I)
    if m:
        n = int(m.group(1) or m.group(2))
        return str(math.factorial(n)) if n <= 200 else None
    return None


def s_sort(goal: str) -> str | None:
    m = re.search(r"sort (?:the numbers\s+)?([-\d.,\s]+?)\s+in (ascending|descending) order", goal, re.I)
    if not m:
        return None
    nums = [float(x) for x in re.findall(_NUM, m.group(1))]
    return ", ".join(_fmt(x) for x in sorted(nums, reverse=m.group(2).lower() == "descending"))


_EXTRACT = {
    "email addresses": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "emails": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "urls": r"https?://[^\s,;]+", "hashtags": r"#\w+", "numbers": _NUM, "years": r"\b(?:1[5-9]|20)\d{2}\b",
}


def s_extract(goal: str) -> str | None:
    m = re.search(r"extract (?:all )?(?:the )?(email addresses|emails|urls|hashtags|numbers|years) from\s*:?\s*(.+)$", goal, re.I | re.S)
    if not m:
        return None
    found = re.findall(_EXTRACT[m.group(1).lower()], m.group(2))
    return ", ".join(f.rstrip(".") for f in found)


def s_text(goal: str) -> str | None:
    m = re.search(r"reverse the (?:string|text|word)\s+['\"](.*?)['\"]", goal, re.I)
    if m:
        return m.group(1)[::-1]
    m = re.search(r"convert\s+['\"](.*?)['\"]\s+to\s+(uppercase|lowercase|upper case|lower case)", goal, re.I)
    if m:
        return m.group(1).upper() if m.group(2).lower().startswith("upper") else m.group(1).lower()
    return None


def s_json(goal: str) -> str | None:
    m = re.search(r"value of (?:the )?key ['\"]([\w.]+)['\"] in (?:the )?json\s*:?\s*(\{.*\})", goal, re.I | re.S)
    if not m:
        return None
    value: Any = json.loads(m.group(2))
    for part in m.group(1).split("."):
        value = value[part]
    return value if isinstance(value, str) else json.dumps(value)


#: read-only scout subcommands the deterministic tier may run (argv after ``scout --json``)
SCOUT_READONLY: tuple[tuple[str, ...], ...] = (("router", "status"), ("forge", "list"), ("system", "doctor"))


def run_scout_readonly(goal: str) -> tuple[str, dict[str, Any]] | None:
    m = re.search(r"run (?:the )?(?:read-only )?(?:scout )?command\s+`?scout ((?:[a-z-]+ ?){1,3})`?", goal, re.I)
    if not m:
        return None
    argv = tuple(m.group(1).split())
    if argv not in SCOUT_READONLY:
        raise NotApplicable(f"scout {' '.join(argv)} is not an allowlisted read-only command")
    proc = subprocess.run([sys.executable, "-m", "bigbang.cli", "--json", *argv], capture_output=True, text=True,
                          timeout=120, check=False)
    return proc.stdout[-4000:], {"exit_code": proc.returncode, "argv": ["scout", "--json", *argv]}


SOLVERS: tuple[tuple[str, Callable[[str], str | None]], ...] = (
    ("hash", s_hash), ("count", s_count), ("extract", s_extract), ("text", s_text), ("json", s_json),
    ("dates", s_dates), ("roman", s_roman), ("base", s_base), ("number_theory", s_number_theory),
    ("sort", s_sort), ("units", s_units), ("percent", s_percent), ("sqrt", s_sqrt), ("arithmetic", s_arithmetic),
)


def run(goal: str) -> ExecResult:
    """Solve ``goal`` with the first matching local solver. NotApplicable when none matches."""
    t0 = time.perf_counter()
    scout = run_scout_readonly(goal)
    if scout is not None:
        text, meta = scout
        return ExecResult(tier="deterministic", backend="scout-readonly", answer=text.strip()[-400:], text=text,
                          latency_ms=round((time.perf_counter() - t0) * 1000, 3), meta=meta)
    for name, solver in SOLVERS:
        try:
            answer = solver(goal)
        except (ValueError, ZeroDivisionError, KeyError, TypeError, OverflowError, IndexError):
            answer = None
        if answer is not None:
            return ExecResult(tier="deterministic", backend="local-python", answer=answer, text=answer,
                              latency_ms=round((time.perf_counter() - t0) * 1000, 3),
                              meta={"solver": name, "exit_code": 0})
    raise NotApplicable("no deterministic solver matches this goal")
