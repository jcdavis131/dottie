# Personal Graphify Report

Solo personal project, no connection to employer, built with public/free-tier only.

**Nodes:** 784 · **Edges:** 2014 · **Communities:** 23

Token estimate: ~1018 tokens per scoped query vs ~83978 naive → **82.5× reduction** (measured: sum of indexed file bytes / 4).

## God Nodes (highest-degree concepts)

- **cli.py** (file) — degree 70 — file `/home/user/personal-graphify/src/personal_graphify/cli.py` — community 3
- **extract.py** (file) — degree 69 — file `/home/user/personal-graphify/src/personal_graphify/extract.py` — community 0
- **query.py** (file) — degree 58 — file `/home/user/personal-graphify/src/personal_graphify/query.py` — community 1
- **INSTALL_GUIDE.md** (doc) — degree 51 — file `/home/user/personal-graphify/INSTALL_GUIDE.md` — community 4
- **serve.py** (file) — degree 48 — file `/home/user/personal-graphify/src/personal_graphify/serve.py` — community 1
- **Personal Graphify** (tool) — degree 41 — file `` — community 1
- **graphify-public-non-pii.json** (file) — degree 38 — file `/home/user/personal-graphify/docs/public/graphify-public-non-pii.json` — community 1
- **func:len** (inferred_ref) — degree 38 — file `` — community 0
- **func:str** (inferred_ref) — degree 36 — file `` — community 0
- **README.md** (doc) — degree 34 — file `/home/user/personal-graphify/README.md` — community 11
- **AGENTIC_GUIDE.md** (doc) — degree 33 — file `/home/user/personal-graphify/AGENTIC_GUIDE.md` — community 8
- **PROJECT_MAP.md** (doc) — degree 33 — file `/home/user/personal-graphify/references/ecosystem/PROJECT_MAP.md` — community 1
- **lighten_public_graph.py** (file) — degree 32 — file `/home/user/personal-graphify/scripts/lighten_public_graph.py` — community 1
- **SPEC.md** (doc) — degree 31 — file `/home/user/personal-graphify/SPEC.md` — community 7
- **Ava AGI Factory v6.4** (ml_concept) — degree 29 — file `` — community 1

## Communities

- **Community 0** — 219 nodes — types [('inferred_ref', 124), ('function', 78), ('module', 7), ('symbol', 3), ('class', 3)] — sample: _resolve_build_roots, cmd_build, cmd_query, cmd_path, cmd_explain
- **Community 1** — 174 nodes — types [('function', 25), ('module', 24), ('symbol', 21), ('file', 19), ('concept', 18)] — sample: Stripe, Plaid, First $1k/mo passive goal, Turnover Shield, Retention Playbook
- **Community 2** — 90 nodes — types [('inferred_ref', 59), ('function', 24), ('symbol', 2), ('class', 2), ('module', 1)] — sample: god_nodes, surprise_edges, naive_token_estimate, token_stats, _cosine
- **Community 3** — 41 nodes — types [('symbol', 29), ('module', 11), ('file', 1)] — sample: cli.py, stat, detect, collect_files, group_by_type
- **Community 4** — 35 nodes — types [('concept', 34), ('doc', 1)] — sample: INSTALL_GUIDE.md, Private GitHub Repo Setup + Cu, 1. Create Private GitHub Repo, Option A — with gh CLI (recomm, Creates private repo github.co
- **Community 5** — 28 nodes — types [('inferred_ref', 25), ('function', 3)] — sample: main, get_ollama_embeddings, main, func:ArgumentParser, func:add_subparsers
- **Community 6** — 22 nodes — types [('concept', 16), ('doc', 2), ('reference', 2), ('product', 2)] — sample: vector-gridiron-README.md, Vector Gridiron, The layers, 1. Data — `pipeline/nfl_data.p, 2. The MTNN — `pipeline/train_
- **Community 7** — 19 nodes — types [('concept', 18), ('doc', 1)] — sample: SPEC.md, SPEC — jcamd.com sync + Person, Objective, Assumptions (correct me now), Non-goals
- **Community 8** — 18 nodes — types [('concept', 16), ('doc', 1), ('reference', 1)] — sample: AGENTIC_GUIDE.md, Agentic Guide — Coding Smarter, Why this beats plain Cursor, Architecture (from Graphify do, Personal Overlay — How we mapp
- **Community 10** — 17 nodes — types [('function', 5), ('inferred_ref', 4), ('symbol', 3), ('class', 3), ('file', 1)] — sample: collect_files, test_detect.py, personal_graphify.detect, collect_files, group_by_type
- **Community 9** — 17 nodes — types [('function', 8), ('symbol', 3), ('module', 2), ('class', 2), ('file', 1)] — sample: run_stdio, test_serve.py, pytest, personal_graphify.serve, handle_stdio_line
- **Community 11** — 16 nodes — types [('concept', 14), ('doc', 1), ('reference', 1)] — sample: README.md, Personal Graphify — Knowledge , Install (30 seconds), isolated install (recommended), or pip install -e .
- **Community 12** — 16 nodes — types [('symbol', 7), ('module', 4), ('file', 1), ('class', 1), ('function', 1)] — sample: test_query_cost.py, personal_graphify.build, build_graph, enrich_graph, personal_graphify.export
- **Community 13** — 15 nodes — types [('concept', 14), ('doc', 1)] — sample: SKILL.md, Graphify Workflow, When to use, Prerequisites, once
- **Community 14** — 12 nodes — types [('concept', 11), ('doc', 1)] — sample: plan.md, Plan — jcamd.com + Personal Gr, Slice notes, 1. Tooling, 2. jcamd sync

## Surprising Connections (cross-community, cross-file)

- `extract.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (0, 1)
- `extract.py` [imports] → `json` — [EXTRACTED] — files differ? True — communities (0, 1)
- `serve.py` [imports] → `Any` — [EXTRACTED] — files differ? True — communities (1, 0)
- `serve.py` [imports] → `load_graph_json` — [EXTRACTED] — files differ? True — communities (1, 3)
- `serve.py` [imports] → `search_nodes` — [EXTRACTED] — files differ? True — communities (1, 3)
- `serve.py` [imports] → `format_query_answer` — [EXTRACTED] — files differ? True — communities (1, 3)
- `serve.py` [imports] → `format_path_answer` — [EXTRACTED] — files differ? True — communities (1, 3)
- `serve.py` [imports] → `explain_node` — [EXTRACTED] — files differ? True — communities (1, 3)
- `serve.py` [imports] → `impact_analysis` — [EXTRACTED] — files differ? True — communities (1, 3)
- `serve.py` [imports] → `task_compiler` — [EXTRACTED] — files differ? True — communities (1, 3)
- `serve.py` [imports] → `onboard_report` — [EXTRACTED] — files differ? True — communities (1, 3)
- `serve.py` [imports] → `format_onboard_answer` — [EXTRACTED] — files differ? True — communities (1, 3)

## Suggested Questions (ask via `pgraphify query`)

- `pgraphify query "what connects auth to database?"`
- `pgraphify query "where is turnover retention logic?"`
- `pgraphify query "how does Ava J-space Planner interact with Critic?"`
- `pgraphify query "how does Scout connect to Ava?"`
- `pgraphify query "trace Stripe webhook to Paid Users MRR"`
- `pgraphify query "show MTNN heads 48→64→k"`

## Rationale & Why

- `NOTE: , # WHY, # HACK, # TODO, # FIXME, # BUG` @ /home/user/personal-graphify/src/personal_graphify/extract.py:109 — explains nearby code
- `NOTE: / # WHY comments found. Consider adding them — they become first-class graph nodes linked to code.")` @ /home/user/personal-graphify/src/personal_graphify/report.py:52 — explains nearby code
- `NOTE: no URL-fetching code path exists in this tool, so there is deliberately no` @ /home/user/personal-graphify/src/personal_graphify/security.py:8 — explains nearby code
- `NOTE: stripe webhook feeds mrr\n"` @ /home/user/personal-graphify/tests/test_query_cost.py:15 — explains nearby code
- `NOTE: s\nSee [alpha](alpha.py).\n", encoding="utf-8")` @ /home/user/personal-graphify/tests/test_incremental.py:16 — explains nearby code

## Personal Ecosystem Overlay

- **Family Brain**: Joint accounts, Betterment buckets, Plaid 5 institutions, Emergency $136.5k
- **Passive Lab**: Turnover Shield $79-$149/mo, 7-13 customers → $1k MRR, Stripe → Supabase → Workers free-tier
- **Ava AGI**: multi_jspace_module.py 4 workspaces S1 hl=8 S2 hl=300 Critic hl=30 Planner hl=150, Router/veto
- **Vector Hoops**: 12,966 player-seasons, MTNN v5_concat_b2_h160_t32_d48_mlp128, CQS 85.87, leakfree 0.7937 composite

> Use `pgraphify path "A" "B"` to trace any two concepts.
