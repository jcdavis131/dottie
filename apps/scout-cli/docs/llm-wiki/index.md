# BigBang CLI — LLM Wiki Index (v0.4.1 + tasks wiring)

**Solo personal project, no connection to employer, built with public/free-tier only**

> Token-efficient brain dump for LLMs + humans. Built for `bb` v0.4.1 with Google Tasks wired as `bb tasks`.

## What BigBang CLI Is
- **One CLI to rule all internet tools** — OpenAPI, MCP, CLI, Python, Google Tasks, via 17 plugins (see plugins.md for the auto-generated catalog).
- **Security-first**: vault 0600 `~/.local/share/bigbang/secrets.json`, keyring + `BB_SECRET_` env, `policy.py enforce_or_raise` before any network, default deny `network.domains`, `fs.write`, `secrets.allow`, audit `audit.jsonl`.
- **Agent-native**: every command `emit(dict, command="...")` → valid JSON when `--json`, rich otherwise, audited.
- **Ava-brained**: `core/llm.py` resilient Ollama router `localhost:11434` + `host.docker.internal:11434`, preferred `qwen3:32b`, heuristic fallback.
- **Proxy-hardened**: `core/http_utils.py sanitize_no_proxy_env()` strips `[::1]` and `fd8b::` IPv6 brackets that break `httpx` `Invalid port: ':1]'` in Hatch egress proxy (`hatch-egress-proxy:3128`).

## Plugin Map (17 plugins — auto-catalog in plugins.md)
| Plugin | Purpose | Key Commands | Capabilities |
|--------|---------|--------------|--------------|
| `tasks` ✅ NEW | Google Tasks via `hatch_gws_cli` | `status`, `lists`, `list`, `get`, `add`, `update`, `complete`, `delete`, `create-list`, `sync-bb`, `export` | network false, fs write llm-wiki/, secrets none (Hatch-managed OAuth) |
| `tools` | Universal OpenAPI registry | `list`, `add`, `get`, `rm`, `search`, `call`, `import-openapi`, `generate` | network true (per-domain netloc), fs false |
| `mcp` | MCP client + serve bb as MCP | `manifest`, `serve`, `add`, `list`, `list-tools`, `call` | `mcp>=1.28.1` sse_client + streamablehttp fallback |
| `ava` | Ava AGI Factory brain | `status`, `train`, `eval`, `route` | router: Ollama qwen3:32b → heuristic |
| `agent` | Ava-native planner | `run`, `bus`, `teach` | `_ollama_plan()` + heuristic |
| `system` | doctor/audit/policy/scaffold | `doctor`, `audit`, `policy`, `scaffold` |  |
| `secrets` | vault | `set`, `get`, `list`, `rm` | vault 0600 |
| `auth` | OAuth device flow | `login`, `status` |  |
| `family`, `vector`, `tennis` | domain plugins | per-domain |  |

## Quick Wiring Diagram
```
User/Agent --bb tasks add--> hatch_gws_cli --OAuth--> Google Tasks API (Lina's Morning/Afternoon)
          --bb agent run "my todos"--> ava heuristic (tasks keyword 0.92) --> plan: ["bb tasks list"]
          --bb ava route "todo"--> {tool: tasks, command: bb tasks list, confidence 0.92}
          --bb tasks sync-bb--> audit.jsonl -> creates Google Tasks from recent bb actions (Turnover Shield, wiki, graphify)
          --bb tasks export--> docs/llm-wiki/tasks-*.json for graphify ingestion
All emit() -> audit.jsonl -> pgraphify build -> graph.json (2k tokens vs 123k naive)
```

## File Pointers (for graphify query)
- Core: `bigbang/core/{http_utils.py, llm.py, mcp_client.py, openapi.py, policy.py, security.py, registry.py, output.py, audit.py, plugin_loader.py}`
- Plugins: `bigbang/plugins/{tasks,tools,mcp,ava,agent,system,secrets,auth,family,vector,tennis}/cli.py + manifest.yaml`
- Graphify: `~/workspace/your_files/personal-graphify/` CLI `pgraphify`, outputs `graphify-out/{graph.json, graph.html, GRAPH_REPORT.md, cost.json}`
- LLM-wiki output: `docs/llm-wiki/{index.md, tasks-plugin.md, architecture.md, security-model.md, graphify-integration.md, plugins.md, quickstart.md, research-mai-thinking-1.md}`
- Tasks source: 2 lists `MDg4NTEzMTkzNjgwNzI5NDMyMDI6MDow` = Lina's Morning, `SURwZDNOTXZRLXpUVkd1ZA` = Lina's Afternoon (connected via Hatch GWS wrapper)

## How to Use This Wiki in Code
```bash
bb tasks status --json
bb tasks lists --json
bb tasks list --tasklist @default --json
bb tasks add "Wire Turnover Shield revenue to tasks" --notes "bb tasks sync-bb" --json
bb agent run "list my Lina morning tasks" --json  # -> routes to tasks
bb ava route "my todos" --json  # -> picked_tool tasks
pgraphify build . --out graphify-out
pgraphify query "how does bb tasks sync-bb work?"
```

## Token Savings (graphify pattern)
- Before: read 12 CLI files ~123k tokens
- After: `pgraphify query "tasks integration"` ~1.7k tokens, 71.5x reduction upstream benchmark
- This index ~1.2k tokens

## Next Steps v0.5
- `bb tasks` <-> `bb family brain` bidirectional sync
- `bb mcp serve` real SSE exposing `bb_tasks_*` as MCP tools for Claude Desktop
- Vector Hoops/Pitch/Gridiron auto-create tasks on MTNN drift
- Docker/pipx isolation for generated OpenAPI plugins

# Solo personal project, no connection to employer, built with public/free-tier only
