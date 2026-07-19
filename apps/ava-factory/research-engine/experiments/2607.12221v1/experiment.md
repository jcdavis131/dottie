# Experiment 2607.12221v1 — From Chaos to Clarity: A Framework for Program-Level AI Learning Outcomes

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2607.122
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.12221v1 / PDF https://arxiv.org/pdf/2607.12221v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.12221v1.md

## Abstract
Industry is leaning into generative artificial intelligence (GenAI), and higher education is under pressure to prepare graduates for a GenAI-augmented workforce. Yet, there is still no clear structure for defining AI readiness across disciplines, programs, courses, and assignments. Current approaches often rely on broad institutional policies or individual course-level decisions, which can also create mixed messages for students, fragmented expectations across programs, and limited visibility for university leaders. In this paper, we argue that higher education needs a more coherent way to connect institutional priorities to curriculum-level action. We propose Program-Level AI Learning Outcomes (PLAI-LOs) as a framework for defining what students graduating from a program should know and be able to do with, without, and about GenAI in a given discipline. The PLAI-LOs framework complements existing program-level learning outcomes and supports alignment across institutional priorities, program-level AI learning outcomes, course-level learning outcomes, and assignment-level objectives. We illustrate the framework with examples from computing and music and show how PLAI-LOs can be implemented through artifact-level GenAI policies, helping programs decide where GenAI should be taught and used, and when students should be expected to work without GenAI. We offer PLAI-LOs as a concrete, measurable, and adaptable path for moving higher education from scattered GenAI rules toward a st

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "From Chaos to Clarity: A Framework for Program-Level AI Learning Outcomes", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2607.122 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.12221v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.12221v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.12221v1 — From Chaos to Clarity: A Framework for Program-Lev"
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
