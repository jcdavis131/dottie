# Experiment 2406.20875v1 — Attention Is All You Need For Mixture-of-Depths Routing

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-ava-jspace-2406.208
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2406.20875v1 / PDF https://arxiv.org/pdf/2406.20875v1
**Topic:** ava-jspace — Ava J-Space Multi-Workspace (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/multi_jspace_module.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2406.20875v1.md

## Abstract
A-MoD leverages existing attention map from preceding layer for routing decisions in current layer, no additional trainable parameters. 2% higher accuracy on ImageNet vs standard routing, 2x faster transfer. For Ava Router: reuse attention scores to decide S1 vs S2 vs Planner without training new router.

## Why relevant
S1 Fast hl=8, S2 Slow hl=300, Critic hl=30, Planner hl=150 + Router/veto — Jacobian regularization, multi-space memory, branching

## Hypothesis (per program.md)
Based on "Attention Is All You Need For Mixture-of-Depths Routing", try applying idea to Ava ava-jspace.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/multi_jspace_module.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-ava-jspace-2406.208 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2406.20875v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2406.20875v1 — trying X"
4. git commit -m "exp: ava-jspace 2406.20875v1 — Attention Is All You Need For Mixture-of-Depths Ro"
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
Generated 2026-07-16 by autoresearch-runner cron
