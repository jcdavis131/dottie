# Plan — Scout foundation for Dottie-claw

## Goal

Build Scout as a **clean, extensible foundational orchestration tool** (Herdr-inspired control surface, not a multiplexer) and **teach Dottie-claw** how to use it.

## Decisions (locked)

1. Scout ≠ Herdr — no PTY TUI in-repo.
2. Agents learn via packaged skills + MCP (`scout_*` tools).
3. New code uses `bigbang/core/contract.py` (`ok`/`err`/`make_plugin_app`).
4. Default teach target is **dottie** → `~/.dottie-claw/skills/`.

## F0 deliverables (execute now)

| Item | Status |
|---|---|
| `docs/FOUNDATION.md` north star | done |
| `core/contract.py` | done |
| `scout skill` list/show/install/teach | done |
| `bigbang/skills/scout/SKILL.md` curriculum | done |
| MCP `scout_*` + `bb_*` compat | done |
| Foundation-shaped `system scaffold` | done |
| Tests | in progress |

## Next waves

- F1: migrate herd/secrets/tools to `ok` envelope; policy enforce at writes
- F2: herd send/watch; import Cursor cloud agents
- F3: plugin marketplace (`scout-plugin` topic)
- F4: Dottie heartbeat + RFT loop docs

## Verify

```bash
pytest tests/ -q
scout skill teach --target dottie --dry-run
scout --json skill show scout
```
