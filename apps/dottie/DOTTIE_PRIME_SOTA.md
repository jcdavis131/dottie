# Dottie — SOTA Edition of Prime Agent

> Dottie is what happens when you take the two great ideas in [prime-agent](https://github.com/PrimeIntellect-ai/prime-agent) — Recursive Language Model + Continual Harness — and ship them with a real factory, an honest memory system, and a single CLI that can extend itself.

Solo personal project, no employer tie, public/free-tier only, MIT.

## One-liner

Prime Agent gave us: `RLM` (prompt-as-variable + recursive subagents in a persistent REPL) + `Continual Harness` (durable, refineable session state).

Dottie SOTA adds: **factory loop that trains its own brain from every trace**, Scout v5 Prime missions that survive a week offline, provenance-honest metrics that refuse to fake, and local-first contacts/graph with no OAuth.

If prime-agent is the research prototype, Dottie is the production OS you actually live in.

---

## Prime → Dottie Mapping

| Prime Concept | Prime Implementation | Dottie SOTA |
|---|---|---|
| **RLM** | IPython REPL, `rlm(...)` spawns child agents, context as variables | Same REPL-first model, plus typed `MissionLog` at `workspace/.scout/missions/<id>/timeline.jsonl`. Pause Monday, resume Thursday, receipts intact. Stuck Detector watches for 2× same query / 2 fails / 0 hits / conf<0.4 and triggers ONE lateral lens, not spam. |
| **Continual Harness** | Supplemental prompts/memories/skills/subagent specs, `/refine` small evidence-backed updates, snapshots + rollback, never rewrites base prompt | Same guarantees, stored at `workspace/.dottie/harness/<session>/harness.jsonl` versioned. Adds People Resolver Write-Back: memory_search → ask once → append to MEMORY.md (<50ms forever). Adds GARNet graph memory (G_workflow live DAG + G_history patterns). Source tracking (`manual|calendar|memory_heuristic|enriched|extraction|ingest`) with confidence, <0.4 = hint only. |
| **Everything programmatic** | File ops, shell, tools via code | Identical, plus scout doctrine: LLM gets exactly ONE tool `scout --json ...`. Forge can `new|edit|test|install` a capability at runtime. `network/filesystem/secrets` default-deny in manifest. |
| **Skills executable** | Importable Python packages | Same, plus `scout forge from-openapi/mcp` generates skill from spec in one line. Zero pip unless opted. Token-cache optimizer (~80% savings) with compressed packs. |
| **Daemon sessions** | Background agents survive terminal close, reattachable | Same, plus `dottie daemon` + `scout` session bus. Agent-to-agent messaging without routing through user. Autonomous mode with triple budgets (turns/tokens/time) + quality gates that actually verify, not just count down. |
| **Long tasks** | Auto-compaction, persistent goals, heartbeats, schedules, retained subagents | Same, plus Mission Log + heartbeat `/heartbeat` + `rlm_heartbeat` + `dottie schedule`. Heartbeat checklist = `HEARTBEAT.md`. All checks log even when "no change". |
| **Factory loop** | _not present_ | Dottie-only: `tasks → traces.jsonl → RFT export + memory mint → eval gate (ava-open-harness) → GRPO train step → better ckpt → serve`. Provenance every number, honest refusal with 503 + true reason when backend missing. No fake metrics, ever. |
| **Contacts/People** | _not present_ | Dottie-only: ACNE local-first contacts, fuzzy trigger phrases, same-name disambiguation, provenance + confidence, writes back to MEMORY.md. No OAuth, no cloud. |

---

## Core Abstractions in Dottie SOTA

### 1. RLM v2 (Recursive Language Model as Code)

Prime's insight is right: don't hide context in a chat array, expose it as variables in a REPL you can program.

```python
# inside Dottie REPL (persistent IPython)
query = "find all stripe vs lemonsqueezy pricing contradictions in sources/"
# prime pattern: spawn researcher subagents programmatically
results = rlm(
  "research stripe vs lemonsqueezy aug 2026",
  sources=["stripe docs","lmsq docs","pricing pages"],
  require=["min 5 sources graded A/B/C","contradiction matrix","freshness aug 2026"],
  model_tier="deep_research" # 9K heavy, predicts capability before full cost
)
# Dottie addition: verifier that ships, not that nags
verify(results, threshold=8.0, budget=3, fix_once_if_below=True)
```

Dottie makes it typed: `mission_id`, `timeline.jsonl` (pause/resume), stuck detector, lateral lens on-demand (SCAMPER/Six Hats/Inversion/Provocation/Random/Analogy/Concept Fan/Lateral/Worst Idea).

### 2. Continual Harness v2

Stored at: `workspace/.dottie/harness/<session-id>/`
- `harness.json` — current supplemental state
- `harness.jsonl` — append-only refinement log
- `snapshots/<timestamp>/` — rollback points
- `timeline.jsonl` — Mission Log (Scout v5 Prime)

`/refine` (or `dottie harness refine --evidence "why"`) reviews trajectory and proposes small updates:
- Must cite evidence from real trajectory steps
- Must not rewrite immutable base system prompt
- One Q max if person needs resolving → MEMORY.md
- <50ms write-back forever after
- Records snapshot supporting rollback

Local by default. `harness push` is opt-in.

### 3. Sessions as OS

```
dottie agent list              # running, idle, saved
dottie agent attach <id>       # reattach REPL + timeline
dottie agent --resume <path>   # cold resume days later
dottie daemon status|doctor|shutdown
dottie goal set "ship arxiviq starter by friday"
dottie heartbeat enable --interval 15m
dottie schedule add "every monday 9am" --task "scan vector-hub"
dottie autonomous --turns 20 --tokens 9K --time 30m --gate "pytest passes"
```

Agents discover each other via `workspace/.dottie/registry.json` and message via:

```python
scout --json comms send --to agent:researcher-2 --msg "stripe contradiction found"
scout --json comms inbox
```

### 4. Single-CLI Doctrine (Dottie's edge)

The model and any harness gets ONE tool: `scout`.

Every capability is a plugin behind `scout --json <name> ...`. Forge engine at `apps/scout-cli/bigbang/plugins/forge/cli.py` (verified e2e):

```bash
scout --json forge new github --description "GitHub API wrapper" --domains api.github.com --network
scout --json forge cat github
scout --json forge edit github --code '<impl>'
scout --json forge test github
scout skill install github --target dottie
```

Generate from spec:

```bash
scout --json forge from-openapi --name linear --url https://api.linear.app/openapi.json
scout --json forge from-mcp --name notion --url https://mcp.notion.com/sse
```

Manifest declares capabilities: `network/filesystem/secrets`, default deny.

---

## Scout v5 Prime Integration

Dottie SOTA ships the 4 fixes basic harnesses don't have (from Scout Lean → Prime):

1. **Mission Log** — `workspace/.scout/missions/<id>/timeline.jsonl` — pause Monday, resume Thursday, receipts.
2. **Stuck Detector** — same query 2× / 2 fails / 0 hits / conf <0.4 / "hmm" → ONE lateral lens showing abandoned possibilities.
3. **People Resolver Write-Back** — one question max → MEMORY.md — trigger <50ms forever after.
4. **Verifier With Budget That Ships** — score 1-10, fix biggest gap once if <8, max 2 loops.

Router = 3-line heuristic: direct / 1 researcher / coordinator+workers. No 13-agent theatre unless epic.

---

## Why This Beats Prime Agent

Prime proved RLM + Harness can run long work. Dottie closes the loop Prime leaves open:

- Prime runs tasks with a big model. Dottie trains a *small* model from those tasks, gates it honestly, and gets better without calling a bigger cloud.
- Prime has snapshots. Dottie has provenance: every number carries *how* it was obtained, and missing backends refuse with 503 + true reason, never a hallucinated reply.
- Prime has skills. Dottie has forge: skills are *created* by the agent mid-task, tested, and persisted, with capability sandboxing.
- Prime has sessions. Dottie has missions with timeline, climb, and a Hub/Guide/Monitor site that shows the factory honestly.
- Prime asks for contacts via OAuth. Dottie says "Don't connect contacts", uses local-first ACNE with fuzzy matching, same-name handling, confidence <0.4 = hint.

No vector DB, no embeddings API required for core. Pure traversal, local R2/Workers/Supabase/HF ZeroGPU.

---

## Quickstart (Dottie SOTA)

```bash
git clone https://github.com/jcdavis131/dottie.git && cd dottie
export DOTTIE_ROOT=$(pwd)
uv sync
pip install -e apps/scout-cli
pip install -e apps/dottie

# RLM session
dottie repl                      # persistent IPython with rlm(...) built-in
dottie repl --resume <session>   # days later

# harness
dottie harness init --session research-stripe-082
dottie harness refine --evidence "found pricing contradiction from 3 sources"
dottie harness snapshots
dottie harness rollback --to <timestamp>

# goals / heartbeats / autonomous
dottie goal set "close factory loop end-to-end unattended"
dottie heartbeat enable
dottie autonomous --turns 15 --gate "eval_score > 8.0"

# factory loop (honest, refuses if no ckpt)
dottie run "compute sum of last 10 traces n_steps" --backend ollama
dottie climb --families mixed --n 20 --backend ollama --iterations 1
```

Every command speaks `--json` for harnesses: `dottie --json engine status`.

---

## Operator Guarantees (from SPEC.md)

- Provenance travels with every number
- A win is cross-seed, not within-run
- Honest refusal over fabrication
- Daemon does not live-reload — boot line (git_sha + prompts_sha256) is ground truth
- One clarifying question max, then execute

## Repo Layout Updated

```
apps/dottie/dottie/
  rlm.py                # NEW: RLM v2 — persistent REPL + programmatic rlm(...)
  harness_continual.py  # NEW: Continual Harness v2 — versioned, snapshot, refine
  sessions.py           # NEW: daemon-backed sessions, registry, messaging
  goals.py              # NEW: persistent goals + progress
  heartbeat.py          # NEW: heartbeats/schedules
  engine.py             # existing — CodeAct loop + trace capture
  policy.py             # existing — Ollama/Ava/Echo
  flywheel.py           # existing — RFT export, mint, eval, train
  climb.py              # existing — measured hill-climb
```

`workspace/.dottie/` and `workspace/.scout/missions/` are gitignored — durable local state, like prime's `.prime/` but with Scout's timeline contract.

---

## License

MIT — like prime-agent. Dottie's factory, forge, and ACNE additions also MIT.
