# Experiment 2509.23106v1 — Effective Quantization of Muon Optimizer for Low-Bit LLM Training

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul15-ava-training-2509.231
**Date:** 2026-07-15
**Paper:** https://arxiv.org/abs/2509.23106v1 / PDF https://arxiv.org/pdf/2509.23106v1
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2509.23106v1.md

## Abstract
Muon optimizer orthogonalizes momentum via Newton-Schulz, achieving 2x computational savings over AdamW. This paper studies low-bit quantization of Muon states, showing 8-bit blockwise preserves performance, mixed-precision needed for 4-bit. Directly relevant to Ava's S1 Fast hl=8 vs S2 Slow hl=300 routing — Muon for Fast, AdamW for Slow.

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "Effective Quantization of Muon Optimizer for Low-Bit LLM Training", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul15-ava-training-2509.231 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2509.23106v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2509.23106v1 — trying X"
4. git commit -m "exp: ava-training 2509.23106v1 — Effective Quantization of Muon Optimizer for Low-B"
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
