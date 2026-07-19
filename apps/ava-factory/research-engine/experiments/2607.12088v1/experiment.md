# Experiment 2607.12088v1 — TESS Photometry and Radial Velocity Analysis of the sub-Neptune Exoplanet π Mensae c and the Wider π Mensae Planetary System

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-workforce-ai-2607.120
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.12088v1 / PDF https://arxiv.org/pdf/2607.12088v1
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.12088v1.md

## Abstract
Exoplanet characterization relies on precise measurements of planetary orbital and physical parameters. This is particularly important for planetary dynamics and atmospheric evolution, as orbital parameters help constrain system evolution, resolve ambiguities, and gauge atmospheric retention. The first exoplanet discovered by the Transiting Exoplanet Survey Satellite (TESS), $π$ Men c, is a warm sub-Neptune orbiting a bright Sun-like star in a system containing (at least) one other planet with a wildly different period and size. Lying near the 1.5-2.0 $R_{\oplus}$ radius gap, $π$ Men c is expected to have lost its primordial hydrogen and helium, but kept heavier compounds like H$_2$O and CO$_2$. The $π$ Men system is well observed with decades of radial velocity measurements, and TESS has continued to observe $π$ Men c, yielding six years and 21 sectors of photometry. We present a comprehensive analysis of these TESS data and 22 years of radial velocity measurements to provide updated orbital ephemerides for $π$ Men b, c, and the proposed third planet, $π$ Men d. Our newly derived $π$ Men c period error margins are an order of magnitude improved from previous estimates, and we estimate the mass range of $π$ Men d to be 13.4 $\leq$ M$_d$ $<$ 20 M$_{\oplus}$. We find that $π$ Men c is a uniquely interesting target for future transmission spectroscopy studies with JWST, and that existing radial velocity data are consistent with the existence of a third planet.

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "TESS Photometry and Radial Velocity Analysis of the sub-Neptune Exoplanet π Mensae c and the Wider π Mensae Planetary System", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-workforce-ai-2607.120 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2607.12088v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.12088v1 — trying X"
4. git commit -m "exp: workforce-ai 2607.12088v1 — TESS Photometry and Radial Velocity Analysis of th"
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
Generated 2026-07-18 by autoresearch-runner cron
