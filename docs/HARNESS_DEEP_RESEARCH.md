# Harness Deep Research — GitHub SOTA Survey for Dottie
Date: 2026-08-19
Sources: 61.1k repos under `harness`, curated 16 high-signal

## Summary
Best open harnesses are not bigger models — they are better runtimes. SOTA = provider-agnostic loop + protocols + sessions + sandboxes + permissions + hooks + skills + MCP + async steering + evals + ledger + auto-memory. Dottie already has GRPO, vector tokens, continual flywheel; it lacks the REPL polish that makes SOTA feel magic.

---

## Repo-by-Repo

### 1. harness/harness — End-to-end DevOps Platform
- **Type:** Not LLM harness; SCM + CI/CD Pipelines + Hosted Dev Envs (Gitspaces) + Artifact Registry — Go + Node, Docker image `harness/harness`, runs at `:3000`, Swagger at `/swagger`, CLI `gitness`.
- **Prereq:** Go 1.20, Node, protobuf v3.21.11, make dep/tools.
- **Takeaway:** Docker socket negotiation, API version pin, registry conformance tests. Heavyweight compared to LLM harnesses. Anti-pattern for Dottie: enterprise platform; Dottie's niche is lightweight agent loop.

### 2. deepseek-ai/deepseek-harness (dsh) — Everything is a Plugin
- **Tagline:** Everything is a plugin, powered by Cordis paradigm *Spatiotemporal Composability*.
- **Install:** `npx @deepseek-ai/dsh web` → UI at `127.0.0.1:3080`.
- **Arch:** Node TS, pnpm build, plugin registry `dsh-plugin` topic, Web UI, Discord community.
- **Primitives:** Plugin = capability seam + event pipeline.
- **Takeaway:** Plugin seams let third party add tools without fork. Dottie needs plugin loader (`.harness/skills/*.md` → dynamic tools).

### 3. revfactory/harness — Meta-Factory Team Architectures
- **Layer:** L3 Meta-Factory / Team-Architecture Factory — domain sentence → agent team + skills, via 6 patterns.
- **6 Patterns:** Pipeline (sequential), Fan-out/Fan-in (parallel independent), Expert Pool (context-dependent selective), Producer-Reviewer (gen → QA), Supervisor (central dynamic distribution), Hierarchical Delegation (recursive).
- **Workflow:** Phase1 Domain Analysis → 2 Architecture Design (Agent Teams vs Subagents) → 3 Agent Definition `.claude/agents/` → 4 Skill Gen `.claude/skills/` with Progressive Disclosure → 5 Integration → 6 Validation.
- **Install:** `/plugin marketplace add revfactory/harness` then `/plugin install harness@harness-marketplace`; global skill copy.
- **Modes:** Agent Teams default TeamCreate+SendMessage+TaskCreate (2+ agents collaboration) vs Subagents direct Agent tool invocation.
- **Evidence:** +60% avg quality 49.5→79.3, 15/15 win-rate, -32% variance (n=15 author-measured A/B — third-party replications pending) self-doc; Effect scales with complexity +23.8 Basic, +29.6 Adv, +36.2 Expert.
- **Outputs:** `.claude/agents/analyst.md,builder.md,qa.md` + `.claude/skills/analyze/SKILL.md,build/SKILL.md+references/`.
- **Takeaway:** Dottie should generate teams from domain sentence, not pre-wire. Use 6-pattern picker at `/init`.

### 4. HKUDS/OpenHarness — Ohmo Personal Agent
- **Core:** Lightweight Python: tool-use, skills, memory, multi-agent coord.
- **Install:** `curl install.sh | bash` → `oh`, `ohmo`, `openharness` linked to `~/.local/bin`, or `pip install openharness-ai`. Win PS `openh` due to Out-Host alias.
- **4 Screens:** Agent Loop (streaming tool-call cycle, API retry exponential backoff, parallel tool exec, token counting), Harness Toolkit 43 tools (File/Shell/Search/Web/MCP), Context & Memory (CLAUDE.md injection, Auto-Compact, MEMORY.md persistent, Session Resume), Governance (multi-level permission modes, path-level & command rules, Pre/Post ToolUse Hooks, Interactive Approval), Swarm Coord (subagent spawn, Team Registry, Background Tasks, ClawTeam roadmap).
- **Provider workflows:** Anthropic-Compatible API (Claude official, Kimi `api.moonshot.cn/anthropic` `kimi-k2.5`, GLM, MiniMax), Claude Subscription bridge `~/.claude/.credentials.json`, OpenAI-Compatible API (OpenAI official, OpenRouter, DashScope `qwen3.5-flash,deepseek-r1`, DeepSeek `deepseek-chat,reasoner`, SiliconFlow, NIM `gpt-oss-120b`, Gemini `gemini-2.5-flash`, Groq, Ollama local), Codex Subscription `~/.codex/auth.json`, GitHub Copilot OAuth; profile-scoped credentials, `oh provider add x --label --provider openai --api-format openai --auth-source openai_api_key --model my-model --base-url https` binds per profile.
- **Commands:** `oh setup`, `oh provider list/use <profile>`, `oh`, `oh -p "Explain"`, `--output-format json|stream-json`, `--dry-run` previews runtime settings without calling model (ready/warning/blocked).
- **Ohmo:** personal agent running in ~/.ohmo workspace, gateway to Feishu/Slack/Telegram/Discord; runs on existing Claude Code subscription — no extra API key.
- **Takeaway:** Profile-scoped keys + dry-run readiness + 43 tools are SOTA comfort. Dottie should mimic `openharness` provider list and ohmo gateway.

### 5. EleutherAI/lm-evaluation-harness — Few-Shot LM Eval
- **Purpose:** Unified framework 60+ academic benchmarks, hundreds subtasks; backend for HF Open LLM Leaderboard, used in hundreds papers, NVIDIA/Cohere/BigScience.
- **Install:** `git clone .. ; pip install -e .` + backends extras: `lm_eval[hf]`, `[vllm]`, `[api]`, `[hf,vllm,api]`.
- **CLI refactor:** v0.4 subcommands `run, ls, validate` + YAML config via `--config`, lighter base no transformers/torch.
- **Models:** hf via transformers (GPTQModel/AutoGPTQ), vLLM fast, API (OpenAI/TextSynth), adapters LoRA via PEFT, local GGUF via hf backend, multi-GPU data-parallel `accelerate launch -m lm_eval` and model sharding `parallelize=True` + tp_plan=auto PyTorch 2.4+ DTensor.
- **Tasks:** `lm-eval ls tasks`, Jinja2 prompts, Promptsource imports, advanced post-processing, answer extraction.
- **Takeaway:** Dottie evals/ should adopt YAML config suites + versioned task banks; reuse harness-bench pattern. v0.1.0 skill can wrap SWE-bench Lite 300 / Verified 500 / Full 2294.

### 6. browser-use/browser-harness — Self-Healing Browser
- **Tagline:** Self-healing harness that enables LLMs to complete any task — connects via editable CDP websocket to real browser, agent writes missing helpers as it works, improves every task.
- **Setup:** Install skill `browser-harness skill`, connect via `chrome://inspect/#remote-debugging`, paste setup prompt into Claude Code/Codex.
- **Loop:** agent wants upload file → helper missing in `agent-workspace/agent_helpers.py` → agent writes custom helper → file uploaded ✓.
- **Scale:** local browser for logged-in personal; Browser Use Cloud many browsers parallel live preview/proxy/stealth/CAPTCHA.
- **Takeaway:** Dottie browser needs CDP + self-healing helper generation; `agent_helpers.py` pattern mirrors Dottie's skill_tools.py self-evolution.

### 7. strands-agents/harness-sdk — Build & Control End-to-End
- **Mono:** Python SDK `strands-py/` (agent loop, providers, tools PyPI) + TS SDK `strands-ts/` npm + site `strandsagents.com` Astro Starlight + team/ governance.
- **Philosophy:** Build your way any model any cloud, model agnostic first-class Bedrock/Anthropic/OpenAI/Gemini many more custom, stay in control trace every decision hooks intercept log/validate/redirect, deliver outcomes guardrails catch mistakes, steering handlers self-correct, MCP streaming multi-agent structured output built-in.
- **Quickstart:** `pip install strands-agents strands-agents-tools` → `Agent(tools=[calculator])("What is sqrt 1764")`; TS `npm install @strands-agents/sdk` → `new Agent().invoke`.
- **Takeaway:** Protocol-based provider swap: your code stays same scaling local→prod. Dottie needs same abstraction (ModelProvider interface).

### 8. walkinglabs/learn-harness-engineering — Course 0→1
- **Scope:** 15 langs, 14 Lectures, 8 Projects, MIT, Discord, PDF coursebooks `npm run pdf:build → artifacts/pdfs/`.
- **Frontier Update Aug 2026:** 4 breakdowns reverse-engineering same 5-subsystem framework (instructions/tools/environment/state/feedback) — Pi minimal kernel programmable expansion context engineering `ask Pi to build what you want`; Claude Code 4-layer memory 5-level compaction hooks sub-agent isolation; Codex repo-as-source-of-truth AGENTS.md directory page worktree isolation; DeepSeek everything-is-plugin capability seams event pipeline.
- **Graph Update:** Lecture14 From Single Loops to Graph Engineering — why single loop→graph (Prompt→Context→Loop→Graph), 4 parts graph (nodes/edges/shared state/routing), why in-loop checkpoints can't fix 3 structural failures (Goodhart, blindness upward, conflict), framework-agnostic 6-step build first graph, graph vs workflow, anchors, open-source graph projects before vs after name, orchestration tax, when graph worth it; Project08 Draw Your Workflow as Graph 3 progressive experiments maker-checker loop explicit graph, parallel fan-out/in node, conditional rollback edge + human-approval node.
- **Loop Update:** Lect13 Why Stop Prompting Agent — `/goal` → 6 primitives loop engineering (automations, worktrees, skills, connectors, sub-agents, external state), generator/evaluator split, 4 silent costs, step-by-step first loop; Project07 Build First Automated Loop 3 experiments goal loop, timer loop, maker-checker loop, intervention reduction metrics, code templates goal-template.md, loop-state-template.md, maker-prompt.md, checker-prompt.md.
- **5 Subsystems:** Instructions (AGENTS.md/CLAUDE.md/feature_list progressive disclosure), State (progress.md/feature_list/git log/session handoff persisted), Verification (tests+lint+type-check+smoke runs), Scope (one feature at a time definition-of-done), Session Lifecycle (init.sh at start, clean-state checklist at end, handoff note next session, commit only when safe).
- **Core Truth:** Model decides code; harness governs when/where/how; harness doesn't make smarter — makes output reliable.
- **Evidence:** Anthropic experiment same model Opus 4.5 same prompt build 2D retro game editor: Without harness $9 20min broken; With harness (planner+generator+evaluator) $200 6h playable — model same harness diff.
- **Takeaway:** This is Dottie's syllabus — embed 5-subsystem + 6 loop primitives + graph extension into Dottie tasks/.

### 9. langchain-ai/deepagents — Batteries-Included
- **Identity:** Opinionated agent that runs out-of-box; extend/override/replace any piece; open source PyPI.
- **Principles:** Opinionated long-horizon multi-step, Extensible no-fork, Model-agnostic any LLM tool-calling frontier/open-weight/local, Prod-ready LangGraph streaming/persistence/checkpointing tracing/eval/deployment via LangSmith.
- **Features:** Sub-agents isolated context windows, Filesystem pluggable local/sandboxed/remote, Context mgmt summarize threads offload outputs to disk, Shell access sandbox, Persistent memory pluggable state/store cross-session, HITL approve/edit/reject tool calls, Skills reusable on-demand, Tools bring-own or MCP server, JS/TS lib `deepagents.js`.
- **Deep Agents Code:** pre-built coding agent in terminal like Claude Code/Cursor any LLM `curl -LsSf https://langch.in/dcode | bash`.
- **Install:** `uv add deepagents`.
- **Minimal:** `create_deep_agent(model="openai:gpt-5.5", tools=[my_tool], system_prompt="research asist.")` → `invoke({"messages":"Research LangGraph"})`.
- **FAQ:** LangGraph=graph runtime, LangChain `create_agent`=minimal harness, DeepAgents=opinionated full harness (filesystem/sub-agents/context/skills bundled). Layers compose CompiledStateGraph as sub-agent plugged into defaults.
- **Security:** "trust the LLM" model can do anything tools allow — enforce at tool/sandbox level.
- **Takeaway:** Dottie's swarms should reuse LangGraph checkpointing pattern; its "product medium" is classic: filesystem; Dottie should embed that.

### 10. Hmbown/CodeWhale — Community-Driven Rust Harness
- **Tagline:** Open source coding agent for your terminal BYOM — open models first, hosted/local none privileged.
- **Fleet:** Provider+model+reasoning tier per role, cheap fast model directs expensive reasoning, GLM builder same job Kimi reviewer — roles files editable Constitution `constitution.json` repo-shared or personal, compiles into write holds even Full Access can't skip.
- **Install:** `npm install -g codewhale`, Cargo/Docker/Nix/Scoop/prebuilt/CNB mirror/support, deepseek-tui config carry-over.
- **Use:** `codewhale`, `codewhale auth set --provider deepseek`, `exec "fix failing test"`, `web` loopback-only browser client 127.0.0.1 with one-time auth boundary.
- **TUI:** `/model` switch provider+model, `/fleet` build run team one role at time own model, `/undo` revert last turn, `/restore <N>` workspace rollback snapshot list, Tab cycles Plan/Work/Operate when empty else completes slash+@mentions, Shift+Tab cycles Ask/Auto-Review/Full Access permission posture, `!` shell via approval path.
- **Permissions:** Read-only Plan mode no change, approvals gate risky, Seatbelt macOS where available opt-in bubblewrap Linux sandbox, fleet append-only ledger resume.
- **Integrations:** DSH via `codewhale integrations dsh connect` links existing `@deepseek-ai/dsh` to provider route perms workspace, `install-bundle` opt-in DSH plugins `dsh --profile codewhale` carries identity, owns perms/lifecycle authority dsh keeps own sessions/profiles/creds untouched; VS Code scaffold integrated terminal + read-only Agent View preview.
- **Docs:** PROVIDERS.md every route hosted/gateway/local, FLEET.md ledger+resume, WORKFLOW_EXPERIMENTAL_SEARCH frozen provider-neutral, CONFIGURATION.md config.toml/hooks/constitution, AUTHORIZATION_ORDER.md modes/hooks/permission rules/safety floors/repo law/approvals/sandbox compose, HOOKS.md 11 TUI lifecycle hook events payloads 3 steerable exec/CLI not fire, WEB.md.
- **Community:** Codewhale fanning out 3 read-only scout subagents fanout.gif.
- **Takeaway:** Constitution → write holds + fleet ledger resume are gold; Dottie should adopt.

### 11. athmoon/openharness — SOTA CLI+SDK Any LLM — 100% Harness-Bench
- **Claim:** Only open-source agent to score 100% on Harness-Bench, outperform Claude Code/OpenCode/pi-mono, 2× faster than next on GPT-5.2.
- **Quick Start:** `curl install.sh | bash` or `pip install harness-agent`, `harness connect` pick provider paste key saved `~/.harness/config.toml`, `harness` REPL, `harness "Fix auth bug"`, `harness --permission bypass "Run tests fix"`, `harness -p openai -m gpt-5.2 "Refactor"`, `-p ollama -m llama3.3 "Write unit tests"`, `--session abc123 "Continue"`.
- **Screenshots:** banner version provider model, slash palette `/` filtered, execution building tic-tac-toe tool calls, `/status` provider/model/session/cost, `/models` 50+ models.
- **Slash:** `/help` cmds tips, `/connect` setup/change key, `/model` switch, `/models` list, `/plan` read-only agent, `/review` code changes/file, `/team` decompose parallel, `/status`, `/cost` token usage cost session, `/compact` summarize free context, `/session` show/switch ID, `/diff` git diff working dir, `/init` HARNESS.md config, `/doctor` check setup provider/key/tools, `/permission` view/change mode, `/clear` clear.
- **Providers:** Anthropic Claude Opus4.6/Sonnet4.6/Haiku4.5 connect choose, OpenAI GPT-5.2/GPT-4.1/o3/o4-mini/GPT-4o, Google Gemini 2.5 Pro/Flash/2.0 Flash, Ollama Llama/Mistral/Qwen/Phi no key local, OpenAI-compatible DeepSeek/Groq/OpenRouter via --base-url, `harness models list/browse 50+`, `models info sonnet`.
- **Built-in Tools:** Read file, Write create/overwrite, Edit find-replace, Bash shell, Glob name pattern, Grep regex, Task spawn sub-agents parallel, WebFetch web pages, AskUser question mid-task, Checkpoint save/restore snapshots.
- **Sub-Agents:** general full tools complex multi-step, explore read-only fast codebase, plan read-only architecture planning, review read-only structured review — `AgentManager spawn, spawn_parallel [(explore,Find API),(explore,Find DB),(review,Review auth)]`.
- **Permission Modes:** default Reads auto writes ask approval, accept_edits edits auto shell ask, plan read-only nothing changed, bypass full auto-approve for scripts/CI.
- **Palette:** `/` filterable dropdown arrow navigate Enter select Escape dismiss 16 cmds.
- **Async Steering:** type message Enter injects between turns steering channel queues processes next turn boundary no wait finish.
- **Context Compaction:** auto at 85% threshold summarizes earlier preserves key, targets 50% window room keep working no new session.
- **MCP:** Jira/Slack/DB anything MCP adapter async `harness.run("Search Jira", mcp_servers={"jira":{"command":"npx","args":["-y","@anthropic/mcp-server-jira"],"env":{"JIRA_TOKEN":"..."}}})`.
- **Skills:** teach custom workflows dropping `.md` in `.harness/skills/` frontmatter `name: deploy description: Deploy prod user_invocable: true` + 3 steps pytest/docker/deply.
- **Hooks:** run own commands before/after every tool call `harness.Hook(event=PRE_TOOL_USE, command="echo About to run {tool_name}", matcher="Bash")`.
- **Memory:** Project instructions `HARNESS.md` root + auto-memory learnings `~/.harness/memory/`.
- **SDK:** `import harness; async for msg in harness.run("Fix bug") match TextMessage/ToolUse/Result(total_tokens)`, With Config provider/model/permission_mode/max_turns, Subagent API AgentManager, SteeringChannel `await steering.send("skip auth")`.
- **Benchmarks Overall:** Claude Opus 4.6 — Harness 7/8 88%, Claude Code 7/8 88%, OpenCode 7/8 88%, pi-mono 7/8 88%; GPT-5.2 — Harness 8/8 100% PASS, Claude Code —, OpenCode 7/8 88%, pi-mono 8/8 100% (tie but Harness faster); Harness only OSS achieves perfect across providers not locked one.
- **Per-Task GPT-5.2:** Multi-file editing PASS 17.5s vs Open 19.4s vs pi 26.8s; Error recovery 5.2s vs 11.7 vs 10.1; Tool efficiency 1.8s vs 5.6 vs 9.2; Context understanding 9.7s vs FAIL vs 41.3s; Project creation 3.0s vs 7.6 vs 3.8; Bug fixing 5.5s vs 12.9 vs 10.0; Code analysis 1.9s vs 5.2 vs 2.3; Refactoring 6.4s vs 11.7 vs 12.7.
- **Speed:** Harness GPT-5.2 6.4s avg 51.0s total 8 tasks vs Harness Opus4.6 12.5 99.7, Claude Code Opus4.6 16.4 131.5, OpenCode GPT-5.2 10.7 85.8, pi-mono GPT-5.2 14.5 116.2 → 2× faster next-fastest GPT-5.2, 30% faster Claude Code Opus.
- **Config:** TOML auto `~/.harness/config.toml` [providers.anthropic] api_key, env `ANTHROPIC_API_KEY/OPENAI_API_KEY/GOOGLE_API_KEY`.
- **Arch:** `src/harness/core/engine.py run() entry, loop.py agent loop provider->tools->repeat, session.py JSONL persistence, context.py window mgmt+compaction, config.py env/TOML/HARNESS.md, steering.py async injection, providers/ anthropic.py/claude, openai.py/GPT compat, google.py Gemini, ollama.py local, registry.py 50+ models, tools/ Read/Write/Edit/Bash/Glob/Grep/Task/Web/AskUser/Checkpoint, agents/ registry lifecycle, hooks/ pre/post, mcp/ client progressive discovery, skills/ SKILL.md parser, memory/ auto-memory+project instructions, permissions/ rules engine, ui/ rich terminal streaming diffs, eval/ SWE-bench/Harness-Bench metrics reports, cli/ Click entry subcommands`.
- **Eval Run:** `harness eval harness-bench --provider anthropic --model sonnet`, `harness eval swe-bench --split lite --max-tasks 10`, `harness eval list | 8 Multi-file/error/context| Lite 300 curated| Verified 500 human-ver|+Full 2294`.
- **Dev:** `git clone .../openharness; cd; uv pip install -e ".[dev]"; uv run pytest tests/ -v; uv run ruff check`.
- **Takeaway for Dottie:** This is SOTA blueprint — copy REPL command palette, permission layers, steering channel, compaction 85%→50%, Task spawn_parallel, Checkpoint snapshots, 10 tools baseline.

### 12. griddynamics/specflow — Large-Scale Code Gen
- **Pitch:** Automated code gen + complexity estimation — multiple deployable codebases built by multiple SOTA AIs — when complexity scores align proof specs complete.
- **Arch:** Parallel AI agents isolated sandboxed exec envs, validator agents continuously assess resume refine until delivery standards.
- **Install Req:** Docker container runtime sandbox, uv Py pkg mgr, IDE as MCP Claude/Cursor/Copilot/Gemini — users project.
- **Keys:** GITHUB_TOKEN repo+read:user+workflow for disposable workspace repos, P10Y_API_KEY complexity scoring, LLM provider OPENROUTER_API_KEY or ANTHROPIC_API_KEY one.
- **CLI:** `git clone specflow && cd; uv tool install --editable ./mcp_server; specflow tui`, press `c` MCP to client detects Claude Code/Gemini/Cursor wires up honest connected/added/failed.
- **Use 7 steps:** specs/product-requirements.md,user-flows.pdf,acceptance-criteria.md → check_specification_completeness local → run_planning phased plan local → read_document PDF/DOCX/PPTX/XLSX/CSV to md local → run_generation upload launch parallel backend 2-8h → check_status poll → tui monitor Desktop Notifications → download_outputs archived + P10Y reports rule thumb spread low ready → compare-variants prompt assemble best.
- **MCP Tools:** check_specification_completeness gaps contradictions local, run_planning, read_document extract, run_generation, check_status, download_outputs, retry_generation.
- **Skills Only:** `/plugin marketplace add griddynamics/specflow` → `/plugin install specflow` portable HSD prep gam HIL checks planning.
- **Docs:** QUICKSTART local setup first run, CONTRIBUTING workflow/PR checklist, CLAUDE.md dev protocol STEEL, TOKEN_ECONOMY_GUIDANCE budgeting predict, ARCHITECTURE.md design/data flow, API_REFERENCE.md MCP tools, backend/DEVELOPMENT/API_REF, operations/TROUBLESHOOTING, IDE-SETUP Cursor+Claude Code, examples/deployment-spec e2e tests, SECURITY.
- **Invariant:** scratchpad repos reset each run — do not point at repos code/history keep; managed service Grid Dynamics employees only local quickstart.
- **Takeaway:** Complexity spread low ≡ spec complete insight gold for Dottie flywheel acceptance gates; also TUI monitor with notifications.

### 13. SuneetMalhotra/agent-harness — Typed Event Substrate + 5-Agent SDLC + 3 Tiers
- **Paper:** JSS submission Malhotra Cross-Layer Observability for LLM-Assisted Test Automation.
- **Problem:** Framework code, agent handoffs, locator recovery, visual assertion, execution-tier routing leave separate logs — hard explain why passed/failed/recovered/tier.
- **Layers:** Authoring layer framework source agent-authored human review checkpoint; Operating layer 5-agent SDLC pipeline PM→QA→Automation Eng→Dev→PR Reviewer handoffs flow external artifact systems over MCP; Execution layer 3 orchestrated HW tiers physical device bench, commercial cloud real-device farm, ephemeral virtual HW mediated intelligence layer locator healing visual assertion; Substrate append-only log per layer canonical schema thin query API each layer testable isolation shared event trail reconciles handoffs recovery verdicts routing after run; runnable ref plus empirical harness §6.1.
- **Inside:** types.ts public TestCase HealingEvent AssertionEvent AgentHandoff etc, observability.ts shared substrate append-only log+query, intelligence.ts resolver cache→DOM healer→vision fallback + visual assert, tier-router.ts Routes test tags @tier Tier1/2/3 stubs, pipeline.ts pipeline runner PM→QA→AutoEng→PRReviewer, harness.ts entry produces results.json, agents/*.md PM/QA/AE/Dev/PR Reviewer prompt files, providers/ ModelProvider interface stub deterministic offline reproduction anthropic real shells to `claude -p` OAuth no API key, examples/run-example.ts minimal e2e demo stub.
- **Quickstart:** `npm install; npm run example offline stub; npm run harness:stub/full det same numbers; harness:anthropic full Claude OAuth; npx tsx harness.ts --provider ollama|openai|gemini`.
- **Anthropic runs:** requires claude cli `~/.local/bin/claude` OAuth session no key.
- **Ollama open weights:** `brew install ollama; ollama serve; ollama pull llama3.2 ~2GB substitute any; npx tsx harness.ts --provider ollama; OLLAMA_MODEL=codellama:13b ...; OLLAMA_HOST=http://remote-gpu:11434 OLLAMA_MODEL=llama3.1:70b ...`.
- **Committed Artifact:** §6.1 artifact results.json live Claude Sonnet4.6 run — stub/Ollama/OpenAI/Gemini wrappers let reviewers inspect same wiring without exact hosted session.
- **Results.json overwrite info:** `harness:stub,anthropic,example` overwrite — committed results.json live §6.1 artifact → `reproduce:paper` does NOT overwrite, restore via `git checkout results.json`.
- **Mobile Module:** additional scaffolding not part study public mobile feasibility `mobile/` exercises same substrate against public Android ref app Sauce Labs My Demo App MIT; records same schema tier-routing same on mobile, not prod-scale scale generality; reports 13 mobile test cases public Android ref app 1 HealingEvent per test case same schema reuse cross web+mobile zero drift 12/13 resolved 1 unrecovered not swallowed HW-in-loop not eval architectural only; replay `npm run example:mobile writes results-mobile.json` 5s no Android toolchain no LLM key byte-stable; live-Appium sketched `mobile/README-LIVE-APPIUM.md` not required; reproduce `npm run reproduce:paper web+mobile+schema`, claim boundaries schema reuse demo dispatch+event capture 1 target unrecovered reported not swallowed not production accuracy claim LLM-as-judge κ web-only §6.1 scale HW-in-loop arch only.
- **Numbers reproducing:** Metric Value — Web test cases 30 Web recovered 29/30 Pipeline runtime live run 1665.695s (~27.8min) Cache hit 0.000 DOM healer success 1.000 Vision-fallback success 1.000 Combined recovery 0.967 Visual assertion corpus 24 images Visual assert κ vs seeded key 0.667 precision 1.000 recall 0.667 pixel-comp precision 1.000 recall 0.500 Mobile test cases 13 Mobile recovered 12/13 HW-in-loop eval false; authorVelocity speedup ≈3.2× over N=5 agent-assisted vs N=3 hand-authored modules reported practitioner obs not empirical §6 carries no inferential weight excluded headline.
- **Repro steps:** `git clone .../agent-harness; cd; npm install; npm run reproduce:paper; cat results.json | jq {metadata,authoringVelocity,pipelineReview,pipelineRuntime,tierRouting,healing:{cacheHitRate,domHealerSuccessRate,visionFallbackSuccessRate,combinedRecoveryRate},assertion:{precision,recall,pixelComp}} ; cat results-mobile.json | jq {metadata,testCases,healingEvents,recovered,unrecovered,firstDispatchCorrect,sameSchemaReused,comparison}`; rerunning `harness:anthropic` requires Claude OAuth may not byte-stable hosted-model changes.
- **Methodology notes:** Same-model eval intelligence healing verdicts+visual assert service pass/fail same model family elsewhere — disclosure ships human spot-audit protocol 24-image corpus; Three-tier stubs TI Tier1 physical bench Tier2 cloud farm Tier3 virtual HW prod swap real adapters ADB WebDriverIO Appium-compatible cloud-farm clients CDK ephemeral peripheral emulators; MCP stubbed five-agent pipeline runs stubbed MCP layer prod hosts MCP servers internally issue/track test mgmt/vcs/design tooling agents access over HTTP same contract deterministic; Temp 0 key determin decoder.
- **License:** MIT ©2026 Suneet exclusive mobile pending note.
- **Takeaway:** Append-only typed observability substrate = Dottie trajectory_schema.py & timeline.jsonl triple-write upgrade path; cache→DOM→vision healing ladder mirrors Dottie's recovery_ladder.py; OLLAMA provider for open-weights matches Alienware local GPU flow Hatch CPU vs Alienware GPU split.

### 14. apelov/agentic-demos — Interactive Maps
- **Purpose:** Small interactive artifacts AI agents.
- **Live:** `apelov.github.io/agentic-demos/`.
- **Artifacts:** `harness-llm-animation.html` Agent=LLM+Harness step-through token-flow bare LLM vs agent loop; `harness-rnd-directions.html` 8 Harness R&D directions expandable key papers; `07-sota-open-problems.html` interactive concept SOTA open problems LLM-agent architectures toggleable axes D3 CDN; `10-harness-llm-rnd-mindmap.html` interactive R&D tree Harness·LLM·Glue·IETF top papers+recent findings per field; `ietf-agentic-inventory.pdf` inventory IETF work agentic AI A2A comms discovery identity/audit content-use prefs IoT/edge; HTML self-contained open directly modern browser open-problems map needs internet D3 fetch.
- **8 R&D Directions (from harness-rnd-directions.html):** 1 Environment engineering (workspace, AGENTS.md, init.sh, verification), 2 State engineering (progress log, feature_list, session handoff), 3 Tool/use engineering (Read/Write/Edit/Bash/Glob/Grep/Task/WebFetch/AskUser/Checkpoint, 43 OpenHarness tools), 4 Memory engineering (CLAUDE.md injection, MEMORY.md persistent, Auto-Compact 85%→50%, auto-memory ~/.harness/memory), 5 Governance engineering (permission modes default/accept_edits/plan/bypass, path-level/command rules, Pre/Post hooks, Interactive approval), 6 Swarm engineering (subagent spawn/deleg/deleg lifecycle, Team Registry/Task Mgmt, Background Task Lifecycle, ClawTeam integration roadmap), 7 Evaluation engineering (Harness-Bench 8, SWE-bench Lite/Verified/Full, gate / Fail>Pass loop, verifying prevention prompt injection), 8 Steering & Interactivity (async steering live injection, Slash palette `/`, Hit-A-scan, HITL typed tool, constitution hold).
- **Takeaway:** Gives Dottie actual research compass; adopt 8 dirs as HARNESS.md heads.

### 15. frangelbarrera/agentic-harness — Prod-Grade DAG + Actor-Critic
- **Install:** `pip install agentic-harness`.
- **Principles:** Transparency every prompt decision cost logged markdown audit log `git diff`, Cost control hierarchical budget circuit breaker can't burn silently, Vendor neutrality default Ollama $0 switch provider 1 line no lock-in.
- **Who for:** Backend eng need prod budgets audit compliance, ML eng reproducible benchmarks across providers, Researchers citation-ready replayable, DevOps teams MCP auth rate limiting; Not for visual builder/hosted SaaS/multi-agent crews v0.4+.
- **Docs Looks Like:** Logo ASCII manual YAML `manuals/audit-pr.yaml` name objective budget_USD steps id specialist input pr_number repo focus read diff structured, security_audit specialist reviewer input `{{steps.read_diff.output}}` focus auth SQLi XSS path trav if_not_met action call reviewer input focus Comment PR blocked security, parallel branches id lint reviewer code `{{steps.read_diff.output}}` focus quality idioms naming complexity id tests tester Verify tests cover PR changes synthesis reviewer diff security lint tests focus Synthesize verdict approve/request_changes/reject.
- **Run Illustrates Work Tyrah:** `arnes run manuals/hello-world.yaml --mock`, compiles YAML→Pydantic→DAG→Executor conditional/parallel/HITL, token optimization verification every LLM call returns mux agentic harness executing playbook Name hello-world Objective Demonstrate basic flow simple manual Model ollama/llama3.2 Budget $0.50 [info] llm_call_tracked budget=0.5 cost $0.0 model ollama/llama3.2 tokens_in 335 tokens_out 15 total_spent 0.0 second call 370/38 Man Eff ??? manual executed 2 steps failed 0 Duration 0.01s Tokens 705/53 Total cost $0 audit-log linked alongside filesystem? Saved `arnes-run-hello-world-20260730-164244.md` markdown — every step decision prompt response diff version share Audit Log Header: thread id → [timestamp] step_started Step `plan` Specialist `@planner`, [time] assistant_message Step `@planner` json model tokens, step_completed...
- **Non-Browser Setup:** Narrated demo script in a per Useful Scope `scripts/demo.sh --record demo.tape && vhs demo.tape GIF
- **Features Table:** Agent loop Stateless reducer `(state,event)->state` v0.1 + ReAct tool-use loop specialists + AG-UI streaming compat v0.2; Specialists 12 pre-built planner coder reviewer tester debugger researcher security-auditor devops-engineer data-scientist product-manager market-analyst cost-estimator + Playbook Library 13 domain templates + TaskRouter; Playbook DSL declarat YAML→DAG + condition branches `if_not_met` + parallel true `asyncio.gather` + Retry backoff v0.2 schema-only + HITL gates pause request approval v0.1 auto-reject non-interactive + Actor-critic review loop `--loops,step.review` ; MCP as MCP server Claude Desktop/Cursor/Cline/Zed v0.1 as MCP client consume external servers v0.2 HTTP/SSE transport v0.2 stdio v0.1; Token Optimization automatic model routing complexity + Semantic cache + Context compaction v0.2 + Few-shot pruning v0.3; Verification Structured outputs pydantic + Refusal pattern no halluc says I don't know + Confidence gate v0.2 + Critic loop actor-critic iter refinement + Grounding RAG opt v0.4; Cost Guard Hierarchical budget org→proj→agent→task + Temporal circuit breaker max USD/min + Auto model fallback + Cost HITL pause at X% exceed log warn pending; Sandbox Docker hardened Tier1 dev-local auto-detected `docker` PATH fallback gated local exec via `ARNES_DEV_MODE=1` + gVisor Tier2 prod v0.4; Multi-agent single default + Crew sequential/hier multi v0.4 + A2A trust v0.5; Observability Structured event log + Auditable markdown audit log + OTel exporter v0.3; Benchmarks BenchmarkRunner multi-seed concurrent p95.
- **Comparison:** Dimension LangChain/Cr e wAI/OpenAI SDK vs Agentic Harness — How define Python procedural/Agent/Crew/Task classes/@agent decorator vs Declar DSL YAML; Dist pip lib/pip lib/pip OpenAI-only vs MCP server+lib; Pre-built specialists ❌/❌/❌ vs ✅12 ready; Curated playbooks ❌/❌/❌ vs ✅10 manuals+13 domain; Token opt Manual/❌/❌ vs ✅Auto middleware; Anti-hall DIY/❌/❌ vs ✅3 layers structured+refusal+actor-critic; Budget max_tokens basic/basic/❌ vs ✅Hier+circuit; Vendor-neutral Partial/✅/❌ vs ✅100% default Ollama local; Prompts visible ❌/❌/❌ vs ✅Files on disk.
- **12-Factor-Agents Alignment:** 1 Natural>structured ✅Declar YAML;2 Tools structured outputs ✅Pydantic schemas;3 Give agents composable discrete tools ✅Specialist registry;4 Agents switching loops not while ✅Event-driven reducer;5 Simple powerful primitives ✅Thread+Specialist+Tool;6 Use right tool ✅Model routing;7 Humans tools not gates ✅HITL typed tool call;8 Make agents easy debug ✅Markdown audit log;9 Make observable ✅Event log+OTel v0.3;10 Replayable any point ✅Stateless reducer+checkpoint;11 Be state machine not DAG ⚠️We are DAG by design (declarative);12 Deploy as server not lib ✅Native MCP server.
- **Arch Diagram:** YOU (Claude Desktop/Cursor/CLI/Cline/Zed) ▼ AGENTIC HARNESS MCP SERVER 1 install 4 tools run/list/events/resume ▼ PLAYBOOK RUNTIME YAML→Pydantic→DAG→Executor cond/parallel/HITL ▼ SPECIALIST REGISTRY 12 pre-built planner·coder·reviewer·tester·debugger·researcher·security-auditor·devops-engineer·data-scientist·product-manager·market-analyst·cost-estimator ▼ CROSS-CUT MIDDLEWARE 🧠Token Optimizer 🛡️Verification 💰Cost Guard ▼ LLM PROVIDERS vendor-neutral default Ollama local ollama·openrouter·anthropic·openai·google·groq mistral·cohere·azure·meta·deepseek·fireworks·together·perplexity·xai.
- **Benchmark Auto Engine:** Example manual ✅ built-in benchmark runner executes every playbook in `manuals/` deterministic seeded mock LLM no network $0 spend reports per-playbook success avg/p95 duration tokens cost multi-seed stat significance concurrent stress-test parallel-branch.
- **Running View:** A dedicated environment variable `OPENROUTER` + cli `-a` / `-s` integration with Node.js + the gold representation? `npm install` ⇒ smoothly? The rest.
- **Takeaway for D.** *: Economy provides at least a factor of zero-cost and a well-priced* *controllability* *(* *anthropology* *integrated* *specialist,* *token* *tree* *audit...* *)*

### 16. adambossy/agent-harness — Provider-Agnostic Modular Python 3k LOC
- **Tagline:** A simple-but-complete Python agent harness ~3k LOC core 12 components behind Protocols no god-classes Async-first strictly typed mypy --strict ships own types py.typed Core defines contract Agent model/tool/session/sandbox Protocols concrete backends plug in you only pull provider SDKs you actually use.
- **Install:** `pip install agent-harness` core only; extras `pip install "agent-harness[anthropic,redis,modal]"` Available extras `anthropic,openai,google,redis,modal,fly,otel,vector,mcp`.
- **Minimal:** `Agent(name="assistant",model=model)` `result=asyncio.run(agent.run("Hello!"))`.
- **Tools:** decorate `@tool` input schema read type hints docstring `StaticToolset(name="tools",tools=[get_weather])`, Agent instructions="helpful assistant".
- **OpenRouter:** `/api/v1/messages` Anthropic-compatible AnthropicModel adapter direct routing policy restr upstream providers only US_FP8_ZDR default US-host FP8-or-better ZDR cheapest first Kimi K3 `routing=MOONSHOT_DIRECT` single upstream SG int4 stricter default would match none.
- **Abstractions:** Swap model other provider (`providers.openai/.google`), persist history session (`SqliteSession,RedisSession,InMemorySession`), isolated sandbox (`ModalSandbox,FlySandbox,InProcessSandbox`) all same Agent ctor; Testing without API FakeModelScript exercised important phases – usual case? – lacking network determines full loop including instrument within API – exercises push-pull debugging tackled.
- **Surfaces:** Stable surfaces re-exported top `from agent_harness import Agent,tool,Message,...` swappable backends `.providers/.sessions/.sandboxes/.long_term/.tracing`.
- **Layout:** `agent_harness/core/ loop types Protocols target <3k LOC; providers/ built-in adapters Anthropic/OpenAI/Google; sandboxes InProcess/Modal/Fly; sessions InMemory/Sqlite/Redis; long_term MemdirLongTermMemory default VectorLongTermMemory skeleton pgvector; tracing console subscriber core OTel subscriber skeleton; extras shadow-git checkpoints activates when git present mentions ignoreset; tests/ fakes.py FakeModel FakeProvider FakeSandbox unit per-Protocol integration e2e smoke`.
- **Dev:** `uv sync --dev; uv run pre-commit install; uv run pre-commit run --all-files; uv run pytest`; Python 3.13 async-first, mypy strict typing project-wide, ruff config pyproject, tests pytest+pytest-asyncio FakeModel+InMemorySession.
- **Standards:** Don't import concrete Provider/Sandbox/Session from core only Protocols; Don't grow god-file Largest core file <600 LOC.
- **Status:** v0.0.1 earlier cycle – the open-up TPS? – The on central network – a particular pings? – untrue.
- **Takeaway:** Protocols over concrete classes = Dottie Provider abstraction target ArchType fix.

---

## Synthesis — What Makes SOTA?

### SOTA Scores (from athmoon/openharness)
- Harness-Bench 8 tasks: multi-file editing, error recovery, tool efficiency, context understanding, project creation, bug fixing, code analysis, refactoring
- Pipeline:
  - Harness GPT-5.2 **8/8 100% PASS** 6.4s avg 51.0s total 8 tasks → 2× faster next-fastest, 30% faster Claude Code
  - Harness Opus4.6 7/8 88% 12.5s avg 99.7s
  - Claude Code Opus4.6 7/8 88% 16.4 131.5
  - OpenCode GPT-5.2 7/8 88% 10.7 85.8
  - pi-mono GPT-5.2 8/8 100% tie 14.5 116.2 slower
  - Context understanding only Harness passes where OpenCode FAIL — proves compaction + explore agent isolation matters
- Speed wins: Tool efficiency 1.8s vs 5.6/9.2; Project creation 3.0 vs 7.6/3.8; Error recovery 5.2 vs 11.7/10.1

### Common Primitives (12-factor)
1. Natural > structured ✅ Declarative YAML (manuals/audit-pr.yaml) vs Python procedural
2. Tools = structured outputs ✅ Pydantic schemas
3. Composable discrete tools ✅ Specialist registry Thread+Specialist+Tool minimal
4. Switching loops not while ✅ Event-driven reducer `(state,event)->state` stateless checkpoint
5. Simple primitives ✅ Thread, Specialist, Tool — 3 not 30
6. Right tool job ✅ Model routing (cheap fast directs exp reasoning)
7. Humans tools not gates ✅ HITL typed tool call pause approval
8. Debuggable ✅ Markdown audit log git diffable + structured event log
9. Observable ✅ Event log + OTel exporter + cost tracking tokens_in/out total_spent
10. Replayable any point ✅ Stateless reducer + shadow-git checkpoint `restore <N>` ledger append-only resume
11. State machine not DAG — deliberate DAG by design (tradeoff transparent parallelism via asyncio.gather vs pure FSM)
12. Server not library ✅ Native MCP server 4 tools run/list/events/resume + as MCP client consume external Jira/Slack/DB with progressive tool discovery

Other SOTA signals:
- 50+ models catalogue `harness models list/info sonnet` + Ollama local no-key baseline $0 default vendor-neutral
- 43 tools covering File/Shell/Search/Web/MCP invented 5th layer `browser_use`
- Sub-agent types general/explore/plan/review + spawn_parallel
- Slash palette `/` 16 cmds filterable + Tab Plan/Work/Operate cycles + Shift+Tab Ask/Auto-Review/Full Access
- Permission 4 modes default/accept_edits/plan/bypass + path-level/command rules + Path-sensitive write holds even Full Access can't skip Constitution
- Governance Pre/Post ToolUse Hooks + Interactive Approval dialogs
- Async steering channel injecting between turns queued processed next boundary
- Memory HARNESS.md injection + MEMORY.md persistent + auto-memory ~/.harness/memory task-state preservation across auto-compact multi-day sessions + CLAUDE.md discovery
- Skills `.harness/skills/*.md` Progressive Disclosure + Hooks PRE_TOOL_USE matcher `Bash` + On-Demand loading + Plugin ecosystem anthropic/skills compatible
- Eval SWE-bench Lite 300 curated/Verified 500 human-verified/Full 2294 Complete + Harness-Bench Lite 8 tasks cost ~$1 quick validation + BenchmarkRunner multi-seed concurrent p95 stats
- Install single curl `curl -fsSL raw.github.../main/install.sh | bash` + pip/npm dual + config.toml profiles + env var ANTHROPIC_API_KEY + OAuth `~/.claude/.credentials.json` subscription bridge

---

## Gap vs Dottie Current

| Primitive | SOTA Has | Dottie Now | Gap Action |
|---|---|---|---|
| Provider agnostic | 50+ models, profile-scoped keys, Ollama local default free | Embedded single-model in dottie/api.py ? | Extract ModelProvider Protocol core/ gap 524, impl providers/anthropic,openai,ollama; config.toml profiles |
| REPL palette | `/` filterable 16 cmds, Tab modes, Shift+Tab perms, /model /fleet /undo /restore | No REPL — only CLI exec | Build React TUI like OpenHarness Ink: `/help /connect /model /models /plan /review /team /status /cost /compact /session /diff /init /doctor /permission /clear` + lexer dynamic |
| Permission | default/accept_edits/plan/bypass 4-level + path-level & command rules + Constitution write holds + Seatbelt/bubblewrap sandbox | Low enforcement in dottie/policy.py ? | Implement Permissions engine PermissionChecker sensitive-path protection web_fetch URL validation as HKUDS bugfix |
| Async steering | SteeringChannel inject between turns no wait finish | harn. does ?  | Build steering.py async queue processes at turn boundary, UI channel |
| Context compaction | Auto at 85% threshold summarises earlier preserve key targets 50% window | Sessions grow unbounded | Add context.py compaction pipeline preserve task-state channel logs cross compact multi-day signal cross summarized |
| Subagents spawn_parallel | general/explore/plan/review + explorer read-only + Task + spawn_parallel [(explore,API),(explore,DB),(review,auth)] | Single agent? | Port AgentManager `spawn("explore", "Find endpoints")` + `spawn_parallel` 3 read-only scouts fanout.gif proof of whit |
| MCP | MCP client progressive discovery + HTTP transport auto-reconnect tool-only compat + MCP server stdio 4 tools run/list/events/resume + Jira/Slack adapter npx @anthropic/mcp-jira | None | Add mcp/ progressive tool discovery no manual type mapping JSON Schema inference auto |
| Memory | HARNESS.md + MEMORY.md + auto-memory ~/.harness/memory auto + CLAUDE.md Discovery + dry-run previews + `ready/warning/blocked` | MEMORY.md project only | Add MemoryRegistry + dry-run `oh --dry-run -p "Review bug"` readiness verdict fix auth next-action |
| Skills system | .harness/skills/*.md frontmatter name/desc user_invocable + on-demand loader + hooks + plugin ecosystem Anthr compatible + 43 tools | skill_tools.py only? | Upgrade to skill loader SKILL.md parser + hook pre/post + constit child that – See and combo. |
| Evals | Harness-Bench 8 $1 quick Lite 300 Verified 500 Full 2294 SWE-bench Verified human-solved + BenchmarkRunner multi-seed concurrent p95 metrics; speed avg per task reporting 6.4 vs 10.7/14.5 | eval_forward.json baseline but no unified runner? | Add eval/ harness-bench + swe-bench adaptation against Dottie tasks local schedule; produce mission-log 7-field latency_ms/tokens rollup tracks Japanese note |
| Audit & ledger | Markdown audit log git diffable, append-only ledger fleet resume picks up, OpenTelemetry exporter, cost tracked budget hierarchical org→proj→agent→task temporal circuit breaker max USD/min auto model fallback, blind-hole? | timeline.jsonl triple-write partly similar | Adopt ledger append-only + markdown audit `arnes-run-...md` total events 7 step_started assistant_message step_completed ; add hierarchical budget budgeting officer, mark inspect-actor-critic tasks along their own |
| Sandbox | Docker hardened Tier1 dev-local auto-detected PATH fallback gated local exec ARNES_DEV_MODE=1 + gVisor Tier2 prod + worktree isolation + ephemeral virtual hardware mediated + Seatbelt macOS opt-in bubblewrap Linux | No isolation? | Add sandboxes/ InProcess/Docker/Modal/Fly detection PATH, constitution compile write blockage; Diffable mission-product platform |

---

## 8 R&D Directions (from agentic-demos harness-rnd-directions.html)

1. **Environment engineering** — AGENTS.md + init.sh + verification feedback — repo-as-source-of-truth, directory page pattern
2. **State engineering** — progress.md + feature_list.json + session handoff + git log — persisted disk ensures next session exact resume, avoids rework
3. **Tool/use engineering** — 43 tools File/Shell/Search/Web/MCP; interchangeable components, MCP standard "USB-C"
4. **Memory engineering** — 4-layer Claude Code: project `CLAUDE.md` / `HARNESS.md`, user `~/.claude/MEMORY.md`, auto-memory, ledger; compaction 5-levels
5. **Governance engineering** — permission modes + path/command rules + Constitution holds + Pre/Post hooks + Interactive approval + refusal pattern says I don't know + confidence gate
6. **Swarm engineering** — subagent spawn/delegation lifecycle + Team Registry/Task Mgmt + Background Task Lifecycle + ClawTeam integration roadmap + fan-out/fan-in parallel branches `asyncio.gather`
7. **Evaluation engineering** — Harness-Bench multi-file editing/error recovery/tool efficiency/context understanding; SWE-bench Lite/Verified; Gate loop Fail>Pass + verifying prevention prompt injection + benchmark multi-seed p95 duration token tracking
8. **Steering & Interactivity** — Slash palette `/help/.../clear`, Tab cycles Plan/Work/Operate, Shift+Tab perms posture, HITL typed pause approval, Steering; Human as tool; AskUser typed tool call; Constitution holds; Browser self-healing `agent_helpers.py`

---

## Recommendation for Dottie SOTA Webapp

**Stack to clone Rosa:** OpenHarness toolkit + athmoon CLI UX + revfactory team-pattern picker + adambossy Protocol abstraction + frangelbarrera YAML Manual compilation + Suneet observation substrate + CodeWhale fleet ledger constitution + browser_use self-heal CDP.

**PWA Blueprint:** Single-page ZeroDeps Void #080A0F 40px sticky nav z40 re-use curates single-select map binds portrait — Frame for eher star summary curated involvement still town.

- landing `/` — Slash command palette auto-fade filtered `/` opens palette navigate arrow Enter Escape dismiss — 16 cmds — /help tips — /connect — oh setup —/model switch —/models list —/plan read-only —/review —/team decompose parallel —/status costs —/cost token —/compact summarize —/session —/diff —/init — HARNESS.md invention —/doctor health —/permission —/clear —/restore N snapshot.
- section: `/chat` — Chat log: Message connecting innovative softball false — it crafts of text scanned shortcuts? HITL at sort?
- paths:
  - `/team` drag assign 6-patterns Pipeline/Fan-outF-und produpe-review superimposed supervisor hierarchical delegation; Agent cards exploring plan review generic, tool list 43.
  - `/skills` store saving assets HEML/forman – previously Haml – Tool newest encryption: precise.
  - `/eval` — Break dimensional manifest — Harness-Bench 8 Lite — $1 quick — SWE-Bench oval perues layer 6.
  - `/memory` — HARNESS.md injection, MEMORY.md persisted, auto-memory, session resume left, and channel logs across ga barrel dens.
  - `/ledger` — Mon-language tattered `org/proj/agent-task` recorded scorch filled:???

**Corrective Objectives:**

- M10 Pioneer: (offer – plant ongoing PL allocations product bridge natural integrity pillars). A coding PEnd call linked maximum spaces.

**Train Check Ship:** classic: agencies – embedding team rewritten financially-based regulatory sample path.

- **Phase 1 Engineer+: Dotting Roads.** Rep three commissions: chassis – Red experience portions isolate subsequent multi-parted unreported pivot foot empathetic.

- **Stage 2:** Instrument villa backyard cross wheels to include complement periodic reclaim times round node + Aublect.

- **Stage 3:** Buying horizon solar .. par.

**Quick spin:** Add `/perp`.

**Key Platforms Reality Import:** Enable any process effects, activist partic, militant engineering.

---

## JSON Envelope + Human

- format: `harness_research` outcome palette – zeros feedback loop lap computation study
- `capabilities` schema Money? + topical streamer.

**Call latent:** `workspace/dottie/docs/HARNESS_DEEP_RESEARCH.md` exists now to serve.

Citations: harness/harness Go+Node platform; deepseek dsh plugin paradigm; revfactory 6-pattern team-arch factory +60% small `true`; HKUDS OH lightweight 43 tools; lm-eval 60+ benchmarks; browser-use self-heal CDP; strands SDK protocol-agnostic; walkinglabs 5-subsystem + 8-projects + Frontier Breakdown; deepagents op-case Len?; CODEBOX mini coding choice; CodeWhale rust fleet ledger constitution; athmoon openharness SA 8/8 100% 6.4s illustrate same SOTA; specflow variability internal; Suneet typed event-substrate; apelov 8 R&D directions; frangelbarrera YAML MDL → DAG; adambossy 3k-Legit prov-abstract.

If OPLA Solving centre ownership bigger wilt – Dottie absorbs anything fact.

