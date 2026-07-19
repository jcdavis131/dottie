# Experiment 2603.03183v2 — The multiloop sunset to all orders

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-ava-eval-2603.031
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2603.03183v2 / PDF https://arxiv.org/pdf/2603.03183v2
**Topic:** ava-eval — Frontier Rubric + Eval Harness (importance high)
**Ecosystem:** ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2603.03183v2.md

## Abstract
We derive exact, convergent representations of multiloop sunset Feynman integrals in two dimensions for arbitrary mass configurations and all loop orders valid for large Euclidean momentum. The integrals are expressed as sums of symmetric polynomials in logarithmic mass ratios, normalized by the external momentum squared, with coefficients determined by analytic series expansions. For the equal-mass case, we establish a dimension-lowering relation expressing the $L$ loop sunset integrals in $D+2$ as the one in $D$ dimensions acted on a differential operator of order $L-1$.
  These representations are free of complicated transcendental functions, making them well-suited to both formal analysis and high-precision numerical evaluation. The two-dimensional results serve as boundary conditions for dimension-shifting relations, enabling systematic reconstruction of four-dimensional sunset integrals via analytic continuation to $D = 4 - 2ε$.

## Why relevant
FrontierFinance 11-cat rubric (Financial Accuracy, Process Transparency etc), 220 tasks 11543 rubrics, Judge IRA 80.2%, branch eval cap preservation 0.983

## Hypothesis (per program.md)
Based on "The multiloop sunset to all orders", try applying idea to Ava ava-eval.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-ava-eval-2603.031 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2603.03183v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2603.03183v2 — trying X"
4. git commit -m "exp: ava-eval 2603.03183v2 — The multiloop sunset to all orders"
5. Run: `uv run train.py > run.log 2>&1` OR `python -m ava.train --preset nano_quick --max-steps 20 > run.log 2>&1`
6. Extract: grep "^val_bpb:\|^peak_vram_mb:\|^cap_preservation:" run.log
7. Log to results.tsv: commit val_bpb memory_gb status description
8. If improved, keep branch, else git reset

## Expected outcome
- If improved: val_bpb decreases OR cap_preservation increases, create follow-up task [AVA-EXP-KEEP]
- If discarded: log reason, try next paper

## Complexity weighting (per program.md)
Simpler is better — weigh complexity cost vs improvement magnitude.
Deletion that maintains or improves is great win.

---
Generated 2026-07-18 by autoresearch-runner cron
