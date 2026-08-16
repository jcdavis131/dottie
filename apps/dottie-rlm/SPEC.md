# dottie-rlm — Prime-Agent-style RLM harness for Dottie (SPEC v1, 2026-08-06)

Reference design: Prime Intellect's Prime Agent (open-source RLM harness).
Core inversion: the model gets ONE tool — a persistent IPython kernel.
Everything else (file edits, shell, sub-agents, compaction, messaging) is a
function call INSIDE that kernel.

## Non-negotiables (production grade, house rules)

- Every state write is atomic (per-pid temp + replace, bounded retry on
  WinError 32) — the vault/herd/telemetry lessons apply verbatim.
- NO fail-silent reads: corrupt state → preserve bytes as
  `<name>.corrupt-<ts>`, announce on stderr, then fail or reset LOUDLY.
  Missing is empty; unreadable is not.
- No secrets in trajectories or logs. Never touch `steer_poll.py`.
- LLM backend degrades honestly: if no backend is reachable, commands refuse
  with a clear error. Tests use a deterministic FakeBackend — zero network.
- Site page renders numbers only from published local status
  (`source:"local"`); stale data is labeled history, not telemetry.
- Windows-first: paths via pathlib, UTF-8 everywhere, no POSIX-only calls.

## Layout

```
apps/dottie-rlm/
  SPEC.md                      # this file
  pyproject.toml               # [project] dottie-rlm, deps: ipython, typer, requests
  dottie_rlm/
    __init__.py                # __version__, public API re-exports
    atomic.py                  # write_json/read_json/append_jsonl (port the bigbang atomic_json contract)
    kernel.py                  # PersistentKernel
    llm.py                     # Backend protocol + OllamaBackend + OpenAICompatBackend + FakeBackend
    session.py                 # Session: one agent = one kernel + one history
    registry.py                # SessionRegistry: disk index, idle eviction, reload
    rlm.py                     # in-kernel function surface: rlm(), agent_message(), inbox
    harness.py                 # H=(rho,G,K,M) + refinement ledger + /refine + rollback
    loop.py                    # the RLM loop
    status.py                  # publish rlm_status.json for the site (atomic)
    cli.py                     # typer CLI
  tests/                       # pytest, no network, FakeBackend only
```

## Module contracts

### kernel.py — PersistentKernel
- In-process `IPython.core.interactiveshell.InteractiveShell` (no zmq — one
  process, one namespace that PERSISTS across calls).
- `run(code: str, timeout_s: float = 120) -> ExecResult` where ExecResult =
  dataclass(stdout, stderr, result_repr, error: str|None, duration_s).
  Timeout via a watchdog thread that interrupts (`KeyboardInterrupt` into the
  shell); on timeout error="TimeoutError: ...".
- `inject(name, obj)` — how rlm.py installs the function surface.
- stdout/stderr captured per-call (redirect_stdout/redirect_stderr), truncated
  to 20_000 chars each with an explicit `...[truncated N chars]` marker.
- The namespace is the ONLY state the model manipulates directly.

### llm.py — backends
- `class Backend(Protocol): def complete(self, messages: list[dict], *, max_tokens: int) -> str`
- `OllamaBackend(model="qwen3:8b", host="http://localhost:11434")` — /api/chat,
  stream=False, hard timeout 300s, raises BackendUnavailable(clear message) on
  connection failure. NOTE: qwen3:8b runs NUM_GPU=0 (system RAM) on this box.
- `OpenAICompatBackend(base_url, model, api_key_env="DOTTIE_RLM_API_KEY")` —
  key from env ONLY, never a file, never logged.
- `FakeBackend(script: list[str])` — pops scripted replies; raises when
  exhausted (a test that over-consumes must fail, not loop).
- `resolve_backend(spec: str) -> Backend` — "fake:", "ollama:qwen3:8b",
  "openai:<base_url>:<model>".

### session.py — Session
- Fields: id (uuid4 hex12), parent_id, role ("root"|"sub"), model_spec,
  created_utc, kernel, history (list of turn dicts), base_prompt.
- Turn record: {"t": iso_utc, "kind": "model"|"exec"|"message"|"system", ...}.
- `save(dir)` → `<dir>/<id>/session.json` (meta) + `trajectory.jsonl`
  (append-only, atomic appends). `load(dir, id)` reconstructs meta+history;
  the KERNEL namespace is NOT persisted (documented: reload = fresh kernel,
  history intact — same tradeoff Prime Agent makes on reload).
- Corrupt session.json on load → atomic.read_json contract (preserve+raise).

### registry.py — SessionRegistry
- Root dir: `%LOCALAPPDATA%/dottie-rlm/sessions` default, overridable
  (tests use tmp_path). Index `registry.json` via atomic.py.
- Tracks: id, parent_id, state ("live"|"idle"|"done"), last_active_utc.
- `evict_idle(now, idle_minutes=30)` — live→idle unloads the in-memory
  Session (kernel dropped), state persists on disk; addressing an idle
  session reloads it (fresh kernel + full history). Explicit, tested.
- Scoping helper: `allowed_targets(sender_id) -> set[str]` = parent, siblings
  (same parent), direct children. Messaging outside that set raises
  ScopeError — TESTED, not advisory.

### rlm.py — the in-kernel function surface
Injected into every kernel namespace:
- `rlm(prompt: str, model: str|None = None) -> dict` — spawns a CHILD session
  (own kernel, own history, base prompt = harness rho for role "sub").
  Returns AT ADMISSION: {"id": ..., "state": "admitted"} — never blocks on
  the child's answer. Child runs its loop in a daemon thread; its final
  answer is delivered as an agent_message to the parent inbox.
- `agent_message(target_id: str, text: str) -> dict` — delivers into target's
  inbox if target in allowed_targets(sender) else ScopeError.
- `inbox() -> list[dict]` — drain pending messages for this session.
- `edit_file(path, old, new)` / `read_file(path)` / `sh(cmd, timeout_s=120)`
  / `compact(keep_last=20)` — compaction summarizes older turns into one
  system turn (via the session's backend) and truncates history in memory +
  writes a compaction record to the trajectory. All are plain functions in
  the namespace — the model calls them in code, the kernel executes.
- Every function returns plain dicts/strings (kernel-reprable), never raises
  raw internals at the model except ScopeError/BackendUnavailable with
  actionable text.

### harness.py — H = (rho, G, K, M)
- rho: base system prompt — IMMUTABLE, stored once at
  `harness/base_prompt.md`; hash recorded; any attempt to edit via refinement
  is rejected.
- G: sub-agent defaults (model spec per role), K: skills (markdown files in
  `harness/skills/`, name+description loaded into rho's skill listing),
  M: memory (markdown notes in `harness/memory/`, loaded on session start).
- Refinement ledger `harness/refinements.jsonl` (append-only, atomic):
  {"id": r-<n>, "t": iso, "trigger": str, "edit": {"target": "skills"|"memory"|"agents",
   "op": "add"|"update"|"remove", "name": str, "content": str|None},
   "outcome": str|None, "rolled_back": bool}.
- `refine(trajectory_tail, trigger) -> Refinement` — applies the SMALLEST
  relevant edit to G/K/M (never rho); `record_outcome(id, outcome)`;
  `rollback(id)` — reverse the edit, mark rolled_back (idempotent; rollback
  of a rollback is a no-op with a clear message).
- `effective_prompt()` = rho + skill listing + memory digest — rebuilt, never
  mutated in place.

### loop.py — the RLM loop
- `run_turn(session, user_text)` → messages = effective_prompt + history
  tail; backend.complete(); parse the reply: fenced ```python blocks are
  EXECUTED in the kernel in order; everything else is narration. Exec results
  are appended as turns and fed to the next completion. Loop until the model
  replies with no code block (that reply is the answer) or max_steps (16)
  — hitting max_steps records "step-limit" honestly in the trajectory.
- Inbox is drained into the message stream at the start of every turn.
- Child sessions run the same loop with max_steps 8.

### status.py + site
- `publish_status(registry, path)` → rlm_status.json: {"published_utc",
  "source": "local", "sessions": [{id, role, state, turns, last_active}],
  "refinements": last 20 ledger entries}. Atomic write.
- Site: `apps/bluehenre/public/rlm.html` (console: sessions table, refinement
  ledger, architecture explainer) + `apps/bluehenre/api/rlm-status.mjs`
  following fleet.mjs's pattern EXACTLY: fetch the published gist/local file,
  else `{source:"offline", reason}` — never fabricate, stale = labeled.

### cli.py
- `dottie-rlm run "goal" [--model ollama:qwen3:8b] [--max-steps N]`
- `dottie-rlm repl` — interactive; `dottie-rlm sessions` — list from registry
- `dottie-rlm refine --trigger "..."` / `rollback <id>` / `ledger`
- `dottie-rlm status --publish [path]`
- Entry point `[project.scripts] dottie-rlm = "dottie_rlm.cli:app"`.

## Test floor (every module; FakeBackend; tmp_path registries)
- kernel: namespace persists across run() calls; timeout fires; output
  truncation marker; stderr captured.
- llm: FakeBackend exhaustion raises; resolve_backend parses all three specs;
  Ollama/OpenAI constructors never touch network in tests.
- session/registry: save→load round-trip; corrupt session.json preserved
  loudly; idle eviction unloads and reload-on-address works; scope matrix
  (parent ok / sibling ok / child ok / stranger raises) — all four asserted.
- rlm: rlm() returns at admission (parent turn completes while child pending);
  child answer arrives via inbox; agent_message to stranger raises ScopeError.
- harness: rho immutable (edit attempt rejected); refine writes ledger entry;
  rollback reverses and is idempotent; effective_prompt contains added skill.
- loop: scripted FakeBackend drives code-exec-code-answer; max_steps honest.
- cli: `--help` and `sessions` on empty registry exit 0.
- Anti-vacuity: at least one test asserts the ledger/trajectory files are
  NON-EMPTY after activity (a ceiling on nothing is satisfied by nothing).
```
