# Experiment 2607.14073v1 — An exactly solvable macroscopic fluctuation theory of single-file diffusion

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14073v1 / PDF https://arxiv.org/pdf/2607.14073v1
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14073v1.md

## Abstract
Single-file diffusion is a ubiquitous phenomenon in low-dimensional systems, arising in transport inside narrow channels. Its natural continuum model is a one-dimensional gas of extended Brownian hard rods (BHR). Perhaps owing to the perceived intractability of this problem, much of the literature has traditionally focused on lattice exclusion models, where integrability methods have yielded remarkable, albeit limited, exact results. A major recent advance comes from a formal solution of macroscopic fluctuation theory (MFT) for the exclusion process. Yet, despite the formal solution, only a handful of properties have been made explicit. We show that the corresponding MFT of the extended BHR gas is in fact exactly solvable through a canonical transformation. We demonstrate this by explicit computation of the large-deviation statistics of the tracer-position and integrated-current in both annealed and quenched ensembles. We further show that an analogous canonical transformation applies to the MFT of lattice gases with finite-volume exclusion, yielding corresponding tracer and current statistics. We validate our results using rare-event simulations for both the continuum and the lattice models.

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "An exactly solvable macroscopic fluctuation theory of single-file diffusion", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14073v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14073v1 — trying X"
4. git commit -m "exp: bigbang-mcp 2607.14073v1 — An exactly solvable macroscopic fluctuation theory"
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
