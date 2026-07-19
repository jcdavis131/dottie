# Experiment 2607.14040v1 — Can an Old Dog Be Taught New Tricks? Taking LLMs Beyond Sentence Level Translation

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-ava-training-2607.140
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2607.14040v1 / PDF https://arxiv.org/pdf/2607.14040v1
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14040v1.md

## Abstract
Automatic translation systems, from CAT tools to MT, overwhelmingly treat translation as a sentence-by-sentence act. This paper asks whether LLMs can be moved beyond that paradigm through whole-document, corpus-informed translation. We present PAT (Pragmatic Auto-Translator), a RAG-based system that pairs user-configured specifications with context from a comparable corpus of authentic longform texts in U.S. English and Latin American Spanish, passing retrieved paragraph-, section-, and document-level examples to an LLM for whole-document generation. The goal is draft translation for professional verification: target texts reformulated to fit their Spanish-language context, where discourse organization, rhetorical style, and pragmatic norms differ meaningfully from English. We evaluated six automatic translations of essays on generative AI across three projects using a customized MQM typology, assessed by two trained evaluators working from U.S. English into LATAM and Mexican Spanish. Results show that a limited prompt produced no meaningful reformulation, and specifications and corpus-informed translations at times showed substantial reformulation, though not always to effect. We find that LLMs can be moved toward reformulation and away from the sentence-by-sentence paradigm, though more work is needed to improve the effectiveness of those reformulations. In this paper, we discuss considerations related to automatic translation system design, corpus construction, and transla

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "Can an Old Dog Be Taught New Tricks? Taking LLMs Beyond Sentence Level Translation", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-ava-training-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14040v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14040v1 — trying X"
4. git commit -m "exp: ava-training 2607.14040v1 — Can an Old Dog Be Taught New Tricks? Taking LLMs B"
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
