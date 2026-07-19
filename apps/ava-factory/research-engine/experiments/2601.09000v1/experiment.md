# Experiment 2601.09000v1 — Universal Dynamics of Warmup Stable Decay: understanding WSD beyond Transformers

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul15-ava-training-2601.090
**Date:** 2026-07-15
**Paper:** https://arxiv.org/abs/2601.09000v1 / PDF https://arxiv.org/pdf/2601.09000v1
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2601.09000v1.md

## Abstract
Compares WSD on Pythia LM 160M and CNN 334K CIFAR10 — same dynamics: modest decreases during stable, sharp gain during cooldown. Points to shared geometric characteristics. Validates Ava's approach of stable 736k tokens.

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "Universal Dynamics of Warmup Stable Decay: understanding WSD beyond Transformers", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul15-ava-training-2601.090 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2601.09000v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2601.09000v1 — trying X"
4. git commit -m "exp: ava-training 2601.09000v1 — Universal Dynamics of Warmup Stable Decay: underst"
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
Generated 2026-07-15 by autoresearch-runner cron
