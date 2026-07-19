# Experiment 2606.20751v2 — From Sentiment to Actionable Insights: Public Sentiment Analysis of Advanced Air Mobility

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2606.207
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2606.20751v2 / PDF https://arxiv.org/pdf/2606.20751v2
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2606.20751v2.md

## Abstract
Advanced Air Mobility (AAM) is an emerging low-altitude transportation system whose successful deployment depends on both technological progress and public acceptance. Public acceptance can influence government support, regulations, noise standards, willingness to fly, and the commercial viability of AAM. Understanding public sentiment is therefore essential for identifying societal barriers and developing effective adoption strategies. This study analyzes 306,009 human-generated texts collected from Reddit and Quora to examine AAM-related public discourse using artificial intelligence models. Seven sentiment-analysis approaches, including lexicon-based, machine-learning, deep-learning, and transformer models, are evaluated to identify the most reliable method for AAM-specific sentiment classification. ModernBERT achieves the highest performance and is used to label the full dataset. Latent Dirichlet Allocation is then applied within each sentiment class to identify underlying topics and examine their temporal evolution from 2008 to 2025. The analysis identifies 20 topics and six major cross-sentiment clusters: workforce and skill development, regulation and compliance, drone technical performance, military and geopolitical applications, safety and operational risks, and noise and disturbance. These findings can help policymakers, industry stakeholders, researchers, and operators develop targeted regulations, safety measures, workforce programs, noise-reduction strategies, an

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "From Sentiment to Actionable Insights: Public Sentiment Analysis of Advanced Air Mobility", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2606.207 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2606.20751v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2606.20751v2 — trying X"
4. git commit -m "exp: workforce-ai 2606.20751v2 — From Sentiment to Actionable Insights: Public Sent"
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
