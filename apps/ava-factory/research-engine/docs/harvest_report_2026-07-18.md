# Daily ArXiv Harvest v2 — 2026-07-18

- Topics: 7
- Queries: 25 (limit 4 per topic)
- Raw: 0 (egress failed IncompleteRead)
- Deduped: 0 from API
- Fallback: seeded 21 real papers from browser.search
- Total graphify_source: 170 files

## Egress Status
- Direct arxiv API queries failed with IncompleteRead( bytes read, X more expected) + Remote end closed
- Same pattern observed 2026-07-15 for 6/7 topics — hatch-egress-proxy:3128 Invalid port for ::1, fd8b::
- Robustness measures (3 retries exponential backoff + jitter, HTTPS then HTTP fallback, UA header, 45s timeout, 2-3s delay, NO_PROXY sanitized) still insufficient
- Fallback succeeded per v0.4.2 spec

## Seeded Papers (21 verified real arXiv IDs)
- Muon: 2509.23106v1, 2507.11005v1, 2506.15054v1, 2407.19929v1
- YaRN/LongRoPE2: 2406.20092v2, 2408.06081v2
- WSD: 2410.05192v3, 2601.09000v1
- Jacobian/DREG: 2312.03386v2, 2606.23942v1
- MoD: 2410.13859v1, 2406.20875v1
- GraphRAG: 2507.03226v2, 2601.05254v2, 2404.14507v2
- MCP: 2505.02279v1, 2504.21018v1, 2601.11595v2
- Eval: 2407.03173v2, 2409.13743v1
- Vector: 2403.16933v1

All IDs verified via browser.search — not invented per spec.

## Per-Topic API Count
- ava-jspace: 0
- ava-training: 0
- ava-eval: 0
- graphify-rag: 0
- bigbang-mcp: 0 (process killed early)
- vector-mtnn: 0
- workforce-ai: 0

## Output
- /home/hatch/workspace/your_files/research/arxiv/2026-07-18/*.json (7 topics, 0 papers today)
- graphify_source/*.md (170 files total, 21 newly seeded fallback)
- rolling_index.json -> 110 papers (papers dict)

## Next
- research-graphify-build (interval 4h) will rebuild graphify-out-research/graph.json (266KB) + research-graph.json + research-weekly.md
- Will produce 232 nodes/619 edges baseline even with 0 new API papers due to fallback preservation

Solo personal project, no connection to employer, built with public/free-tier only
