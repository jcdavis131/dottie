# Tasks Plugin — LLM Wiki (Wired v0.4.1)

**Solo personal project, no connection to employer, built with public/free-tier only**

## Why Tasks Matters
Google Tasks is now first-class citizen of BigBang control plane. It turns ephemeral `bb agent run` plans into durable todos, and Google Tasks into agent-triggerable actions.

Real wiring via `hatch_gws_cli tasks` — managed OAuth (no secret in repo), connection status `connected`, 2 existing lists: Lina's Morning (`MDg4NTEzMTkzNjgwNzI5NDMyMDI6MDow`) and Lina's Afternoon (`SURwZDNOTXZRLXpUVkd1ZA`).

## Implementation File
`bigbang/plugins/tasks/cli.py` (340 lines) + `manifest.yaml` v0.4.0

### Core Function
```python
def _run_gws(args, json_input=None):
  cmd = ["hatch_gws_cli", "tasks"] + args
  if json_input: cmd += ["--json", json.dumps(json_input)]
  subprocess.run(cmd, capture_output=True, text=True, timeout=30) -> json.loads stdout
```

All commands go through this — no direct network, so `capabilities.network.enabled=false`.

### Commands Detail
| Command | Args | What it does | Example |
|---------|------|--------------|---------|
| `status` | — | `hatch_gws_cli tasks status` + count lists via `tasklists list` | `bb tasks status` -> connected, 2 lists |
| `lists` | — | `tasklists list --params {"maxResults":50}` | lists Lina's Morning/Afternoon |
| `list` | `--tasklist @default\|<id> --show-completed --max 50 --due-min/--due-max RFC3339` | `tasks list --params {...}` | `bb tasks list --tasklist @default` |
| `get` | `<task_id> --tasklist` | `tasks get --params {"tasklist":..., "task":...}` | |
| `add` | `<title> --notes --due RFC3339 --tasklist` | `tasks insert --params {"tasklist":...} --json {"title":...}` | `bb tasks add "Ship turnover fix" --notes "bb tools generate"` |
| `update` | `<task_id> --title/--notes/--due --tasklist` | `tasks patch --params ... --json {fields}` | |
| `complete` | `<task_id> --tasklist` | patch `{"status":"completed"}` | |
| `uncomplete` | `<task_id>` | patch `{"status":"needsAction"}` | |
| `delete` | `<task_id> --force` | delete with confirm | |
| `create-list` | `<title>` | `tasklists insert --json {"title":...}` | |
| `sync-bb` | `--tasklist` `--from-audit` | reads `audit.py tail_events(20)` + creates 3 starter tasks: "Wire Google Tasks into BigBang", "Generate LLM-wiki for BigBang CLI v0.4", "Run graphify build" | `bb tasks sync-bb --tasklist @default` |
| `export` | `--tasklist` | exports `tasks list maxResults 100` to `docs/llm-wiki/tasks-<id>.json` for graphify ingestion | |

### Security & Policy
- Manifest: `network.enabled=false`, `filesystem.write=true` only to `docs/llm-wiki/` and `~/.local/share/bigbang/`
- No `secrets.allow` — auth via Hatch wrapper `status/disconnect_url` (managed)
- `http_utils.sanitize_no_proxy_env()` called on import to avoid `[::1]` bug breaking underlying `httpx` if future versions switch from subprocess to direct API.
- Audit: every emit goes to `audit.jsonl`, which `sync-bb` can turn into tasks.

### Ava & Agent Routing
- `ava/cli.py _heuristic_route`: if `task` or `todo` or `lina` in query → `picked_tool=tasks`, `picked_command=bb tasks list` confidence 0.92
- `agent/cli.py builtin_hints`: `task→bb tasks list`, `todo→bb tasks list`, `lina→bb tasks lists`
- So `bb agent run "list my Lina morning tasks"` → plan includes `bb tasks lists` → `bb tasks list`

### Graphify Save
- `export` creates `docs/llm-wiki/tasks-@default.json` or `tasks-<id>.json` — graphify sees JSON as node with edges to `tasks/cli.py` and `ava/cli.py`
- `pgraphify build bigbang-cli` will include these exports automatically (respects `.gitignore`? We write to docs/llm-wiki which is tracked)
- Query: `pgraphify query "tasks sync"` returns subgraph: tasks/cli.py → _run_gws → hatch_gws_cli → audit.py tail_events + docs/llm-wiki

### Examples (Real CLI)
```bash
# Check connection
bb tasks status --json | jq .connection.status  # connected

# List lists
bb tasks lists --json | jq .tasklists[].title  # Lina's Morning, Lina's Afternoon

# List tasks in default
bb tasks list --json

# Add task linked to BigBang work
bb tasks add "Generate LLM wikis" --notes "index.md + tasks-plugin.md + graphify integration" --tasklist @default

# Complete
bb tasks complete <id> --tasklist @default

# Sync recent bb audit as tasks
bb tasks sync-bb --tasklist @default

# Export for graphify
bb tasks export --tasklist @default
cat docs/llm-wiki/tasks-@default.json | jq .count
```

### Edge Cases & Fixes Applied
- Initial `bb tasks status` timed out due to double gws call in status (status + lists) — fixed to cache or separate calls with 15s timeout each, now 0.8s + 1.5s.
- `Expecting value: line 1 col 1` when `--json` emitted empty → ensured _run_gws always returns dict with ok flag.
- NO_PROXY `[::1]` bug: `sanitize_no_proxy_env()` strips brackets, prevents `httpx Invalid port ':1]'` in Hatch.

### Future Wiring (v0.5 ideas)
- `bb tasks` as MCP tool: expose `bb_tasks_list`, `bb_tasks_add`, `bb_tasks_complete` via `bb mcp serve --port 8787` S