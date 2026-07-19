# Experiment 2607.14035v1 — Optimizing Visibility in Generative Engines: A Critical Survey of Generative Engine Optimization (2023-2026)

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-ava-training-2607.140
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2607.14035v1 / PDF https://arxiv.org/pdf/2607.14035v1
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14035v1.md

## Abstract
Generative Engine Optimization (GEO) seeks to increase content's presence, likelihood of citation, or influence in answers produced by generative engines. Since the foundational GEO paper, the field has expanded rapidly, but terminology, metrics, and evidence standards remain heterogeneous. This critical survey reviews 45 studies selected under a November 2023-July 2026 publication window, including one earlier preprint published at EMNLP after the window opened, plus relevant RAG and evaluation work. We argue that GEO is not a single ranking task but a stochastic, partially observable pipeline spanning search activation, crawling and indexing, retrieval, reranking and context allocation, citation, prominence, factual absorption, fidelity, and user behavior. The foundational paper's widely cited gains are valid within its experimental setting but conditional on a source already being present in a fixed context; they establish neither organic discoverability nor durable traffic effects. Reviewed work indicates that topical relevance and context position are the most reproducible levers, generic heuristics transfer poorly, competition can erode individual gains, and citation-oriented rewrites can impair retrieval. Commercial audits further reveal low source overlap, substantial run-to-run variability, and persistent fidelity gaps. We contribute a multistage formal model, a visibility vector separating discoverability, citation, absorption, and economic outcomes, an evidence hie

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "Optimizing Visibility in Generative Engines: A Critical Survey of Generative Engine Optimization (2023-2026)", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-ava-training-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14035v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14035v1 — trying X"
4. git commit -m "exp: ava-training 2607.14035v1 — Optimizing Visibility in Generative Engines: A Cri"
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
