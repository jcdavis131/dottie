# Personal Graphify Report

Solo personal project, no connection to employer, built with public/free-tier only.

**Nodes:** 5330 · **Edges:** 15528 · **Communities:** 166

Token estimate: ~1500 tokens per scoped query vs ~335900 naive → **223.9× reduction** (mirrors upstream 71.5×).

## God Nodes (highest-degree concepts)

- **func:len** (inferred_ref) — degree 272 — file `` — community 0
- **Ava AGI Factory v6.4** (ml_concept) — degree 224 — file `` — community 1
- **func:str** (inferred_ref) — degree 174 — file `` — community 0
- **OPEN_SOURCE_TOOLCHAIN.md** (doc) — degree 144 — file `C:\Users\jcdav\ava-agi-factory-v6-4\OPEN_SOURCE_TOOLCHAIN.md` — community 5
- **func:range** (inferred_ref) — degree 141 — file `` — community 0
- **test_datagen.py** (file) — degree 116 — file `C:\Users\jcdav\ava-agi-factory-v6-4\tests\test_datagen.py` — community 3
- **func:print** (inferred_ref) — degree 111 — file `` — community 0
- **func:Path** (inferred_ref) — degree 105 — file `` — community 0
- **func:int** (inferred_ref) — degree 105 — file `` — community 0
- **Ava J-Space Multi** (ml_concept) — degree 103 — file `` — community 1
- **func:exists** (inferred_ref) — degree 99 — file `` — community 0
- **Ava Critic hl30** (ml_concept) — degree 98 — file `` — community 1
- **LOCAL_MAX_SETUP.md** (doc) — degree 94 — file `C:\Users\jcdav\ava-agi-factory-v6-4\docs\LOCAL_MAX_SETUP.md` — community 6
- **func:isinstance** (inferred_ref) — degree 94 — file `` — community 0
- **pathlib** (module) — degree 91 — file `` — community 1

## Communities

- **Community 0** — 1319 nodes — types [('inferred_ref', 676), ('function', 639), ('file', 4)] — sample: sanitize_path, sanitize_id, sanitize_label, main, god_nodes
- **Community 1** — 1262 nodes — types [('symbol', 255), ('function', 242), ('file', 197), ('module', 161), ('concept', 136)] — sample: .gitattributes, Personal Graphify, Ollama qwen3:32b local, .gitignore, .graphifyignore
- **Community 2** — 404 nodes — types [('inferred_ref', 216), ('function', 176), ('symbol', 8), ('file', 2), ('class', 2)] — sample: enrich_graph, get_ollama_embeddings, _check_sdk, _check_sdk, edit_workspace
- **Community 3** — 315 nodes — types [('function', 152), ('inferred_ref', 116), ('symbol', 25), ('class', 13), ('module', 6)] — sample: itertools, gen_jsonl_example, __init__, __init__, batches
- **Community 4** — 290 nodes — types [('function', 151), ('inferred_ref', 130), ('symbol', 7), ('module', 1), ('file', 1)] — sample: __init__, ava_data_gen_flow, monitor_metrics, ava_train_flow, generate_teacher_rollouts
- **Community 5** — 138 nodes — types [('concept', 137), ('doc', 1)] — sample: OPEN_SOURCE_TOOLCHAIN.md, Awesome Open Source AI - Struc, Overview of 14 Categories, PRIORITY FOCUS - Detailed Extr, Data Processing  (Data Process
- **Community 6** — 89 nodes — types [('concept', 88), ('doc', 1)] — sample: LOCAL_MAX_SETUP.md, Ava AGI Factory v6.4 — LOCAL M, 1. Prereqs, Hardware check, expect driver >= 555.xx, 12GB+
- **Community 7** — 61 nodes — types [('symbol', 29), ('inferred_ref', 17), ('module', 10), ('function', 4), ('file', 1)] — sample: cli.py, stat, detect, collect_files, group_by_type
- **Community 8** — 60 nodes — types [('symbol', 22), ('module', 13), ('function', 10), ('class', 7), ('inferred_ref', 5)] — sample: fastapi, FastAPI, fastapi.responses, JSONResponse, uvicorn
- **Community 9** — 48 nodes — types [('concept', 40), ('reference', 5), ('doc', 3)] — sample: ORCHESTRATION.md, ORCHESTRATION — Foreman / Sub-, Roles, Dispatch loop, Standing rules for every worke
- **Community 10** — 47 nodes — types [('concept', 46), ('doc', 1)] — sample: LOCAL_PICKUP.md, LOCAL PICKUP — Alienware RTX 4, Prerequisites (Alienware), Clone + First Check, quick e2e mock — no GPU, no to
- **Community 11** — 44 nodes — types [('concept', 43), ('doc', 1)] — sample: README.md, Scout CLI 🐾 — One CLI to Rule , What's New in v0.6.0 — Scout r, v0.6.0 Flow (end-to-end), Cloud → Local offload (Hatch)
- **Community 12** — 37 nodes — types [('concept', 36), ('doc', 1)] — sample: graphify-integration.md, Graphify Integration — LLM Wik, What is Personal Graphify?, Install & Outputs (for referen, outputs:
- **Community 13** — 36 nodes — types [('inferred_ref', 24), ('function', 12)] — sample: handle_tool_call, run_http, http_cost, list_mcp_tools_sync, call_mcp_tool_sync
- **Community 14** — 35 nodes — types [('concept', 34), ('doc', 1)] — sample: INSTALL_GUIDE.md, Private GitHub Repo Setup + Cu, 1. Create Private GitHub Repo, Option A — with gh CLI (recomm, Creates private repo github.co

## Surprising Connections (cross-community, cross-file)

- `cli.py` [imports] → `argparse` — [EXTRACTED] — files differ? True — communities (7, 1)
- `cli.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (7, 1)
- `cli.py` [imports] → `json` — [EXTRACTED] — files differ? True — communities (7, 1)
- `serve.py` [imports] → `load_graph_json` — [EXTRACTED] — files differ? True — communities (1, 7)
- `serve.py` [imports] → `search_nodes` — [EXTRACTED] — files differ? True — communities (1, 7)
- `serve.py` [imports] → `format_query_answer` — [EXTRACTED] — files differ? True — communities (1, 7)
- `serve.py` [imports] → `format_path_answer` — [EXTRACTED] — files differ? True — communities (1, 7)
- `serve.py` [imports] → `explain_node` — [EXTRACTED] — files differ? True — communities (1, 7)
- `serve.py` [imports] → `impact_analysis` — [EXTRACTED] — files differ? True — communities (1, 7)
- `serve.py` [imports] → `task_compiler` — [EXTRACTED] — files differ? True — communities (1, 7)
- `serve.py` [imports] → `onboard_report` — [EXTRACTED] — files differ? True — communities (1, 7)
- `serve.py` [imports] → `format_onboard_answer` — [EXTRACTED] — files differ? True — communities (1, 7)

## Suggested Questions (ask via `pgraphify query`)

- `pgraphify query "what connects auth to database?"`
- `pgraphify query "where is turnover retention logic?"`
- `pgraphify query "how does Ava J-space Planner interact with Critic?"`
- `pgraphify query "how does Scout connect to Ava?"`
- `pgraphify query "trace Stripe webhook to Paid Users MRR"`
- `pgraphify query "show MTNN heads 48→64→k"`

## Rationale & Why

- `NOTE: , # WHY, # HACK, # TODO, # FIXME, # BUG` @ C:\Users\jcdav\personal-graphify\src\personal_graphify\extract.py:109 — explains nearby code
- `NOTE: / # WHY comments found. Consider adding them — they become first-class graph nodes linked to code.")` @ C:\Users\jcdav\personal-graphify\src\personal_graphify\report.py:52 — explains nearby code
- `OPTIMIZE: r: AdamW or 8-bit via bitsandbytes` @ C:\Users\jcdav\ava-agi-factory-v6-4\on_policy_distill.py:481 — explains nearby code
- `NOTE: newer API uses rules not recipe, so we don't pass recipe` @ C:\Users\jcdav\ava-agi-factory-v6-4\streaming_data.py:214 — explains nearby code
- `NOTE: on ordering: specific, high-confidence secret shapes (sk-..., AKIA...)` @ C:\Users\jcdav\ava-agi-factory-v6-4\ava\pipeline\clean.py:221 — explains nearby code

## Personal Ecosystem Overlay

- **Family Brain**: Joint accounts, Betterment buckets, Plaid 5 institutions, Emergency $136.5k
- **Passive Lab**: Turnover Shield $79-$149/mo, 7-13 customers → $1k MRR, Stripe → Supabase → Workers free-tier
- **Ava AGI**: multi_jspace_module.py 4 workspaces S1 hl=8 S2 hl=300 Critic hl=30 Planner hl=150, Router/veto
- **Vector Hoops**: 12,966 player-seasons, MTNN v5_concat_b2_h160_t32_d48_mlp128, CQS 85.87, leakfree 0.7937 composite

> Use `pgraphify path "A" "B"` to trace any two concepts.
