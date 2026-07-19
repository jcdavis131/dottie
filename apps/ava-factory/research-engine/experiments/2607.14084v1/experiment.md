# Experiment 2607.14084v1 — Investigating anomalous microwave emission near G107.2+5.20 in Ku-band with the Green Bank Telescope

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14084v1 / PDF https://arxiv.org/pdf/2607.14084v1
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14084v1.md

## Abstract
Anomalous microwave emission (AME) is 30 GHz-peaking continuum emission thought to arise from spinning dust grains. Observations suggest that the local environment shapes the AME spectral energy distribution (SED), so building a spatially resolved sample of AME regions is a key step towards understanding its emission mechanism. Using the Green Bank Telescope Ku-band receiver, we obtained a ~1 arcmin resolution map of radius 1.25 deg centered on G107.2+5.20. Our first objective was to constrain the low-frequency side of the AME SED with 13 GHz data. Using matched-resolution aperture photometry, we measure the SED from 408 MHz-3 THz and fit two emission models: one including spinning dust, the other optically thick free-free emission. We find that the spinning dust model is superior, with an amplitude of $14.1\pm1.1$ Jy and a peak frequency of $27\pm2$ GHz. Our second objective was to spatially locate excess 13 GHz emission consistent with spinning dust. We compare our Ku-band map to multi-wavelength gas and dust tracers at ~4 arcmin resolution. We observe two sources of 13 GHz excess at 3$σ$ significance consistent with spinning dust emission, though potential contributions from optically thick free-free emission remain ambiguous. ``Region A'' (G106.95+5.19) is spatially coincident with peak dust radiance. ``Region B'' (G107.08+4.90) is spatially coincident with peak PAH abundance. If regions A and B are indeed sources of spinning dust emission, they are a resolved example of 

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "Investigating anomalous microwave emission near G107.2+5.20 in Ku-band with the Green Bank Telescope", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14084v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14084v1 — trying X"
4. git commit -m "exp: bigbang-mcp 2607.14084v1 — Investigating anomalous microwave emission near G1"
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
