# Experiment 2607.11722v1 — STEP: Career-Path Recommendation via Temporal and Educational Trajectory Modeling

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2607.117
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.11722v1 / PDF https://arxiv.org/pdf/2607.11722v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.11722v1.md

## Abstract
Career paths encode decades of skill acquisition, role transitions, and educational investment, and understanding them at scale underpins workforce planning, labor market policy, and job recommendation. Resumes are a rich source of information about career paths: they contain detailed descriptions of work experience, education, and skills. Yet their unstructured, heterogeneous, and multilingual nature has long prevented large-scale systematic analysis. With the advent of large language models (LLMs), it is now possible to source rich career trajectory data containing temporal and educational signals from unstructured resumes, enabling new opportunities for career-path recommendation. Exploiting this opportunity, we present STEP (Sequential Trajectory of Employment Prediction), a novel career-path recommendation system that leverages temporal and educational signals to predict the next job in a career trajectory. STEP integrates a time-decay Gated Recurrent Unit (GRU) cell to model temporal dynamics, Feature-wise Linear Modulation (FiLM) conditioned on educational attainment, and attention-based sequence pooling to select relevant features for next job prediction. To improve internal occupation representation for STEP, we introduce ROUTE, a two-stage contrastive procedure that first adapts a multilingual encoder to the career domain via unsupervised denoising autoencoding, then performs supervised contrastive fine-tuning with guided negative selection. We evaluate STEP on four

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "STEP: Career-Path Recommendation via Temporal and Educational Trajectory Modeling", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2607.117 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.11722v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.11722v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.11722v1 — STEP: Career-Path Recommendation via Temporal and "
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
