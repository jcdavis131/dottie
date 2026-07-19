# Experiment 2607.14076v1 — From Pixels to States: Rethinking Interactive World Models as Game Engines

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14076v1 / PDF https://arxiv.org/pdf/2607.14076v1
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14076v1.md

## Abstract
Building interactive worlds that respond coherently to player actions has long been a shared goal of computer graphics, games, and artificial intelligence. Recent video generative models provide a data-driven route toward this goal by predicting future observations conditioned on user actions, and are increasingly regarded as potential next-generation game engines. Realizing a genuinely interactive game world, however, requires interaction outcomes that follow rules over evolving game conditions, consequences that persist over long horizons, and a generation loop that operates in real time. Conventional game engines realize these properties through a recurrent action-state-observation loop, in which player actions update an explicit game state according to predefined rules and observations are rendered from the resulting state. Taking this loop as an organizing lens, this paper examines interactive game world modeling along four dimensions: player action control, game state dynamics, state-observation persistence, and real-time interactive generation. For each dimension, we start from the capabilities required by an interactive game world, group existing approaches into representative families, and discuss the strengths and trade-offs of each family. Complementing this analysis, we present a scalable data engine for Black Myth: Wukong that collects over 90 hours of gameplay with frame-aligned player actions, ground-truth game states, and visual observations, together with str

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "From Pixels to States: Rethinking Interactive World Models as Game Engines", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14076v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14076v1 — trying X"
4. git commit -m "exp: bigbang-mcp 2607.14076v1 — From Pixels to States: Rethinking Interactive Worl"
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
