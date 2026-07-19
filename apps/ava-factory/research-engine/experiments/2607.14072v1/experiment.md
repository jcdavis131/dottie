# Experiment 2607.14072v1 — MetaPerch: Learning from metadata for bioacoustics foundation models

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14072v1 / PDF https://arxiv.org/pdf/2607.14072v1
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14072v1.md

## Abstract
Bioacoustic foundation models rely on large-scale citizen science platforms like Xeno-Canto for geographically and ecologically diverse data. Recent work has shown that supervision alone can produce SotA species detection models when trained on this large-scale data -- however, there remains unutilized potential in the form of recording metadata readily available within these community-driven data hubs. In this work, we explore the use of metadata -- such as location and time -- as auxiliary supervision signals, allowing the model to leverage species-metadata correlations in its learned representation. Auxiliary metadata losses provide additional information beyond vocalizations alone that can encourage a richer, more robust representation that generalizes better to species distribution and acoustic domain shifts -- important challenges for deployment in real-world passive acoustic monitoring (PAM) settings. We introduce MetaPerch, a new foundation model that achieves strong species identification performance across multiple challenging domains and present an extensive empirical study of the effects of 9 diverse metadata sources on 17 bioacoustic datasets.

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "MetaPerch: Learning from metadata for bioacoustics foundation models", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14072v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14072v1 — trying X"
4. git commit -m "exp: bigbang-mcp 2607.14072v1 — MetaPerch: Learning from metadata for bioacoustics"
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
