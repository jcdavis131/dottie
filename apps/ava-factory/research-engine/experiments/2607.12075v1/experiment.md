# Experiment 2607.12075v1 — Calibrated Selective Prediction Using Deep Ensembles for ROI-Based Thyroid Nodule Ultrasound Classification Under Dataset Shift: A Retrospective Evaluation

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2607.120
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.12075v1 / PDF https://arxiv.org/pdf/2607.12075v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.12075v1.md

## Abstract
Background: Deep learning models can classify thyroid nodules on ultrasound, but reliable clinical decision support also requires calibrated probabilities, uncertainty estimation, and selective referral, particularly under dataset shift.
  Methods: We developed a calibrated deterministic five-member deep ensemble for ROI-based thyroid nodule classification and selective image-based triage. TN5000 was used for model development, five-fold cross-validation, member-wise vector-scaling calibration, and fold-specific threshold selection. TN3K served as an independent external dataset-shift evaluation. The framework used ConvNeXt-Tiny with squeeze-and-excitation attention, ensemble-mean malignancy probability, and mutual information (MI) as an ensemble-disagreement score. A three-tier policy assigned images to No-FNA suggestion, FNA recommendation, or radiologist review.
  Results: On pooled out-of-fold TN5000 predictions, the ensemble achieved AUC-ROC 0.9395, AP 0.9715, ECE 0.0088, and Brier score 0.0813. At 50% nominal MI retention, 7.2% of cases received a No-FNA suggestion, 39.9% an FNA recommendation, and 52.9% radiologist review, with 98.3% No-FNA NPV and 99.83% malignancy capture. On TN3K, AUC-ROC decreased to 0.7870, AP to 0.7254, ECE increased to 0.1899, and Brier score to 0.2281. The frozen TN5000 policy assigned 83.7% to review, 1.0% to No-FNA, and 15.3% to FNA recommendation. No malignant image entered the No-FNA pathway, but FNA-recommendation PPV fell to 76.6%.
  Conc

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "Calibrated Selective Prediction Using Deep Ensembles for ROI-Based Thyroid Nodule Ultrasound Classification Under Dataset Shift: A Retrospective Evaluation", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2607.120 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.12075v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.12075v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.12075v1 — Calibrated Selective Prediction Using Deep Ensembl"
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
