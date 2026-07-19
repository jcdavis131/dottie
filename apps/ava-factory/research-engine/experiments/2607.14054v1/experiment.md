# Experiment 2607.14054v1 — Fast Cascaded Recursive Filtering via a Block-Matrix Reformulation

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-graphify-rag-2607.140
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2607.14054v1 / PDF https://arxiv.org/pdf/2607.14054v1
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14054v1.md

## Abstract
Recursive (IIR) filters realized as cascaded second-order sections (biquads) offer both design generality and robustness against coefficient quantization. However, their inherent sample-to-sample feedback dependency poses a fundamental obstacle to parallel computation. This paper reformulates the biquad difference equation as a banded block-Toeplitz linear system and introduces a stride-$N$ permutation that maps a group of $NL$ samples into a block-tridiagonal structure whose entries are scalar multiples of identity and shift matrices. Within this framework, two parallel algorithms are developed for the recursive solution: a partial LU (PH) factorization that preserves the sparse block structure and a cyclic reduction that is applied to recursive filtering, to the best of our knowledge, for the first time. It reduces the sequential dependency depth from $\mathcal{O}(N)$ to $\mathcal{O}(\log_2 N)$. For a cascade of $K$ biquads, the intermediate permutations between successive sections cancel exactly, so that only a single permutation/de-permutation pair is required for the entire cascade, eliminating $2(K{-}1)$ redundant stages. Exact block-level operation counts are derived for every algorithmic stage and validated against cycle-accurate measurements on three Intel micro-architectures supporting AVX2 SIMD instructions. Experimental results for a 16th-order system show that the proposed multi-block algorithms reduce clock cycles per sample by up to $10\times$ compared to scala

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "Fast Cascaded Recursive Filtering via a Block-Matrix Reformulation", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-graphify-rag-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14054v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14054v1 — trying X"
4. git commit -m "exp: graphify-rag 2607.14054v1 — Fast Cascaded Recursive Filtering via a Block-Matr"
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
