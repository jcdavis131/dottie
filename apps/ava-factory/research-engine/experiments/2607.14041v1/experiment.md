# Experiment 2607.14041v1 — Multi-Expert Routing for Multi-Domain Low-Resource OCR: A Manchu Case Study

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-ava-eval-2607.140
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.14041v1 / PDF https://arxiv.org/pdf/2607.14041v1
**Topic:** ava-eval — Frontier Rubric + Eval Harness (importance high)
**Ecosystem:** ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14041v1.md

## Abstract
Historical Manchu OCR must accommodate various visually distinct writing styles, including regular script, running script, and the semi-cursive chancery hand used in palace memorials, despite limited labeled data. We study a multi-expert system that reuses checkpoints from an iterative fine-tuning process as domain specialists and uses a lightweight page-level image classifier to dispatch pages by visual style. When the checkpoint pool lacks a suitable specialist, we train an additional expert for that domain. On three frozen test sets, the routed system matches the selected specialist for each style at two-decimal precision: 0.30 percent CER on regular script, 1.57 percent on memorials, and 4.83 percent on running script. The router achieves 99.3 percent page-level domain accuracy and matches the domain-label oracle at the same precision. Two of the three selected specialists were not trained specifically for their final domain; only the running-script expert was trained with that domain as its target. We report the evaluation protocol, router design, and per-page predictions to make the comparison reproducible.

## Why relevant
FrontierFinance 11-cat rubric (Financial Accuracy, Process Transparency etc), 220 tasks 11543 rubrics, Judge IRA 80.2%, branch eval cap preservation 0.983

## Hypothesis (per program.md)
Based on "Multi-Expert Routing for Multi-Domain Low-Resource OCR: A Manchu Case Study", try applying idea to Ava ava-eval.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-ava-eval-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14041v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14041v1 — trying X"
4. git commit -m "exp: ava-eval 2607.14041v1 — Multi-Expert Routing for Multi-Domain Low-Resource"
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
