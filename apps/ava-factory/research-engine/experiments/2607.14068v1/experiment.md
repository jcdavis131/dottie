# Experiment 2607.14068v1 — The even-uniform hypergraph Moore bound

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-graphify-rag-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14068v1 / PDF https://arxiv.org/pdf/2607.14068v1
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14068v1.md

## Abstract
The hypergraph Moore bound conjectured by Feige (2008) controls the size of the smallest even cover in a $k$-uniform hypergraph in terms of the average density of hyperedges. An even cover is a set of hyperedges covering each vertex an even number of times, generalizing the notion of a cycle in a graph, so the size of the smallest non-trivial even cover provides a notion of hypergraph girth. Recent work starting from the breakthrough result of Guruswami, Kothari, and Manohar (2022) proved the conjecture up to polylogarithmic factors, whose exponents were later gradually improved. We give a simple proof of Feige's original hypergraph Moore bound conjecture for all even $k\ge 4$, with no superfluous polylogarithmic factors. Our proof roughly follows the proof of the graph Moore bound, but works with colored walks in a Kikuchi graph built from a hypergraph and controls their growth using a polynomial interpolation method.

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "The even-uniform hypergraph Moore bound", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-graphify-rag-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14068v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14068v1 — trying X"
4. git commit -m "exp: graphify-rag 2607.14068v1 — The even-uniform hypergraph Moore bound"
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
