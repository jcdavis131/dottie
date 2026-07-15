# Extending BigBang CLI v0.3

## 30-sec Plugin

```bash
bb system scaffold mytool --with-manifest
# edits bigbang/plugins/mytool/manifest.yaml for caps + cli.py
bb mytool hello --json
# instantly in bb --help and bb mcp manifest as bb_mytool
```

## Universal Tool Registry — One CLI to Rule Internet

Add any external tool:

```bash
bb tools add github --type openapi --url https://api.github.com/openapi.json --tags api,code
bb tools add stripe --type openapi --url https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json
bb mcp add notion https://mcp.notion.com/sse
bb tools list
bb tools search payments
```

Import OpenAPI as tool:

```bash
bb tools import-openapi https://api.example.com/openapi.json --name example
```

## Security

Declare caps in manifest.yaml — default deny. Access secrets via vault:

```python
from bigbang.core.security import get_secret
token = get_secret("GITHUB_TOKEN")  # from keyring/0600 file/env
```

Never log secrets — audit.py strips secret/key substrings.

## Agent Native

Every command must use `emit(data, command="...")` → valid JSON when --json, rich otherwise, audited.

Agent planner:

```python
# bb agent run "do X"
# -> list_tools() -> search_tools() -> build plan with policy checks
# Future: call Ollama for real planning
```

## MCP

Serve BigBang as MCP:

```bash
bb mcp manifest  # all bb_* tools
bb mcp serve --port 8787
# Claude Desktop: {"mcpServers": {"bigbang": {"url": "http://localhost:8787/sse"}}}
```

Consume external MCP:

```bash
bb mcp add myserver http://localhost:3000/sse
bb mcp list-tools myserver
bb mcp call myserver some_tool --args '{"q":"test"}'
```

## Ava Integration

Ava is brain for routing + evaluation:

- `bb ava route "task"` → returns tool + confidence (stub → Ollama in v0.6)
- `bb ava eval --frontier` → Frontier rubric for tool promotion
- Future: vector store over audit.jsonl for lifelong memory
