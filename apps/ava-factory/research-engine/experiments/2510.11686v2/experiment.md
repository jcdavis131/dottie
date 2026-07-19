# Experiment 2510.11686v2 — Representation-Based Exploration for Language Models: From Test-Time to Post-Training

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-graphify-rag-2510.116
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2510.11686v2 / PDF https://arxiv.org/pdf/2510.11686v2
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2510.11686v2.md

## Abstract
Reinforcement learning (RL) promises to expand the capabilities of language models, but it is unclear if current RL techniques promote the discovery of novel behaviors, or simply sharpen those already present in the base model. In this paper, we investigate the value of deliberate exploration -- explicitly incentivizing the model to discover novel and diverse behaviors -- and aim to understand how the knowledge in pre-trained models can guide this search. Our main finding is that exploration with a simple, principled, representation-based bonus derived from the pre-trained language model's hidden states significantly improves diversity and pass@k rates -- both for post-training, and in a novel inference-time scaling setting we introduce. For inference-time, exploration with representation-based diversity improves efficiency, consistently improving pass@k rates across a variety of models and reasoning tasks. For example, for Qwen-2.5-14b-Instruct we obtain over 50% improvement in verifier efficiency on almost all tasks. For post-training, we show that integrating this exploration strategy into an RL pipeline improves reasoning performance over that of the initial model and over standard RL post-training. For example, on AIME 2024, our post-trained Qwen-2.5-7b-Instruct's pass@80 matches the pass@256 of GRPO on the same model, demonstrating a 3x improvement in test-time sample efficiency. Overall, our findings suggest that deliberate exploration -- with the right notion of diver

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "Representation-Based Exploration for Language Models: From Test-Time to Post-Training", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-graphify-rag-2510.116 from master in bigbang-cli
2. Read paper PDF + graphify_source/2510.11686v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2510.11686v2 — trying X"
4. git commit -m "exp: graphify-rag 2510.11686v2 — Representation-Based Exploration for Language Mode"
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
