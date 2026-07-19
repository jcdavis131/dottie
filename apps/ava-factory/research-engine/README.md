# Ava Research Engine — README
# Solo personal project, no connection to employer, built with public/free-tier only

## What this is

Continuous research engine that:
1. Harvests latest relevant research from arxiv + HuggingFace daily (06:00 UTC)
2. Builds Graphify knowledge base (727 nodes baseline → now + research corpus) — 35.2× token reduction
3. Bakes research into [AVA-RESEARCH] tasks in Google Tasks (Lina's Morning / Ava Research) for Ava AGI Factory v6.4 to research
4. Runs autonomous autoresearch loop (Karpathy concepts) hourly — picks one task, creates branch, runs 5-min fixed budget smoke, logs results.tsv, never stops

Inspired by:
- https://github.com/karpathy/autoresearch — program.md as research org code, LOOP FOREVER, single file to modify, fixed time budget, results.tsv, never ask human
- https://github.com/karpathy/nanochat / BigBang CLI v0.4.1 — universal router, MCP SDK real, OpenAPI codegen, Ava router 0.92
- Personal Graphify fork: pgraphify build/query/path/explain

## Architecture

```
arxiv API (export.arxiv.org) + HF daily papers
   ↓ daily 06:00 UTC
scripts/arxiv_harvester.py — queries topics.yaml (7 topics, 20 queries), saves JSON + graphify_source/*.md
   ↓ interval 4h / daily 07:00
scripts/graphify_research.py — pgraphify build graphify_source → graphify-out-research/
   → graph.json 574KB baseline + research nodes → copy to personal-graphify references/spaces/research-graph.json
   → updates bigbang-cli/docs/llm-wiki/research-latest.md
   ↓ daily 08:00 UTC
scripts/research_task_synth.py — reads rolling_index.json, creates [AVA-RESEARCH] tasks via hatch_gws_cli tasks insert
   → bb tasks list --tasklist MDg4... (Lina's Morning) shows new tasks with arxiv_id, hypothesis, experiment steps
   ↓ hourly
scripts/autoresearch_runner.py — picks top untried paper, creates branch autoresearch/<tag>, experiment.md, run.log smoke, logs results.tsv
   → creates follow-up [AVA-EXP-KEEP/CRASH] tasks
   ↓ weekly Sun 10:00
scripts/weekly_summary.py — aggregates results.tsv + harvests into LLM wiki + briefs
```

## Topics (config/topics.yaml)

- ava-jspace: Jacobian, multi-space memory, planner/critic, router
- ava-training: Muon optimizer, WSD schedule, YaRN NTK-aware QK-Norm, single-GPU efficient
- ava-eval: Frontier rubric 11-cat, branch eval cap preservation 0.983
- graphify-rag: GraphRAG, tree-sitter, token reduction, LLM wikis
- bigbang-mcp: MCP, OpenAPI tool use, agentic routing
- vector-mtnn: MTNN, embedding eval
- workforce-ai: Turnover prediction

Each with arxiv_queries + categories + ecosystem mapping

## Cron Jobs (Hatch)

- `arxiv-harvest-daily` — daily@06:00 UTC — harvests arxiv
- `research-graphify-build` — interval@4h — builds graphify knowledge base
- `research-task-synth-daily` — daily@08:00 UTC — creates tasks
- `autoresearch-loop-hourly` — interval@1h — runs one autoresearch iteration (Karpathy loop)
- `research-wiki-weekly` — weekly@Sun-10:00 UTC — deep summary + LLM wiki

All cron bodies are in ~/workspace/cron.d/*/*.md — check with `default.cron list`

## Program.md (research org code)

See `program.md` — adapted from Karpathy: setup, experimentation, output format, logging, LOOP FOREVER, never stop.

Key differences for Ava:
- Multi-repo: ava-agi-factory-v6-4, bigbang-cli, ava-research-engine
- Single file to modify per experiment (train_1b_deepspeed.py OR model_1b.py OR multi_jspace_module.py OR mcp_client.py)
- Metric: val_bpb lower is better (or cap preservation 1.0)
- Simplicity criterion: delete code win > hacky improve
- First run baseline always

## Results

- `results/results.tsv` — append-only log: commit, val_bpb, memory_gb, status, description (like Karpathy)
- `results/harvest_*.json` — daily harvest summary
- `results/tasks_*.json` — daily task synth
- `results/graphify_*.json` — graphify builds
- `results/autoresearch_*.json` — hourly runner
- `experiments/<arxiv_id>/` — experiment.md + run.log + diff
- `graphify_source/*.md` — curated papers for pgraphify

## Usage

```bash
cd ~/workspace/ava-research-engine
# Manual harvest
python3 scripts/arxiv_harvester.py
# Build graphify
python3 scripts/graphify_research.py
# Create tasks
python3 scripts/research_task_synth.py
# Run one autoresearch iteration
python3 scripts/autoresearch_runner.py

# Query knowledge base
cd ~/workspace/bigbang-cli
pgraphify query "Muon optimizer for S1 Fast hl=8" --graph graphify-out-research/graph.json
pgraphify query "GraphRAG code knowledge graph" --graph graphify-out-research/graph.json
pgraphify path "multi_jspace_module.py" "Jacobian" --graph graphify-out-research/graph.json

# Check tasks
bb tasks list --tasklist MDg4NTEzMTkzNjgwNzI5NDMyMDI6MDow --json | jq '.tasks[] | select(.title | contains("AVA-RESEARCH")) | .title'
bb tasks lists
```

## Security + Home-life only

- No secrets — uses arxiv public API + Hatch OAuth for tasks
- FS write only to research/ and graphify_source/ and docs/llm-wiki/
- NO_PROXY sanitized like bigbang-cli (strips [::1] fd8b)
- Footer: Solo personal project, no connection to employer, built with public/free-tier only
- Zero reference to work IP GSD/Phabricator/Workplace/PAJAMA/Ursa Major

## Next steps

- Run first harvest manually to seed graph
- After 7 days, you'll have ~35-70 papers, 5 tasks/day = 35 tasks/week
- Autoresearch loop hourly = 8-12 experiments/day (Karpathy 100 overnight on H100, we do 24/day on free-tier)
- Weekly wiki summarizes progress for Sunni check-in

---
Built 2026-07-15 — v0.4.1 Tasks wired + Graphify 727 nodes
