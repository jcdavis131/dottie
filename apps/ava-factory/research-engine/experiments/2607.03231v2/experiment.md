# Experiment 2607.03231v2 — Odd-parity ringdown gravitational waves of a spherically symmetric black hole with perfect fluid accretion

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2607.032
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.03231v2 / PDF https://arxiv.org/pdf/2607.03231v2
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.03231v2.md

## Abstract
The ringdown waves from a black hole offer a clean probe of strong-field gravity, but a matter distribution that may be present around a realistic black hole renders the background spacetime dynamical and the ringdown frequencies time-dependent. We study the odd-parity ringdown of a Schwarzschild black hole that grows through the dilute, steady, spherically symmetric accretion of a perfect fluid. Working to first order in the accretion rate, we compute the ringdown waveform directly in the time domain on this dynamical background. Since the odd-parity matter perturbation decouples from the metric perturbation, the wave mode can be described by a purely tensorial mode on the accreting background. In particular, the ratio of the imaginary to the real part of the frequency cancels both the secular variation caused by the growth of the black hole and the redshift factor, so that its deviation from the Schwarzschild value purely reflects the surrounding environment. The time dependence of the frequency, on the other hand, reflects the accretion rate and allows us to define a second observable tied to it. We argue that measuring these observables across multiple modes may provide significant information to constrain the surrounding environment of the black hole.

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "Odd-parity ringdown gravitational waves of a spherically symmetric black hole with perfect fluid accretion", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2607.032 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.03231v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.03231v2 — trying X"
4. git commit -m "exp: bigbang-mcp 2607.03231v2 — Odd-parity ringdown gravitational waves of a spher"
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
