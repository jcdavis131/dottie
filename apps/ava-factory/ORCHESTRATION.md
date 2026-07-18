# ORCHESTRATION — Foreman / Sub-Agent Protocol

How the foreman session dispatches and verifies sub-agents to execute [`PLAN.md`](PLAN.md).
Task states live in [`TODOS.md`](TODOS.md).

There are **two kinds of agent** in this project, and they are easy to confuse:

- **Build-time sub-agents** — Claude agents that *write the code* for a service, then exit.
- **Runtime services** — the long-lived containers (`collector`, `curator`, `trainer`, `server`,
  `janitor`) that the code becomes. These are processes, not models.

---

## Roles

| Role | Who | Responsibility |
|---|---|---|
| **Foreman** | the interactive session | decomposes work, dispatches sub-agents, **runs every acceptance command itself**, updates `TODOS.md`, commits, babysits long runs, makes GO/NO-GO calls |
| 🟦 **Sonnet worker** | sub-agent | mechanical, fully-specified: scaffolding, generators, tokenizer, bench, report HTML, Docker, docs |
| 🟪 **Opus worker** | sub-agent | correctness-critical: manifest concurrency, model fixes, curator, trainer, evals, serve engine. A silent bug here poisons everything downstream |
| 👷 **Human** | you | host-level actions (`wsl --shutdown`), GPU scheduling, the mini→base1b decision |

## Dispatch loop

1. **Select** unblocked tasks from `TODOS.md`; maximize parallel lanes.
2. **Dispatch** one worker per task. The prompt must carry: task id, the full contract (or a pointer
   to its `specs/` section), the **existing API surface it must use** (paste the signatures — workers
   otherwise invent their own), the acceptance command, and the standing rules below.
3. Mark `dispatched`.
4. **Verify.** The foreman runs the acceptance command *itself*. Green → `done`. Red → hand the
   failure back to the *same* agent (via `SendMessage`, preserving its context) for one repair round;
   second failure → escalate tier or split the task.
5. **Commit** per verified task or coherent batch. Push at stage boundaries.

## Standing rules for every worker prompt

> - Implement exactly the deliverable files listed. Do not touch files another agent owns.
> - **Do not run `git`. Do not commit.**
> - No network calls in produced code, except the collector's HF streaming.
> - Determinism: seed from config/CLI; same seed ⇒ byte-identical output.
> - Ship the tests named in your contract; run the acceptance command yourself before returning.
> - Report the exact commands you ran and their **real** output. Do not claim a test passed unless
>   you saw it pass. Deviations from the spec are welcome — state them and why.

That last clause earns its keep. The curator agent overrode its spec's ordering (`complete()` before
deleting the raw file) because deleting first and then crashing would requeue a row whose data is
gone. It was right and the spec was wrong.

## Verification culture

**A test that cannot fail is worse than no test.** The manifest's concurrency test was validated by a
negative control: downgrading `BEGIN IMMEDIATE` to `BEGIN DEFERRED` makes it fail immediately. Do the
same wherever a test guards a subtle property — perturb the implementation, confirm the test screams.

Three properties in this repo were "passing" for years by being unobservable:
- attention had no causal mask (a loss curve just drops implausibly fast),
- the workspace broadcast the future into the past,
- `verbalizable_mass` was the constant `0.06`.

None of these show up as an exception. Assert the *property*, not the absence of a crash.

## Long-run supervision (Stage 9)

- Launch: `docker compose up -d`, then `make logs`.
- Poll `runs/*/metrics.jsonl` and `make ps` on a timer. Watch: new lines appearing, smoothed `lm_loss`
  trending down, no NaN/inf, `tok_s` ≥ 60% of bench, `DATA_STARVED` bursts < a few seconds, disk under
  the high watermark.
- Crash/stall → relaunch with `--resume` (bit-exact by construction, asserted in `test_train_smoke`).
- Loss spike > 3× trailing median → pause, inspect the phase transition (a seq-len or RoPE change is
  the usual culprit), then resume or roll back to the last stable checkpoint with a lower `j_weight`.

## Decision gates

| Gate | Rule |
|---|---|
| T5.4 bench | curation tok/s < 3× trainer tok/s → raise curator replicas or relax MinHash bands |
| T9.1 nano | the loop must work end-to-end. **Not** a capability claim |
| T9.2 mini | `hl_est → target`, `route_probs` separating by `task_type`, val PPL falling |
| T9.3 base1b | GO only if mini's probes clearly beat nano **and** VRAM math closes (1409M needs a trim decision) |
| any eval | canonical J-Space tests may legitimately FAIL at small scale. **Report measured values.** Only pipeline errors block |

## Tier map

| Tasks | Tier |
|---|---|
| T1.*, T3.2/3.3, T4.6, T5.*, T6.5, T8.4/8.5, docs | 🟦 Sonnet |
| T2.*, T3.1, T4.1–4.5, T6.1–6.4, T7.*, T8.1–8.3 | 🟪 Opus |
| T0.*, T3.4, T9.* | 👷 foreman / human |
