# Experiment 2505.02279v1 — A survey of agent interoperability protocols: MCP, ACP, A2A, and ANP

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-bigbang-mcp-2505.022
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2505.02279v1 / PDF https://arxiv.org/pdf/2505.02279v1
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2505.02279v1.md

## Abstract
MCP provides JSON-RPC client-server for secure tool invocation, typed data exchange. ACP REST-native multipart async streaming. A2A peer-to-peer task outsourcing via Agent Cards. ANP decentralized DIDs JSON-LD. Phased adoption: MCP for tool access, ACP for multimodal, A2A for collaborative, ANP for decentralized marketplaces. BigBang CLI universal router should implement all 4.

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "A survey of agent interoperability protocols: MCP, ACP, A2A, and ANP", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-bigbang-mcp-2505.022 from master in bigbang-cli
2. Read paper PDF + graphify_source/2505.02279v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2505.02279v1 — trying X"
4. git commit -m "exp: bigbang-mcp 2505.02279v1 — A survey of agent interoperability protocols: MCP,"
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
