# Experiment 2406.20092v2 — YaRN: Efficient Context Window Extension of Large Language Models

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul15-ava-training-2406.200
**Date:** 2026-07-15
**Paper:** https://arxiv.org/abs/2406.20092v2 / PDF https://arxiv.org/pdf/2406.20092v2
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2406.20092v2.md

## Abstract
Yet another RoPE extension — NTK-aware interpolation, segments RoPE dims into high vs low frequency. Extends LLaMA2 4k to 128k with 400 steps fine-tuning, 64k to 128k interpolation. Ava uses YaRN 10k->1M NTK-aware QK-Norm. Extend to 2M with LongRoPE2 improvements.

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "YaRN: Efficient Context Window Extension of Large Language Models", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul15-ava-training-2406.200 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2406.20092v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2406.20092v2 — trying X"
4. git commit -m "exp: ava-training 2406.20092v2 — YaRN: Efficient Context Window Extension of Large "
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
