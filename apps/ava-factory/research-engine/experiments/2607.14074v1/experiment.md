# Experiment 2607.14074v1 — Quantum Transport and Apparent Work Function Distributions of Atomic Contacts via a 3D-Printed High-Vacuum Platform

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14074v1 / PDF https://arxiv.org/pdf/2607.14074v1
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14074v1.md

## Abstract
We present a low-cost, 3D-printed high-vacuum platform integrating a mechanically controllable break-junction system and a custom logarithmic amplifier for room-temperature quantum transport measurements. Using copper as a highly reactive test case, we successfully resolve the $1G_0$ conductance quantum under both high vacuum and anhydrous glycerol, demonstrating the effectiveness of these environments against rapid atmospheric oxidation. In parallel, utilizing gold as a robust benchmark, we systematically extract the apparent work function ($φ$) from thousands of tunneling traces across ambient air, vacuum, and glycerol. Our analysis demonstrates that the statistical distribution of $φ$ rigorously follows a non-central chi-square distribution. The obtained gold work functions match existing literature across all environments. Although lower than bulk values, they perfectly align with theoretical models accounting for atomic-scale roughness, apex geometry, and environmental adsorbates. Ultimately, this methodology establishes an accessible and reproducible framework for systematic nanoscale research on reactive materials.

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "Quantum Transport and Apparent Work Function Distributions of Atomic Contacts via a 3D-Printed High-Vacuum Platform", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14074v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14074v1 — trying X"
4. git commit -m "exp: bigbang-mcp 2607.14074v1 — Quantum Transport and Apparent Work Function Distr"
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
