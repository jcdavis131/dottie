# Experiment 2607.14078v1 — A modular state-space model of human perception, cognition, and decision dynamics

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14078v1 / PDF https://arxiv.org/pdf/2607.14078v1
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14078v1.md

## Abstract
Human-centered adaptive systems require behavioral models that are both psychologically interpretable and mathematically analyzable. Many existing predictors either operate as black-box input-output mappings or provide limited access to latent internal dynamics. This paper addresses this gap by modeling behavior as a perception-cognition-decision pipeline. We propose a modular state-space model in which attentional selection, predictive inference, cognitive-state evolution, intention formation, and action selection are represented by coupled mathematical mappings. The model links sensory inputs to observable behavior through latent internal states while retaining interpretable connections to neuro-cognitive mechanisms. We establish sufficient conditions for boundedness, Lipschitz regularity, forward invariance, contraction of perceptual inference under constant input, and input-to-state stability of the cognitive state dynamics. Numerical sensitivity analyses show that the model yields interpretable changes in perceptual tracking, cognitive amplification, intention expression, and action decisiveness. We further demonstrate a closed-loop rehabilitation case study in which a receding-horizon controller uses the model to adapt movement difficulty from partial feedback. In this proof-of-concept setting, the model-based controller sustains simulated task participation and achieves lower realized cumulative cost than target-following and random baselines. Overall, the framework pr

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "A modular state-space model of human perception, cognition, and decision dynamics", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14078v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14078v1 — trying X"
4. git commit -m "exp: bigbang-mcp 2607.14078v1 — A modular state-space model of human perception, c"
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
