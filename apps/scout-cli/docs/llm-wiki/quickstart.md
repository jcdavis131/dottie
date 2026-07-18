# BigBang CLI Quickstart — LLM Wiki

**Solo personal project, no connection to employer, built with public/free-tier only**

## Install & Doctor
```bash
git clone ~/workspace/bigbang-cli
cd bigbang-cli
# dottie monorepo location: <dottie>/apps/scout-cli (e.g. ~/workspace/dottie/apps/scout-cli)
pip3 install -e .
bb --help  # 17 plugins discovered automatically
bb system doctor
bb system policy
```

## Google Tasks Wiring (new v0.4.1)
```bash
bb tasks status --json  # connected? 2 lists: Lina's Morning/Afternoon
bb tasks lists --json | jq .tasklists[].title
bb tasks list --tasklist @default --json
bb tasks add "Ship Turnover Shield $79/mo" --notes "bb tools generate + Stripe webhook" --json
bb tasks complete <task_id> --tasklist @default
bb tasks sync-bb --tasklist @default  # audit.jsonl -> Google Tasks
bb tasks export --tasklist @default  # -> docs/llm-wiki/tasks-@default.json
```

## Universal Tool Registry
```bash
bb tools list
bb tools add petstore --type openapi --url https://petstore.swagger.io/v2/swagger.json
bb tools generate petstore  # -> bb petstore --help with 20 ops
bb petstore findPetsByStatus --status available --json | jq .data[0].name
bb tools call petstore findPetsByStatus '{"status":"available"}' --json
```

## MCP
```bash
bb mcp manifest --json  # 17 bb_* tools
bb mcp add myserver https://mcp.example.com/sse
bb mcp list-tools myserver --json
bb mcp call myserver some_tool --args '{"q":"test"}' --json
# Serve bb as a real MCP server (stdio default; --sse --port 8787 for SSE):
# bb mcp serve
# Claude Desktop config (stdio): {"mcpServers": {"scout": {"command": "scout", "args": ["mcp", "serve"]}}}
```

## Ava & Agent
```bash
bb ava status --json  # Ollama detection localhost:11434 + host.docker.internal:11434
bb ava route "list my Lina morning tasks" --json  # -> tasks 0.92
bb ava route "summarize petstore pets" --json
bb agent run "list my todos and export them" --json  # plan: [bb tasks list, bb tasks export]
bb agent run "ship Turnover Shield fix" --json
```

## Graphify (Knowledge Graph for LLMs)
```bash
pip install -e ~/workspace/your_files/personal-graphify  # provides pgraphify
# dottie monorepo: pip install -e <dottie>/packages/personal-graphify
cd ~/workspace/bigbang-cli   # dottie monorepo: cd <dottie>/apps/scout-cli
pgraphify build . --out graphify-out
ls graphify-out/  # graph.json, graph.html, GRAPH_REPORT.md, cost.json
pgraphify query "how does bb tasks sync-bb work?"
pgraphify query "what connects ava router to tasks?"
pgraphify path "tasks/cli.py" "audit.py"
pgraphify explain "_run_gws"
# Token savings: ~71.5x (graph.json ~2k tokens vs 123k naive)
```

## LLM Wiki Docs Built
Located in docs/llm-wiki/:
- index.md (entry)
- architecture.md (v0.4.1 flow)
- tasks-plugin.md (wiring details)
- security-model.md (caps, vault, proxy fix)
- graphify-integration.md (build/query/save to personal graphify)
- plugins.md (auto-generated catalog of 17 plugins)
- quickstart.md (this file)
- tasks-*.json (exported Google Tasks for ingestion)

# Solo personal project, no connection to employer, built with public/free-tier only