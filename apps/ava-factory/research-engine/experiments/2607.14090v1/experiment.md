# Experiment 2607.14090v1 — Cold Stream Penetration of Virial Shocks: Fragmentation, Coagulation, and Disruption in the Hot Circumgalactic Medium

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2607.140
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.14090v1 / PDF https://arxiv.org/pdf/2607.14090v1
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14090v1.md

## Abstract
Cold streams penetrating virial shocks of massive halos along cosmic web filaments are expected to fuel galaxy growth at high redshift, yet the physical processes governing their penetration remain uncertain. We investigate cylindrical cold streams penetrating a hot circumgalactic medium (CGM) using idealized three-dimensional simulations. We systematically vary the stream radius, Mach number, and initial pressure contrast between the stream and the CGM across three density contrasts, while controlling stream properties after pressure equilibrium is re-established. We identify three evolutionary regimes: coagulation, fragmentation, and disruption, plus a borderline regime in which the stream core marginally survives while detached fragments are disrupted. At modest pressure contrast, survival is governed primarily by the competition between velocity shear and radiative cooling. Increasing pressure contrast produces a transient response during pressure restoration, temporarily enhancing or suppressing the cold-gas mass and cold-hot interfacial area before evolution converges to a shear-dominated state. At larger pressure contrasts, the oblique shock steepens into a bow shock, and the final outcome is determined by the ratio of the post-shock cooling time to the virial crossing time. In all survival cases, post-equilibration evolution is well described by turbulent radiative entrainment at the stream-CGM interface: the cold-gas mass flux increases while the mean streamwise mome

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "Cold Stream Penetration of Virial Shocks: Fragmentation, Coagulation, and Disruption in the Hot Circumgalactic Medium", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2607.140 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.14090v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14090v1 — trying X"
4. git commit -m "exp: bigbang-mcp 2607.14090v1 — Cold Stream Penetration of Virial Shocks: Fragment"
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
