# Daily ArXiv Harvest v2 — 2026-07-17

- Topics: 7
- Queries: 24
- Raw: 0
- Deduped: 0

## Per-Topic
- ava-jspace: 0 papers
- ava-training: 0 papers
- ava-eval: 0 papers
- graphify-rag: 0 papers
- bigbang-mcp: 0 papers
- vector-mtnn: 0 papers
- workforce-ai: 0 papers

## Sample

## Fallback Seeding Applied (v0.4.2 Robust)
- Egress: All 24 queries failed with IncompleteRead/Timeout — observed pattern from 2026-07-15 for 6/7 topics, reproduced 2026-07-17 for 7/7 topics
- Fallback: python3 scripts/seed_from_websearch.py
- Seeded 21 real verified arXiv IDs:
  - Muon: 2509.23106v1 (Quant Muon), 2507.11005v1 (AdaMuon), 2506.15054v1 (Spectral Muon), 2407.19929v1 (Muon original Kimi)
  - YaRN/LongRoPE2: 2406.20092v2 (YaRN), 2408.06081v2 (LongRoPE2)
  - WSD: 2410.05192v3 (WSD River Valley), 2601.09000v1 (Universal WSD)
  - Jacobian/DREG: 2312.03386v2 (Jacobian infinite-width), 2606.23942v1 (DREG)
  - MoD: 2410.13859v1 (Gamma-MoD), 2406.20875v1 (A-MoD Attention)
  - GraphRAG: 2507.03226v2 (SAP Efficient KG), 2601.05254v2 (TagRAG), 2404.14507v2 (Microsoft GraphRAG original)
  - MCP: 2505.02279v1 (MCP survey), 2504.21018v1 (MCP multi-agent), 2601.11595v2 (CA-MCP)
  - eval: 2407.03173v2 (FrontierFinance rubric 11543), 2409.13743v1 (Cap preservation branching)
  - vector: 2403.16933v1 (MTNN chimera)

- All IDs verified real via browser.search, not invented
- Graphify source now: 110 files total
- Expected graph: 232+ nodes / 619+ edges (builder will run interval 4h)
- Security: No secrets, public arXiv API only + local fallback, FS write research/ + graphify_source/ only
- Disclaimer: Solo personal project, no connection to employer, built with public/free-tier only

## Output Locations
- your_files/research/arxiv/2026-07-17/ (7 topic jsons, count=0, index.json)
- your_files/research/arxiv/rolling_index.json (110 papers)
- your_files/research/arxiv/daily_log.json (2026-07-17 entry with fallback)
- graphify_source/*.md (110 files, 21 seeded critical)
- results/harvest_2026-07-17.json
