# Experiment 2607.12048v1 — An Empirical Analysis of Continual Learning for Heterogeneous Medical Visual Question Answering

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2607.120
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.12048v1 / PDF https://arxiv.org/pdf/2607.12048v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.12048v1.md

## Abstract
Deploying medical visual question answering (MedVQA) systems in real-world clinical settings requires models that adapt to new clinical tasks without forgetting previously acquired knowledge. Continual learning (CL) provides a practical framework for this setting. Despite rapid progress in medical vision-language models, the behavior of CL methods when training these models across heterogeneous MedVQA tasks remains underexplored. This work presents a systematic evaluation of CL for MedVQA across diverse clinical objectives, including classification, multi-label classification, detection, cell counting, and report generation. Specifically, we explore (1) the ability of existing CL methods to mitigate catastrophic forgetting; (2) their sensitivity to task ordering, analyzing how different task sequences influence performance retention and forgetting; and (3) the evolution of low-rank adaptation parameters as new tasks are learned, revealing patterns of weight drift under different CL methods. Our findings suggest that existing CL methods struggle to maintain stability-plasticity balance when tasks with different objectives and supervision formats are interleaved. Code and full experimental setup will be publicly available.

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "An Empirical Analysis of Continual Learning for Heterogeneous Medical Visual Question Answering", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2607.120 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.12048v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.12048v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.12048v1 — An Empirical Analysis of Continual Learning for He"
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
