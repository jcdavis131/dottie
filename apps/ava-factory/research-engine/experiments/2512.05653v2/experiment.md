# Experiment 2512.05653v2 — Executing Discrete/Continuous Declarative Process Specifications via Complex Event Processing

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2512.056
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2512.05653v2 / PDF https://arxiv.org/pdf/2512.05653v2
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2512.05653v2.md

## Abstract
Traditional Business Process Management (BPM) focuses on discrete events and fails to incorporate critical continuous sensor data in cyber-physical environments. Hybrid declarative specifications, utilizing Signal Temporal Logic (STL), address this limitation by allowing constraints over both discrete events and real-valued signals. However, existing work has been limited to monitoring and post-hoc conformance checking. This paper introduces a novel execution architecture based on Complex Event Processing (CEP) that enables the real-time execution and enforcement of hybrid declarative models. Our three-layer approach integrates STL-inspired predicates into the execution flow, allowing the system to actively trigger activities and enforce process boundaries based on continuous sensor behavior. This approach bridges the gap between hybrid specification and operational control.

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "Executing Discrete/Continuous Declarative Process Specifications via Complex Event Processing", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2512.056 from master in bigbang-cli
2. Read paper PDF + graphify_source/2512.05653v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2512.05653v2 — trying X"
4. git commit -m "exp: bigbang-mcp 2512.05653v2 — Executing Discrete/Continuous Declarative Process "
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
