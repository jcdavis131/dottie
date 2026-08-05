# Harness Polish 2026-08-05 — v0.8.0 Verified

> Scout CLI harness manifest polish — minimal verification, no torch, no candidate.json promotion.

## Manifest
- Path: `apps/scout-cli/bigbang/plugins/harness/manifest.yaml`
- Verified contents:
```yaml
name: harness
description: Scout v3.3 harness — MoMA-lite router + graph memory GARNet + checkpoint + recovery ladder + pacing + verification econ.
capabilities:
  network: false
  filesystem: true
  secrets: false
version: 0.8.0
entry: cli.py
```
- Capabilities honest: `network:false` (pure local routing, no fetch), `filesystem:true` (checkpoint/timeline reads), version bump 0.7 → 0.8.0 for MoMA-lite + GARNet + pacing + verification additions.

## Wrapper Executable
- `~/workspace/bundles/cli.sh` — 896 B, executable `rwxrwx---` (2026-08-05 02:58 CT inspected)
- Single-source shim: `python3 -m bigbang.cli "$@"` with PYTHONPATH to `~/workspace/dottie/apps/scout-cli`
- Usage: `bundles/cli.sh --json harness route "goal"`
- Perms verified executable, shebang `#!/usr/bin/env bash`, set -euo pipefail — ready for any Hatch agent/harness.

## Shared Lib Provenance
- `apps/scout-cli/bigbang/plugins/vector/shared/towers.py` — 6404 B (verified 2026-08-05)
- `apps/scout-cli/bigbang/plugins/vector/shared/losses.py` — 2745 B (verified 2026-08-05)
- Both tracked, no new binary blinding — sizes match honest on-disk.

## CLI Surface
- `cli.py` 11352 B harness router — MoMA-lite tiers:
  - deterministic / llm / deep_research / action_operator / agentic_epic
- Commands: `route`, `agents`, `checkpoint`, `verify`, `pace` verified in `cli.py` header.
- Example: `scout --json harness route 'compare Stripe vs Lemon Squeezy Aug 2026'` → deep_research, 3-agent, stickiness_guard.

## No-Torch Guard
- No pip install executed in this polish lane.
- No candidate.json → vectors promotion (per bundle rules gate requires eval beat + audit).
- Minimal commit: doc only + manifest.yaml (already correct, no diff if untouched).

## Provenance Honest
- Branch: `scout/scout-cli-harness-polish`
- Status: manifest v0.8.0 verified fs true/net false, wrapper exec verified, shared lib sizes honest.
- Commit: `chore: harness polish v0.8.0 fs true net false — verify wrapper + shared lib`

— Scout 🐱✨ 2026-08-05 04:14 CT
