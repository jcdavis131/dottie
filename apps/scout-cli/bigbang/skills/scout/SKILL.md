---
name: scout
description: >
  Drive Scout CLI — Cam's local-first orchestration control plane (tools, vault,
  policy, herd sessions, Ava routing, MCP). Primary curriculum for Dottie-claw
  and other agents. Prefer scout --json. Not a PTY multiplexer (use Herdr for panes).
---

# Scout — Dottie-claw curriculum

You are learning **Scout**, the personal control plane. Use it for secrets, tools, MCP, session orchestration (`herd`), and Ava routing. Do **not** treat Scout as tmux/Herdr.

Solo personal project, no connection to employer, built with public/free-tier only.

## Positioning (do not confuse with Herdr)

**Thesis:** Most agent managers are multiplexers. **Scout is a judgment plane.**

- **Herdr** = WHERE agents live (PTY panes, SSH attach, TUI)
- **Scout** = HOW agents decide (trust, tools, judgment, memory, learning)

Never try to turn Scout into a responsive TUI multiplexer. Pair with Herdr for panes.

```bash
scout --json planes thesis
scout --json planes compare    # honest matrix vs herdr/tmux/apps
scout --json planes status     # five planes cockpit
scout --json planes loop       # act → audit → rft → ava flywheel
```

## Hard rules

1. Prefer `scout --json <plugin> <cmd> …` and parse stdout JSON.
2. Never wait on interactive prompts — pass `--token`, `--value`, `--stdin`, `--force`, `--yes`.
3. Discover layered: `scout --help` → `scout <plugin> --help` → `scout <plugin> <cmd> --help`.
4. On errors, read `example` / `discover` fields and retry that invocation.
5. Destructive ops: `--dry-run` first when available, then `--force`.

## Discovery ladder

```bash
scout --help
scout planes status
scout herd --help
scout tools --help
scout skill list
scout skill show scout
```

## Five planes (Scout-only)

| Plane | Question | Start here |
|---|---|---|
| Trust | May this agent do that — without phone-home? | `system doctor` · `secrets` · `policy` · **local audit only** (no product telemetry) |
| World | What tools exist? | `tools list` · `mcp serve` |
| Herd | What’s running/blocked/done? | `herd status` · `herd wait` |
| Judgment | What next? | `ava route` · `agent run` |
| Memory | What do we know/learn? | `brain sync` · `graphify` · `rft` |

## Everyday loops

### Health

```bash
scout --json planes status
scout --json system doctor
scout --json herd status
```

### Vault (never print secrets to chat logs)

```bash
scout secrets set GITHUB_TOKEN --value "$TOKEN"
# or: printf '%s' "$TOKEN" | scout secrets set GITHUB_TOKEN --stdin
scout --json secrets list
scout auth set-token github --token "$TOKEN"
```

### Tools + MCP

```bash
scout --json tools list
scout tools add github --type openapi --url https://api.github.com/openapi.json
scout mcp serve                    # stdio MCP for Cursor/Claude/Dottie
# MCP tool names: scout_<plugin>  (bb_<plugin> still works)
```

### Herd orchestration (Herdr-inspired, file-backed)

```bash
scout herd create --label job --cwd "$PWD"
scout herd start job --cmd "pytest -q"
scout --json herd wait job --status done --timeout 120   # exit 2 on timeout
scout --json herd read job --lines 40
scout herd report job --status blocked --note "need secret FOO"
scout herd close job --force
```

States: `idle` · `working` · `blocked` · `done` · `failed` · `unknown`

Pair with Herdr panes when needed: `scout --json herd herdr`

### Route + plan

```bash
scout --json ava route "check draft for ai slop"
scout --json agent run "list my tools"                 # plan only
scout --json agent run "system doctor" --execute       # run plan
```

### Writing / lab / brain

```bash
scout --json write scan --text "…"
scout --json lab ideas
scout --json brain sync
```

## MCP (for Dottie-claw / Cursor / Claude)

```json
{
  "mcpServers": {
    "scout": {
      "command": "scout",
      "args": ["mcp", "serve"]
    }
  }
}
```

Call `scout_herd` with `args="status"`, `scout_tools` with `args="list"`, etc.

## Install / refresh this skill

```bash
scout skill install scout --target dottie
scout skill install scout-herd --target dottie
scout skill install --all --target dottie
```

Targets: `dottie` → `~/.dottie-claw/skills/`, also `openclaw`, `claude`, `cursor`.

## Extending Scout

```bash
scout system scaffold mytool
# edit bigbang/plugins/mytool/{cli.py,manifest.yaml}
scout --json mytool hello
```

Foundation docs: repo `docs/FOUNDATION.md`, `docs/herdr-inspired.md`.

## What not to do

- Do not build a Scout TUI multiplexer — that is Herdr.
- Do not invent tool results when a command fails — surface the JSON error.
- Do not put secrets in command positionals when `--value`/`--stdin` exist.
- Do not treat bookmark plugins (`family`, `tennis`) as live backends.
