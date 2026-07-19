# Experiment 2607.07513v2 — Fast Rates for Semi-Supervised Learning via Data-Augmentation Graph Regularization

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-graphify-rag-2607.075
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2607.07513v2 / PDF https://arxiv.org/pdf/2607.07513v2
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.07513v2.md

## Abstract
Self-supervised learning matches supervised accuracy from a fraction of the labels, but the labeled-sample efficiency behind this has lacked a theoretical explanation. We provide one. Data augmentation induces a similarity graph on the unlabeled data, so downstream learning on that graph is graph-Laplacian-regularized learning. We prove a fast transductive rate, $O(1/n_L)$ in the number of labels, in place of the supervised $O(1/\sqrt{n_L})$, by carrying the leave-one-out stability apparatus of Johnson and Zhang (JMLR 2007) over to the augmentation graph, and without the unrealistic assumptions of limit-based analyses (exact kernel, generalizing features). The bound makes augmentation quality explicit: the expected error is at most $C/n_L + R_{\mathrm{DA}}(y)$, where the data-augmentation alignment error $R_{\mathrm{DA}}(y)$ is proportional to the graph-cut mass of augmentations that cross a label boundary, so good augmentations let few labels suffice. The analysis uses a streamlined loss that drops the projector, negative-sample, and orthogonality overhead of standard objectives yet still recovers the top-$K$ ideal features in the infinite-data limit, the augmentation-kernel eigenspace studied by Zhai et al. The bound gives a mechanistic account of the accuracy-versus-label-count curve through augmentation quality, verified in a controlled model where the constants are known.

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "Fast Rates for Semi-Supervised Learning via Data-Augmentation Graph Regularization", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-graphify-rag-2607.075 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.07513v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.07513v2 — trying X"
4. git commit -m "exp: graphify-rag 2607.07513v2 — Fast Rates for Semi-Supervised Learning via Data-A"
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
