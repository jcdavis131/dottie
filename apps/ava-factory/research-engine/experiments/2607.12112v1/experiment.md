# Experiment 2607.12112v1 — Continual Learning with Elastic Regularization and Synthetic Replay for Federated MLLM Fine-Tuning

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2607.121
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.12112v1 / PDF https://arxiv.org/pdf/2607.12112v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.12112v1.md

## Abstract
Federated fine-tuning of Multimodal Large Language Models (MLLMs) across distributed networks enables privacy-sensitive adaptation to evolving data streams, yet a fundamental obstacle prevents robust deployment in dynamic environments: catastrophic forgetting, wherein sequential task updates erase previously acquired knowledge across visual, linguistic, and cross-modal representations. Addressing this challenge is especially critical for autonomous networked AI operating in safety-sensitive domains, such as content moderation, where reliable retention of prior knowledge underpins system integrity. To overcome this, we propose Federated Continual Multimodal Learning (FedCMM), a framework that embeds continual-learning safeguards into the federated optimization loop at three complementary levels. At the parameter level, modality-aware elastic weight consolidation computes separate Fisher information matrices for the vision encoder, language backbone, and cross-modal projector, providing granular, asymmetry-aware protection against modality-specific forgetting. At the data level, each client trains a lightweight local generative replay module to synthesize raw-data-free embedding-level multimodal replay tuples without any raw data sharing. At the aggregation level, Task-similarity-aware gradient aggregation autonomously filters and reweights client updates by gradient cosine similarity, suppressing conflicting directions and stabilizing the global learning trajectory. Extensive 

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "Continual Learning with Elastic Regularization and Synthetic Replay for Federated MLLM Fine-Tuning", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2607.121 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.12112v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.12112v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.12112v1 — Continual Learning with Elastic Regularization and"
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
