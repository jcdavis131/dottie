# Experiment 2607.11269v1 — Trustworthy synthetic data for campaign decision support: strategy simulation fidelity and the PolicySynth framework

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2607.112
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.11269v1 / PDF https://arxiv.org/pdf/2607.11269v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.11269v1.md

## Abstract
Decision support systems (DSS) increasingly run retention what-if analysis on synthetic customer populations, because privacy constraints preclude unrestricted use of real data. Such a system is trustworthy only if the synthetic data lead managers to the same decisions as the real data would; yet prevailing criteria certify distributional similarity, not decision alignment, so a synthetic population can match every marginal distribution while still steering a marketing team toward the wrong campaigns. We close this decision-alignment gap with three contributions: strategy simulation fidelity (SSF), a criterion measuring how often the synthetic population yields the same go/no-go campaign decision as the real population; PolicySynth, a DSS framework whose generator is conditioned on the production churn scorer to align decision-relevant structure; and a three-axis reporting standard of decision alignment, membership-inference resistance, and novel-record rate as the minimum deployment quality gate. On a telecommunications churn corpus and a banking acquisition corpus, PolicySynth attains a mean SSF of 0.923 and 0.960, with seed-to-seed variance roughly ten times tighter than CTGAN on telecommunications and 2.5 times on banking. This stability is the deployable property: go/no-go recommendations shift by at most 1.2 percentage points between monthly retraining cycles, against 11.5 for CTGAN, a reversed recommendation on one campaign in nine. A bootstrap baseline matches PolicyS

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "Trustworthy synthetic data for campaign decision support: strategy simulation fidelity and the PolicySynth framework", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2607.112 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.11269v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.11269v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.11269v1 — Trustworthy synthetic data for campaign decision s"
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
