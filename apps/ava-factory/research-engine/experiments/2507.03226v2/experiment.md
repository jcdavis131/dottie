# Experiment 2507.03226v2 — Efficient Knowledge Graph Construction and Retrieval from Unstructured Text for Large-Scale RAG Systems

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-graphify-rag-2507.032
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2507.03226v2 / PDF https://arxiv.org/pdf/2507.03226v2
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2507.03226v2.md

## Abstract
Scalable GraphRAG for enterprise. Dependency-based KG construction pipeline using industrial NLP to extract entities/relations, completely eliminating LLM reliance. Lightweight graph retrieval with hybrid query node ID + one-hop traversal. 15% improvement over traditional RAG (LLM-as-Judge), 4.35% RAGAS, 94% of LLM-generated KG performance (61.87 vs 65.83) while reducing cost massively. Directly applicable to personal-graphify -> pgraphify should use spaCy dependency parsing to avoid LLM calls.

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "Efficient Knowledge Graph Construction and Retrieval from Unstructured Text for Large-Scale RAG Systems", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-graphify-rag-2507.032 from master in bigbang-cli
2. Read paper PDF + graphify_source/2507.03226v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2507.03226v2 — trying X"
4. git commit -m "exp: graphify-rag 2507.03226v2 — Efficient Knowledge Graph Construction and Retriev"
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
