# Experiment 2607.11715v1 — JobHop v2: A Large-Scale Career Trajectory Dataset from Unstructured Resumes

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2607.117
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.11715v1 / PDF https://arxiv.org/pdf/2607.11715v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.11715v1.md

## Abstract
Large-scale, richly annotated career trajectory data underpins workforce planning, job recommendation, and labour market analysis, yet publicly available datasets are either small, closed to independent use, or built from pre-standardized occupational codes with LLM-synthesized rather than authentic free text. We present JobHop~v2, an improved version of the publicly available JobHop dataset, constructed through end-to-end large language model (LLM) extraction from a corpus of ${\sim}440{,}000$ pseudonymized, multilingual resumes provided by VDAB, the Flemish Public Employment Service. The released dataset comprises $355{,}315$ career trajectories annotated with ESCO occupational codes, quarter-level temporal information, and normalized five-level education attainment, broadening both the coverage and the annotation richness of the original release. Relative to v1, JobHop~v2 introduces a redesigned extraction pipeline based on reasoning-controlled LLM inference with a retry mechanism (achieving a 100% JSON parse rate), a richer extraction schema, and a revised evaluation protocol scored against three complementary annotation baselines. Evaluated against these baselines, our best extractor comes closest to the inter-annotator agreement ceiling among all compared models, trailing it by only 1.1-2.7 percentage points. The dataset and code are publicly released to support reproducible career-trajectory research.

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "JobHop v2: A Large-Scale Career Trajectory Dataset from Unstructured Resumes", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2607.117 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.11715v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.11715v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.11715v1 — JobHop v2: A Large-Scale Career Trajectory Dataset"
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
