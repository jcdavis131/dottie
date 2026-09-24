#!/usr/bin/env python3
"""Build ``dottie_loop/benchmarks/router_bench_v1.jsonl``: curated goals with automatic verifiers.

Every goal is a real task with a checkable answer, written down BEFORE any
executor runs:

* deterministic-shaped (arithmetic, unit conversion, bases, hashes, dates,
  roman numerals, number theory, sorting, extraction, JSON lookup, read-only
  scout commands): expected answers computed here with plain Python;
* llm-shaped (word problems, code with unit tests, JSON generation, language
  and fact questions): expected answers written here, code tests checked
  against a reference solution through the same verifier the probe uses;
* deep_research-shaped (arXiv lookups): expected answers are arXiv's own
  metadata, fetched live into ``arxiv_snapshot.json`` (68 papers, 2026-09-23).

``tier_hint`` is the author's guess, kept for analysis only; the label is
whatever ``scout router probe`` observes. Goals are deduped by normalised
hash, and the build refuses any goal whose normalised hash appears in an
existing eval set of this repo (see :data:`EVAL_SETS`).

    uv run python packages/dottie-loop/scripts/build_router_bench.py [--check]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parents[1]
sys.path.insert(0, str(PKG))

from dottie_loop.provenance import goal_norm_sha256
from dottie_loop.verifiers import validate_spec, verify

OUT = PKG / "dottie_loop" / "benchmarks" / "router_bench_v1.jsonl"
SNAPSHOT = PKG / "dottie_loop" / "benchmarks" / "arxiv_snapshot.json"
#: Existing eval sets in this repo that the benchmark must not overlap.
EVAL_SETS = [
    *sorted((REPO / "apps" / "ava-factory" / "evals" / "probe_items").glob("*.jsonl")),
    REPO / "apps" / "ava-factory" / "data" / "orchestration" / "corpus.jsonl",
    REPO / "examples" / "goldens.jsonl",
    REPO / "packages" / "dottie-loop" / "tests" / "fixtures" / "moma_route_goldens.json",
]


def num(expected: float, rel: float = 1e-4, abs_tol: float = 1e-6) -> dict:
    return {"type": "numeric", "expected": expected, "rel_tol": rel, "abs_tol": abs_tol}


def exact(expected: str, *accept: str) -> dict:
    return {"type": "exact", "expected": expected, **({"accept": list(accept)} if accept else {})}


def g(task_type: str, tier_hint: str, goal: str, verifier: dict, **extra) -> dict:
    return {"task_type": task_type, "tier_hint": tier_hint, "goal": goal, "verifier": verifier, **extra}


def deterministic_goals(rng: random.Random) -> list[dict]:
    out = []
    for _ in range(12):
        a, b, c = rng.randint(12, 999), rng.randint(3, 99), rng.randint(1, 500)
        op = rng.choice(["+", "-"])
        val = a * b + c if op == "+" else a * b - c
        out.append(g("arithmetic", "deterministic", f"What is {a} * {b} {op} {c}?", num(val, 0, 1e-9)))
    for _ in range(6):
        p, n = rng.choice([5, 12.5, 15, 18, 35, 62]), rng.randint(40, 4000)
        out.append(g("arithmetic", "deterministic", f"What is {p}% of {n}?", num(p * n / 100)))
    conv = [(3.2, "miles", "km", 1.609344), (180, "cm", "inches", 1 / 2.54), (72, "kg", "pounds", 1 / 0.45359237),
            (5.5, "gallons", "liters", 3.785411784), (250, "grams", "ounces", 1 / 28.349523125),
            (1500, "meters", "feet", 1 / 0.3048), (2.75, "hours", "minutes", 60), (3, "weeks", "hours", 168),
            (4, "GiB", "MiB", 1024), (7.5, "GB", "MB", 1000), (12, "yards", "meters", 0.9144)]
    for v, a, b, f in conv:
        out.append(g("unit_conversion", "deterministic", f"Convert {v} {a} to {b}.", num(round(v * f, 6), 1e-4)))
    for v, a, b in [(98.6, "fahrenheit", "celsius"), (-40, "celsius", "fahrenheit"), (300, "kelvin", "celsius")]:
        c = (v - 32) * 5 / 9 if a == "fahrenheit" else v if a == "celsius" else v - 273.15
        want = c if b == "celsius" else c * 9 / 5 + 32
        out.append(g("unit_conversion", "deterministic", f"Convert {v} {a} to {b}.", num(round(want, 6), 1e-4, 1e-3)))
    for n in (rng.randint(100, 5000) for _ in range(3)):
        out.append(g("arithmetic", "deterministic", f"Convert {n} to binary.", exact(format(n, "b"))))
    for n in (rng.randint(300, 70000) for _ in range(2)):
        out.append(g("arithmetic", "deterministic", f"Convert {n} to hexadecimal.", exact(format(n, "x"), format(n, "X"))))
    out.append(g("arithmetic", "deterministic", "Convert the binary number 1011011101 to decimal.", num(0b1011011101, 0, 0)))
    for algo, text in [("sha256", "router bench v1"), ("md5", "dottie"), ("sha256", "cheapest tier first"),
                       ("sha1", "minimal sufficient")]:
        out.append(g("text_transform", "deterministic", f"Compute the {algo} hash of '{text}'.",
                     exact(hashlib.new(algo, text.encode()).hexdigest())))
    for kind, text in [("words", "the quick router picks the cheapest tier that works"),
                       ("characters", "benchmark-verified"), ("vowels", "automatic verifier registry"),
                       ("letters", "tier probe 2026!"), ("words", "one two three four five six seven"),
                       ("vowels", "decontaminate the training split")]:
        t = text
        val = {"words": len(t.split()), "characters": len(t), "letters": sum(c.isalpha() for c in t),
               "vowels": sum(c in "aeiou" for c in t.lower())}[kind]
        out.append(g("text_transform", "deterministic", f"How many {kind} are in '{text}'?", num(val, 0, 0)))
    for a, b in [("2023-02-14", "2023-11-30"), ("2019-07-04", "2024-07-04"), ("2025-12-25", "2026-03-01")]:
        out.append(g("arithmetic", "deterministic", f"How many days are there between {a} and {b}?",
                     num(abs((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days), 0, 0)))
    for d in ["1969-07-20", "2000-01-01", "2031-10-09"]:
        out.append(g("text_transform", "deterministic", f"What day of the week was {d}?",
                     exact(dt.date.fromisoformat(d).strftime("%A"))))
    for y in (1900, 2024):
        leap = "yes" if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else "no"
        out.append(g("text_transform", "deterministic", f"Is {y} a leap year?", exact(leap)))
    roman = [(1987, "MCMLXXXVII"), (2026, "MMXXVI"), (444, "CDXLIV"), (3999, "MMMCMXCIX")]
    for n, r in roman:
        out.append(g("text_transform", "deterministic", f"Convert {n} to roman numerals.", exact(r)))
    for r, n in [("MDCCLXXVI", 1776), ("XCIV", 94)]:
        out.append(g("arithmetic", "deterministic", f"Convert the roman numeral {r} to an integer.", num(n, 0, 0)))
    for a, b in [(1071, 462), (840, 3528), (97, 89)]:
        out.append(g("arithmetic", "deterministic", f"What is the greatest common divisor of {a} and {b}?", num(math.gcd(a, b), 0, 0)))
    for a, b in [(21, 6), (48, 180)]:
        out.append(g("arithmetic", "deterministic", f"What is the least common multiple of {a} and {b}?", num(math.lcm(a, b), 0, 0)))
    for n in (7919, 8633, 104729):
        prime = all(n % d for d in range(2, math.isqrt(n) + 1))
        out.append(g("text_transform", "deterministic", f"Is {n} a prime number?", exact("yes" if prime else "no")))
    for n in (12, 20):
        out.append(g("arithmetic", "deterministic", f"What is the factorial of {n}?", num(math.factorial(n), 0, 0)))
    for nums, order in [([42, -7, 19, 3.5, 0], "ascending"), ([15, 99, 4, 61, 23, 8], "descending"),
                        ([1000, 10, 100, 1], "ascending")]:
        s = sorted(nums, reverse=order == "descending")
        want = ", ".join(str(int(x)) if float(x).is_integer() else str(x) for x in s)
        out.append(g("text_transform", "deterministic",
                     f"Sort the numbers {', '.join(str(x) for x in nums)} in {order} order.", exact(want)))
    extracts = [
        ("email addresses", "Reach ops at ops@example.org or the lead, j.doe+router@mail.example.com, today.",
         "ops@example.org, j.doe+router@mail.example.com"),
        ("urls", "Docs live at https://example.com/docs and the mirror https://mirror.example.net/a/b.",
         "https://example.com/docs, https://mirror.example.net/a/b"),
        ("hashtags", "Shipping the probe #router #benchmarks and resting #weekend", "#router, #benchmarks, #weekend"),
        ("years", "The survey covers 1998, 2004 and 2021 releases.", "1998, 2004, 2021"),
    ]
    for kind, text, want in extracts:
        out.append(g("regex_extraction", "deterministic", f"Extract all {kind} from: {text}", exact(want)))
    out.append(g("text_transform", "deterministic", "Reverse the string 'minimal sufficient tier'.",
                 exact("reit tneiciffus laminim")))
    out.append(g("text_transform", "deterministic", "Convert 'shape concentration' to uppercase.",
                 exact("SHAPE CONCENTRATION")))
    js = {"router": {"tier": "llm", "budget": {"tokens": 2000}}, "ok": True}
    out.append(g("json", "deterministic", f"What is the value of key 'router.budget.tokens' in JSON {json.dumps(js)}",
                 num(2000, 0, 0)))
    out.append(g("json", "deterministic", f"What is the value of key 'router.tier' in JSON {json.dumps(js)}", exact("llm")))
    for n in (1764, 2.25):
        out.append(g("arithmetic", "deterministic", f"What is the square root of {n}?", num(math.sqrt(n))))
    for cmd in ("router status", "forge list"):
        out.append(g("command", "deterministic", f"Run the read-only scout command `scout {cmd}`.",
                     {"type": "exit_code", "expected_output": r'"ok":\s*true'}))
    return out


NAMES = ["Maya", "Arjun", "Lena", "Tomas", "Ife", "Noor", "Kenji", "Rosa"]
NUMBER_WORDS = {13: "thirteen", 17: "seventeen", 24: "twenty-four", 36: "thirty-six", 45: "forty-five",
                58: "fifty-eight", 72: "seventy-two", 91: "ninety-one"}


def word_problems(rng: random.Random) -> list[dict]:
    out = []
    for _ in range(4):
        p, n = rng.randint(2, 9), rng.randint(3, 12)
        bill = 100 if p * n > 50 else 50
        name = rng.choice(NAMES)
        out.append(g("numeric_reasoning", "llm", f"A shop sells notebooks at ${p} each. {name} buys {n} notebooks and "
                     f"pays with a ${bill} bill. How much change, in dollars, does {name} receive?", num(bill - p * n, 0, 0)))
    for _ in range(4):
        v, t = rng.randint(40, 120), rng.choice([1.5, 2.5, 3, 4.25])
        out.append(g("numeric_reasoning", "llm", f"A train travels at {v} km per hour for {t} hours. How many kilometres "
                     "does it travel?", num(v * t)))
    for _ in range(4):
        a, b, c = rng.randint(20, 60), rng.randint(3, 15), rng.randint(5, 30)
        name = rng.choice(NAMES)
        out.append(g("numeric_reasoning", "llm", f"{name} has {a} apples, gives {b} of them to a friend, then buys {c} "
                     f"more. How many apples does {name} have now?", num(a - b + c, 0, 0)))
    for _ in range(4):
        w, h = rng.randint(3, 40), rng.randint(3, 40)
        out.append(g("numeric_reasoning", "llm", f"A rectangular garden is {w} m wide and {h} m long. A fence goes "
                     "all the way around it. How many metres of fence are needed?", num(2 * (w + h), 0, 0)))
    for _ in range(4):
        n, k, hrs = rng.randint(2, 9), rng.randint(4, 30), rng.randint(2, 8)
        out.append(g("numeric_reasoning", "llm", f"{n} workers each assemble {k} widgets per hour. How many widgets do "
                     f"they assemble together in {hrs} hours?", num(n * k * hrs, 0, 0)))
    pairs = rng.sample(sorted(NUMBER_WORDS), 8)
    for a, b in zip(pairs[::2], pairs[1::2], strict=True):
        out.append(g("numeric_reasoning", "llm", f"Multiply {NUMBER_WORDS[a]} by {NUMBER_WORDS[b]}.", num(a * b, 0, 0)))
    return out


CODE_TASKS = [
    ("is_palindrome(s)", "returns True when s reads the same backwards, ignoring case and non-alphanumeric characters",
     "assert is_palindrome('A man, a plan, a canal: Panama')\nassert not is_palindrome('router')\nassert is_palindrome('')",
     "def is_palindrome(s):\n    t=[c.lower() for c in s if c.isalnum()]\n    return t==t[::-1]"),
    ("fizzbuzz(n)", "returns a list of strings for 1..n: 'Fizz' for multiples of 3, 'Buzz' for 5, 'FizzBuzz' for both, else the number",
     "assert fizzbuzz(5)==['1','2','Fizz','4','Buzz']\nassert fizzbuzz(15)[-1]=='FizzBuzz'\nassert fizzbuzz(0)==[]",
     "def fizzbuzz(n):\n    return ['FizzBuzz' if i%15==0 else 'Fizz' if i%3==0 else 'Buzz' if i%5==0 else str(i) for i in range(1,n+1)]"),
    ("flatten(xs)", "flattens arbitrarily nested lists into one flat list, preserving order",
     "assert flatten([1,[2,[3,[4]]],5])==[1,2,3,4,5]\nassert flatten([])==[]\nassert flatten([[[]]])==[]",
     "def flatten(xs):\n    out=[]\n    for x in xs:\n        out.extend(flatten(x) if isinstance(x,list) else [x])\n    return out"),
    ("word_count(text)", "returns a dict mapping each lowercase word (split on whitespace) to its count",
     "assert word_count('a b A')=={'a':2,'b':1}\nassert word_count('')=={}",
     "def word_count(text):\n    d={}\n    for w in text.lower().split():\n        d[w]=d.get(w,0)+1\n    return d"),
    ("is_anagram(a, b)", "returns True when a and b are anagrams, ignoring case and spaces",
     "assert is_anagram('Listen','Silent')\nassert is_anagram('dormitory','dirty room')\nassert not is_anagram('abc','abd')",
     "def is_anagram(a,b):\n    f=lambda s: sorted(s.replace(' ','').lower())\n    return f(a)==f(b)"),
    ("fib(n)", "returns the n-th Fibonacci number with fib(0)=0 and fib(1)=1, efficiently for n up to 90",
     "assert fib(0)==0 and fib(1)==1 and fib(10)==55\nassert fib(90)==2880067194370816120",
     "def fib(n):\n    a,b=0,1\n    for _ in range(n):\n        a,b=b,a+b\n    return a"),
    ("merge_intervals(iv)", "merges overlapping [start, end] intervals and returns them sorted by start",
     "assert merge_intervals([[1,3],[2,6],[8,10],[15,18]])==[[1,6],[8,10],[15,18]]\nassert merge_intervals([[1,4],[4,5]])==[[1,5]]\nassert merge_intervals([])==[]",
     "def merge_intervals(iv):\n    out=[]\n    for s,e in sorted(iv):\n        if out and s<=out[-1][1]:\n            out[-1][1]=max(out[-1][1],e)\n        else:\n            out.append([s,e])\n    return out"),
    ("rotate(m)", "rotates a square matrix (list of lists) 90 degrees clockwise and returns the new matrix",
     "assert rotate([[1,2],[3,4]])==[[3,1],[4,2]]\nassert rotate([[1]])==[[1]]",
     "def rotate(m):\n    return [list(r) for r in zip(*m[::-1])]"),
    ("roman_to_int(s)", "converts a valid Roman numeral string to an integer",
     "assert roman_to_int('MCMXCIV')==1994\nassert roman_to_int('LVIII')==58\nassert roman_to_int('IX')==9",
     "def roman_to_int(s):\n    v={'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}\n    return sum(-v[c] if i+1<len(s) and v[c]<v[s[i+1]] else v[c] for i,c in enumerate(s))"),
    ("binary_search(arr, target)", "returns the index of target in the sorted list arr, or -1 when absent",
     "assert binary_search([1,3,5,7,9],7)==3\nassert binary_search([1,3,5],4)==-1\nassert binary_search([],1)==-1",
     "def binary_search(arr,target):\n    lo,hi=0,len(arr)-1\n    while lo<=hi:\n        mid=(lo+hi)//2\n        if arr[mid]==target: return mid\n        if arr[mid]<target: lo=mid+1\n        else: hi=mid-1\n    return -1"),
    ("dedupe(xs)", "removes duplicates from a list while preserving first-occurrence order",
     "assert dedupe([3,1,3,2,1])==[3,1,2]\nassert dedupe([])==[]",
     "def dedupe(xs):\n    seen=set(); out=[]\n    for x in xs:\n        if x not in seen:\n            seen.add(x); out.append(x)\n    return out"),
    ("chunk(xs, n)", "splits a list into consecutive chunks of size n (the last may be shorter)",
     "assert chunk([1,2,3,4,5],2)==[[1,2],[3,4],[5]]\nassert chunk([],3)==[]",
     "def chunk(xs,n):\n    return [xs[i:i+n] for i in range(0,len(xs),n)]"),
    ("camel_to_snake(s)", "converts camelCase or PascalCase to snake_case",
     "assert camel_to_snake('minimalSufficientTier')=='minimal_sufficient_tier'\nassert camel_to_snake('HTTPServer')=='http_server'\nassert camel_to_snake('x')=='x'",
     "import re\ndef camel_to_snake(s):\n    s=re.sub(r'([A-Z]+)([A-Z][a-z])',r'\\1_\\2',s)\n    return re.sub(r'([a-z0-9])([A-Z])',r'\\1_\\2',s).lower()"),
    ("second_largest(nums)", "returns the second largest DISTINCT value, or None when there is none",
     "assert second_largest([4,1,4,3])==3\nassert second_largest([5,5])is None\nassert second_largest([-2,-1])==-2",
     "def second_largest(nums):\n    u=sorted(set(nums))\n    return u[-2] if len(u)>1 else None"),
    ("transpose(m)", "returns the transpose of a rectangular matrix given as a list of lists",
     "assert transpose([[1,2,3],[4,5,6]])==[[1,4],[2,5],[3,6]]\nassert transpose([])==[]",
     "def transpose(m):\n    return [list(r) for r in zip(*m)]"),
    ("rle(s)", "run-length encodes a string: 'aaabcc' becomes 'a3b1c2'",
     "assert rle('aaabcc')=='a3b1c2'\nassert rle('')==''\nassert rle('z')=='z1'",
     "def rle(s):\n    out=[]\n    i=0\n    while i<len(s):\n        j=i\n        while j<len(s) and s[j]==s[i]: j+=1\n        out.append(f'{s[i]}{j-i}'); i=j\n    return ''.join(out)"),
    ("balanced(s)", "returns True when the brackets ()[]{} in s are balanced and properly nested",
     "assert balanced('([]{})')\nassert not balanced('([)]')\nassert balanced('')\nassert not balanced('((')",
     "def balanced(s):\n    st=[]; pairs={')':'(',']':'[','}':'{'}\n    for c in s:\n        if c in '([{': st.append(c)\n        elif c in pairs:\n            if not st or st.pop()!=pairs[c]: return False\n    return not st"),
    ("gcd_all(nums)", "returns the greatest common divisor of a non-empty list of positive integers",
     "assert gcd_all([12,18,24])==6\nassert gcd_all([7])==7\nassert gcd_all([9,28])==1",
     "import math\ndef gcd_all(nums):\n    g=0\n    for n in nums: g=math.gcd(g,n)\n    return g"),
    ("caesar(s, k)", "shifts each ASCII letter k places through the alphabet (wrapping, preserving case); other characters unchanged",
     "assert caesar('abc XyZ!',2)=='cde ZaB!'\nassert caesar('hello',26)=='hello'\nassert caesar('b',-1)=='a'",
     "def caesar(s,k):\n    out=[]\n    for c in s:\n        if c.isascii() and c.isalpha():\n            b=ord('a') if c.islower() else ord('A')\n            out.append(chr((ord(c)-b+k)%26+b))\n        else:\n            out.append(c)\n    return ''.join(out)"),
    ("median(nums)", "returns the median of a non-empty list of numbers (the mean of the two middle values for even length)",
     "assert median([3,1,2])==2\nassert median([4,1,3,2])==2.5\nassert median([7])==7",
     "def median(nums):\n    s=sorted(nums); n=len(s)\n    return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2"),
]


def code_goals() -> list[dict]:
    out = []
    for sig, desc, tests, ref in CODE_TASKS:
        goal = f"Write a Python function `{sig}` that {desc}."
        spec = {"type": "unit_tests", "tests": tests}
        if not verify({"answer": ref}, spec)["passed"]:
            raise SystemExit(f"reference solution fails its own tests: {sig}")
        out.append(g("code", "llm", goal, spec, reference=ref))
    return out


def json_goals() -> list[dict]:
    specs = [
        ("Return only a JSON object with keys \"city\" (a string) and \"population\" (an integer) for a town named "
         "Brightwater with 18250 residents.", {"city": "Brightwater", "population": 18250},
         {"type": "object", "required": ["city", "population"],
          "properties": {"city": {"type": "string"}, "population": {"type": "integer"}}}),
        ("Return only a JSON array of the three primary colours of light, in lowercase, ordered red, green, blue.",
         ["red", "green", "blue"], {"type": "array", "items": {"type": "string"}, "minItems": 3}),
        ("Return only a JSON object mapping each of the words \"tier\", \"probe\" and \"label\" to its number of letters.",
         {"tier": 4, "probe": 5, "label": 5}, {"type": "object", "required": ["tier", "probe", "label"]}),
        ("Return only a JSON object with a boolean key \"is_weekend\" that is true, and an integer key \"hours\" equal to 48.",
         {"is_weekend": True, "hours": 48}, {"type": "object", "required": ["is_weekend", "hours"],
                                               "properties": {"is_weekend": {"type": "boolean"}, "hours": {"type": "integer"}}}),
        ("Return only a JSON object describing a book: \"title\" is \"Dune\", \"author\" is \"Frank Herbert\", \"year\" is 1965.",
         {"title": "Dune", "author": "Frank Herbert", "year": 1965},
         {"type": "object", "required": ["title", "author", "year"], "properties": {"year": {"type": "integer"}}}),
        ("Return only a JSON array of the first five square numbers starting from 1.", [1, 4, 9, 16, 25],
         {"type": "array", "items": {"type": "integer"}, "minItems": 5}),
        ("Return only a JSON object with key \"celsius\" set to 100 and key \"fahrenheit\" set to the equivalent temperature.",
         {"celsius": 100, "fahrenheit": 212}, {"type": "object", "required": ["celsius", "fahrenheit"]}),
        ("Return only a JSON object with a key \"weekdays\" whose value is the list of the five weekday names from Monday to Friday.",
         {"weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
         {"type": "object", "required": ["weekdays"], "properties": {"weekdays": {"type": "array", "minItems": 5}}}),
    ]
    return [g("json", "llm", goal, {"type": "json_schema", "schema": schema, "expected": want}) for goal, want, schema in specs]


def language_goals() -> list[dict]:
    rows = [
        ("What is the plural of the English noun 'mouse' (the animal)? Answer with one word.", exact("mice")),
        ("What is the plural of 'goose'? Answer with one word.", exact("geese")),
        ("What is the past tense of the verb 'swim'? Answer with one word.", exact("swam")),
        ("What is the past tense of the verb 'teach'? Answer with one word.", exact("taught")),
        ("Put these words in alphabetical order, comma-separated: pear, apple, fig, banana.", exact("apple, banana, fig, pear")),
        ("Spell the word 'necessary' backwards, all lowercase.", exact("yrassecen")),
        ("Which word does not belong: apple, banana, carrot, cherry? Answer with the word.", exact("carrot")),
        ("What is the chemical symbol for tungsten?", exact("W")),
        ("What is the chemical symbol for potassium?", exact("K")),
        ("How many sides does a heptagon have?", num(7, 0, 0)),
        ("How many bits are in one byte?", num(8, 0, 0)),
        ("Which planet is closest to the Sun? Answer with one word.", exact("Mercury")),
        ("In which year did the Apollo 11 crew first land on the Moon?", num(1969, 0, 0)),
        ("What is the freezing point of water at sea level in degrees Fahrenheit?", num(32, 0, 0)),
    ]
    return [g("fact_exact" if "chemical" in q or "planet" in q or "Apollo" in q or "freezing" in q or "heptagon" in q
              or "bits" in q else "text_transform", "llm", q, spec) for q, spec in rows]


def _surname(name: str) -> str:
    return name.split()[-1]


def research_goals() -> list[dict]:
    papers = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["papers"]
    rng = random.Random(20260923)
    order = list(range(len(papers)))
    rng.shuffle(order)
    out = []
    kinds = ["title_to_id"] * 24 + ["first_author"] * 16 + ["year"] * 14 + ["category"] * 14
    for kind, i in zip(kinds, order, strict=True):
        p = papers[i]
        pid = p["id"].replace(".", r"\.")
        cite = {"type": "citations", "min_sources": 1}
        if kind == "title_to_id":
            goal = f'Find the arXiv identifier of the paper titled "{p["title"]}".'
            check = {"type": "regex", "pattern": rf"\b{pid}(v\d+)?\b"}
        elif kind == "first_author":
            goal = f"Who is the first author of arXiv paper {p['id']}?"
            check = {"type": "contains", "expected": _surname(p["authors"][0])}
        elif kind == "year":
            goal = f"In which year was arXiv paper {p['id']} first submitted?"
            check = {"type": "regex", "pattern": rf"\b{p['year']}\b"}
        else:
            goal = f"What is the primary arXiv category of paper {p['id']}?"
            check = {"type": "regex", "pattern": rf"(?<![\w.]){p['primary_category'].replace('.', chr(92) + '.')}(?![\w.])"}
        out.append(g("lookup", "deep_research", goal, {**cite, "answer_check": check}, source=p["source"]))
    return out


def eval_set_hashes() -> set[str]:
    hashes: set[str] = set()
    for path in EVAL_SETS:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        docs = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" else [json.loads(text)]
        stack = list(docs)
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                stack += list(d.values())
            elif isinstance(d, list):
                stack += d
            elif isinstance(d, str) and len(d) >= 6:
                hashes.add(goal_norm_sha256(d))
    return hashes


def build() -> list[dict]:
    rng = random.Random(1117)
    goals = deterministic_goals(rng) + word_problems(rng) + code_goals() + json_goals() + language_goals() + research_goals()
    external = eval_set_hashes()
    seen: dict[str, str] = {}
    out = []
    for n, goal in enumerate(goals, 1):
        errs = validate_spec(goal["verifier"])
        if errs:
            raise SystemExit(f"goal {n}: {errs}")
        key = goal_norm_sha256(goal["goal"])
        if key in seen:
            raise SystemExit(f"duplicate after normalisation: {goal['goal']!r}")
        if key in external:
            raise SystemExit(f"contaminated: {goal['goal']!r} is in an existing eval set")
        seen[key] = goal["goal"]
        out.append({"id": f"rb1-{n:03d}", **goal})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed file differs from a fresh build")
    args = ap.parse_args(argv)
    body = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in build())
    if args.check:
        same = OUT.is_file() and OUT.read_text(encoding="utf-8") == body
        print("router bench up to date" if same else f"{OUT} is stale; re-run without --check")
        return 0 if same else 1
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT} ({body.count(chr(10))} goals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
