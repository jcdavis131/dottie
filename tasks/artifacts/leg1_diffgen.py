"""Regenerate the Leg 1 mini.yaml unified diff (tasks/artifacts/leg1_mini_diff.md).

*** SUPERSEDED 2026-07-24 — the Leg 1 schedule is APPLIED and TRAINING. ***
This generator emitted the PRE-REVISION DRAFT (p3 1.1B, p5 doubled to 400M, and
NO replay keys in p4/p5) — exactly the configuration the completion eval
invalidated (p4/p5 without replay cost 275.95 -> 4,103 weighted ppl on p0-p3
bins). It has been corrected to the REVISED plan (p3 1.3B, p5 stays 200M with
logic/math replay), BUT it still does NOT emit the p4 replay shares
(long_docs .40 / needle .20 / tool_use .20 / encyclopedia .10 / math .10) that
the revision requires — the draft left p4 untouched.
The SOURCE OF TRUTH is now the live apps/ava-factory/configs/mini.yaml
(committed 92baf4b, verified: tokens_total == phase sum == 3.4B, every mix sums
to 1.0). Do NOT apply this generator's output over that file — it would revert
the corrections. Kept only as a provenance record of how the diff was built.

Reads the LIVE configs/mini.yaml (read-only), applies the six Leg 1 edits to an
in-memory copy, and emits a git-apply-able unified diff on stdout. Run from the
repo root:  python tasks/artifacts/leg1_diffgen.py [out.patch]
(writes the patch file itself -- UTF-8 no BOM, LF -- because PowerShell 5.1
redirection adds a BOM that makes git apply reject the patch)
Never writes into apps/ava-factory/ (configs/ is bind-mounted into the live
trainer; the diff is applied by the operator after steer approval).
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps" / "ava-factory" / "configs" / "mini.yaml"

REPLACEMENTS: list[tuple[str, str]] = [
    (
        "  tokens_total: 2_500_000_000\n",
        "  # Leg 1 (docs/CURRICULUM_EXPANSION.md): 2.5B + 0.9B = 3.4B -- TPP ~20 on the\n"
        '  # 171M-param basis the doc\'s own "TPP 12.5" figure uses.\n'
        "  # HAZARD: cfg.total_steps() for a BASE-preset boot grows with this value; do\n"
        "  # NOT boot the base compose service after applying (see Risks #1).\n"
        "  tokens_total: 3_400_000_000\n",
    ),
    (
        "phases:                            # same 6-phase shape, 2.5B budget\n",
        "phases:                            # same 6-phase shape, 3.4B budget (Leg 1)\n",
    ),
    (
        "  - {name: p3_reasoning,  tokens: 400_000_000, seq: 2048, rope_base: 50000,"
        "  ntk: 1.0, mix: {math_reasoning: 0.30, tool_use: 0.30, logic: 0.15,"
        " temporal: 0.15, code: 0.10}}\n",
        "  # Leg 1 depth REVISED: +900M in p3 (the seq-2048 regime with the POSITIVE\n"
        "  # extension precedent; the completion eval killed the draft's p5 doubling).\n"
        "  # weights sum to 1.0. phase_for_step() puts the resumed branch (tokens_done\n"
        "  # 2.5B) back in p3 until 3.05B: 550M fresh at this mix, then p4, then anneal.\n"
        "  - {name: p3_reasoning,  tokens: 1_300_000_000, seq: 2048, rope_base: 50000,"
        "  ntk: 1.0, mix: {math_reasoning: 0.35, tool_use: 0.35, logic: 0.10,"
        " temporal: 0.10, code: 0.10}}\n",
    ),
    (
        "  - {name: p5_anneal,     tokens: 200_000_000, seq: 4096, rope_base: 100000,"
        " ntk: 1.2, mix: {tool_use: 0.25, proofs_verified: 0.20, chat: 0.20,"
        " safety: 0.20, math_reasoning: 0.15}}\n",
        "  # Anneal stays 200M (the draft's doubling would amplify the measured\n"
        "  # narrowing); tool_use .25->.30; logic+math REPLAY .15 funded by\n"
        "  # proofs_verified .20->.10 and chat .20->.15. safety untouched.\n"
        "  - {name: p5_anneal,     tokens: 200_000_000, seq: 4096, rope_base: 100000,"
        " ntk: 1.2, mix: {tool_use: 0.30, proofs_verified: 0.10, chat: 0.15,"
        " safety: 0.20, math_reasoning: 0.15, logic: 0.05, math: 0.05}}\n",
    ),
    (
        "    tokens: 750_000_000            # extended 2026-07-22 (was 390M/1487 steps, done): ~2861\n"
        "                                   # steps @ 262144 tok/step. Completes the FULL curriculum:\n"
        "                                   # p3 tail (2.14->2.15B) then p4_long + p5_anneal to 2.5B.\n"
        "                                   # p4/p5 seq-4096 is proven on this GPU in bf16 (base run's\n"
        "                                   # stable_p4 exists); AVA_MAX_MICRO_BATCH is the relief valve.\n"
        '                                   # Operator 2026-07-22: "get training up and running" for the\n'
        "                                   # live dashboard + game twin. Prior leg (390M) logged below.\n"
        "                                   # was: 300M->390M 2026-07-21, +343 steps within p3 for the\n"
        "                                   # scout_cli (tool_use) + zk_math (math_reasoning) curriculum.\n",
        "    tokens: 1_650_000_000          # Leg 1 (was 750M/2861 steps, done): +0.9B to 3.4B cum\n"
        "                                   # = ~6294 steps @ 262144 tok/step. WSD horizon\n"
        "                                   # re-extends: plateau to step ~5790 (0.92), then\n"
        "                                   # decay -- the same move as the 390M->750M\n"
        "                                   # extension that took weighted heldout ppl\n"
        "                                   # 7,814 -> 276. ~1-1.3 GPU-days at ~10.5k tok/s;\n"
        "                                   # AVA_MAX_MICRO_BATCH stays the p4/p5 seq-4096\n"
        "                                   # relief valve.\n"
        "                                   # was: 750M 2026-07-22 (full curriculum to 2.5B);\n"
        "                                   # 390M 2026-07-21 (+343 steps within p3).\n",
    ),
    (
        "    mix: {math_reasoning: 0.30, tool_use: 0.30, logic: 0.15, temporal: 0.15,"
        " code: 0.10}\n",
        "    # descriptive only -- train.py never reads branch mix; the sampler follows\n"
        "    # phases[] via phase_for_step(). Mirrors the new p3 mix.\n"
        "    mix: {math_reasoning: 0.35, tool_use: 0.35, logic: 0.10, temporal: 0.10,"
        " code: 0.10}\n",
    ),
]


def main() -> int:
    before = SRC.read_text(encoding="utf-8")
    after = before
    for old, new in REPLACEMENTS:
        if after.count(old) != 1:
            print(
                f"ABORT: expected exactly 1 occurrence, found {after.count(old)}:"
                f"\n{old!r}",
                file=sys.stderr,
            )
            return 1
        after = after.replace(old, new)
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="a/apps/ava-factory/configs/mini.yaml",
            tofile="b/apps/ava-factory/configs/mini.yaml",
        )
    )
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as f:
            f.write(diff)
    else:
        sys.stdout.write(diff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
