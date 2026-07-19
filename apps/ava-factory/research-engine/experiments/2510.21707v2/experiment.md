# Experiment 2510.21707v2 — A Unified Framework Connecting Chemical Enrichment to Resolved Star Formation Histories with Applications to Local Group Dwarf Irregulars

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul19-workforce-ai-2510.217
**Date:** 2026-07-19
**Paper:** https://arxiv.org/abs/2510.21707v2 / PDF https://arxiv.org/pdf/2510.21707v2
**Topic:** workforce-ai — Workforce Turnover + Retention Prediction (importance medium)
**Ecosystem:** 02_Passive_Lab/ + Turnover Shield MVP
**Graphify source:** /home/hatch/workspace/dottie/apps/ava-factory/graphify_source/2510.21707v2.md

## Abstract
We present a new framework for modeling the chemical enrichment histories of galaxies by integrating chemical evolution with resolved star formation histories (SFHs) derived from color-magnitude diagrams. This novel approach links the time evolution of the metallicity of the star-forming ISM to the cumulative stellar mass formed in the galaxy, enabling a self-consistent description of chemical evolution. We apply this methodology to four isolated, gas-rich Local Group dwarf galaxies -- WLM, Aquarius, Leo A, and Leo P -- using deep HST and JWST imaging. For WLM, Aquarius, and Leo A, we independently validate our metallicity evolution results against ages and metallicities of individual red giant stars with spectroscopic measurements. We quantify systematic uncertainties by repeating our analysis with multiple stellar evolution and bolometric correction libraries. We compare the observed chemical enrichment histories to predictions from the TNG50 and FIREbox cosmological hydrodynamic simulations and the Galacticus semi-analytic model. Of our four galaxies, only WLM is sufficiently massive to be reliably represented in these simulations; the remaining three fall below current resolution limits. We find that the enrichment history of WLM is best reproduced by FIREbox, while TNG50 and Galacticus predict higher metallicities at early times, suggesting that differences in stellar feedback and metal recycling prescriptions drive significant variation in predicted enrichment histories

## Why relevant
Trade Crew Turnover Shield $79-$149/mo, 7-13 customers -> $1k MRR, solo boring B2B, free-tier Supabase/R2/Workers

## Hypothesis (per program.md)
Based on "A Unified Framework Connecting Chemical Enrichment to Resolved Star Formation Histories with Applications to Local Group Dwarf Irregulars", try applying idea to Ava workforce-ai.

**What to modify (ONE file only for clean diff):**
- 02_Passive_Lab/ + Turnover Shield MVP
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul19-workforce-ai-2510.217 from master in 02_Passive_Lab
2. Read paper PDF + graphify_source/2510.21707v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2510.21707v2 — trying X"
4. git commit -m "exp: workforce-ai 2510.21707v2 — A Unified Framework Connecting Chemical Enrichment"
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
Generated 2026-07-19 by autoresearch-runner cron
