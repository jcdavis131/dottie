# Plugins Catalog — LLM Wiki

**Solo personal project, no connection to employer, built with public/free-tier only**

Total plugins: 17

| Plugin | Version | Commands | Capabilities | Description |
|--------|---------|----------|--------------|-------------|
| agent | 0.4.0 | run, bus, teach | net:True localhost,127.0.0.1 | Ava-native planner that routes to any tool |
| auth | 0.4.0 | login, set-token, list-auth, get-token-cmd, status-cmd +1 | net:True github.com,api.github.com | Unified auth for all internet services — OAuth device flow + |
| ava | 0.4.0 | status, train, eval-cmd, route | net:True huggingface.co,localhost | Ava AGI Factory — local CUDA brain for BigBang routing + eva |
| brain | 0.5.0 | memory-cmd, goals-cmd, goal-detail, sync-cmd, daily-cmd | net:False  | Hatch brain — goals, MEMORY.md, daily notes, projects. Bridg |
| family | 0.4.0 | brain, bills, list-items | net:False  | Family Brain generic tools |
| graphify | 0.6.1 | status-cmd, status, query-cmd, path-cmd, explain-cmd +6 | net:False  | Personal Graphify (pgraphify) — query-first knowledge graph  |
| lab | 0.5.0 | ideas-cmd, shield-cmd, mrr-cmd, log-cmd, pitch-cmd | net:False  | Passive Lab — boring B2B SaaS ideas, Turnover Shield MVP, MR |
| mcp | 0.4.0 | manifest, serve, add-server, list-servers, list +1 | net:True localhost,127.0.0.1 | MCP client + server — consume any MCP, serve bb as MCP |
| rft | 1.0.0 | export, stats, schema | net:False  | RFT workflow-trace ETL — audit.jsonl episodes -> redacted, r |
| rtx | 0.5.0 | status, queue-cmd, results, programs, releases-cmd +2 | net:False  | Alienware RTX 4080/4090 offload — queue tasks to local autor |
| secrets | 0.4.0 | set-cmd, get-cmd, list-cmd, list | net:False  | Vault for API keys, tokens — security first |
| system | 0.4.0 | doctor, policy-cmd, scaffold-plugin, hello | net:True localhost | System health, audit, policy, scaffold |
| tasks | 0.4.0 | status-cmd, lists-cmd, list-tasks, get-task, add-task +7 | net:False  | Google Tasks — task lists + tasks CRUD wired into BigBang vi |
| tennis | 0.4.0 | serve | net:True huggingface.co | Tennis DINOv3 serve coach |
| tools | 0.4.0 | list-cmd, add-cmd, get-cmd, get, rm +3 | net:True * | Universal registry — turn any internet API into bb command |
| vector | 0.4.0 | list-sites, list, verify | net:True hoops.dumbmodel.com,pitch.dumbmodel.com | Vector MTNNs — hoops/pitch/gridiron control |
| write | 0.5.0 | scan-cmd, humanize-cmd, generate-cmd, sources-cmd, check-cmd +2 | net:True localhost,127.0.0.1 | Authentic-feeling content generators that auto-scan for AI s |

## Per-Plugin Details

### agent (0.4.0)
- **Path**: `bigbang/plugins/agent/cli.py`
- **Description**: Ava-native planner that routes to any tool
- **Commands**: `run`, `bus`, `teach`
- **Capabilities**: ```json
{
  "network": {
    "enabled": true,
    "domains": [
      "localhost",
      "127.0.0.1",
      "host.docker.internal"
    ]
  },
  "filesystem": {
    "write": false
  },
  "secrets": {
    "allow": []
  }
}
```
- **Tags**: []

### auth (0.4.0)
- **Path**: `bigbang/plugins/auth/cli.py`
- **Description**: Unified auth for all internet services — OAuth device flow + PAT + vault
- **Commands**: `login`, `set-token`, `list-auth`, `get-token-cmd`, `status-cmd`, `logout`
- **Capabilities**: ```json
{
  "network": {
    "enabled": true,
    "domains": [
      "github.com",
      "api.github.com",
      "oauth.github.com",
      "oauth2.googleapis.com",
      "accounts.google.com",
      "www.googleapis.com",
      "api.notion.com",
      "www.notion.com",
      "notion.com",
      "api.linear.app",
      "linear.app",
      "api.openai.com",
      "login.microsoftonline.com",
      "graph.microsoft.com"
    ]
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/.local/share/bigbang/auth.json",
      "~/.local/share/bigbang/secrets.json"
    ]
  }
}
```
- **Tags**: []

### ava (0.4.0)
- **Path**: `bigbang/plugins/ava/cli.py`
- **Description**: Ava AGI Factory — local CUDA brain for BigBang routing + eval
- **Commands**: `status`, `train`, `eval-cmd`, `route`
- **Capabilities**: ```json
{
  "network": {
    "enabled": true,
    "domains": [
      "huggingface.co",
      "localhost",
      "host.docker.internal"
    ]
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/workspace/ava-agi-factory-v6-4/",
      "~/.cache/huggingface/"
    ]
  },
  "secrets": {
    "allow": [
      "HF_TOKEN"
    ]
  }
}
```
- **Tags**: []

### brain (0.5.0)
- **Path**: `bigbang/plugins/brain/cli.py`
- **Description**: Hatch brain — goals, MEMORY.md, daily notes, projects. Bridge for Ava co-dev. Token-efficient.
- **Commands**: `memory-cmd`, `goals-cmd`, `goal-detail`, `sync-cmd`, `daily-cmd`
- **Capabilities**: ```json
{
  "network": {
    "enabled": false
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/MEMORY.md",
      "~/memory/",
      "~/workspace/projects/",
      "~/workspace/your_files/"
    ]
  },
  "secrets": {
    "allow": []
  }
}
```
- **Tags**: ['memory', 'goals', 'ava']

### family (0.4.0)
- **Path**: `bigbang/plugins/family/cli.py`
- **Description**: Family Brain generic tools
- **Commands**: `brain`, `bills`, `list-items`
- **Capabilities**: ```json
{
  "network": {
    "enabled": false
  },
  "filesystem": {
    "write": false
  }
}
```
- **Tags**: []

### graphify (0.6.1)
- **Path**: `bigbang/plugins/graphify/cli.py`
- **Description**: Personal Graphify (pgraphify) — query-first knowledge graph for Scout/Ava/Vector/Lab. build/query/path/explain/impact/task/onboard/cost + ecosystem multi-root sync.
- **Commands**: `status-cmd`, `status`, `query-cmd`, `path-cmd`, `explain-cmd`, `impact-cmd`, `task-cmd`, `onboard-cmd`, `cost-cmd`, `sync-cmd`, `ecosystem-cmd`
- **Capabilities**: ```json
{
  "network": {
    "enabled": false
  },
  "filesystem": {
    "write": true,
    "paths": [
      "./graphify-out/",
      "~/personal-graphify/",
      "~/scout-cli/",
      "~/ava-agi-factory-v6-4/"
    ]
  },
  "secrets": {
    "allow": []
  }
}
```
- **Tags**: ['graphify', 'pgraphify', 'ava', 'scout', 'knowledge-graph']

### lab (0.5.0)
- **Path**: `bigbang/plugins/lab/cli.py`
- **Description**: Passive Lab — boring B2B SaaS ideas, Turnover Shield MVP, MRR tracking for First $1k/mo goal. Ava co-dev ready.
- **Commands**: `ideas-cmd`, `shield-cmd`, `mrr-cmd`, `log-cmd`, `pitch-cmd`
- **Capabilities**: ```json
{
  "network": {
    "enabled": false
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/workspace/projects/first-1k-mo-passive/",
      "~/workspace/projects/build-a-self-sustaining-web-app-for-passive-income/",
      "~/workspace/your_files/"
    ]
  },
  "secrets": {
    "allow": []
  }
}
```
- **Tags**: ['passive', 'mrr', 'turnover-shield']

### mcp (0.4.0)
- **Path**: `bigbang/plugins/mcp/cli.py`
- **Description**: MCP client + server — consume any MCP, serve bb as MCP
- **Commands**: `manifest`, `serve`, `add-server`, `list-servers`, `list`, `call-tool`
- **Capabilities**: ```json
{
  "network": {
    "enabled": true,
    "domains": [
      "localhost",
      "127.0.0.1"
    ]
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/.local/share/bigbang/"
    ]
  }
}
```
- **Tags**: []

### rft (1.0.0)
- **Path**: `bigbang/plugins/rft/cli.py`
- **Description**: RFT workflow-trace ETL — audit.jsonl episodes -> redacted, reward-annotated training datasets (MAI-Thinking-1 RFT-on-own-traces pattern)
- **Commands**: `export`, `stats`, `schema`
- **Capabilities**: ```json
{
  "network": {
    "enabled": false,
    "domains": []
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/.local/share/bigbang/rft/"
    ]
  },
  "secrets": {
    "allow": []
  }
}
```
- **Tags**: []

### rtx (0.5.0)
- **Path**: `bigbang/plugins/rtx/cli.py`
- **Description**: Alienware RTX 4080/4090 offload — queue tasks to local autoresearch-win-rtx custom, monitor results, sync to Hatch
- **Commands**: `status`, `queue-cmd`, `results`, `programs`, `releases-cmd`, `sync-cmd`, `dashboard-cmd`
- **Capabilities**: ```json
{
  "network": {
    "enabled": false,
    "domains": []
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/workspace/autoresearch-rtx-custom/",
      "~/workspace/your_files/rtx-offload/",
      "~/workspace/projects/first-1k-mo-passive/files/"
    ]
  },
  "secrets": {
    "allow": []
  }
}
```
- **Tags**: []

### secrets (0.4.0)
- **Path**: `bigbang/plugins/secrets/cli.py`
- **Description**: Vault for API keys, tokens — security first
- **Commands**: `set-cmd`, `get-cmd`, `list-cmd`, `list`
- **Capabilities**: ```json
{
  "filesystem": {
    "write": true,
    "paths": [
      "~/.local/share/bigbang/"
    ]
  },
  "secrets": {
    "allow": [
      "*"
    ]
  }
}
```
- **Tags**: []

### system (0.4.0)
- **Path**: `bigbang/plugins/system/cli.py`
- **Description**: System health, audit, policy, scaffold
- **Commands**: `doctor`, `policy-cmd`, `scaffold-plugin`, `hello`
- **Capabilities**: ```json
{
  "network": {
    "enabled": true,
    "domains": [
      "localhost"
    ]
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/workspace/bigbang-cli/"
    ]
  }
}
```
- **Tags**: []

### tasks (0.4.0)
- **Path**: `bigbang/plugins/tasks/cli.py`
- **Description**: Google Tasks — task lists + tasks CRUD wired into BigBang via hatch_gws_cli, agent-native
- **Commands**: `status-cmd`, `lists-cmd`, `list-tasks`, `get-task`, `add-task`, `update-task`, `complete-task`, `uncomplete-task`, `delete-task`, `create-list`, `sync-bb`, `export-tasks`
- **Capabilities**: ```json
{
  "network": {
    "enabled": false,
    "domains": []
  },
  "filesystem": {
    "enabled": true,
    "write": true,
    "paths": [
      "~/workspace/bigbang-cli/docs/llm-wiki/",
      "~/.local/share/bigbang/"
    ]
  },
  "secrets": {
    "allow": []
  }
}
```
- **Tags**: ['productivity', 'google', 'tasks', 'gws']

### tennis (0.4.0)
- **Path**: `bigbang/plugins/tennis/cli.py`
- **Description**: Tennis DINOv3 serve coach
- **Commands**: `serve`
- **Capabilities**: ```json
{
  "network": {
    "enabled": true,
    "domains": [
      "huggingface.co"
    ]
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/workspace/tennis-dinov3-serve-coach/"
    ]
  }
}
```
- **Tags**: []

### tools (0.4.0)
- **Path**: `bigbang/plugins/tools/cli.py`
- **Description**: Universal registry — turn any internet API into bb command
- **Commands**: `list-cmd`, `add-cmd`, `get-cmd`, `get`, `rm`, `call-cmd`, `import-openapi`, `generate-cmd`
- **Capabilities**: ```json
{
  "network": {
    "enabled": true,
    "domains": [
      "*"
    ]
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/.local/share/bigbang/"
    ]
  }
}
```
- **Tags**: []

### vector (0.4.0)
- **Path**: `bigbang/plugins/vector/cli.py`
- **Description**: Vector MTNNs — hoops/pitch/gridiron control
- **Commands**: `list-sites`, `list`, `verify`
- **Capabilities**: ```json
{
  "network": {
    "enabled": true,
    "domains": [
      "hoops.dumbmodel.com",
      "pitch.dumbmodel.com",
      "gridiron.dumbmodel.com",
      "vercel.com"
    ]
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/workspace/vector-hoops/",
      "~/workspace/vector-pitch/",
      "~/workspace/vector-gridiron/"
    ]
  }
}
```
- **Tags**: []

### write (0.5.0)
- **Path**: `bigbang/plugins/write/cli.py`
- **Description**: Authentic-feeling content generators that auto-scan for AI slop and fix it — HUMAN_LIKE 0, batch, pre-commit hook, real sources
- **Commands**: `scan-cmd`, `humanize-cmd`, `generate-cmd`, `sources-cmd`, `check-cmd`, `batch-cmd`, `hook-cmd`
- **Capabilities**: ```json
{
  "network": {
    "enabled": true,
    "domains": [
      "localhost",
      "127.0.0.1",
      "host.docker.internal"
    ]
  },
  "filesystem": {
    "write": true,
    "paths": [
      "~/workspace/your_files/write-outputs/",
      "~/workspace/",
      "./"
    ]
  },
  "secrets": {
    "allow": []
  }
}
```
- **Tags**: []
