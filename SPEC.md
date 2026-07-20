<!-- v0.1 DRAFT — auto-mode spec gate (2026-07-20). Grounded in the codebase + TODOS.md, not
     invented. Operator: confirm or redirect the "Definition of done" and "Build priorities"
     sections — those are yours; everything above them is a description of what exists. -->

# SPEC — Dottie: Self-Evolving LLM Factory + Agent OS

**One line:** a closed-loop MLOps factory that trains your own small LLM, gates it on honest
evals, serves it to a self-extending agent (`scout`), and feeds the traces back into
retraining — solo, on public/free-tier only.

**The loop (the whole product is this loop closing):**
`data → train → eval gate → serve → agent → skills → build → deploy → traces → retrain`

## Components (what exists, and its honest state as of 2026-07-20)

| # | Component | Path | State |
|---|---|---|---|
| 1 | **Factory** — data pipeline, nano trainer, FastAPI serve, console webapp `/app` | `apps/ava-factory` | Code green (485 tests). **Fleet DOWN** (docker engine not started); training OFF since ~00:29. |
| 2 | **Research loop** — ideate→implement→validate→train→evaluate daemon that proposes model-block improvements | `apps/dottie` | Code green (199 w/ `AVA_FACTORY_ROOT`). Daemon **Disabled**. **Real wins = ZERO** — all 3 `sota` rows are artifacts (§5.3.R93); baseline is a measured regression needing re-seed. |
| 3 | **Agent OS** — `scout`, the agent's single self-extending CLI | `apps/scout-cli` | Code green (130). |
| 4 | **Trainer (RTX)** | `apps/scout-rtx` | UNMEASURED — needs `typer`+`rustbpe`+... installed. |
| 5 | **Eval gate** — anti-mock frontier rubric harness | `packages/ava-open-harness` | Green (30). |
| 6 | **Skills** — J-Space skill registry (memory-mint, jspace-context-engine, …) | `packages/ava-skills` | Green (80 via bare `pytest`). |
| 7 | **Graphify** — personal knowledge graph | `packages/personal-graphify` | Green (64), Windows-safe as of this session. |
| — | **Console** | `apps/ava-factory/dottie/webapp` (`/app`), live at arxiviq.com | Webapp contracts green (35 Node). Provenance-honest: unreachable sources render as explicit "unreachable", never stale numbers. |

## Invariants the platform must not violate (learned, enforced by tests)

- **Provenance travels with every number.** A metric is shown with how it was obtained; an
  unreachable source is labelled, never faked. A baseline set by a rejected/confounded
  candidate carries its caveat (`promoted_contaminated` / `promoted_capacity_flagged`).
- **A win is cross-seed, not within-run.** Significance uses per-seed spread; a within-run
  basis is flagged (§5.3.R93). Every promotion ships a paired `ab_nano.py` re-verifier.
- **Honest refusal over fabrication.** Ollama down, corpus missing, low memory → the stage
  refuses visibly and backs off; it never invents a result.
- **The daemon does not live-reload.** The `boot` line in `run.log` (git_sha + prompts_sha256)
  is the only ground truth for what code is running.

## Definition of "done" for end-to-end  *(operator: confirm/adjust — this is the target)*

The platform is "closing the loop" when, unattended:
1. The factory trains a nano checkpoint and the eval gate scores it (not 0.000).
2. `scout` serves that checkpoint and runs a task end-to-end, emitting a real trace.
3. The research loop proposes a block change, and a **genuine** (cross-seed, capacity-fair)
   improvement promotes — moving `real wins` off zero for the first time.
4. The console at arxiviq.com shows all of the above with honest provenance.

## Build priorities  *(the ordered path; detail + commands live in TODOS.md "DECISION QUEUE")*

0. **Reconcile git** — 250 local commits vs origin's cosmetic/docs commits; operator-run
   (he is curating origin by hand). Verified procedure: merge → `ruff check --fix` → suites.
1. **Re-seed the baseline, then restart** — the loop rejects everything against the current
   unreachable bar until re-seeded (`calibrate-baseline --overwrite`, ≈5.737).
2. **Fix the proposal pipeline** (search-quality, §item 8) — 36% of proposals are category
   errors; this is the highest-leverage change to *what gets proposed*.
3. **Per-seed factory trainer** — record `per_seed` so promotions are paired at source, not
   flagged after (§5.3.R93/R94; ~2 min/candidate idle).
4. **Fix the training monitor's pseudo-steps fallback** — when `reports/metrics_<preset>.jsonl`
   is absent (training never ran), `mode_monitor` falls back to STATUS.json and reports the
   data builder's tokens/docs as training "steps", crying "training stale" off the builder's
   clock (`dottie_continuous_loop.py:~408`, §5.3.R102, which corrects R100). Fix: absent
   metrics file → report "not running", never "stale at step N".

## Constraints

Solo, public/free-tier only (R2/Workers/Supabase/HF ZeroGPU, ONNX WASM, public pip). One
16 GB Windows 4080-laptop; RAM is the binding constraint (`NUM_GPU=0` puts Ollama models in
system RAM). Env: tests + trainer need `AVA_FACTORY_ROOT` (see `HANDOFF.md`). Ops discipline
in TODOS §9.
