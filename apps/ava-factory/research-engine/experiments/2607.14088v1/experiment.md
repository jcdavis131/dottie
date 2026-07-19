# Experiment 2607.14088v1 — VideoRAE: Taming Video Foundation Models for Generative Modeling via Representation Autoencoders

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-ava-training-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14088v1 / PDF https://arxiv.org/pdf/2607.14088v1
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14088v1.md

## Abstract
Video generative models commonly rely on latent spaces learned by 3D Variational Autoencoders (3D-VAEs). However, conventional 3D-VAEs are mainly optimized for pixel-level reconstruction, which can limit the semantic and spatio-temporal structure captured by their latents. Meanwhile, Video Foundation Models (VFMs) such as V-JEPA 2 and VideoMAEv2 show strong video understanding capabilities, yet whether their frozen representations can be transformed into compact, reconstruction-capable, and generation-friendly video latents remains largely unexplored. We answer this question with VideoRAE, a representation autoencoder that leverages multi-scale hierarchical features from a frozen video foundation encoder and compresses them with a lightweight 1D self-attention projector. VideoRAE supports both continuous latents for Diffusion Transformers and discrete tokens for autoregressive models via multi-codebook high-dimensional quantization. During decoding, a local-and-global representation alignment objective with the frozen VFM teacher improves semantic preservation and enables training without KL regularization. Experiments show that VideoRAE achieves strong reconstruction in both continuous and discrete regimes. On UCF-101, it obtains state-of-the-art class-to-video gFVDs of 40 and 93 with AR and DiT generators, respectively, while converging approximately 5x faster than competing autoencoder baselines. In a controlled 2B-scale text-to-video study, replacing LTX-VAE with VideoRAE

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "VideoRAE: Taming Video Foundation Models for Generative Modeling via Representation Autoencoders", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-ava-training-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14088v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14088v1 — trying X"
4. git commit -m "exp: ava-training 2607.14088v1 — VideoRAE: Taming Video Foundation Models for Gener"
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
Generated 2026-07-17 by autoresearch-runner cron
