# Experiment 2607.10889v2 — Post-Newtonian N-Body Dynamics in Extended Theories of Gravity

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-bigbang-mcp-2607.108
**Date:** 2026-07-17
**Paper:** https://arxiv.org/abs/2607.10889v2 / PDF https://arxiv.org/pdf/2607.10889v2
**Topic:** bigbang-mcp — MCP + OpenAPI Tool Use + Agentic Routing (importance critical)
**Ecosystem:** bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.10889v2.md

## Abstract
We derive the complete first post-Newtonian (1PN) Lagrangian and corresponding equations of motion for the relativistic $N$-body system in Scalar-Tensor-Fourth-Order Gravity (STFOG), including the Non-Commutative Spectral Geometry (NCSG) sector as a special case. In the regime $Φ\sim Ψ$ ($γ\sim 1$), the linearized fourth-order field equations are solved in the Standard Post-Newtonian gauge, and the variational Lagrangian is built directly from the point-particle action. The resulting dynamics is governed by three Yukawa functions $ζ$, $\mathcal{W}$ and $Ξ$, which encode the scalar, gravitomagnetic and three-body sectors and depend on the effective masses $(m_R,m_Y,m_φ)$ of the additional propagating modes. In this context, we show that the nonlinear metric component ${}^{(4)}\!g_{00}$ plays no role at 1PN level. The 1PN orbital motion of the above extended theories is thus obtained in closed form, and the Einstein--Infeld--Hoffmann equations are recovered in the corresponding general-relativistic limit. The formalism provides a common framework for the relativistic celestial mechanics of the Solar System, binary pulsars such as PSR J0737-3039, Galactic-center stellar orbits and triple systems.

## Why relevant
BigBang CLI universal router: MCP SDK sse_client + streamablehttp, OpenAPI codegen fetch_spec parse_operations generate_typer_plugin, Ava router qwen3:32b heuristic 0.92 for tasks

## Hypothesis (per program.md)
Based on "Post-Newtonian N-Body Dynamics in Extended Theories of Gravity", try applying idea to Ava bigbang-mcp.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/bigbang/core/mcp_client.py + openapi.py + llm.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul17-bigbang-mcp-2607.108 from master in bigbang-cli
2. Read paper PDF + graphify_source/2607.10889v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.10889v2 — trying X"
4. git commit -m "exp: bigbang-mcp 2607.10889v2 — Post-Newtonian N-Body Dynamics in Extended Theorie"
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
