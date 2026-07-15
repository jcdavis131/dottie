# Extending BigBang CLI v0.5 — Ava Co-Dev Plane

> Solo personal project, no connection to employer, built with public/free-tier only

## 30-sec Plugin

```bash
bb system scaffold mytool --with-manifest
# edits bigbang/plugins/mytool/manifest.yaml for caps + cli.py
bb mytool hello --json
# instantly in bb --help and bb mcp manifest as bb_mytool
```

Scaffold template now includes:

```python
import typer
from bigbang.core.output import emit
app = typer.Typer(name="mytool", help="…", no_args_is_help=True)

@app.command("hello")
def hello():
    emit({"message": "Hello from mytool!"})

def register(root):
    root.add_typer(app, name="mytool")
```

**Manifest required** — default deny:

```yaml
name: mytool
capabilities:
  network: {enabled: false, domains: []}
  filesystem: {write: false, paths: []}
  secrets: {allow: []}
```

## Core Plugins Catalog v0.5 (14 plugins)

- `write` ✍️ Authentic writing — scan AI slop, humanize, generate with real sources. Research-grounded: ai-slop-detect 70+ patterns, slop-radar 245 buzzwords, slop-cop 36 rules, CMU PNAS 2025 participial 2-5x, tapestry 150x. Commands: scan, humanize, generate, sources, check, batch, hook
- `lab` 🧪 Passive Lab — Turnover Shield MVP, MRR tracking for First $1k/mo. Commands: ideas, shield, mrr, pitch, log
- `brain` 🧠 Hatch goals + MEMORY.md bridge for Ava. Commands: memory, goals, goal, sync, daily
- `ava` 🧠 Factory router — now detects write/lab/brain with 0.90+ confidence, Ollama qwen3:32b fast path 0.8s timeout (trust_env=False)
- `agent` 🤖 Planner — builtin_hints includes slop/write/humanize/mrr/lab/brain
- `tasks` ✅ Google Tasks via hatch_gws_cli
- `vector` MTNN 12,966 Hoops
- `family`, `tennis`, `tools`, `mcp`, `secrets`, `auth`, `system`

## Write Plugin Deep Dive — Authentic Generators Goal

Goal: `build-authentic-feeling-content-generators-that-auto-scan-for-ai-slop`

```bash
# Scan (research-grounded, no network)
bb --json write scan -t "In today's digital landscape, it's important to note..."
# → {"verdict":"STRONG_AI","ai_score":100,"hits":13}

# Deterministic fix — now HUMAN_LIKE 0 (was 20 before participial strip)
bb --json write check -t "In today's digital landscape, ... leveraging holistic..."
# BEFORE 100 → AFTER 0, fixes: em-dash, buzzword removal, participial comma strip x2

bb --json write humanize -t "..." --no-ollama --save
bb --json write generate "Turnover Shield launch email for plumbing owners in Austin" --no-ollama --save
# Always HUMAN_LIKE, cites real sources: ai-slop-detect, slop-cop, slop-radar, CMU, arXiv 2509.19163

# Batch + pre-commit hook (v0.5 new)
bb --json write batch docs/ --glob "*.md"
bb --json write batch docs/ --fix        # auto-fix if becomes HUMAN_LIKE
bb write hook --install   # writes .pre-commit-config.yaml + .git/hooks/pre-commit
```

Implementation notes v0.5:

- Weight tuning: participial 0.5 (CMU shows overuse but not pure slop), char 0.8, phrase 3.0
- Short-text scaling: hits*6 + weight*0.9 under 50 words (was 8* +1.2) → avoids false STRONG_AI
- Participial fix: `",\\s+([a-z]+ing)" → " \\1"` strips comma before any verbing — fixes TRACES 20 → 0
- Ollama fast path: `_ollama_base_fast()` 0.8s timeout, localhost only unless OLLAMA_ALLOW_DOCKER_HOST, trust_env=False to avoid 20s DNS hang
- `_ollama_chat` 6.0s total (was 15s) — prevents `exit 124` timeout 25s
- Fallback generate template is already HUMAN_LIKE 0, no em dashes

Sources curated (REAL_SOURCES, verified):

- https://github.com/antydizajn/ai-slop-detect
- https://github.com/awnist/slop-cop
- https://github.com/renefichtmueller/slop-radar
- https://www.cmu.edu/dietrich/news/news-stories/2025/large-language-models-writing-text
- https://arxiv.org/abs/2509.19163

## Lab Plugin — Passive Lab Co-Dev

```bash
bb --json lab ideas                 # top 10 boring B2B SaaS
bb --json lab shield                # Turnover Shield MVP status + next bb commands
bb --json lab mrr --trials 3 --paid 0
bb --json lab mrr --paid 1 --mrr 79 --note "First customer via Authentic Generators"
bb --json lab pitch --persona "Plumbing owner Austin 20 techs"
# → pitch scanned HUMAN_LIKE 0 by write plugin internally
```

MRR log → `~/workspace/projects/first-1k-mo-passive/files/mrr.jsonl` — used by bb brain goals + bb ava route.

## Brain Plugin — Hatch Memory Bridge for Ava

```bash
bb --json brain memory --n 20
bb --json brain goals --search "passive"
bb --json brain goal first-1k-mo-passive
bb --json brain sync --out ~/workspace/your_files/brain-sync.json
bb brain daily "Shipped write batch + hook, lab mrr tracking"
```

Ava uses `bb brain sync` to get token-efficient snapshot (memory tail + goal list) without loading full MEMORY.md (8000 char cap). Future: vector store over audit.jsonl.

## Universal Tool Registry — One CLI to Rule Internet

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

Declare caps in manifest.yaml — default deny. Vault:

```python
from bigbang.core.security import get_secret
token = get_secret("GITHUB_TOKEN")  # from keyring/0600 file/env
```

- Every plugin has manifest.yaml with capabilities.network.domains, filesystem.write.paths, secrets.allow
- core/policy.py enforce_or_raise before network
- audit.jsonl at ~/.local/share/bigbang/audit.jsonl
- http_utils.sanitize_no_proxy_env() strips [] :: fd8b hatch-egress-proxy Invalid port
- Ollama clients use trust_env=False to avoid 20s DNS hang

Never log secrets — audit.py strips secret/key substrings.

## Agent Native

Every command must use `emit(data, command="...")` → valid JSON when --json, rich otherwise, audited.

```bash
bb --json agent run "my todos"           # → [bb tasks list]
bb --json agent run "check slop in docs" # → [bb write scan ...]
bb --json agent run "show mrr"            # → [bb lab mrr]
bb --json ava route "draft authentic email for Turnover Shield"
# → picked_tool=write, confidence 0.93
```

## MCP

Serve BigBang as MCP:

```bash
bb mcp manifest  # all bb_* tools → bb_write, bb_lab, bb_brain, etc.
bb mcp serve --port 8787
# Claude Desktop: {"mcpServers": {"bigbang": {"url": "http://localhost:8787/sse"}}}
```

## Ava Ecosystem — Co-Development Loop

BigBang is the tool you use for everything AND the tool you give to Ava:

1. You: `bb lab mrr --paid 1 --mrr 79`
2. Ava: `bb brain sync` → reads goals + memory
3. Ava: `bb write generate "retention email — specific, no slop"` → HUMAN_LIKE 0 with real citations
4. Ava: `bb agent run "ship it"` → plans [bb write batch --fix, bb lab log, bb brain daily]
5. Audit log → `~/.local/share/bigbang/audit.jsonl` → future vector memory
6. Frontier eval: `bb ava eval --frontier` scores 11 cats (Financial Accuracy → Tool Accuracy, etc.) — judges if new automation safe

**Hill-climbing loop**: Use bb daily → audit shows patterns 3x → `bb system scaffold <name>` → Ava judges → new `bb <name>` command → instant new MCP tool.

## Testing

```bash
pytest tests/test_cli.py -v
# 14 tests: import, security, registry, manifests (now includes write/lab/brain), json contract,
# write scan STRONG_AI, humanize 0, generate HUMAN_LIKE, cli json, lab ideas, brain, ava routes
```

## Disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. Free-tier: R2/Workers/Supabase/HF ZeroGPU, ONNX WASM, Ollama local qwen3:32b.
