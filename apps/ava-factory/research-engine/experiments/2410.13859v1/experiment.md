# Experiment 2410.13859v1 — Gamma-MoD: Exploring Mixture-of-Depth Adaptation for Multimodal Large Language Models

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-ava-jspace-2410.138
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2410.13859v1 / PDF https://arxiv.org/pdf/2410.13859v1
**Topic:** ava-jspace — Ava J-Space Multi-Workspace (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/multi_jspace_module.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2410.13859v1.md

## Abstract
Mixture-of-Depths adapts dense layers to MoD layers via ARank metric (rank of attention maps) to identify redundant layers. Shared vision-language router and masked routing learning. 90% dense layers can be converted to MoD with -1.5% drop. For Ava: Router tuning for S1/S2/Critic/Planner gating.

## Why relevant
S1 Fast hl=8, S2 Slow hl=300, Critic hl=30, Planner hl=150 + Router/veto — Jacobian regularization, multi-space memory, branching

## Hypothesis (per program.md)
Based on "Gamma-MoD: Exploring Mixture-of-Depth Adaptation for Multimodal Large Language Models", try applying idea to Ava ava-jspace.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/multi_jspace_module.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-ava-jspace-2410.138 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2410.13859v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2410.13859v1 — trying X"
4. git commit -m "exp: ava-jspace 2410.13859v1 — Gamma-MoD: Exploring Mixture-of-Depth Adaptation f"
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
