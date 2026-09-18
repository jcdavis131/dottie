#!/usr/bin/env python3
"""Tier 2 training-data pipeline (stdlib — runs anywhere).

Generates (prompt, completion) pairs from Dottie's REAL tool catalog. The
model learns: intent + tool schemas -> valid call JSON. No scraped data, no
synthetic published benchmarks — every pair is derived from our own schemas,
with argument values sampled from the schemas' own constraints.

Split discipline: held-out TOOLS (not just held-out intents). The eval split
contains tools the model never saw in training, so the eval measures true
schema-following generalization.

Prompt format mirrors dottie_needle.engine's prompt exactly, so train-time
and inference-time inputs agree. Each prompt carries the gold tool plus
k-1 random distractor tools (matching the top-k retrieval at inference).

Usage:
    python3 make_data.py --out data --per-tool 60 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_needle.catalog import build_catalog  # noqa: E402
from dottie_needle.grammar import ToolSpec  # noqa: E402

# Tools never seen in training: the eval measures generalization to new tools.
HELD_OUT = ("reward_compute", "approval_consume", "dataset_release", "incident_drill")

INTENT_TEMPLATES = [
    "{desc}",
    "{desc} please",
    "can you {ldesc}?",
    "i need to {ldesc}",
    "please {ldesc}",
    "could you {ldesc} for me",
    "{ldesc} now",
    "hey, {ldesc}",
    "task: {ldesc}",
    "I want you to {ldesc}",
    "{ldesc} — thanks",
    "would you {ldesc}?",
]

REASONINGS = [
    "The intent maps to this tool.",
    "Matching the request against the available tools.",
    "This is the right tool for the job.",
    "Selecting the tool and filling its arguments.",
]


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


def sample_value(schema: dict, rng: random.Random, name: str):
    """Sample a valid value from a schema subset (mirrors the grammar)."""
    if "enum" in schema:
        return rng.choice(schema["enum"])
    t = schema.get("type", "string")
    if t == "string":
        if "pattern" in schema:
            pat = schema["pattern"]
            if pat == r"^g[0-9]+$":
                return f"g{rng.randint(1, 999)}"
            if pat == r"^apv_[a-z0-9]{16}$":
                return "apv_" + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(16))
            return "sample"
        pool = {
            "path": [".", "packages/dottie-loop", "README.md", "src"],
            "title": ["refresh the nightly board", "verify the deploy", "rebuild the index"],
            "action": ["deploy", "restart", "migrate"],
            "scope": ["production", "staging"],
            "source": ["runs.jsonl", "traces.jsonl"],
            "bundle": ["eval-bundle.json", "gates.json"],
            "run_id": ["run-001", "run-042"],
            "spec_path": ["job.json", "specs/train.json"],
            "graph": ["plan.json", "graph.json"],
            "config": ["leaks.json"],
            "checklist": ["restore", "failover"],
        }
        choices = pool.get(name, ["value"])
        return rng.choice(choices)
    if t == "integer":
        lo = schema.get("minimum", 0)
        hi = schema.get("maximum", 100)
        return rng.randint(lo, hi)
    if t == "number":
        lo = schema.get("minimum", 0.0)
        hi = schema.get("maximum", 1.0)
        return round(rng.uniform(lo, hi), 3)
    if t == "boolean":
        return rng.choice([True, False])
    if t == "array":
        n = rng.randint(0, min(3, schema.get("maxItems", 3)))
        return [sample_value(schema.get("items", {}), rng, name) for _ in range(n)]
    if t == "object":
        return {}
    return None


def sample_arguments(tool: ToolSpec, rng: random.Random) -> dict:
    params = tool.parameters or {"type": "object"}
    props = params.get("properties", {})
    required = set(params.get("required", []))
    args = {}
    for name, subschema in props.items():
        # Always fill required; fill optional ~70% of the time (teaches defaults).
        if name in required or rng.random() < 0.7:
            args[name] = sample_value(subschema, rng, name)
    return args


PROMPT_TEMPLATE = """You are Dottie's tool router. Reply with a brief reasoning trace (free text), then emit EXACTLY ONE tool call as JSON matching the schema below. The call must be valid JSON — no trailing commas, no comments, no extra keys.

Available tools:
{schema}

Intent: {intent}

Format your reply as:

Reasoning: <one or two sentences, free text>
Call: {{"tool": "<name>", "arguments": {{...}}}}
"""


def render_schema(tools: list[ToolSpec]) -> str:
    lines = []
    for t in tools:
        props = (t.parameters or {}).get("properties", {})
        required = set((t.parameters or {}).get("required", []))
        parts = []
        for k, s in props.items():
            typ = s.get("type", "string")
            if "enum" in s:
                typ = " | ".join(json.dumps(v) for v in s["enum"])
            mark = "" if k in required else "?"
            parts.append(f"{k}{mark}: {typ}")
        desc = f": {t.description}" if t.description else ""
        lines.append(f"- {t.name}({', '.join(parts)}){desc}")
    return "\n".join(lines)


def make_pairs(tools: list[ToolSpec], per_tool: int, seed: int, distractors: int = 4):
    rng = random.Random(seed)
    pairs = []
    for tool in tools:
        others = [t for t in tools if t.name != tool.name]
        for i in range(per_tool):
            tmpl = INTENT_TEMPLATES[i % len(INTENT_TEMPLATES)]
            intent = tmpl.format(desc=tool.description, ldesc=_lower_first(tool.description))
            args = sample_arguments(tool, rng)
            shown = [tool] + rng.sample(others, min(distractors, len(others)))
            rng.shuffle(shown)
            prompt = PROMPT_TEMPLATE.format(schema=render_schema(shown), intent=intent)
            call = json.dumps({"tool": tool.name, "arguments": args}, separators=(",", ":"))
            completion = f"Reasoning: {rng.choice(REASONINGS)}\nCall: {call}"
            pairs.append({
                "tool": tool.name,
                "intent": intent,
                "prompt": prompt,
                "completion": completion,
                "gold": {"tool": tool.name, "arguments": args},
            })
    rng.shuffle(pairs)
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--per-tool", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    catalog = build_catalog()
    train_tools = [t for t in catalog if t.name not in HELD_OUT]
    eval_tools = [t for t in catalog if t.name in HELD_OUT]

    train = make_pairs(train_tools, args.per_tool, args.seed)
    # Eval prompts may show any tools (like inference retrieval does), but the
    # gold tool is always held-out.
    eval_pairs = make_pairs(eval_tools, args.per_tool, args.seed + 1)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "train.jsonl").write_text("\n".join(json.dumps(p) for p in train) + "\n")
    (out / "eval.jsonl").write_text("\n".join(json.dumps(p) for p in eval_pairs) + "\n")
    (out / "manifest.json").write_text(json.dumps({
        "train_size": len(train),
        "eval_size": len(eval_pairs),
        "train_tools": sorted(t.name for t in train_tools),
        "held_out_tools": sorted(HELD_OUT),
        "seed": args.seed,
        "note": "Derived from Dottie's real tool catalog; no external data.",
    }, indent=2) + "\n")
    print(f"wrote {len(train)} train + {len(eval_pairs)} eval pairs to {out}/")
    print(f"held-out tools: {sorted(HELD_OUT)}")


if __name__ == "__main__":
    main()
