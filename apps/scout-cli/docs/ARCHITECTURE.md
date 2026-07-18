# Architecture v0.5 — Ava Co-Dev Plane: Write + Lab + Brain

## Vision
BigBang is *the* universal router: one CLI to rule all internet tools, with security-first, agent-native, Ava-brained. v0.5 adds Authentic Generators + Passive Lab MRR + Hatch brain as the tool you use for everything and the tool you give to Ava ecosystem.

## What's New in v0.5 (from v0.4.1)

- **Write Plugin v0.5** (`plugins/write/`):
  - `scan` research-grounded: ai-slop-detect 70+ patterns, slop-radar 245 buzzwords, slop-cop 36 rules, CMU PNAS 2025 participial 2-5x, tapestry 150x. Weights: participial 0.5, char 0.8, phrase 3.0 + soft <50w scoring hits*6+0.9w.
  - `check` deterministic fixer: em-dash strip, buzzword map word-boundary (crafting→making not makeing), participial comma strip `", verbing" → " verbing"` via `re.sub(r",\s+([a-z]+ing)")`. Test: BEFORE STRONG_AI 100 13 hits → AFTER HUMAN_LIKE 0 10 fixes (participial x2).
  - `humanize` + `generate` always HUMAN_LIKE 0 fallback template (no Ollama needed), `sources` curated REAL_SOURCES with offline fallback, `batch` scans dir + --fix, `hook --install` writes pre-commit yaml + .git/hooks/pre-commit.
  - Ollama fast: `_ollama_base_fast()` localhost only unless ALLOW_DOCKER, 0.8s timeout, trust_env=False, chat 6s (not 15s) → no timeout 124.
  - Manifest 0.5.0, fs write `write-outputs/` + `.` for batch.

- **Lab Plugin v0.5** (`plugins/lab/`):
  - `ideas` loads TOP10-HOME-ONLY-SOLO.md, `shield` shows Turnover Shield MVP $79-149/mo persona pain ROI, `mrr` logs to `~/workspace/projects/first-1k-mo-passive/files/mrr.jsonl` with customers_needed_at_79, `pitch` generates authentic pitch + scans via write.
  - No network, no secrets — solo footer.

- **Brain Plugin v0.5** (`plugins/brain/`):
  - `memory` tail MEMORY.md + daily notes, `goals` list projects, `goal <slug>` PROJECT.md + files count, `sync` token-efficient JSON for Ava LLM-wiki ingest, `daily` append to daily note.
  - Bridge so Ava `bb brain sync` gets full context without 52k token MEMORY.md load.

- **Routing Upgraded**:
  - `ava/_heuristic_route`: slop/write/authentic/blog/email → write 0.93, mrr/passive/turnover/lab → lab 0.91, memory/goals/brain sync → brain 0.90.
  - `agent/_heuristic_plan` builtin_hints: slop→write scan, write→write check, authentic→write generate, mrr→lab mrr, passive→lab ideas, turnover/shield→lab shield, brain/memory/goals→brain goals.
  - Verified: ava route "check slop" → write 0.93, agent run "authentic email Turnover Shield" → [bb write generate, bb lab shield].

## Core Flow v0.5
```
User/Ava: bb --json ava route "check my writing for slop"
  → _ava_heuristic_route: q=write/slop → picked_tool=write 0.93 (no Ollama)
  → outputs JSON {picked_tool, picked_command} → audited

User: bb --json write check -t "In today's... leveraging holistic"
  → scan_text: STRONG_AI 100, hits 13 by_kind {char:4, phrase:6, buzzword:3}
  → _apply_deterministic_fixes: strip leading connectors, word-boundary phrase map, participial strip x2 → "today that our new solution..."
  → after scan HUMAN_LIKE 0 → emit before/after + final_text

User: bb --json lab mrr --trials 2 --note "v0.5 shipped"
  → writes mrr.jsonl → used by brain goals + ava eval for Frontier finance accuracy

Ava co-dev loop:
  bb brain sync → memory tail + goals list (token-efficient)
  bb write generate --no-ollama → HUMAN_LIKE 0 pitch with real sources
  bb agent run "ship it" → plan [bb write batch --fix, bb lab log, bb brain daily]
  audit.jsonl → future pgraphify vector memory
  bb ava eval --frontier → 11 cats judges if automation safe
```

## Security v0.5

- 14 plugins, each has manifest.yaml — capability engine via policy.py enforce_or_raise.
- Vault: keyring + 0600 file + env fallback, audit.py strips secret substrings.
- http_utils sanitizes no_proxy []/:: (Invalid port error), Ollama clients trust_env=False.
- write plugin network domains en.wikipedia.org, api.duckduckgo.com, localhost only; lab/brain no network, no secrets.
- All JSON root via --json flag, emit() handles, audited.

## Testing v0.5

pytest tests/ → full suite (run `pytest tests/ -q` for the current count). test_cli.py covers:
- import, plugin_list_security_first (now 14 names inc write/lab/brain), security_vault, registry, policy_manifests_exist, json_contract
- write_scan_strong_ai 100, write_humanize_deterministic_zero 0 with participial strip, write_generate_humanlike HUMAN_LIKE, write_cli_json
- lab_ideas TOP10 rank1 Turnover Shield, brain_goals exists, ava_route_write 0.93, ava_route_lab 0.91

## Hill-Climb Metrics v0.5

- Write test sentence BEFORE 100 → AFTER 0 (was 20) — fixed via participial comma strip.
- Ollama timeout 25s → 0.8s base + 6s chat, no DNS hang.
- Ava routes: slop→write 0.93, mrr→lab 0.91, brain→brain 0.90.
- LLM-wiki 14 plugins via generate_llm_wiki.py.
- MRR: v0.5 logged trials 2, paid 0, mrr 0, target 1000, 13 customers needed @79.

## Roadmap

- v0.5 ✅ Authentic Generators v0.5 + Lab + Brain + routing
- v0.6 🔜 Docker isolation, age encryption, Sigstore, Ava vector memory over audit.log
- v0.7 🔜 Tailscale tunnel for iOS/Android, heartbeat bus, Frontier auto-pitch
```
