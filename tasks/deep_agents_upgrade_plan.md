# Deep-agents upgrade plan — what Stripe's Kai actually implies for this repo

**Source:** [How Stripe built their knowledge AI platform on deep
agents](https://www.langchain.com/blog/how-stripe-built-their-knowledge-ai-platform-on-deep-agents)
(LangChain, read 2026-08-03). **Written 2026-08-03 against HEAD `ec6ddfc`.** Every number
below was measured in this repo, not carried from the article or from memory.

---

## The one-line finding

**This repo already wrote the deep-agents design and then built something else.**

`apps/ava-factory/dottie/llmvm/` is 1,087 lines of near-textbook deep agents — defer-loaded
tool registry with `search()`/`load()`, `ContextManager.compact()`, skillbook,
gated self-modification with an audit log. **Nothing imports it.** Grep for `llmvm` returns
the module's own five files, a shim, a status-display line in `ecosystem_updater.py`, one
shell script, and a results JSON. Meanwhile the live path — `rl/codeact_loop.py` +
`apps/dottie/dottie/engine.py` — is CodeAct with a **statically bound** tool surface and
**fixed truncation**.

The gap between `llmvm/` and `engine.py` is almost exactly the gap between Stripe's
architecture and this codebase's reality. So the question the article raises here is not
"should we build deep agents" — it is **"we designed it; wire it or delete it."**

Leaving both is the worst of the three. This repo's own
`scripts/check_declared_capabilities.py` names the defect precisely, about a different
subject: *"documentation wearing a gate's clothes — and worse than none, because it buys
confidence it has not earned."* An orphaned 1,087-line prototype that reads like
architecture is the same thing one level up.

Measured, and it decides the question on its own: **`llmvm/tool_registry.py`'s
`create_dottie_registry` registers eight tools whose bodies are literally `pass`** (8
matches for `^\s*pass$` in that file). The registry as written cannot do anything. It is a
sketch, and it should be labelled one or removed.

> **`apps/ava-factory/**` is FROZEN — read, never modify.** So this is an operator
> decision, not something to action from a session. What a session *can* do is the rest of
> this list, none of which touches the frozen tree.

---

## What NOT to adopt, and why

Cargo-culting is the main risk with an article this good, so these are stated first.

**1. Two-pass dynamic skill loading — not yet.** It is Stripe's headline pattern and it
exists because they **measured quality degradation past ~150 skills** against 1,000+ skills
and 500+ MCP tools. This repo has **58 scout-cli plugins and 11 ava-skills**. It is below
the threshold that makes the machinery pay for itself. Building a selection step here buys
a second failure mode and solves no observed problem. *The right first move is to measure
whether routing quality degrades today with the full surface exposed — see item 2 below,
which is a real defect in the opposite direction.*

**2. Sub-agents — no.** Zero hits repo-wide for `subagent|spawn_agent|child_agent|
delegate.*agent|multi_agent`. Their absence is not a gap until something needs them; the
research loop already gets parallelism from separate cron-scheduled workers.

**3. Their evaluation posture — emphatically not.** The article is explicit that it
"provides minimal detail on formal evaluation methodology." This repo runs baselined
ratchets (`gate_audit.py`, `check_declared_capabilities.py`, `check_documented_counts.py`,
`check_handoff_fresh.py`, each with a `*_baseline.json`), a promotion gate that requires
*both* overall improvement and no per-family regression and returns `insufficient` rather
than promoting on missing data (`climb.py::compare_iterations`), and retrieval evals with
explicit answer-in-query leakage controls. **Take the architecture. There is nothing to
learn here about rigor, and something to lose.**

---

## What to actually do, ordered by what pays

### 1. The planner cannot see most of its own tools — `[:25]`

`apps/scout-cli/bigbang/plugins/agent/cli.py:331`

```python
    for name, m in list(tools.items())[:25]
```

The LLM planner's system prompt is built from the **first 25 tools** in dict order. No
constant, no comment, no ordering by relevance — a bare slice to make the prompt fit.

And the fallback path is narrower still. `_heuristic_plan`'s `builtin_hints` dict has **30
entries routing to 12 distinct plugins**, against **58 plugin directories on disk**:

    plugins on disk                              58
    hint entries                                 30
    distinct plugins reachable via heuristics     12
    hints naming a non-existent plugin             0   (no dangling entries — good)
    plugins unreachable from the heuristic router  46

*This is the same problem Stripe solved, arriving from the opposite direction.* They had too
many skills to fit a prompt and built selection. This repo has few enough to fit and
**silently drops half of them anyway.** Fixing it does not need two-pass loading — it needs
the slice replaced by something that either fits all 58 descriptions (they are truncated to
80 chars; 58 × ~90 bytes ≈ 5 KB, which is nothing) or selects deliberately and says so.

**Acceptance:** the planner prompt covers every registered plugin, or the omission is a
declared constant with a written reason and a test that fails when the plugin count exceeds
what the prompt carries. The second half matters more than the first — a cap that cannot
drift silently is fine; a bare `[:25]` is not.

### 2. Context compaction exists, in the orphaned tree, and the live path truncates

Live caps, all fixed, all lossy at the tail:

    codeact_sandbox.py   STDOUT_CAP        8192
    codeact_sandbox.py   VALUE_CAP         2048
    engine.py            _STDOUT_EXCERPT   1000
    engine.py            _ERROR_EXCERPT     500

Stripe's summarization middleware is tunable (threshold, model, output size) precisely
because long sessions degrade. Truncation throws away the end of a long output; a summary
keeps a lossy version of all of it. `llmvm/context.py` already implements `compact()` and
`summarize_session()`.

**Caveat that has to be measured first, not assumed:** the CodeAct loop is currently
`max_steps=8` and single-shot per task. Compaction pays for long sessions. **Measure whether
any real trajectory approaches the caps before building anything** — `traces/traces.jsonl`
has the data. If nothing is being truncated, this is a non-problem and the honest answer is
to say so and close it.

### 3. `knowledge/` is not consumed by code, and at least one review in it is stale

Five markdown files under `knowledge/reviews/`. Nothing reads them —
grep across Python/Markdown/TOML/YAML in apps, scripts and packages returns only a
reference to a *different* `knowledge/` in a vendored README.

Worse, they are trusted at face value while rotting. `knowledge/reviews/agent-os.md`
documents that `resolve.py`'s marker probe looks for `ava/rl/codeact_loop.py`, which does
not exist in the monorepo, and concludes dottie silently depends on an out-of-repo checkout.
**Verified today: that is fixed.** `resolve.py:64` probes `dottie/rl/codeact_loop.py`
first, and `resolve.py:56` states it is the source of truth. The review is describing a
resolved bug as if it were live.

That is exactly the failure `HANDOFF.md`'s own top block warns about — *"A stale 'current
state' block is worse than none, because it is trusted at face value"* — applied to a
directory that has no freshness gate on it at all.

**Do one of:** date-stamp each review with the SHA it was written against and add it to the
`check_handoff_fresh.py` family, or move them to `docs/archive/`. Not both, and not neither.

### 4. Capability declaration still outruns enforcement

`check_declared_capabilities.py` records it: 37 plugins call `enforce_or_raise`, **9 declare
filesystem paths and never check them**, and one of those — `herd` — had its ledger
destroyed by an unguarded write in a live session.

Stripe solved the equivalent structurally: the sandbox middleware keeps model-generated code
outside the agent's execution context **by construction**, so a policy cannot be forgotten
because there is nowhere to forget it. This repo's sandbox
(`rl/codeact_sandbox.py`) is genuinely the best-engineered component here — fd-1 reparenting
before user code runs, realpath-checked scratch writes, frozen clock for byte-identical
replay — but the *plugin* path is a different mechanism with partial coverage.

The ratchet is the right shape and already exists. **The work is retiring the nine baselined
cases, one judgement at a time**, not building anything new.

### 5. Windows drops half the sandbox's guarantees, on the box this repo lives on

`codeact_sandbox.py`'s docstring is honest that it "is **not** a hostile-code jail" — and on
Windows the POSIX `resource` rlimits and process-group kill are skipped entirely, leaving
only the wall-clock timeout. CPU and memory limits do not apply.

**This is not an architecture upgrade, it is a stated limit that should be measured and
written where it will be read** — the sandbox docstring says it, the operator-facing runbooks
do not.

---

## What Stripe has that this repo has no analogue for

Recorded for completeness, none recommended yet:

| Stripe primitive | Here |
|---|---|
| Virtual filesystem, S3-backed, sync-in/sync-out | Does not exist — sandbox uses a real scratch dir |
| Config layer for the agent itself | Does not exist — `max_steps=8`, `timeout_s=5.0`, `DEFAULT_TOOL_SOURCES`, `DEFAULT_OLLAMA_MODEL` are constants scattered across `engine.py` and `policy.py` |
| Foundational skills pinned for policy | Partial — `core/policy.py` is default-deny, but there is no pinned-skill concept |

The config layer is the one with an obvious payoff and no downside: four constants in two
files is not a configuration system, and every experiment currently edits code.

---

## Scoreboard against the article's own claims

| Deep-agents primitive | Status here |
|---|---|
| Agent loop | **Yes** — CodeAct, `rl/codeact_loop.py` + `engine.py` |
| Planning / todo in the loop | **No** — planning only in the offline research loop |
| Sub-agents | **None** — zero hits repo-wide |
| Skills with dynamic selection | **Yes, real** — `ava-skills/loader.py`, wRRF + tool graph + topo sort. *Accuracy unmeasured, and the loader's own docstring says so.* |
| Defer-loaded tool registry | **Orphaned prototype**, 8 `pass` bodies |
| Context compaction | **Orphaned prototype**; live path truncates at fixed caps |
| Virtual filesystem | **None** |
| Persistent cross-session state | **Yes** — `state_store.py`, SQLite WAL |
| Sandboxed execution | **Yes, best-in-repo** — with a documented Windows gap |
| Retrieval | **No embedding RAG.** Graph query + a BM25 baseline built to *evaluate* a future retriever |
| Eval harness | **Yes, several.** No external agent benchmark (SWE-bench / GAIA / τ-bench) |

---

## Order of work

1. **Item 1** — the `[:25]` slice. Small, verifiable, and it is a live defect rather than an
   enhancement.
2. **Item 3** — date-stamp or archive `knowledge/reviews/`. Cheap, and one file is already
   misleading.
3. **Item 2, measurement half only** — check `traces/traces.jsonl` for trajectories near the
   caps. Build nothing until that number exists.
4. **Item 4** — retire baselined capability cases as judgement allows.
5. **Operator decision** — wire or delete `llmvm/`. Frozen tree; not a session's call.
