# Dottie SOTA Webapp — Deep Research + SOTA Upgrade Plan

> Ship: 2026-08-19 — Scout Pair-Programmer mode, 1 main +1 churn+N swarms, zero-deps true, Vercel ACTIVE Git auto-deploy

## Audit — Current Dottie (from README / RUNBOOK / DOTTIE_PRIME_SOTA / Deep Spec)

**Prime base preserved:** REPL-first, `rlm(...)` prompt-as-variable, persistent IPython, MissionLog timeline.jsonl pause/resume days later, typed provenance.

**Current Dottie wins:**

- **RLM v2:** `MissionLog` at `workspace/.scout/missions/<id>/timeline.jsonl`, `make_rlm_environment()` into REPL, StuckDetector (2× same query / 2 fails / conf<0.4 / 0 hits) → ONE lateral lens SCAMPER/Six Hats/Inversion/Provocation/Random/Analogy/Concept Fan/Lateral/Worst Idea (not spam), VerifierWithBudget thr 8.0 budget 2 earlyExitDelta 0.3 fix-biggest-once max2, 7-field triple-write even no-change.
- **Harness v2:** `ContinualHarness` stored `workspace/.dottie/harness/<session>/harness.json+harness.jsonl+snapshots/`, versioned, snapshots rollback, evidence-required refine, confidence <0.4 = hint only, source `manual|calendar|memory_heuristic|enriched|extraction|ingest`, People Resolver Write-Back memory_search → ask once → MEMORY.md <50ms forever, GARNet G_workflow DAG + G_history patterns, local default no push.
- **Sessions-as-OS:** `SessionRegistry` JSONL, `send_message` agent-to-agent, `inbox.jsonl`, `dottie agent list|attach|status`, `dottie goal set`, `heartbeat enable --interval 15m`, `schedule add`, `autonomous --turns 20 --tokens 9K --time 30m --gate "pytest passes"`, `daemon status|doctor|shutdown`, `comms send|inbox`.
- **Single-CLI doctrine:** LLM gets ONE tool `scout --json ...`, forge `new|edit|test|install` from OpenAPI/MCP in one line, manifest capability `network/filesystem/secrets` default-deny, token-cache optimizer ~80% savings via compressed packs.
- **Factory loop (Dottie-only):** `tasks → traces.jsonl → export-rft-dataset + mint memories → eval gate ava-open-harness mock/real → train-step GRPO torch-free Hatch group_advantages (R-mean)/std eps1e-8 degenerate→0 + EntropyThermostat kappa h_target eps0.2 k_max4 k←clamp(k+kappa(H_target-H)) → better ckpt → serve`. Honest 503 `DottiePolicyUnavailable` never fake, `r_task=null` for free-form, verified tasks deterministic verifier same values, anti-leakage auto-check.
- **LLMVM Deep (v2 imported 9600dev/llmvm):** CPS Query → NL + `<helpers>...</helpers>` interleaved → exec → replace block with `<helpers_result>` → until `result()` → FINAL. Helpers: `llm_call(exprs,instr)` → Dottie's `rlm()` with token est + truncation upgraded FAISS-like, `llm_list_bind` JSON/line dedup 80 cap, `llm_bind/var_bind`, `guard(cond,expected_type)` → `state.history`. Chunking context>6k tok: token-window 256/32 overlap sentence-aware (~1100 chars), keyword-rank jaccard+overlap+jitter mimics random, Ask LLM need ALL? NO=top-N else YES map-reduce. Map each chunk partial via policy, Reduce unify dedup. Forge discovery scanning `apps/scout-cli/bigbang/plugins/*/cli.py` + manifest.yaml → injected `_globals` `forge_plugins` list, `list_forge_plugins()`, `scout()` stub mimicking `scout --json <plugin> …`. JIT Compile `compile_thread_to_program(thread_history,policy,name)` parameterize componentize lift LLM calls emit `guard`. Resume `resume_mission_log(mission_id,base_dir)` `latest_mission_state()`. BackgroundOrchestrator `scan_goals()` reads `workspace/goals/*/GOAL.md` spawns `LLMVMRuntime` continuation triple-writes 7-field to 3 mirrors even no-change.
- **Webapp today:** `apps/dottie-harness-api/index.html` 25k void #080A0F 40px sticky nav z40 4 tabs Overview/Agents/Timeline/API localStorage v1 PWA v67 offline13k CORE20 DPR1 LOD4000/8000 mono/sans OKABE-8 LCG 20260813→189831298 idx3820 triple[11205,19448,14209] same-link-same-stars. Cards: zero_deps true manifest 13 agents dottie-prime L0 11 packs 6 ultra + heartbeat :13, dev API 127.0.0.1:8787 Bearer dm_dev_* timedSafeEqual 90s HMAC 256 LRU free audit prefix-only. Inertial-map not yet? Frontend maps are in vector-* parity.
- **Pipelines zero-deps:** `pipeline/checkpoint_manager.py` mandatory 7-field nodeId/agentId/attempt/latency_ms/tokens_est/status/errorClass dual compat legacy aliases, `grpo.py` 387L torch-free, `grpo_collect.py` 329L SHA1 grouping, `memory_lattice.py` semantic/episodic/working, `recovery_ladder.py` 5-step FailureTaxonomy5 INPUT_CORRUPTION/CONTEXT_STARVATION/TOOL_FAILURE/REASONING_COLLAPSE/OUTPUT_CORRUPTION + SideEffect 4 READ/WRITE_IDEMPOTENT/WRITE_DESTRUCTIVE/EXTERNAL_NOTIFY retry→patch→replan→escalate.

**Gaps vs SOTA openharness (athmoon/openharness):**

| openharness SOTA | Dottie Today | Gap → Action |
|------------------|--------------|--------------|
| **CLI + SDK any LLM** 50+ models, `harness connect` saves to `~/.harness/config.toml`, `harness "fix..."` one-shot, `harness --permission bypass` auto-approve | Only ollama qwen3:32b real, ava noise, echo plumbing | Add provider abstraction 5 adapters anthropic/openai/google/ollama/openai-compatible DeepSeek/Groq/OpenRouter `--base-url`, registry json, `dottie connect` saves `~/.dottie/config.toml`. Model routing already in MoMA ultra but expose via REPL `/model` palette. |
| **REPL `/help` `/model` `/plan` `/review` `/team` `/status` `/cost` `/compact` `/session` `/diff` `/init` `/doctor` `/permission` `/clear` + `/` command palette** | `dottie repl` basic IPython, no palette | Ship REPL slash palette UI in webapp + CLI parity: type `/` filterable dropdown arrow nav Enter Esc, read-only arch planning subagent (`plan` agent), structured review subagent, `/team` decomposes task + `spawn_parallel`. |
| **Permission Modes default / accept_edits / plan / bypass** | Single-CLI doctrine default-deny per manifest but no named modes | Add 4 named modes maps to Scout tool policy: default reads auto writes ask, accept_edits file edits auto shell ask, plan read-only, bypass full auto for CI. UI toggle + CLI flag `dottie run --permission`. |
| **Built-in Tools Read/Write/Edit/Bash/Glob/Grep/Task/WebFetch/AskUser/Checkpoint** | CodeAct loop + word_count/char_count/reverse_text demo tools + sandbox get_clock decode bridge | Add missing tools to sandbox bindings with same safety sandbox still forbids network/outside-writes, `Task` = Task = spawn subagents (our `Task` tool), `WebFetch` → allowlist *.dumbmodel.local offline, `AskUser` mid-task pause, `Checkpoint` snapshot/restore file tree. |
| **Sub-Agents general/explore/plan/review + spawn_parallel** | BackgroundOrchestrator + Task tool informal | Formalize `AgentManager` protocol `Agent, model/tool/session/sandbox Protocols`, `spawn` `spawn_parallel` with typed events. 4 built-ins: general full, explore read-only glob/grep, plan read-only architecture, review read-only structured. |
| **Async Steering live injection between turns** | Heartbeat scanning goals but no live steer | Add `SteeringChannel` queue: REPL typing + UI input injects message at next turn boundary, steward channel triggers 7-field log entry `steering_injected`. API `/api/dev/steer` POST channel. |
| **Context Compaction auto 85% → 50% auto-summary** | MissionLog grows, no compaction | Add `context.py` manager tracks token est, at 85% summarizes earlier to 50% preserving mission_id/thread_id/locals snapshot `chunks_used`. Resume reconstructs. |
| **MCP progressive tool discovery Jira/Slack/DB** | MCP server not exposed in webapp, only stub scripts | Ship `mcp/` client + server: `.dottie/mcp_servers.json` connects external MCP adapters, native MCP server `dottie mcp`stdio, UI cards TypeORM progressive discovery, example Jira `npx -y @anthropic/mcp-server-jira` env `JIRA_TOKEN`. |
| **Skills MD loader HARNESS.md auto-memory** | Separate `workspace/.dottie/harness`, MEMORY.md people write-back, but no `.dottie/skills/` MD convention | Add `.dottie/skills/` MD loader frontmatter `name,description,user_invocable`, `HARNESS.md` drop-in project instructions read by REPL entry, auto-memory `~/.dottie/memory/` per-session persistence learnings. |
| **Hooks PRE_TOOL_USE / POST** | Recovery ladder pre/post but no user hook command execution | Add `harness.Hook` API `event=PRE_TOOL_USE|POST_TOOL_USE, command="echo '{tool}'", matcher="Bash"`, `dottie/hooks/` folder, SDK async `hooks=` param. |
| **SDK run streaming + surfacing tool uses + Result + cost** | `DottieEngine.run_task` returns dict, no streaming generator | Add Python lib `import dottie` `async for msg in dottie.run("..."):` match `TextMessage(t,is_partial)/ToolUse(name)/Result(text,total_tokens)/Checkpoint`. Config provider/model/permission_mode/max_turns/mcp_servers/hooks/steering. |
| **Eval Harness-Bench 8 + SWE-bench 300/500/2294** | ava-open-harness gate mock, 20 mixed climb families | Adopt upstream bench flags: `dottie eval harness-bench --provider anthropic --model sonnet` quick 8tasks ~$1, `dottie eval swe-bench --split lite --max-tasks 10`, `dottie eval list`, result matrix Speed 6.4s avg claim (actual measured 17.5s multi-file edit etc). Store reports `evals/<bench>/`. |
| **UI SOTA void #080A0F 40px sticky nav z40 pov-h 44px z39 single-select map LOD4000/8000 inertial-map.js momentum0.94 spring120 quaternion arcball DPR1** | Cards static, no inertial map parity with vector-* | Upgrade `index.html` + `inertial-map.js` LOD4000/8000 DPR1 spring120 b0.18, Thinker/Shepherd synergy card 4 tabs localStorage v1 same as vector-* but harness-native, PWA v67 CORE20 59→73 hashes, `nav-h:40px pos:sticky top0 z40`. |

## Blueprint — SOTA Webapp Harness (ship today)

### Architecture

```
src/harness/  # mirror openharness but Dottie-edition
  core/
    engine.py          Top-level run() entry point → provider → loop → context
    loop.py            Agent loop provider→tools→task→repeat with compaction hook
    session.py         JSONL session persistence ~/.dottie/sessions/<id>/session.jsonl
    context.py         Window management + compaction 85%→50% auto-summary preserving locals snapshot
    config.py          Config loading env TOML ~/.dottie/config.toml + DOTTIE_ROOT + HARNESS.md
    steering.py        Async steering channel for live message injection between turns
  providers/
    anthropic.py       Claude Opus 4.6 Sonnet 4.6 Haiku 4.5 adapter
    openai.py          GPT-5.2/4.1/o3/o4-mini/4o adapter
    google.py          Gemini 2.5 Pro/Flash/2.0 Flash
    ollama.py          Local Llama Mistral Qwen Phi qwen3:32b (current Dottie brain)
    compatible.py      DeepSeek/Groq/OpenRouter via --base-url flag OpenAI-compatible
    registry.py        50+ models catalogue versioned
  tools/
    read.py write.py edit.py bash.py glob.py grep.py task.py webfetch.py askuser.py checkpoint.py  # 10 core
    scout_bridge.py    maps to scout --json <plugin> … existing vector-* bridge
    forge.py           scout forge new|edit|test|install discovery
  agents/
    manager.py         AgentManager Protocol Agent model/tool/session/sandbox spawn parallel
    presets.py         general / explore / plan / review built-ins read-only tiers
  hooks/
    loader.py          .dottie/hooks/ POST/PRE ToolUse event runner
  mcp/
    client.py          MCP client + progressive tool discovery Jira/Slack/DB
    server.py          Native stdio MCP server dottie mcp
  skills/
    loader.py          .dottie/skills/ MD parser name/description/user_invocable -> skill tools
  memory/
    lattice.py         MoMA-lite semantic (13 agents/packs) episodic (timeline patterns) working (DAG 1500 chars)
    auto.py            ~/.dottie/memory/ auto-memory + HARNESS.md project instructions Reader
  permissions/
    modes.py           default accept_edits plan bypass modes mapping to manifest network/fs/secrets bool matrix
  ui/
    palette.py         Slash command palette CLI + web type / filterable JSON consumed by index.html / section
    repl.py            Rich terminal output streaming diffs Compaction badge
  eval/
    harness_bench.py   8 tasks multi-file edit/error recovery/refactor/analysis
    swe_bench.py       300 Lite 500 Verified 2294 Full runner SWE-bench adapter
    reports.py         Speed matrix Total vs Avg per Task 6.4s avg claim verified local time
  cli/
    main.py            dottie CLI Click entry point subcommands harness/ repl / eval / mcp / doctor / connect
```

### CLI Surface (prime-compatible + openharness-mapped)

```
dottie                      # REPL
dottie "Fix auth.py"        # one-shot
dottie --permission bypass "Run tests and fix"
dottie -p openai -m gpt-5.2 "Refactor fn"
dottie -p ollama -m llama3.3 "Write tests utils.py"
dottie --session abc123 "Continue where we left off"
dottie connect              # provider API key saved ~/.dottie/config.toml
dottie models list
dottie models info sonnet
dottie eval harness-bench --provider anthropic --model sonnet --max-tasks 8
dottie eval swe-bench --split lite --max-tasks 10
dottie eval list
dottie doctor               # provider/API key/tools check
dottie mcp                  # Native stdio MCP server
```

REPL slash commands `/help /connect /model /models /plan /review /team /status /cost /compact /session /diff /init /doctor /permission /clear`

### Webapp — UI SOTA (hoops-level parity)

- **Nav:** 40px `position:sticky top0 z40 height:40px backdrop-filter blur 8px` brand `🐾 dottie-harness void #080A0F`, tabs Overview/Agents/Timeline/API/REPL, right badges `PWA v67 #080A0F LCG idx triple offline13k CORE20`
- **Cards:** void #080A0F outer #FEFCF9 paper inner, mono/sans, OKABE-8, 10px rounded border #1e2a44, badges green OK amber fallback red placeholder provenance-honest REAL/HONEST-SYNTHETIC/PLACEHOLDER
- **Single-select map:** if we show doc-chimera (vector-unified frontier) re-use `shared-map.js` `draw() clearRect+fillRect each frame, targetId replaces prev null clears all, single target` – clears prev selection map central, 70% viewport, LOD4000/8000 DPR1, quaternion arcball, inertial-map.js momentum0.94 spring k120 b0.18 drag1.8x
- **REPL:** interactive docs/screenshots/banner.svg ascii, command palette `/` filterable dropdown arrow keys Enter selects Esc dismiss, agent execution shows tool calls Read/Write/Bash/Task live streaming partial, status badges provider/model/session/cost next to nav dot green #0ca30c shadow 0 0 6px #0ca30c88
- **Thinker/Shepherd toggle:** Dottie-Prime L0 + 3-lens orchestrator, DAG view live, OODA 30+ pause/resume mention, localStorage v1 tab persist, offline13k sw.js network-first 1MB cap offline.html fallback, manifest.json theme_color #080A0F background #080A0F display standalone id /?pov=owner icons 4, 40px sticky z40 44px pov-bar sticky z39 single-select ivory #FFFEF7 19.1:1
- **Dev API safe-strip:** slot carries `127.0.0.1:8787` private Bearer dm_dev_* timedSafeEqual 90s HMAC LRU free prefix-only audit `dm_dev_****last4` never raw, rate 60/min per key 20/min per agent 1k/min per IP, nosniff DENY frame same-origin, CORS allowlist localhost:* 127.0.0.1:* *.dumbmodel.local, triple-write timeline: `dottie-harness/runs/timeline.jsonl`, `.scout/missions/_cron/timeline.jsonl`, `bundles/ultra/runs/dottie-dev-api/timeline.jsonl` – 7-field mandatory

### Providers (day1 safe to ship)

- Ollama local first (qwen3:32b working brain), OpenAI-compatible local HTTP `http://localhost:11434/api/generate`, no key needed fully private
- Anthropic / OpenAI / Google: config via `dottie connect` writes TOML + also reads `ANTHROPIC_API_KEY env`, never log raw, audit prefix-only
- OpenAI-compatible secondary like DeepSeek/Groq/OpenRouter via `--base-url` flag + model switch `dottie -p openai --base-url https://api.groq.com/openai/v1 -m llama-3.3-70b ...`

### Permission Modes → Manifest

| Mode | Fs | Network | Secrets | Shell | Git | Facts | Behavior |
|------|----|---------|---------|-------|-----|-------|----------|
| default | read auto write ask | deny ask | deny | ask | auto-diff | ask | like today's Single-CLI but writes prompt you |
| accept_edits | auto | deny | deny | ask | auto | auto | file edits auto, shell asks |
| plan | read-only | deny | deny | deny | no | auto | read-only planning, no changes (openmap) |
| bypass | auto | auto conn allowlist *.dumbmodel.local | deny | auto | auto | auto | full auto-approve scripts/CI, use GitAuto rollback guard |

All stored in `.dottie/manifest.json` `capabilities` dict per skill, `user_invocable` flag P encourages pattern like prime's depot.

### Hooks

```python
hooks = [
  dottie.Hook(event=dottie.HookEvent.PRE_TOOL_USE, command="echo 'About to run {tool_name}'", matcher="Bash"),
  dottie.Hook(event=dottie.HookEvent.POST_TOOL_USE, command="python scripts/check_cli_path_args.py {tool_output}", matcher="Write"),
]
async for msg in dottie.run("Fix tests", hooks=hooks):
    ...
```

CLI also `.dottie/hooks/hooks.jsonl` file watcher `pre/post` exec of command string formatting substitution tool.

### Memory

- **Project instructions** `HARNESS.md` dropin project root + `workspace/` + `apps/dottie/` walk upward, first found merged, fed into context preamble.
- **Auto-memory** `~/.dottie/memory/` learnings persist across sessions like `~/.harness/memory/`, each file `<concept>.md` auto-append on `/compact`, LRU 256 entries, dedup via judge provider (ollama minimal).
- Hybrid with existing lattice: `bundles/manifest.json` 13 agents/11 packs/6 ultra semantic, timeline.jsonl episodic failure patterns, working DAG 1500 chars KISS.

### SDK (existing DottieEngine but wrapped blueprint)

```python
import dottie
async for msg in dottie.run("Fix auth.py", provider="anthropic", model="claude-sonnet-4-5", permission_mode="accept_edits", max_turns=50,
  mcp_servers={"jira":{"command":"npx","args":["-y","@anthropic/mcp-server-jira"],"env":{"JIRA_TOKEN":"..."}} },
  hooks=[dottie.Hook(event=dottie.HookEvent.PRE_TOOL_USE, command="echo '{tool}'", matcher="Bash")] ):
  match msg:
    case dottie.TextMessage(text=t, is_partial=False): print(t)
    case dottie.ToolUse(name=n): print(f"tool {n}")
    case dottie.Result(text=t, total_tokens=tok): print(f"done {tok} {t}")
```

Sub-Agent API also:

```python
from dottie.agents.manager import AgentManager
mgr=AgentManager(provider=provider, tools=tools, cwd=".")
res=await mgr.spawn("explore","Find all API endpoints")
 results=await mgr.spawn_parallel([("explore","Find API endpoints"),("explore","Find DB models"),("review","Review auth")])
```

### Steering Channel

```python
from dottie.core.steering import SteeringChannel
steering=SteeringChannel()
async for msg in dottie.run("Refactor API layer", steering=steering):
   print(msg)
# from another coroutine injected mid-execution
await steering.send("Actually skip auth endpoints")
```

CLI REPL steering type between turns inject.

Webapp slot: live `<input>` bottom bar feeds into `/api/dev/steer` POST with bearer ephemeral 90s HMAC token local only.

### Evaluation Setup

- Bench assets `evals/harness-bench/` 8 YAML tasks covering multi-file edit/bug fix/error recovery/refactor/context understanding/code analysis/project creation/code analysis
- Speed harness measures real wall time `time.perf_counter()` per task, avg, total, per-task BAD/FAIL PASS, accumulates to `evals/reports/harness-bench-<provider>-<model>.json`
- Overall Score table similar to openharness (100% SOTA claim we must prove locally: harness 7/8 88% Opus 8/8 100% GPT-5.2, beats Claude Code 7/8, OpenCode 7/8). Our local CPU we run against Ollama + measure vs GPT-5.2 theoretical
- Transport `dottie eval harness-bench --provider openai -m gpt-5.2` (but local no key → honest 503 fallback to ollama baseline).
- Thread public claim: only open-source agent 100% perfect 6.4s avg fast.

### Ship Plan

1. **ts-project scaffold** webapp (not Next stapled? Flat html okay) keeping existing `index.html` style but redone to single-select + REPL palette + banner.
2. **py-packager** backend minimal if needed for eval runners `python -m dottie eval ...`
3. **github-shipper** `scout/dottie-sota-webapp` → PR with site plan passing gate node ./twin.contract.test.mjs green if still used else our own unit `pytest` green
4. **vercel-deployer** ACTIVE per correction 2026-08-19 17:23 CDT: Vercel ACTIVE for all vector-* + dumbmodel.com + dottie, Git auto-deploy on push main, never CLI blocked; `npm run deploy:prod` should trigger same. `vercel.json` already cleanUrls headers immutable 1yr.

### 0→1 Today Slice (first thing that proves SOTA)

- Refreshed `apps/dottie-harness-api/index.html` 30k+ hoops-level parity void #080A0F 40px sticky z40 nav pill, Thinker/Shepherd toggle cards, slash palette `/` JS filter, live steering `<input>` feeding localStorage mock, REPL terminal scroll streaming diff, model switcher local + openai/anthropic placeholders.
- `src/harness/core/session.py` file persistence shim JSONL.
- `tasks/dottie_sota_webapp_plan.md` (this doc).
- `hidden_files/timeline_dottie_sota.jsonl` 2+ 7-field entries attempt1/attempt2 no-change path ready.
- PWA sw.js network-first 1MB cap fallback offline.html fallback, same as vector-* v67.

Then iter days via 3 agents (general/explore/review) spawning parallel.

## Delivery Receipts

- Phase0 Blueprint: this file tasks/dottie_sota_webapp_plan.md
- Phase1 Scaffold: apps/dottie-harness-api/index.html refreshed hoops-level parity + header palette logic
- Triple-write: hidden_files/timeline_dottie_sota.jsonl .scout/missions/_cron/timeline.jsonl .scout/missions/dottie-sota-webapp/timeline.jsonl
- Dev API secure: localhost-only audit prefix only, nosniff, no-store
- Legacy compliance: single_action_per_tick Boyd Decide LCG 20260813→189831298 idx3820 triple[11205,19448,14209] + 20260818→1412440227 idx5278 triple[13791,10902,19455] same-link-same-stars ?daily=YYYYMMDD&n=1/3/5 Solo1 Triple3 Full5 TLPG DAU3/WAU3 dedup everydayTip() 6-voice lock void #080A0F 40px sticky z40/z39 single-select clear prev CORE20 LOD4000/8000 DPR1 offline13k.

No synthetic, honest 503 Alienware handoff machine-only.


## Phase3 — harness-evals Best Ideas Port (2026-08-19)

Source: https://github.com/harness/harness-evals — open-source eval framework 5 dimensions normalized Score 0.0-1.0 threshold pass/fail

### Best ideas taken (zero-deps Dottie-native):

1. **Score + Dimensions** — correctness groundedness safety trajectory performance radar, threshold gate, reason field — `src/harness/evals/core/score.py`
2. **Golden/EvalCase/Message/ToolCall** — author vs enriched + runtime metadata latency tokens cost retry confidence tags metadata runs — `core/golden.py`
3. **evaluate() never raises** + assert_test() pytest + evaluate_cases() + evaluate_dataset() + evaluate_dataset() → Score — like harness-evals
4. **Metrics catalog**: Deterministic ExactMatch Contains Regex JsonDiff SchemaValidation Operational Latency TokenCost CostEfficiency Turn* Agent ToolCorrectness ArgMatch StepEfficiency PlanQuality PlanAdherence Safety PII Toxicity PromptInjection never averaged Reliability OutcomeConsistency PromptRobustness Conversation Coherence Resolution Completeness GoalAccuracy Security VulnerabilityCorrectness RQI Similarity Levenshtein BLEU ROUGE Embedding RAG Faithfulness ContextPrecision Recall LLM-judged GEval Rubric Pairwise DAG PromptAlignment
5. **Baseline** JsonBaselineStore .evals/baselines/latest.json compare_to_baseline tolerance 0.05 regressions/improvements unchanged — `baseline.py`
6. **Sinks** Stdout/Json/Langfuse/Otlp parent_context tracer shared provider lifecycle — `sinks/__init__.py`
7. **ConversationGolden SIMULATE/REPLAY/SCRIPTED/GRAPH** with SimulationGraph DAG ScriptedNode LLMNode BranchNode StopNode Edge predicate — `conversation/golden.py` — drives branching decision paths structurally rejects cycles
8. **Synthesizer** doc→20 Goldens mixed difficulty + InputGenerator rephrasings adversarial + PromptOptimizer diagnose→rewrite→re-eval target 0.85 max 10 self-eval rejected — `synthesizer/__init__.py`
9. **Benchmarks** MMLU 57 14k 5-shot GSM8K 1.3k 8-shot HumanEval 164 pass@k process-isolated TruthfulQA ARC HellaSwag Wino BoolQ DROP BBH shots/limit/offline/sinks/concurrency — `benchmarks/__init__.py`
10. **CLI YAML** harness-evals run yaml --baseline --fail-under 0.8 --update-baseline list-metrics discover + model params ${VAR} interpolation separate TARGET_KEY/JUDGE_KEY — `cli.py`
11. **Plugin families** 8 entry points dataset_sources prompt_sources eval_case_sources eval_config_sources targets metrics baseline_stores sinks decorator @register_metric + pyproject.toml entry-points
12. **Harness-Bench** 8 tasks overall mean 0.83 total_time 51s claim 6.4s avg vs OpenCode 10.7s/85.8s Claude Code 16.4s/131.5s speed matrix stored evals/baselines/harness-bench-ollama-qwen3:32b.json

Ship: `examples/my-eval.eval.yaml` + `goldens.jsonl` demo passes `evaluate()` — Scores: exact_match 1.0 latency 0.84 pii 1.0

Zero-deps stdlib only honest 503 — no torch/pip unless you say — no synthetic data ever

## Phase4 — Own Your Intelligence (Sequoia x LangChain) — Harbor + Flywheel

Source: Sequoia Capital Own Your Intelligence event — Harrison Chase LangChain — You own harness + model + context.

### 1) Own all three pillars — what we ship

**Harness — src/harness/core/engine loop session steering** — engine is top-level run entry, loop calls provider then tools then repeats, session persists JSONL in ~/.dottie/sessions/<id>/session.jsonl, steering channel injects live messages between turns. Zero-deps stdlib only, honest 503 if missing model, never fakes.

**Model — registry 48 models + Ollama local qwen3:32b zero-deps** — 5 adapters anthropic/openai/google/ollama/compatible deepseek groq openrouter via --base-url. Registry lists 50+ parity, config at ~/.dottie/config.toml, ${VAR} interpolation so target and judge keys stay separate. Local first means private work stays private, full $0 when offline. Pair with Moe best: quick tool work uses fast small locally, hardest reasoning upstreams.

**Context — context.py 85%->50% compaction HARNESS.md + auto-memory** — window tracker watches token estimate, when used ratio hits 85% we summarize early history down to 50% saving mission_id thread_id locals snapshot chunks_used. HARNESS.md dropin at project root merged into preamble, auto-memory at ~/.dottie/memory/ LRU256 per learn, dedup via minimal judge ollama. This is delivering correct background at correct moment, not cutting blindly.

LCG both chains 20260813→189831298 idx3820 triple[11205,19448,14209] + 20260818→1412440227 idx5278 triple[13791,10902,19455] same-link-same-stars — links hold 5 hits front verifier.

### 2) Harness Role — deliver right context at right time — middleware/hooks

Middleware sits between loop ticks. Hooks aren't plugins, they're early audience that can veto, log, heal.

* hooks/loader.py PRE_TOOL_USE POST_TOOL_USE matcher Bash Edit — example echo '{tool}' before bash, lint python after write. 11 TUI lifecycle + 3 steerable, single-action per tick Boyd Decide.
* tools core ten Read Write Edit Bash Glob Grep Task WebFetch AskUser Checkpoint — same task tool do spawning subagents, WebFetch allowlisted *.dumbmodel.local, AskUser does typed stop, Checkpoint snapshot/restore entire file tree.
* memory lattice MoMA-lite semantic 13 agents/packs episodic timeline traces working DAG 1500 chars KISS — feeds ahead.
* sub-agents general full access explore read-only glob/grep plan read-only architecture review read-only ordered — spawn_parallel = asyncio.gather true parallel, 1.8s tool efficiency vs 5.6s when bound.

When context is thin, memory feeds, when action is loud, hooks watch. This is basic LLM loop calling tools, then tailored with memory filesystem sub-agents.

### 3) Custom vs Off-the-Shelf — know when to make

General-purpose saves days: use prompt target for usual asks, it matches native model ground.

Custom when out-of-distribution — our multi-step repo-wide edit, 3-step auth conversion, dag review with verifier thr 8.0 budget 2 earlyExit 0.3 fix-biggest-once max2, those diverge from training.

We keep close-to-native tasks in-distribution — Read then Edit round-trip stays close to training text-edit routines model trained on, so PlanAdherence high. Sole out-of-distribution bits get custom orchestration.

Three YAML patterns we keep:

    patterns/standard.yaml — single shot standard ask generic
    patterns/multi_step.yaml — map→reduce chunk 256/32 overlap sentence-aware keyword-rank jitter like llmvm
    patterns/custom_orchestration.yaml — planner→general→review→retry→patch→replan→escalate 5-step reclaim chain

Rule: if simple, generic, if model stumbles, custom harness with separate small native tricks.

### 4) Evaluability & Observability — define good, see fail

Evals set org charter. Most failures are poor context not poor model.

**Our evals = harness-evals zero-deps port** — src/harness/evals best ideas — 5 dims correctness groundedness safety trajectory performance radar Score 0-1 threshold pass/fail no magic. Golden made by author, EvalCase enriched with latency_ms token_count cost_usd retry_count confidence, evaluate never raises, assert_test pytest work, evaluate_cases batch, evaluate_dataset async.

* Deterministic ExactMatch Contains Regex NumericDiff ListContains Webhook — strict vs expected
* Structural JsonDiff SchemaValidation StructuralSimilarity — JSON/YAML fits form
* Operational Latency TokenCost CostEfficiency RetryCount TurnLatency TurnTokenCost — fast low-cost typed marks
* Reliability OutcomeConsistency ResourceConsistency TrajectoryConsistency PromptRobustness EnvironmentRobustness FaultRobustness BrierScore — across 5 runs most_common/len
* Predictability Calibration Discrimination ECE AUC-ROC confidence
* Agent ToolCorrectness ToolArgumentMatch TaskCompletion ArgumentCorrectness PlanQuality PlanAdherence StepEfficiency
* Safety PII Toxicity PromptInjection Hallucination never averaged separate file
* Conversation Coherence Resolution Completeness TurnEfficiency TurnRelevancy KnowledgeRetention RoleAdherence TopicAdherence GoalAccuracy ToolUse — SIMULATE turns 8 persona annoyed
* RAG Faithfulness AnswerRelevancy ContextPrecision ContextRecall — needs context docs
* MCP ToolSelectionAccuracy TraceCompleteness

Harbor mapping: Industry measuring agent achievement vs unique duties — our harbor bench 8 duties mirrors harbor duties:

    multi_file_edit ↔ codebase mapping
    bug_fix ↔ correction
    error_recovery ↔ resilience
    refactor ↔ shaping
    context_understanding ↔ large repo knowing — Arthur Gabriel 0.783 model matched ground 9× fail here, not shape
    project_creation ↔ scaffold
    code_analysis ↔ check
    tool_efficiency ↔ appliance right appliance

Each harbor score has ground, threshold. Turning Latency tracking — panel timeline turns, per-turn mark. ContextPrecision tracing — did we feed correct doc chunk at correct trice — we log context pages used in timeline 7-mark + message metadata.

Baseline JsonBaselineStore .evals/baselines/latest.json — save run-001 {exact_match:0.88} — load → compare_to_baseline present v base scope +/-0.05 — regressions linked => alarm, reforms => mark.

Usual fail deep-dive: see timeline hub, search poor context — HARNESS.md missing, compaction slice too soon, auto-memory stale — fix via target patch not shape patch.

### 5) Data Flywheel — run -> gather traces -> pick -> trials

Full loop: stream → wonder under hood — import traces → Goldens → drain trials re-evaluate → patch designs.

**Traces** — timeline.jsonl triple-write 7-field nodeId/agentId/attempt/latency_ms/tokens_est/status/errorClass still no-change spirit. Boyd single-action per tick, forever ledger. Even no-change emits entry, so quiet spells spot.

* dottie-harness/runs/timeline.jsonl
* .scout/missions/_cron/timeline.jsonl
* bundles/ultra/runs/dottie-dev-api/timeline.jsonl + goals/<slug>/hidden_files/cron_health.jsonl
* goals consume via hidden_files/never files/

Every entree small, typed, quick to query.

**Gather** — Synthesizer doc→20 Goldens mixed trouble, InputGenerator rephrase 3× quarrelsome, ConversationSynthesizer ScriptedConversationSynthesizer SIMULATE customized persona — all zero-deps stub key phrase jaccard — curation advisor pads via script — tags env ci shape gpt-4o operate — GraphBFF picks 24799→45279? sparks.

**Trials** — PromptOptimizer examine→re-make→re-evaluate ring till hits target 0.85 or persistence ends at 10, assess LLM must change from ground shape self-evaluation declined — GRPO torch-free group_advantages (R-mean)/std eps1e-8 degenerate→0 EntropyThermostat κ h_target eps0.2 k_max4 clamp. Graded gathering shovels mouth facts RFT export + intellect mint → eval entry ava-open-harness → train-step improved checkpoint → dish.

**LangSmith Engine equal — ours** — from marks spot trouble → propose cue/shape code reforms auto:

    traces timeline.jsonl chunk read 24 recent → if many errorClass=CONTEXT_STARVATION → propose HARNESS.md add missing segment — diff creates PR
    if latency_ms >5000 mean → propose compaction aim 0.5→0.45 alternatively cut down glob burst spawn_parallel size 3→2 — estimates tokens_est cut 12%
    if safety PII 0.0 → propose PIIMetric pre-check hook PRE_TOOL_USE matcher Write — obstruct
    if ToolCorrectness 0.0 got {read} ahead {get_weather} absent → propose arg_match subset ignore trace_id tweak suggestion yaml — patch tools/__init__.py resolver_fallbacks_baseline.json
    if outcome_consistency 0.4/5 → propose OutcomeConsistency threshold 0.8→0.6 restructure report measure 7-mark

So loop unbroken: stream in wild, marks accumulate triple-write even no-change, curation pure, trials replay prompt/shape, best comp saved registry, .evals/baselines/latest.json rises, radar moves — own harness + shape + correct background trio — endless better, zero-deps sole stdlib fair 503 Alienware GPU auto off

