# Experiment 2607.12042v1 — SymbOmni: Evolving Agentic Omni Models via Symbolic Concept Learning

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2607.120
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.12042v1 / PDF https://arxiv.org/pdf/2607.12042v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.12042v1.md

## Abstract
Visual generation is increasingly ubiquitous in diverse domains, from text-to-image/video synthesis to multimodal interactive creation. Yet prevailing monolithic models remain fundamentally constrained by their inability to learn cumulatively and evolve autonomously, which is a limitation we term the "perpetual novice" problem. They lack mechanisms for structuring experience into reusable knowledge and therefore rely on brittle, "from-scratch" reasoning for each task, resulting in poor compositional generalization and inefficient knowledge retention. Motivated by these limitations, we propose SymbOmni, an agentic omni-model designed for cumulative evolution through Symbolic Concept Learning. At its core is the Symbolic Concept Box, an optimizable memory module that abstracts low-level operations into reusable Symbolic Workflow Instructions. SymbOmni operates through an induction-transduction cycle: experiences are abstracted into symbolic concepts (induction), which are then adaptively composed to solve novel tasks (transduction). The training is done by verbalized backpropagation with language-based feedback to enable continuous self-improvement without gradient-based model fine-tuning. Comprehensive experiments validate that (I) SymbOmni significantly outperforms existing agent-based systems for iterative creation and also surpasses closed-source models (e.g., Nano Banana, GPT-Image-1) in both image quality and task success rates; (II) SymbOmni effectively reduces token con

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "SymbOmni: Evolving Agentic Omni Models via Symbolic Concept Learning", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2607.120 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.12042v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.12042v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.12042v1 — SymbOmni: Evolving Agentic Omni Models via Symboli"
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
