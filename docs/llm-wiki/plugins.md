# Plugins Catalog — LLM Wiki

**Solo personal project, no connection to employer, built with public/free-tier only**

Total plugins: 11 (v0.4.1 includes tasks)

| Plugin | Version | Commands | Capabilities | Description |
|--------|---------|----------|--------------|-------------|
| agent | 0.4.0 | run, bus, teach | net:True localhost,127.0.0.1 | Ava-native planner that routes to any tool |
| auth | 0.4.0 | login, set-token, list-auth, get-token-cmd, status-cmd +1 | net:True github.com,api.github.com | Unified auth for all internet services — OAuth device flow + |
| ava | 0.4.0 | status, train, eval-cmd, route | net:True huggingface.co,localhost | Ava AGI Factory — local CUDA brain for BigBang routing + eva |
| family | 0.4.0 | brain, bills | net:False  | Family Brain generic tools |
| mcp | 0.4.0 | manifest, serve, add-server, list-servers, list +1 | net:True localhost,127.0.0.1 | MCP client + server — consume any MCP, serve bb as MCP |
| secrets | 0.4.0 | set-cmd, get-cmd, list-cmd, list | net:False  | Vault for API keys, tokens — security first |
| system | 0.4.0 | doctor, policy-cmd, scaffold-plugin, hello | net:True localhost | System health, audit, policy, scaffold |
| tasks | 0.4.0 | status-cmd, lists-cmd, list-tasks, get-task, add-task +7 | net:False  | Google Tasks — task lists + tasks CRUD wired into BigBang vi |
| tennis | 0.4.0 | serve | net:True huggingface.co | Tennis DINOv3 serve coach |
| tools | 0.4.0 | list-cmd, add-cmd, get-cmd, get, rm +3 | net:True * | Universal registry — turn any internet API into bb command |
| vector | 0.4.0 | list-sites, hoops, verify | net:True hoops.dumbmodel.com,pitch.dumbmodel.com | Vector MTNNs — hoops/pitch/gridiron control |

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

### family (0.4.0)
- **Path**: `bigbang/plugins/family/cli.py`
- **Description**: Family Brain generic tools
- **Commands**: `brain`, `bills`
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
- **Commands**: `list-sites`, `hoops`, `verify`
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
