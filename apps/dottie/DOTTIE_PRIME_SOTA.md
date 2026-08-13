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

## Dottie + llmvm — How Dottie Deep Diverges from Prime RLM

Prime RLM is: IPython REPL + `rlm(prompt, tier)` spawns child agents. Context lives as variables.
Great for recursive decomposition, but still bounded by single-turn context + tool list.

Dottie imports https://github.com/9600dev/llmvm continuation-passing pattern and hardens it:

### Prime RLM (baseline)
- Persistent REPL, `prompt = "task"` → `rlm("research ...", tier="deep_research")`
- MissionLog timeline.jsonl pause/resume days later
- StuckDetector → 1 lateral lens
- Verifier with budget that ships
- Single tool `scout --json ...` doctrine

### Dottie + llmvm Deep (v2)

| Feature | Prime RLM | Dottie + llmvm Deep |
|---------|-----------|---------------------|
| **Execution** | Turn = LLM emits code OR final — sync | CPS: Query → NL + `<helpers>…</helpers>` interleaved → `exec` → replace block with `<helpers_result>` → continue until `result()` → summary FINAL |
| **Helpers** | `rlm()` only | `llm_call(exprs, instr)` → Dottie `rlm()` with token est + truncation heuristic upgraded to FAISS-like chunking; `llm_list_bind` JSON/line parse dedup 80 cap; `llm_bind/var_bind` arg binding via LLM; `guard(cond, expected_type)` records hit to `state.history`; `result()` collects answer |
| **Context buster** | Relies on LLM to chunk manually | Auto chunking when `ctx > 6k tok`: token-window 256 tok / 32 overlap sentence-aware splitter (~1100 chars), keyword-rank (jaccard + overlap ratio + jitter mimics random sample), ask LLM “need ALL?” → NO = top-N fitting window else YES = map-reduce |
| **Map-Reduce** | N/A | If ALL needed & `enable_map_reduce` true: Map each chunk → partial via policy, Reduce via combining prompt de-dup + synthesize. Falls back to top-8 if disabled. Tracks `chunks_used`. |
| **Forge plugins** | `scout` tool assumed available | Discovery scan `apps/scout-cli/bigbang/plugins/*/cli.py` + `manifest.yaml` description + `def` parsing → injected into `_globals` as `forge_plugins` list, `list_forge_plugins()`, `scout()` stub that mimics `scout --json <plugin> …` so LLM can call search/browser/sheets via `<helpers>` |
| **JIT / Compile** | Not present | `compile_thread_to_program(thread_history, policy, name)` — asks LLM to parameterize, componentize into funcs, lift LLM calls, emit `guard(var, type)` specialization; returns recompile-needed dict on guard fail, feeding Dottie flywheel `apps/dottie/data/programs/<name>.py` |
| **Pause/Resume** | MissionLog timeline durable | `resume_mission_log(mission_id, base_dir)` + `latest_mission_state()` reconstructs timeline days later preserving `thread_id` + locals snapshot + chunks_used |
| **Background** | Heartbeat + daemon | `background_orchestrator.py`: `BackgroundOrchestrator.scan_goals()` reads `workspace/goals/*/GOAL.md`, for each spawns `LLMVMRuntime` continuation, triple-writes 7-field `nodeId,agentId,attempt,latency_ms,tokens_est,status,errorClass` entries to `missions/<id>/timeline.jsonl` + `goals/<slug>/hidden_files/cron_health.jsonl` + `_cron/timeline.jsonl` even no-change (Scout v5 Prime contract) |
| **Zero-deps** | True | Still true: only stdlib + existing `dottie.policy.PolicyProvider`, no FAISS/tiktoken/pip/torch; ACNE optional local |

#### Example — interleaved NL + helpers (what LLM emits)

```python
# Natural Language: "I will download team page and extract names"

<helpers>
var1 = download("https://ten13.vc/team")  # stubbed offline, forge provides
var2 = llm_call([var1], "extract list of names")
for item in llm_list_bind(var2, "list of names"):
    var3 = llm_bind(item, "WebHelpers.search_linkedin_profile(first_name,last_name,company_name)")
# Dottie addition: forge discovery — LLM sees tools
print(f"forge tools: {list_forge_plugins()[:5]}")
result(var3)
</helpers>
```

#### Triple-write checkpoint (always-even-no-change)

```python
from dottie.background_orchestrator import BackgroundOrchestrator
orch = BackgroundOrchestrator()  # goals_dir=~/workspace/goals, missions_dir=~/.scout/missions
orch.sweep_all_goals(max_goals=3, max_continuations=4)
# writes 7-field entries even no-change to 3 places:
# 1) .scout/missions/<id>/timeline.jsonl
# 2) goals/<slug>/hidden_files/cron_health.jsonl + llmvm_resume_<slug>.json
# 3) .scout/missions/_cron/timeline.jsonl aggregate
# resume days later:
from dottie.llmvm import resume_mission_log
mission, events = resume_mission_log("dottie-refine-dottie-20260807")
```

#### Where files live

- `apps/dottie/dottie/llmvm.py` v2 — `LLMVMRuntime`, `make_llmvm_environment()`, `_chunk_text()`, `_estimate_tokens()`, `list_forge_plugins()`, `resume_mission_log()`
- `apps/dottie/dottie/background_orchestrator.py` — `BackgroundOrchestrator`, `scan_goals()`, `_triple_write_timeline()`, `_make_7field()`
- `apps/dottie/dottie/rlm.py` — `make_rlm_environment()` auto-wires llmvm env (graceful degrade standalone)
- `apps/dottie/dottie/engine.py` — `run_task_llmvm()` parallel to `run_task()`, `schema_version 1.0.0-llmvm`, fields `engine=llmvm`, `llmvm.answers/locals/turns/thread_id/compiled_program`
- `apps/dottie/tests/test_llmvm_deep.py` — 10 smoke/unit tests
- `bundles/cron.d/background_llmvm_orchestrator.json` — interval@300s owner `goal:goal_ec4f28c2bfbf`
- Logs: `goals/refine-dottie-*/hidden_files/cron_health.jsonl`, `hidden_files/brief-auto-exec-checkpoints/`, `.scout/missions/_cron/timeline.jsonl`

#### Why Dottie wins over vanilla llmvm too

- llmvm is heavy: playwright, pdf, yfinance optional imports, OpenAI-only. Dottie keeps zero_deps true, reuses `PolicyProvider` (ollama/ava/echo).
- llmvm original uses FAISS + tiktoken hard dep. Dottie mimics chunking + keyword rank + random jitter + map-reduce decision without dep.
- llmvm thread-to-program compiles but doesn't feed factory. Dottie feeds compiled programs to `data/programs/` → skill registry → flywheel RFT export → GRPO.

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
  rlm.py                     # RLM v2 — persistent REPL + programmatic rlm(...)
  llmvm.py                   # NEW v2 deep: CPS + chunking + map-reduce + forge discovery + resume
  background_orchestrator.py # NEW: autonomous loops, goal scanner, 7-field triple-write
  harness_continual.py       # Continual Harness v2 — versioned, snapshot, refine
  sessions.py                # daemon-backed sessions, registry, messaging
  goals.py                   # persistent goals + progress
  heartbeat.py               # heartbeats/schedules
  engine.py                  # CodeAct loop + llmvm run_task_llmvm + trace capture
  policy.py                  # Ollama/Ava/Echo
  flywheel.py                # RFT export, mint, eval, train
  climb.py                   # measured hill-climb
```

`workspace/.dottie/` and `workspace/.scout/missions/` are gitignored — durable local state, like prime's `.prime/` but with Scout's timeline contract.

---

## License

MIT — like prime-agent. Dottie's factory, forge, and ACNE additions also MIT.
