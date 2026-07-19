# Experiment 2607.14051v1 — Hindcast: Replaying Prediction Markets to Evaluate LLM Forecasters

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-ava-training-2607.140
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2607.14051v1 / PDF https://arxiv.org/pdf/2607.14051v1
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14051v1.md

## Abstract
Forecasters are evaluated by backtesting, which replays resolved questions and grades the probability the system would have assigned before the outcome was known. For LLMs, two channels leak the answer into this test. A model that retrieves can surface reports written after the event, turning forecasting into a lookup, and each new model is trained on data closer to the event, so a question that lay in the future for last year's models sits inside this year's training data. Either way, the test grades recall while claiming to grade foresight. We introduce Hindcast, which closes both leaks by grading a model as if it stood at a chosen past date $t_0$, before the outcome existed in either channel. Hindcast replays resolved Polymarket prediction markets against a frozen snapshot of public Reddit, lets the model read only posts written before $t_0$, and scores each forecast against both what happened and the market's own price at $t_0$, itself a human forecast made from the same past information. Because the cutoff is set per market and the snapshot never changes, the evaluation re-runs on new markets as models improve, without going stale. Once the leak is closed, retrieval still helps most models, but only where Reddit discussed the event beforehand. Where the archive carried only speculation, retrieval hurts.

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "Hindcast: Replaying Prediction Markets to Evaluate LLM Forecasters", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-ava-training-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14051v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14051v1 — trying X"
4. git commit -m "exp: ava-training 2607.14051v1 — Hindcast: Replaying Prediction Markets to Evaluate"
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
