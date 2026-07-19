# Experiment 2603.03444v2 — New Thermal-Relic Targets for sub-GeV Dark Matter Direct Detection

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2603.034
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2603.03444v2 / PDF https://arxiv.org/pdf/2603.03444v2
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2603.03444v2.md

## Abstract
Dark matter direct detection experiments involving electron recoils are beginning to test highly-predictive, thermal-relic milestones for sub-GeV dark matter models. Due to the Lee-Weinberg bound, thermal dark matter candidates in this mass range necessarily require comparably-light mediator particles to achieve a suitably large annihilation cross section. Here we present new thermal-relic milestones for sub-GeV dark matter candidates that couple to vector mediators. In these models, the mediators are massive gauge bosons of anomaly-free abelian extensions to the Standard Model, including the dark photon, gauged $L_i - L_j, B-L$, and $B-3L_i$ models, where $B$ is the baryon number, $L$ is the lepton number, and $i,j$ index the lepton families. Since the same interactions that govern cosmological production also govern electron scattering, the targets we present are firmly predictive and allow for these models to be robustly discovered or falsified. Furthermore, since the mediators we study exhaust the minimal anomaly-free U(1) extensions to the Standard Model, our results offer a complete list of predictive milestones for sub-GeV dark matter coupled to vector mediators.

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "New Thermal-Relic Targets for sub-GeV Dark Matter Direct Detection", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2603.034 from master in bigbang-cli
2. Read paper PDF + graphify_source/2603.03444v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2603.03444v2 — trying X"
4. git commit -m "exp: bigbang-mcp 2603.03444v2 — New Thermal-Relic Targets for sub-GeV Dark Matter "
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
