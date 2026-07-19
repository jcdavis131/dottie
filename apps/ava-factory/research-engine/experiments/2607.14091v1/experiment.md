# Experiment 2607.14091v1 — Pair-Partition Constructions for CPM-Based Quantum LDPC Codes

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-graphify-rag-2607.140
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.14091v1 / PDF https://arxiv.org/pdf/2607.14091v1
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14091v1.md

## Abstract
We construct binary Calderbank--Shor--Steane (CSS) quantum low-density parity-check (LDPC) codes from circulant permutation matrices (CPMs). The construction is parameterized by column weight J, row weight L, and prime lift size P. A J x J array of pair partitions imposes linear paired-difference equations on the CPM exponents. These equations give CSS orthogonality. The main finite examples reported here are the (J,L)=(4,12)-regular girth-six code [[372,130,16]] with rate 0.349, and the (J,L)=(4,14)-regular girth-six code [[518,228,16]] with rate 0.440. We also record (J,L)=(3,8)-regular girth-six instances [[472,122,14]] and [[488,126,14]], with lift sizes P=59 and P=61, respectively. The stated distances are established for the fixed matrices by exhaustive low-weight exclusion together with explicit non-stabilizer witnesses.

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "Pair-Partition Constructions for CPM-Based Quantum LDPC Codes", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-graphify-rag-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14091v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14091v1 — trying X"
4. git commit -m "exp: graphify-rag 2607.14091v1 — Pair-Partition Constructions for CPM-Based Quantum"
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
