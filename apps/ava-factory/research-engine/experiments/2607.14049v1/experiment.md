# Experiment 2607.14049v1 — Deep Interaction: An Efficient Human-AI Interaction Method for Large Reasoning Models

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-ava-training-2607.140
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2607.14049v1 / PDF https://arxiv.org/pdf/2607.14049v1
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14049v1.md

## Abstract
The emergence of Chain-of-Thought (CoT) reasoning has significantly enhanced the ability of large language models (LLMs) to tackle complex, multi-step tasks. However, when errors occur, current interaction approaches typically involve re-generating another response that may make mistakes again, or users laboriously flag the faulty step in follow-up turns that may get responses <You are right, I made a mistake here> followed by similar errors recurring. To address this issue, we propose an efficient human intervention mechanism for precisely correcting reasoning errors in LLMs, termed Deep Interaction. Our approach enables direct editing of the original response, allowing erroneous parts to be corrected while preserving accurate reasoning steps. We refine the edited CoT into a distilled prompt, which then steers the LLM along the corrected reasoning path. Experimental results show that our method achieves over a 25% improvement in correction success rate and reduces token usage by approximately 40% on STEM tasks reasoning compared to baseline approaches.

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "Deep Interaction: An Efficient Human-AI Interaction Method for Large Reasoning Models", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-ava-training-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14049v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14049v1 — trying X"
4. git commit -m "exp: ava-training 2607.14049v1 — Deep Interaction: An Efficient Human-AI Interactio"
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
