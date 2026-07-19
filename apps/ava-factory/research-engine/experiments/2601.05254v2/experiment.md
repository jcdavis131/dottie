# Experiment 2601.05254v2 — TagRAG: Tag-guided Hierarchical Knowledge Graph Retrieval-Augmented Generation

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-graphify-rag-2601.052
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2601.05254v2 / PDF https://arxiv.org/pdf/2601.05254v2
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2601.05254v2.md

## Abstract
Tag Knowledge Graph Construction extracts object tags and relationships, organizes into hierarchical domain tag chains. Tag-Guided Retrieval localizes domain-centric chains. 78.36% win rate vs baselines, 14.6x construction efficiency, 1.9x retrieval efficiency vs GraphRAG. Adaptable to smaller LMs. For Ava Graphify: add tag-guided hierarchical chains.

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "TagRAG: Tag-guided Hierarchical Knowledge Graph Retrieval-Augmented Generation", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-graphify-rag-2601.052 from master in bigbang-cli
2. Read paper PDF + graphify_source/2601.05254v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2601.05254v2 — trying X"
4. git commit -m "exp: graphify-rag 2601.05254v2 — TagRAG: Tag-guided Hierarchical Knowledge Graph Re"
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
