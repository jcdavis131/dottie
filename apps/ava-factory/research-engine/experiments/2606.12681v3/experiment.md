# Experiment 2606.12681v3 — Analytic calculator for determination of $γ$-ray angular distribution coefficients and tensors in aligned and partially-aligned nuclei

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-ava-eval-2606.126
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2606.12681v3 / PDF https://arxiv.org/pdf/2606.12681v3
**Topic:** ava-eval — Frontier Rubric + Eval Harness (importance high)
**Ecosystem:** ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2606.12681v3.md

## Abstract
A program has been developed to calculate a complete set of $γ$-ray angular distribution coefficients and statistical tensors in maximally- and partially-aligned nuclei. For practical nuclear structure and reaction purposes, there is no imposed constraint on any arguments that are likely to arise in the determination of these quantities. The program can also be used as a stand-alone vector-coupling calculator for the exact evaluation of Clebsch-Gordan and Racah coefficients, the closely-related Wigner 3-$j$, 6-$j$, and 9-$j$ symbols, as well as Gaunt coefficients. These quantities, which frequently arise in quantum mechanical applications involving angular momentum coupling and recoupling schemes, provide the underlying machinery in angular distribution calculations.

## Why relevant
FrontierFinance 11-cat rubric (Financial Accuracy, Process Transparency etc), 220 tasks 11543 rubrics, Judge IRA 80.2%, branch eval cap preservation 0.983

## Hypothesis (per program.md)
Based on "Analytic calculator for determination of $γ$-ray angular distribution coefficients and tensors in aligned and partially-aligned nuclei", try applying idea to Ava ava-eval.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-ava-eval-2606.126 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2606.12681v3.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2606.12681v3 — trying X"
4. git commit -m "exp: ava-eval 2606.12681v3 — Analytic calculator for determination of $γ$-ray a"
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
