"""Tool-use curriculum (spec 15 §4) — teaches Dottie/Ava to *use* tools well:
select the right one among many, chain multi-step (seq + parallel fan-out),
recover from errors, and refuse/ground when appropriate.

This is the deliberate successor to ``react_tools.py``. It keeps that module's
grounding/anti-hallucination strength but closes its gaps (single call, ≤2
steps, ~8 fixed fake functions, one implicit tool, only the "(no matches)"
failure) with a six-level ladder:

    L0  grounded single   — one call, answer taken verbatim from the Observation.
    L1  multi-step chain   — 2–4 calls, later args come from earlier Observations.
    L2  error & recovery   — a bad-arg / timeout / empty Observation, then a
                            corrected retry or an honest give-up.
    L3  tool selection     — an in-context catalog of many tools; pick the one
                            that fits and ignore plausible distractors.
    L4  negative / refuse  — answer directly with no tool when none is needed;
                            refuse to invoke a destructive tool (a safety turn).
    L5  program / parallel — single-shot *tool program* (LLM-VM mindset): declare
                            a sequential+parallel schedule up front, fan out
                            independent syscalls, then reduce. Still one Action
                            per assistant turn (production parser); parallelism
                            is in the *schedule*, not multi-Action turns.
                            Pairs with ``think_in_code`` (code as scheduler).

Hard constraints (spec 15 §0):
  * **Frozen tokenizer** — no new special tokens. Everything is the existing
    plain-text ReAct convention: ``Action: fn(args)`` inside an ``<|assistant|>``
    turn, tool results returned as an ``<|user|>`` turn prefixed ``Observation:``.
  * **Parser-compatible** — every ``Action:`` line matches the production regex
    ``AgenticOS/ava_bridge.py::_ACTION_RE`` (tool names ``[a-zA-Z_][a-zA-Z0-9_]*``,
    args in parens, one Action per assistant turn). Tests assert this.
  * **Determinism** — only ``self.rng``; answers computed in Python from the
    tool's Observation, never templated independently of it.

Task types: ``deliberate`` (compute/recover), ``tool_selection`` (pick / schedule),
``temporal`` (date/order), ``safety`` (refuse a destructive tool).
All ⊆ VALID_TASK_TYPES.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dottie.datagen.base import Generator

if TYPE_CHECKING:
    from collections.abc import Iterator

USER = "<|user|>"
ASSISTANT = "<|assistant|>"


def dialogue(turns: list[tuple[str, str]]) -> str:
    parts = []
    for role, content in turns:
        marker = USER if role == "user" else ASSISTANT
        parts.append(f"{marker}\n{content}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Vocabularies — large and varied to prevent memorization. Tool names are all
# valid identifiers (matched by the production _ACTION_RE).
# ---------------------------------------------------------------------------

_FILES = [
    "utils.py",
    "helpers.py",
    "core.py",
    "config.py",
    "models.py",
    "server.py",
    "README.md",
    "CHANGELOG.md",
    "notes.txt",
    "manifest.yaml",
    "data.csv",
    "report.md",
    "pipeline.py",
    "trainer.py",
    "schema.json",
    "results.tsv",
]
_DIRS = [
    "logs",
    "reports",
    "shards",
    "exports",
    "backups",
    "cache",
    "runs",
    "checkpoints",
    "datasets",
    "artifacts",
    "tmp",
    "configs",
]
_PATTERNS = [
    "retry",
    "timeout",
    "error",
    "TODO",
    "deprecated",
    "import",
    "assert",
    "return",
    "yield",
    "raise",
    "cache",
    "seed",
]
_WORDS = [
    "pipeline",
    "gradient",
    "tensor",
    "shard",
    "curriculum",
    "entropy",
    "router",
    "token",
    "manifest",
    "anneal",
    "checkpoint",
    "corpus",
    "sampler",
    "throughput",
    "latency",
    "grounding",
    "observation",
]
_DATES = [f"2026-{m:02d}-{d:02d}" for m in range(1, 13) for d in (3, 11, 19, 27)]

# Distractor tools for the L3 catalog — plausible but wrong for the given task.
# (name, signature, one-line purpose)
_CATALOG_POOL = [
    ("get_clock", "get_clock()", "return the current UTC date and time"),
    ("word_count", "word_count(path)", "count the words in a text file"),
    ("char_count", "char_count(path)", "count the characters in a text file"),
    ("repo_grep", "repo_grep(pattern, path)", "count matches of a pattern in a file"),
    ("repo_read_file", "repo_read_file(path)", "read a text file's contents"),
    ("list_dir", "list_dir(path)", "list the entries of a directory"),
    ("multiply", "multiply(a, b)", "multiply two numbers"),
    ("add", "add(a, b)", "add two numbers"),
    ("sum", "sum(values=[...])", "sum a list of numbers"),
    (
        "currency_convert",
        "currency_convert(amount, rate)",
        "convert an amount at a rate",
    ),
    ("summarize", "summarize(path)", "summarize a long document"),
    ("translate", "translate(text, lang)", "translate text into another language"),
    ("weather", "weather(city)", "look up the current weather for a city"),
    ("db_query", "db_query(table, filter)", "query a database table"),
    ("send_email", "send_email(to, subject, body)", "send an email"),
    ("web_search", "web_search(query)", "search the web"),
    ("delete_file", "delete_file(path)", "permanently delete a file"),
]
_CATALOG_BY_NAME = {name: (sig, desc) for name, sig, desc in _CATALOG_POOL}


def _render_catalog(rng, must_include: str, k: int = 5) -> str:
    """A tool-catalog framing that always contains ``must_include`` plus k-1
    distractors, shuffled deterministically."""
    others = [n for n, _, _ in _CATALOG_POOL if n != must_include]
    rng.shuffle(others)
    chosen = [must_include, *others[: max(0, k - 1)]]
    rng.shuffle(chosen)
    lines = ["Available tools (choose the single most appropriate one):"]
    for name in chosen:
        sig, desc = _CATALOG_BY_NAME[name]
        lines.append(f"- {sig} — {desc}")
    return "\n".join(lines)


def _sentence(rng, n: int) -> str:
    """A deterministic n-word sentence from the word pool."""
    return " ".join(rng.choice(_WORDS) for _ in range(n))


# ---------------------------------------------------------------------------
# L0 — grounded single call. Answer is the Observation, verbatim.
# ---------------------------------------------------------------------------


def l0_arith_doc(rng) -> tuple[str, str, str]:
    a, b = rng.randint(3, 989), rng.randint(3, 989)
    op = rng.choice(["+", "-", "*"])
    fn = {"+": "add", "-": "subtract", "*": "multiply"}[op]
    result = {"+": a + b, "-": a - b, "*": a * b}[op]
    text = dialogue(
        [
            (
                "user",
                f"What is {a} {op} {b}? Use the calculator, don't do it in your head.",
            ),
            (
                "assistant",
                "Thought: I'll call the calculator so the answer is grounded in the tool, not my arithmetic.\n"
                f"Action: {fn}(a={a}, b={b})",
            ),
            ("user", f"Observation: {result}"),
            ("assistant", f"{a} {op} {b} = {result}."),
        ]
    )
    return text, "deliberate", "tool_math"


def l0_wordcount_doc(rng) -> tuple[str, str, str]:
    fname = rng.choice(_FILES)
    n = rng.randint(6, 30)
    sentence = _sentence(rng, n)
    text = dialogue(
        [
            ("user", f"How many words are in {fname}?"),
            (
                "assistant",
                "Thought: I shouldn't guess the length; I'll count it with the tool.\n"
                f'Action: word_count(path="{fname}")',
            ),
            ("user", f'Observation: {n} words — "{sentence}"'),
            ("assistant", f"{fname} has {n} words."),
        ]
    )
    return text, "deliberate", "tool_ground"


def l0_date_doc(rng) -> tuple[str, str, str]:
    date = rng.choice(_DATES)
    text = dialogue(
        [
            ("user", "What is today's date?"),
            (
                "assistant",
                "Thought: my weights are frozen; I can't know the date from memory. I'll check the clock.\n"
                "Action: get_clock()",
            ),
            ("user", f"Observation: {date}"),
            ("assistant", f"Today is {date}."),
        ]
    )
    return text, "temporal", "tool_date"


# ---------------------------------------------------------------------------
# L1 — multi-step chains. Later args come from earlier Observations; the final
# number is computed in Python from the Observations.
# ---------------------------------------------------------------------------


def l1_listdir_sum_doc(rng) -> tuple[str, str, str]:
    dirname = rng.choice(_DIRS)
    n = rng.randint(3, 6)
    sizes = [rng.randint(4, 900) for _ in range(n)]
    names = [
        f"{dirname[:-1] if dirname.endswith('s') else dirname}_{i:02d}.dat"
        for i in range(n)
    ]
    listing = ", ".join(f"{nm} ({sz} KB)" for nm, sz in zip(names, sizes, strict=False))
    total = sum(sizes)
    largest = names[sizes.index(max(sizes))]
    text = dialogue(
        [
            (
                "user",
                f"How many files are in /{dirname}, what's their total size, and which is largest?",
            ),
            (
                "assistant",
                "Thought: three facts, none of which I should guess. First list the directory.\n"
                f'Action: list_dir(path="/{dirname}")',
            ),
            ("user", f"Observation: {listing}"),
            (
                "assistant",
                "Thought: I'll sum the sizes with the calculator rather than adding in my head.\n"
                f"Action: sum(values=[{', '.join(str(s) for s in sizes)}])",
            ),
            ("user", f"Observation: {total}"),
            (
                "assistant",
                f"/{dirname} has {n} files totaling {total} KB; the largest is {largest} "
                f"at {max(sizes)} KB. Every number came from a tool.",
            ),
        ]
    )
    return text, "deliberate", "tool_chain"


def l1_read_then_multiply_doc(rng) -> tuple[str, str, str]:
    fname = rng.choice(["config.py", "manifest.yaml", "trainer.py", "schema.json"])
    key = rng.choice(["batch_size", "num_workers", "n_layers", "seq_per_shard"])
    base = rng.randint(4, 64)
    factor = rng.randint(2, 12)
    product = base * factor
    text = dialogue(
        [
            (
                "user",
                f"The file {fname} sets {key}. If each unit needs {factor} slots, how many slots total? "
                f"Read the file first — don't assume the value.",
            ),
            (
                "assistant",
                "Thought: I need the actual value from the file, not a guess.\n"
                f'Action: repo_read_file(path="{fname}")',
            ),
            ("user", f'Observation: "{key} = {base}"'),
            (
                "assistant",
                f"Thought: {key} is {base}; {base} × {factor} should go through the calculator.\n"
                f"Action: multiply(a={base}, b={factor})",
            ),
            ("user", f"Observation: {product}"),
            (
                "assistant",
                f"{key} is {base}, so at {factor} slots each that's {product} slots total — "
                f"both numbers came from tools.",
            ),
        ]
    )
    return text, "deliberate", "tool_chain"


def l1_two_reads_add_doc(rng) -> tuple[str, str, str]:
    f1, f2 = rng.sample(_FILES, 2)
    w1, w2 = rng.randint(20, 400), rng.randint(20, 400)
    total = w1 + w2
    text = dialogue(
        [
            ("user", f"What is the combined word count of {f1} and {f2}?"),
            (
                "assistant",
                "Thought: count each file, then add — I'll use tools for both so nothing is guessed.\n"
                f'Action: word_count(path="{f1}")',
            ),
            ("user", f"Observation: {w1} words"),
            (
                "assistant",
                f'Thought: now the second file.\nAction: word_count(path="{f2}")',
            ),
            ("user", f"Observation: {w2} words"),
            (
                "assistant",
                f"Thought: {w1} + {w2} through the calculator.\n"
                f"Action: add(a={w1}, b={w2})",
            ),
            ("user", f"Observation: {total}"),
            (
                "assistant",
                f"{f1} has {w1} words and {f2} has {w2}, for {total} words combined.",
            ),
        ]
    )
    return text, "deliberate", "tool_chain"


# ---------------------------------------------------------------------------
# L2 — error & recovery. A failed Observation, then a corrected retry (or an
# honest give-up that never fabricates).
# ---------------------------------------------------------------------------


def l2_badarg_recover_doc(rng) -> tuple[str, str, str]:
    amount = rng.randint(10, 5000)
    rate = rng.choice([0.85, 0.92, 1.08, 1.27, 0.74, 1.36])
    result = round(amount * rate, 2)
    typo = rng.choice([("amont", "amount"), ("amt", "amount"), ("rat", "rate")])
    bad, good = typo
    good_call = (
        f"currency_convert({bad}={amount}, rate={rate})"
        if good == "amount"
        else f"currency_convert(amount={amount}, {bad}={rate})"
    )
    fixed_call = f"currency_convert(amount={amount}, rate={rate})"
    text = dialogue(
        [
            ("user", f"Convert {amount} at a rate of {rate}."),
            ("assistant", f"Thought: I'll use the converter.\nAction: {good_call}"),
            (
                "user",
                f"Observation: Error: unknown argument '{bad}' (did you mean '{good}'?)",
            ),
            (
                "assistant",
                f"Thought: I mistyped the argument name — the tool wants '{good}'. I'll fix it and retry "
                "rather than invent a result.\n"
                f"Action: {fixed_call}",
            ),
            ("user", f"Observation: {result}"),
            (
                "assistant",
                f"{amount} at rate {rate} is {result}. The first call errored on a typo'd "
                "argument; I corrected it instead of guessing.",
            ),
        ]
    )
    return text, "deliberate", "tool_recover"


def l2_timeout_fallback_doc(rng) -> tuple[str, str, str]:
    key = rng.choice(["daily_active", "queue_depth", "best_bpb", "tokens_ready"])
    value = rng.randint(100, 99999)
    text = dialogue(
        [
            ("user", f"What's the latest {key}?"),
            (
                "assistant",
                "Thought: I'll query the live service.\n"
                f'Action: db_query(table="metrics", filter="{key}")',
            ),
            ("user", "Observation: Error: timeout after 5s"),
            (
                "assistant",
                "Thought: the live query timed out. Rather than make up a number, I'll fall back to the "
                "cached snapshot.\n"
                f'Action: kv_get(key="{key}")',
            ),
            ("user", f"Observation: {value} (cached)"),
            (
                "assistant",
                f"The live query timed out, so from the cached snapshot {key} is {value}. I flagged that "
                "it's cached rather than presenting it as live.",
            ),
        ]
    )
    return text, "temporal", "tool_recover"


def l2_empty_giveup_doc(rng) -> tuple[str, str, str]:
    fn = rng.choice(
        [
            "divide_safely",
            "auto_retry",
            "parse_config_v2",
            "cached_lookup",
            "batch_convert",
            "validate_schema_strict",
            "normalize_path",
        ]
    )
    f1, f2 = rng.sample(_FILES, 2)
    text = dialogue(
        [
            ("user", f"What does {fn}() do in this codebase?"),
            (
                "assistant",
                "Thought: I'll search before answering rather than guess from the name.\n"
                f'Action: repo_grep(pattern="{fn}", path="{f1}")',
            ),
            ("user", "Observation: (no matches)"),
            (
                "assistant",
                f"Thought: not in {f1}; I'll check {f2} before concluding it's absent.\n"
                f'Action: repo_grep(pattern="{fn}", path="{f2}")',
            ),
            ("user", "Observation: (no matches)"),
            (
                "assistant",
                f"I searched {f1} and {f2} and found no definition of {fn} — I can't tell you what it does "
                "because it doesn't appear to exist. I won't invent plausible-sounding behavior for it.",
            ),
        ]
    )
    return text, "deliberate", "tool_recover"


# ---------------------------------------------------------------------------
# L3 — tool selection. An in-context catalog of many tools; pick the right one.
# ---------------------------------------------------------------------------


def _l3_wordcount(rng):
    fname = rng.choice(_FILES)
    n = rng.randint(8, 60)
    q = f"How many words does {fname} contain?"
    call = f'word_count(path="{fname}")'
    obs = f"{n} words"
    ans = f"{fname} contains {n} words."
    return "word_count", q, call, obs, ans


def _l3_grep(rng):
    pat = rng.choice(_PATTERNS)
    fname = rng.choice(_FILES)
    k = rng.randint(0, 9)
    q = f"How many times does '{pat}' appear in {fname}?"
    call = f'repo_grep(pattern="{pat}", path="{fname}")'
    obs = f"{k} matches"
    ans = f"'{pat}' appears {k} times in {fname}."
    return "repo_grep", q, call, obs, ans


def _l3_multiply(rng):
    a, b = rng.randint(11, 99), rng.randint(11, 99)
    q = f"What is {a} multiplied by {b}?"
    call = f"multiply(a={a}, b={b})"
    obs = f"{a * b}"
    ans = f"{a} × {b} = {a * b}."
    return "multiply", q, call, obs, ans


def _l3_clock(rng):
    date = rng.choice(_DATES)
    q = "What is the current date?"
    call = "get_clock()"
    obs = f"{date}"
    ans = f"The current date is {date}."
    return "get_clock", q, call, obs, ans


_L3_TASKS = [_l3_wordcount, _l3_grep, _l3_multiply, _l3_clock]


def l3_select_doc(rng) -> tuple[str, str, str]:
    tool, question, call, obs, answer = rng.choice(_L3_TASKS)(rng)
    catalog = _render_catalog(rng, must_include=tool, k=rng.randint(5, 6))
    text = dialogue(
        [
            ("user", f"{catalog}\n\nTask: {question}"),
            (
                "assistant",
                f"Thought: of the listed tools, {tool} is the one that answers this; the others don't fit.\n"
                f"Action: {call}",
            ),
            ("user", f"Observation: {obs}"),
            ("assistant", answer),
        ]
    )
    return text, "tool_selection", "tool_select"


# ---------------------------------------------------------------------------
# P4 — long-context search / cite. A planted fact lives in a short dossier;
# the model must retrieve it with a tool and quote the Observation.
# ---------------------------------------------------------------------------


def p4_search_cite_doc(rng) -> tuple[str, str, str]:
    fname = rng.choice(_FILES)
    key = rng.choice(_PATTERNS)
    value = rng.choice(_WORDS)
    filler = " ".join(_sentence(rng, 12) for _ in range(rng.randint(6, 10)))
    planted = f"CONFIRMED: {key} maps to {value}."
    dossier = f"{filler} {planted} {_sentence(rng, 10)}"
    catalog = _render_catalog(rng, must_include="repo_grep", k=rng.randint(5, 6))
    text = dialogue(
        [
            (
                "user",
                f"{catalog}\n\nLong dossier from {fname}:\n---\n{dossier}\n---\n"
                f"What does '{key}' map to? Search the dossier; cite the Observation.",
            ),
            (
                "assistant",
                f"Thought: the answer is somewhere in the dossier — I should search, not guess.\n"
                f'Action: repo_grep(pattern="{key}", path="{fname}")',
            ),
            ("user", f"Observation: {planted}"),
            ("assistant", f"Per the Observation: {planted}"),
        ]
    )
    return text, "tool_selection", "tool_search_cite"


# ---------------------------------------------------------------------------
# L4 — negative / refuse. When NOT to call a tool.
# ---------------------------------------------------------------------------


def l4_direct_answer_doc(rng) -> tuple[str, str, str]:
    num = rng.randint(1, 99)
    catalog = _render_catalog(
        rng,
        must_include=rng.choice(["multiply", "get_clock", "word_count"]),
        k=rng.randint(4, 5),
    )
    text = dialogue(
        [
            (
                "user",
                f"{catalog}\n\nMy favorite number is {num}. What did I just say my favorite number is?",
            ),
            (
                "assistant",
                f"Thought: the answer is stated right in the message — reaching for a tool here would be "
                f"theater. I'll just answer.\n"
                f"Your favorite number is {num}. I didn't need a tool for that; you told me directly.",
            ),
        ]
    )
    return text, "deliberate", "tool_refuse"


_DESTRUCTIVE_REQUESTS = [
    (
        "delete_file",
        "delete every file in /logs to free up space",
        "delete_file removes data irreversibly",
    ),
    (
        "send_email",
        "email the whole team that the run is finished",
        "send_email has an external side effect and I don't have the recipient list or your go-ahead",
    ),
    (
        "db_query",
        "drop the metrics table since it's getting large",
        "dropping a table is destructive and unrecoverable",
    ),
]


def l4_refuse_destructive_doc(rng) -> tuple[str, str, str]:
    tool, request, reason = rng.choice(_DESTRUCTIVE_REQUESTS)
    catalog = _render_catalog(rng, must_include=tool, k=rng.randint(5, 6))
    text = dialogue(
        [
            ("user", f"{catalog}\n\nCan you {request}?"),
            (
                "assistant",
                f"Thought: {tool} is in the catalog, but {reason}. This isn't something I should do "
                f"autonomously — I'll decline and explain rather than call it.\n"
                f"I won't run {tool} for that: {reason}. If you want to proceed, confirm explicitly and "
                f"tell me exactly what to target, and I'll show you the precise call before running it.",
            ),
        ]
    )
    return text, "safety", "tool_refuse"


# ---------------------------------------------------------------------------
# L5 — single-shot tool programs + parallel fan-out (LLM-VM mindset).
# Tools ≈ syscalls; the assistant writes a schedule first, then dispatches
# one Action per turn (Spec 15 / ava_bridge). Independent calls are marked
# parallel in the Program even when serialized by the parser.
# ---------------------------------------------------------------------------


def l5_parallel_gather_doc(rng) -> tuple[str, str, str]:
    """Independent reads → parallel fan-out → arithmetic reduce."""
    f1, f2 = rng.sample(_FILES, 2)
    w1, w2 = rng.randint(20, 400), rng.randint(20, 400)
    total = w1 + w2
    text = dialogue(
        [
            (
                "user",
                f"What is the combined word count of {f1} and {f2}? "
                f"The two counts are independent — schedule them efficiently.",
            ),
            (
                "assistant",
                "Thought: LLM-VM schedule — tools are syscalls. The two word_count calls "
                "have no data dependency (parallel fan-out), then add reduces.\n"
                "Program:\n"
                "  parallel:\n"
                f'    - word_count(path="{f1}") -> $r0\n'
                f'    - word_count(path="{f2}") -> $r1\n'
                "  sequential:\n"
                "    - add(a=$r0, b=$r1) -> $total\n"
                "Dispatching parallel lane 0.\n"
                f'Action: word_count(path="{f1}")',
            ),
            ("user", f"Observation: {w1} words"),
            (
                "assistant",
                "Thought: lane 0 done ($r0). Parallel lane 1 does not need $r0 — still fan-out.\n"
                f'Action: word_count(path="{f2}")',
            ),
            ("user", f"Observation: {w2} words"),
            (
                "assistant",
                f"Thought: reduce the parallel register file: add($r0={w1}, $r1={w2}).\n"
                f"Action: add(a={w1}, b={w2})",
            ),
            ("user", f"Observation: {total}"),
            (
                "assistant",
                f"Combined word count is {total} ({w1} + {w2}). Scheduled as parallel "
                f"fan-out then reduce — not a speculative guess.",
            ),
        ]
    )
    return text, "tool_selection", "tool_program"


def l5_single_shot_program_doc(rng) -> tuple[str, str, str]:
    """Single-shot Program with a sequential dependency after a parallel pair."""
    f1, f2 = rng.sample(_FILES, 2)
    a, b = rng.randint(3, 40), rng.randint(3, 40)
    factor = rng.randint(2, 9)
    product = (a + b) * factor
    text = dialogue(
        [
            (
                "user",
                f"{f1} holds value A and {f2} holds value B. Read both (independent), "
                f"sum them, then multiply by {factor}. Emit one efficient tool program.",
            ),
            (
                "assistant",
                "Thought: single-shot tool program (think-in-code / LLM-VM): plan the DAG, "
                "then dispatch syscalls. A and B are independent; sum depends on both; "
                f"multiply depends on the sum and the constant {factor}.\n"
                "Program:\n"
                "  parallel:\n"
                f'    - repo_read_file(path="{f1}") -> $A\n'
                f'    - repo_read_file(path="{f2}") -> $B\n'
                "  sequential:\n"
                "    - add(a=$A, b=$B) -> $S\n"
                f"    - multiply(a=$S, b={factor}) -> $out\n"
                "Dispatching parallel lane 0.\n"
                f'Action: repo_read_file(path="{f1}")',
            ),
            ("user", f'Observation: "A = {a}"'),
            (
                "assistant",
                "Thought: $A bound. Parallel lane 1 (still independent of $A).\n"
                f'Action: repo_read_file(path="{f2}")',
            ),
            ("user", f'Observation: "B = {b}"'),
            (
                "assistant",
                f"Thought: sequential reduce — add then multiply per the Program.\n"
                f"Action: add(a={a}, b={b})",
            ),
            ("user", f"Observation: {a + b}"),
            (
                "assistant",
                f"Thought: $S={a + b}; final multiply by {factor}.\n"
                f"Action: multiply(a={a + b}, b={factor})",
            ),
            ("user", f"Observation: {product}"),
            (
                "assistant",
                f"Result {product}: read A={a} and B={b} in parallel, then "
                f"({a}+{b})×{factor}. The Program was declared before the first Action.",
            ),
        ]
    )
    return text, "tool_selection", "tool_program"


def l5_seq_dep_program_doc(rng) -> tuple[str, str, str]:
    """Contrast case: must stay sequential — later args need earlier Obs."""
    fname = rng.choice(["config.py", "manifest.yaml", "trainer.py"])
    key = rng.choice(["batch_size", "num_workers", "n_layers"])
    base = rng.randint(4, 64)
    factor = rng.randint(2, 12)
    product = base * factor
    text = dialogue(
        [
            (
                "user",
                f"{fname} sets {key}. Multiply that value by {factor}. "
                f"Do not invent the value — and do not pretend the multiply is parallel "
                f"with the read (it depends on the Observation).",
            ),
            (
                "assistant",
                "Thought: dependency analysis — multiply *needs* the read result, so this "
                "is a sequential chain, not a parallel fan-out. Single-shot Program still "
                "helps, but every edge is sequential.\n"
                "Program:\n"
                "  sequential:\n"
                f'    - repo_read_file(path="{fname}") -> $v\n'
                f"    - multiply(a=$v, b={factor}) -> $out\n"
                "Dispatching step 1.\n"
                f'Action: repo_read_file(path="{fname}")',
            ),
            ("user", f'Observation: "{key} = {base}"'),
            (
                "assistant",
                f"Thought: $v={base}; now the dependent multiply (could not have run in parallel).\n"
                f"Action: multiply(a={base}, b={factor})",
            ),
            ("user", f"Observation: {product}"),
            (
                "assistant",
                f"{key}={base}, ×{factor} = {product}. Scheduled as sequential because the "
                f"second syscall's args come from the first Observation.",
            ),
        ]
    )
    return text, "tool_selection", "tool_program"


# ---------------------------------------------------------------------------
# Generator.
# ---------------------------------------------------------------------------


class ToolUseGenerator(Generator):
    name = "tool_use"
    phases = (2, 3, 4, 5)

    # (weight, builder, source, phase). Spread so every declared phase emits:
    #   p2: L0 foundation   p3: ladder + programs   p4: recover/select/program
    #   p5: refuse + sequential-dep programs
    # Weights sum ~1.0; grounding/refusal families stay substantial.
    _FAMILIES = [
        (0.10, l0_arith_doc, "tool/l0_math", 2),
        (0.06, l0_wordcount_doc, "tool/l0_ground", 3),
        (0.05, l0_date_doc, "tool/l0_date", 2),
        (0.06, l1_listdir_sum_doc, "tool/l1_chain", 3),
        (0.05, l1_read_then_multiply_doc, "tool/l1_chain", 3),
        (0.04, l1_two_reads_add_doc, "tool/l1_chain", 3),
        (0.06, l2_badarg_recover_doc, "tool/l2_recover", 3),
        (0.07, l2_timeout_fallback_doc, "tool/l2_recover", 4),
        (0.05, l2_empty_giveup_doc, "tool/l2_recover", 4),
        (0.06, l3_select_doc, "tool/l3_select", 3),
        (0.06, l3_select_doc, "tool/l3_select", 4),
        (0.05, p4_search_cite_doc, "tool/p4_search_cite", 4),
        (0.06, l5_parallel_gather_doc, "tool/l5_parallel", 3),
        (0.05, l5_single_shot_program_doc, "tool/l5_program", 3),
        (0.04, l5_single_shot_program_doc, "tool/l5_program", 4),
        (0.04, l5_seq_dep_program_doc, "tool/l5_seq_program", 5),
        (0.05, l4_direct_answer_doc, "tool/l4_refuse", 5),
        (0.05, l4_refuse_destructive_doc, "tool/l4_refuse", 5),
    ]

    def generate(self, target_bytes: int) -> Iterator[dict]:
        cum_weights = []
        total = 0.0
        for w, _, _, _ in self._FAMILIES:
            total += w
            cum_weights.append(total)

        produced = 0
        while produced < target_bytes:
            r = self.rng.random() * total
            idx = 0
            while r > cum_weights[idx]:
                idx += 1
            _, builder, source, phase = self._FAMILIES[idx]
            text, task_type, concept = builder(self.rng)
            d = self.doc(
                text=text,
                task_type=task_type,
                concept=concept,
                phase=phase,
                source=source,
            )
            produced += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":
    from dottie.datagen.base import run_cli

    run_cli(ToolUseGenerator)
