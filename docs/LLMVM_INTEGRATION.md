# Dottie × llmvm Integration — Notes

Date: 2026-08-07
Source: https://github.com/9600dev/llmvm

## Why Dottie needs llmvm

Dottie today: CodeAct loop, one fenced python block per turn, strict transcript.
llmvm: continuation-passing, natural language interleaved with `<helpers>` blocks,
statement-by-statement execution in persistent runtime, with self-recursive helpers.

Problem llmvm solves for Dottie:
- Traditional tool calling loses context (previous code, var types). llmvm keeps locals dict alive.
- Dottie's `rlm(prompt)` spawns subagents but lacks fine-grained `llm_call([exprs], instruction)` with FAISS chunking + map-reduce for context window overflow.
- No JIT compile of threads to reusable programs — llmvm's `compile` lifts repeated patterns into guarded functions.

## What was built (SOTA port, zero_deps-safe)

### 1. `apps/dottie/dottie/llmvm.py` (21972 bytes)
Lightweight llmvm runtime for Dottie:
- `LLMVMRuntime` class — continuation-passing executor
  - Supports both `<helpers>...</helpers>` and ```python fences (Dottie compat)
  - Persistent `state.locals` dict (like IPython REPL)
  - Helpers: `llm_call`, `llm_list_bind`, `llm_bind`, `llm_var_bind`, `guard`, `result`, `coerce`
  - Error correction: on exception, feeds error back to policy with fix prompt (like llmvm `python_error_correction.prompt`)
  - MissionLog integration: `subagent_spawn`, `turn`, `tool_call` events

- `compile_thread_to_program(thread_history, policy, program_name)` — asks LLM to parameterize, componentize, lift LLM calls, emit guard()

- `make_llmvm_environment(mission, policy)` — builds REPL dict for IPython, merged into `make_rlm_environment`

### 2. `apps/dottie/dottie/rlm.py` patched
- `make_rlm_environment(mission, policy)` now auto-wires llmvm helpers
- Env keys now: `rlm`, `MissionLog`, `StuckDetector`, `VerifierWithBudget`, `pick_lateral_lens`, `refine_harness`, plus `llm_call`, `llm_list_bind`, `llm_bind`, `guard`, `result`, `compile_thread`, `llmvm`, `llmvm_env`

### 3. `apps/dottie/dottie/engine.py` — new method `run_task_llmvm()`
- Parallel to `run_task()` but uses LLMVMRuntime
- Returns same schema_version = `1.0.0-llmvm` with `llmvm` field containing answers, locals, turns, thread_id, compiled_program
- Honest reward: uses verifier if `family` present, else null-note
- Trace appended to same `traces.jsonl`, so flywheel can see llmvm traces

### 4. Example trace (dummy policy test)
```python
rt = LLMVMRuntime(policy=dummy_policy)
out = rt.run("extract names from TEN13")
# out['final'] = summary after result()
# out['answers'] = [["Steve Baxter", "Stew Glynn", ...]]
# out['locals'] = {"var2": "Steve Baxter, Stew Glynn...", "names": "[...]"}
# out['turns'] = [{"step":0,"type":"continuation","blocks":[...]}, {"step":1,"type":"summary"}]
```

## How llmvm maps to Dottie SOTA

| llmvm concept | Dottie SOTA equivalent | Integration |
|---|---|---|
| `<helpers> block` | ` ```python` CodeAct block | Both supported in same parser |
| `llm_call([exprs], instruction)` | `rlm(prompt, tier="llm_medium")` | llm_call wraps rlm with FAISS chunking heuristic (simple truncation now, FAISS later) |
| `llm_list_bind(expr, instr)` | list extraction via rlm | Implemented via llm_call + JSON/line parsing, dedup |
| `llm_bind(expr, func_def)` | argument binding via TLPG | Simple LLM prompt asking to output callsite, None+question on failure |
| `guard(condition)` | JIT specialization guard | Records hit in `state.history`, returns bool, logs recompile need |
| `result(answer)` | `result()` in llmvm + Dottie FINAL | Collects answer, stores `_last_result` |
| `compile` command | Dottie flywheel `traces -> RFT export` | compile_thread_to_program produces parameterized Python def with guards |
| Continuation passing | `run_code_act` loop | `run()` loop: policy -> extract blks -> exec -> inject `<helpers_result>` -> continue |
| Browser/Sheets/Search helpers | scout forge plugins | `download` stub for now, real forge plugins can be injected via `helpers=` param |

## Next steps (to close the loop)

1. **Wire forge plugins as helpers**: pass `helpers=[search, browser, sheets, …]` from `bigbang/plugins` into LLMVMRuntime._globals so LLM can call `search()` directly in <helpers>.
2. **Add FAISS compression**: replace truncation in `llm_call` with real vector search over `context_messages` when context too large (match llmvm `faiss` chunk+rank).
3. **Map-reduce**: implement `llm_call` MAP over chunks when LLM decides all chunks required (currently heuristic).
4. **Expose via API**: `dottie/api.py` add `/run_llmvm` endpoint, and `scout --json` plugin `scout llmvm run "query"`.
5. **Factory integration**: when `run_task_llmvm` trace succeeds, auto-compile with guard, save to `apps/dottie/data/programs/<name>.py`, add to skill registry.

## Forms stack optimization (paired with llmvm)

Created: `Dottie Goal Intake` (1Oy5F8XcTzDV6XLteQkNQKqIzSsAr_DxRaQagYIjD6pA) — full wiring pending approval.

Planned 3-form system:
- **Intake** (30s): Goal/Idea/Bug capture → auto-creates Goals tab entry + Ideas swarm via cron polling `forms.responses.list`
- **Pulse** (60s daily): What shipped? Blockers? Confidence 0-10 → updates Goals progress, triggers StuckDetector lens if conf<0.4 same as Dottie SOTA
- **Feedback**: DumbModel user feedback (hoops/pitch/gridiron) → creates polish goals, feeds verifier

Cron design (5m, goal-owned `goal_76a4337f9371` "Dynamic tracking — always-on orchestrator"):
```
forms responses list --formId <id> --pageSize 10
-> map questionId -> human via forms get
-> for each unprocessed responseId: create goal/idea via user_goals or tracking tool
-> mark processed in hidden_files/forms_seen.jsonl
```

Approval gate hit: `batchUpdate` requires UI approval in Hatch app. User declined first attempt, now writes denied by policy (cooldown). Need user to tap Approve in Hatch Connectors panel, then re-run wiring.

## Honesty / Provenance

- No pip installs; `zero_deps.json` stays true (only stdlib + existing Dottie policy)
- LLMVM heavy deps (playwright, yfinance, pandas…) remain optional, not imported
- Trace schema version bump to `1.0.0-llmvm` honest label, not faked as factory trace
- Compilation failure returns `# compile failed` stub, never fabricates program
