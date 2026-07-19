# Experiment 2605.05308v2 — The diverse outcomes of binary white dwarf mergers and connections to Galactic LISA sources

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-graphify-rag-2605.053
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2605.05308v2 / PDF https://arxiv.org/pdf/2605.05308v2
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2605.05308v2.md

## Abstract
In the coming decade, the millihertz gravitational wave observatory LISA will provide the best constraints yet on the tens of thousands of close white dwarf binaries in the Milky Way, yielding unprecedented insights into the most abundant class of compact object binaries. Following inspiral via gravitational wave emission, interacting white dwarf binary pairs can lead to a multitude of outcomes, including AM Canum Venaticorum (AM CVn) binaries, R Coronae Borealis stars, young, rapidly-spinning single white dwarfs, (millisecond) magnetars, and a variety of explosive transients, most notably Type Ia supernovae. Current and future electromagnetic observations of these various outcomes coupled with the forthcoming flood of data from LISA place us on the precipice of a significant advance in our understanding of the long-term fate of white dwarf binaries. In this paper, we present a suite of mock catalogs of the Milky Way's white dwarf merger history, created using the population synthesis code $\texttt{COSMIC}$ combined with a metallicity-dependent star formation history from FIRE-2 galaxy simulations. We summarize the various merger outcomes expected (based upon varying white dwarf masses and chemical compositions) and explore ways the rates of these outcomes may vary with model uncertainties pertaining to binary evolution. We publicly release these merger catalogs as a tool for facilitating connections between gravitational wave science and white dwarf binary astrophysics.

## Why relevant
personal-graphify: 727 nodes 1713 edges 49 comms, tree-sitter extraction, 35.2x token reduction (71.5x upstream), LLM wikis token-efficient, GraphRAG

## Hypothesis (per program.md)
Based on "The diverse outcomes of binary white dwarf mergers and connections to Galactic LISA sources", try applying idea to Ava graphify-rag.

**What to modify (ONE file only for clean diff):**
- bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-graphify-rag-2605.053 from master in bigbang-cli
2. Read paper PDF + graphify_source/2605.05308v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2605.05308v2 — trying X"
4. git commit -m "exp: graphify-rag 2605.05308v2 — The diverse outcomes of binary white dwarf mergers"
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
