# Building Scout in the Herdr direction

**Reference:** [herdr.dev](https://herdr.dev/) — *one terminal for the whole herd*  
**Date:** 2026-07-17

Solo personal project, no connection to employer, built with public/free-tier only.

**Foundation plan:** see [`docs/FOUNDATION.md`](FOUNDATION.md) — Scout stays the orchestration control plane; we teach Dottie-claw via `scout skill teach`.

## Positioning (do not confuse the products)

| | **Herdr** | **Scout** |
|---|---|---|
| Shape | Rust binary, agent-aware **PTY multiplexer** | Python CLI, **personal control plane** |
| Core job | Real panes, detach/reattach, agent sidebar | Tools/MCP/vault/policy/Ava + session ledger |
| Control surface | CLI + Unix socket API | `scout --json …` + MCP serve |
| Persistence | Live PTY sessions | Registry + logs under `~/.local/share/bigbang/` |
| Plugins | GitHub `herdr-plugin` marketplace | `bigbang/plugins/*/manifest.yaml` |

Scout should **not** become Electron or a fake chat UI — same values as Herdr (local-first, no account, no telemetry). Scout **should** steal Herdr’s *orchestration* ideas:

1. Semantic agent state (`idle|working|blocked|done`)
2. Resource+verb CLI agents can drive
3. `wait` instead of sleep loops
4. Read output / report status
5. An agent skill that teaches the surface
6. Optional pairing with a real multiplexer

## Shipped: `scout herd` (v0.7 slice)

```bash
scout herd status
scout herd create --label api --cwd ~/project
scout herd start api --cmd "pytest -q"
scout --json herd wait api --status done --timeout 120
scout herd read api --lines 40
scout herd report api --status blocked --note "need token"
scout herd herdr          # detect Herdr binary + pairing flow
```

Skill for coding agents: `bigbang/skills/scout-herd.md`

## Roadmap toward a Herdr-class Scout

### Wave A — control surface (now → next)

- [x] Session ledger + status refresh from PID
- [x] `wait` / `read` / `report` / `close --kill`
- [x] Agent skill + Ava/agent routing hints
- [ ] `scout herd send <id> --stdin` / append input file for interactive CLIs
- [ ] Socket or named-pipe event stream (`events.subscribe` analogue) for long waits
- [ ] Mirror Cursor cloud-agent runs into herd (`scout herd import cursor`)

### Wave B — marketplace & plugins

- [ ] `scout plugin search` over GitHub topic `scout-plugin` (Herdr marketplace pattern)
- [ ] `scout plugin install org/repo` → drop into `~/.local/share/bigbang/plugins/`
- [ ] Strengthen `system scaffold` to emit herd-aware manifests + Examples epilog by default

### Wave C — remote & mobile

- [ ] Tailscale / SSH notes for `scout mcp serve` (README v0.7)
- [ ] `scout herd status --watch` TUI-lite (rich live table) — still not a multiplexer
- [ ] Document phone-SSH workflow: Herdr for panes, Scout for tools

### Wave D — honesty & polish

- [ ] Keep bookmark plugins labeled (`family`/`tennis`)
- [ ] Finish cli-for-agents Wave 1 on remaining plugins
- [ ] Standard JSON envelope `{ok, command, data}`

## Suggested Cam workflow

```text
Herdr          →  where agents live (PTYs, layouts, remote attach)
Scout herd     →  ledger + wait/read that scripts/Ava can poll
Scout tools/*  →  internet tools, vault, MCP, write/lab/brain/rtx
```

Install Herdr when you want the multiplexer; keep building Scout as the brain/router that understands *your* tools.
