# Experiment 2607.14082v1 — Building Shor's Algorithm in Lean: An Agentic Formalization of Quantum Attacks on RSA-2048 and P-256

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-graphify-rag-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14082v1 / PDF https://arxiv.org/pdf/2607.14082v1
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14082v1.md

## Abstract
Large language models are increasingly assisting with demanding formal theorem-proving tasks, particularly when grounded in machine-checked libraries such as Lean. Agentic systems further amplify this process by searching, reusing, and extending existing formal developments to uncover new discoveries. In quantum computing, Shor's algorithm and its variants present such a demanding case for Lean formalization. In this work, we formalize this algorithm family in Lean through agentic formalization: software agents analyze sources, write Lean code and repair proofs, with human review of the scientific claims and machine checking of the resulting formal proofs. Our formalization develops the mathematical foundations for analyzing quantum attacks in two cryptographic settings: a 2048-bit modulus in the RSA-2048 and the standardized elliptic curve over a 256-bit prime field (P-256). To support these analyses, the formalization ranges from quantum algorithms for order finding to reversible quantum circuits for modular and elliptic-curve arithmetic. Based on [Quantum 5, 433] and [ASIACRYPT 2017, 241--270], we formalize the logical resource estimates for RSA-2048 and P-256, respectively, and provide additional estimates of classical operations. We expect the results pave the way for broader machine-checked quantum cryptanalysis and represent a step toward AI-assisted design and verification of quantum algorithms.

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "Building Shor's Algorithm in Lean: An Agentic Formalization of Quantum Attacks on RSA-2048 and P-256", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-graphify-rag-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14082v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14082v1 — trying X"
4. git commit -m "exp: graphify-rag 2607.14082v1 — Building Shor's Algorithm in Lean: An Agentic Form"
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
