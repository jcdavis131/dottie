---
name: scout-herd
description: Orchestrate Scout herd sessions (Herdr-inspired control surface) — create/start/wait/read/report agent jobs via JSON CLI.
---

# Scout Herd — agent skill

Scout is the personal control plane (tools, MCP, Ava, vault, policy).
[Herdr](https://herdr.dev/) is the PTY multiplexer. **`scout herd`** is the JSON session ledger agents can drive — same *idea* as Herdr's CLI/socket control surface, without owning panes.

## States

`idle` · `working` · `blocked` · `done` · `failed` · `unknown`

## Non-interactive commands (always prefer `--json`)

```bash
# Glance
scout --json herd status
scout --json herd list

# Create + run detached job (logs under ~/.local/share/bigbang/herd/logs/)
scout herd create --label api --cwd "$PWD"
scout herd start api --cmd "pytest -q"

# Or create-on-start
scout herd start --label job --cmd "python train.py --smoke"

# Wait (exit 0 on match, exit 2 on timeout)
scout --json herd wait api --status done --timeout 120

# Inspect
scout --json herd read api --lines 40

# Self-report (when you need human input)
scout herd report api --status blocked --note "need GITHUB_TOKEN"

# Cleanup
scout herd close api --force          # ledger only
scout herd close api --kill --force   # SIGTERM process + remove
```

## Pairing with Herdr

If `herdr` is on PATH:

```bash
scout --json herd herdr     # detection + pairing notes
herdr workspace create --cwd "$PWD" --label api
# run the coding agent inside the Herdr pane; mirror status into Scout:
scout herd create --label api --cwd "$PWD"
scout herd report api --status working
```

## Rules for agents

1. Prefer flags (`--cmd`, `--status`, `--timeout`) — never prompts.
2. Default to `scout --json …` and parse stdout.
3. Use `wait` instead of sleep loops.
4. On `blocked`, put the unblock hint in `--note`.
5. Do not confuse Scout herd with Herdr panes — herd logs are file-backed, not PTY scrollback.
