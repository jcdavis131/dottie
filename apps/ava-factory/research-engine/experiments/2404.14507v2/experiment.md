# Experiment 2404.14507v2 — GraphRAG: Unlocking Query-Focused Summarization via Graph-Based RAG

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-graphify-rag-2404.145
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2404.14507v2 / PDF https://arxiv.org/pdf/2404.14507v2
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2404.14507v2.md

## Abstract
Original Microsoft GraphRAG — builds hierarchical Leiden clustering over KG, generates community summaries. Enables global sensemaking over entire corpus. 35.2x token reduction claim originates here. Ava Graphify baseline 727 nodes 1713 edges 49 comms implements similar.

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "GraphRAG: Unlocking Query-Focused Summarization via Graph-Based RAG", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-graphify-rag-2404.145 from master in bigbang-cli
2. Read paper PDF + graphify_source/2404.14507v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2404.14507v2 — trying X"
4. git commit -m "exp: graphify-rag 2404.14507v2 — GraphRAG: Unlocking Query-Focused Summarization vi"
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
