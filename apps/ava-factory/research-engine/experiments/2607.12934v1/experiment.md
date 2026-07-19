# Experiment 2607.12934v1 — Domain-Incremental Remote Sensing Change Detection via Difference-Guided Adaptation and Frequency-Decoupled Distillation

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul19-workforce-ai-2607.129
**Date:** 2026-07-19
**Paper:** https://arxiv.org/abs/2607.12934v1 / PDF https://arxiv.org/pdf/2607.12934v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/dottie/apps/ava-factory/graphify_source/2607.12934v1.md

## Abstract
Remote sensing change detection (RSCD) models are prone to catastrophic forgetting when incrementally adapted to new domains. Existing domain-incremental learning (DIL) methods mainly preserve image-level representations but often overlook bitemporal discrepancy cues, which are critical for robust change detection under domain shifts. To address this limitation, we propose DG-FDD, a domain-incremental change detection framework that integrates Difference-Guided Adaptation and Frequency-Decoupled Distillation. Specifically, the Difference-Guided Dynamic Adapter (DGDA) models bitemporal feature discrepancies to promote change-aware feature adaptation and reduce domain-specific interference. Meanwhile, the Frequency-Decoupled Knowledge Distillation strategy with Cross-domain Synthesis (FDKD-CS) separates structural information from domain style in the frequency domain, enabling stable knowledge transfer without historical data. Extensive experiments on three public high-resolution RSCD datasets under two- and three-domain incremental protocols demonstrate that DG-FDD effectively mitigates catastrophic forgetting. Compared with independently trained single-task models, DG-FDD records mean relative changes in F1 and IoU of only -0.23% and -0.45%, respectively, across six two-domain sequences, and -0.69% and -1.31%, respectively, across the three evaluated three-domain sequences. These results indicate a favorable stability-plasticity balance between historical knowledge retention 

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "Domain-Incremental Remote Sensing Change Detection via Difference-Guided Adaptation and Frequency-Decoupled Distillation", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul19-workforce-ai-2607.129 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.12934v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.12934v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.12934v1 — Domain-Incremental Remote Sensing Change Detection"
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
Generated 2026-07-19 by autoresearch-runner cron
