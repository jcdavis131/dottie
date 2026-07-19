# Experiment 2606.13061v2 — LaME: Learning to Think in Latent Space for Multimodal Embedding via Information Bottleneck

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-ava-training-2606.130
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2606.13061v2 / PDF https://arxiv.org/pdf/2606.13061v2
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2606.13061v2.md

## Abstract
Reasoning-driven universal multimodal embedding has advanced rapidly by introducing Chain-of-Thought (CoT) reasoning into the embedding pipeline. Despite the strong performance across both general and complex tasks, this paradigm suffers from two core limitations: (i) autoregressive CoT reasoning incurs high computational cost, making it impractical for low-latency retrieval; and (ii) embedding performance is heavily coupled with CoT annotation quality, making large-scale training unreliable. These raise fundamental questions: Is textual CoT the optimal form of reasoning for embedding, and can effective embedding reasoning be accomplished in latent space? To this end, we propose LaME (Latent Reasoning Multimodal Embedding), which formulates embedding-oriented latent reasoning as a weakly supervised information bottleneck. LaME employs K learnable reason tokens as a fixed-capacity bottleneck, completing all reasoning within a single forward pass. The two weak supervision signals structurally decouple contrastive from autoregressive objectives and eliminate dependence on CoT annotations, while a two-stage training pipeline ensures stable convergence. Experiments on MMEB-v2 and MRMR show that LaME achieves competitive performance, surpassing some explicit CoT-based models, while delivering 60x faster inference than explicit CoT methods and 2x faster than latent baselines with throughput comparable to discriminative embedding models. Code is available at https://github.com/PeppaW

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "LaME: Learning to Think in Latent Space for Multimodal Embedding via Information Bottleneck", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-ava-training-2606.130 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2606.13061v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2606.13061v2 — trying X"
4. git commit -m "exp: ava-training 2606.13061v2 — LaME: Learning to Think in Latent Space for Multim"
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
