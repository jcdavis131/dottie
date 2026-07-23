# Curriculum expansion — design note (DRAFT for operator edit, 2026-07-22)

Status: PROPOSAL ONLY. Nothing here is built or applied. Leg 1's concrete
mini.yaml diff posts to the steer thread after the current run's eval A/B
(the baseline every claim below gets measured against).

## Why expand (measured, not vibes)
- TPP 12.5 vs Chinchilla ~20 / T2T 40 — the feed's own hint: undertrained.
- Probes 0/200 (tool-selection) and agent-eval 0% — the weak axes are known.
- Packed runway full (3.16B tokens ready); 4 new generators barely exploited.
- The mechanism is proven: the p3 extension moved weighted ppl 7,814 → 276.

## Leg 1 — depth (post-eval, propose-first diff)
Extend the tool branch toward **TPP ≈ 20**: +0.9B tokens (~1.3 GPU-days at
measured ~10.5k tok/s). Mix shifts toward the probe-facing axes:
`tool_use` and `math_reasoning` up; keep an anneal tail. Gate: eval harness
A/B + probe delta vs the post-run baseline. No graduation without a win.

## Leg 2 — mission-aligned breadth (build after Leg 1 result)
New domains from the org's OWN platform (the data flywheel feeding the model
that powers it):
1. **Prediction & calibration reasoning** — real forecasting corpora we now
   generate: gridiron walk-forward backtest rows (projection vs actual, per
   position), pitch difficulty calibration (expected-solve modeling),
   equities coherence diagnostics. Task shapes: "given features → ranked
   forecast + calibrated confidence", "diagnose the miscalibration".
2. **Embedding-similarity reasoning** — vector-games material: nearest-
   neighbor justification, era-cohort normalization reasoning, archetype
   assignment with evidence (hoops/pitch spaces).
3. **Agentic tool-chains from scout `reach`** — probe → classify → unblock
   traces as tool_use curriculum (the self-unblocking loop as training data).
4. (candidate) **Repair-loop transcripts** — validator failure → hint →
   corrected code pairs from the research ledger, teaching self-correction.

## Build discipline (from memory: adding-curriculum-generator)
5 touch-points per generator; gotchas: ALL_GENERATORS is hardcoded;
source.phases must be a subset of generator.phases (else the collector
spins); every phase's weights must sum to 1.0. Each generator lands with its
own tests + a small sample audit before collectors pick it up.

## Sequencing
current run finishes → eval A/B posted → Leg 1 diff (steer approval) →
Leg 1 trains + gated eval → Leg 2 generators built + audited → Leg 2 leg
proposed. Research daemon runs in parallel on its own gates (repair hints
now in place).

*Edit freely — every list above is a menu, not a commitment.*

## Leg 2 addendum (2026-07-23) — verification-trace corpus

Upgrades candidate 4 (repair-loop transcripts) from failure→fix pairs to
**obligation→discharge traces**, after the Emira/LemmaScript pattern
(distilled in `tasks/artifacts/verification_engine_learnings.md`): the
training signal is the verification WORKFLOW itself — "obligation X open →
targeted rewrite → obligation X discharged" — which is exactly what
Graciolli's endgame fine-tunes an open model on, produced here from our own
ledger instead of a proof assistant.

- **New substrate (landed 2026-07-23):** `dottie/research/validate.py` now
  emits a named obligation ledger — 15 stable ids (`shape_conservation`,
  `rank_health`, `param_capacity`, `gradient_flow`, ...) with status
  `discharged|failed|unchecked|skipped` — per attempt in
  `validation.history` and in feedback (`PROOF OBLIGATIONS [11/15
  discharged] / DISCHARGE NEXT -> rank_health`). Note: the research daemon
  never live-reloads, so ledger rows carry `obligations` only after its next
  restart; rows before that are hint-era rows.
- **Existing machinery to extend:**
  `apps/dottie/scripts/export_repair_transcripts.py` already exports
  failure→hint→corrected-code rows from RECOVERED experiments off a ledger
  COPY, with its honesty constraints structural (copy-only, recovered-only,
  no fabricated per-attempt diffs, hint provenance stamped). Extension: emit
  each attempt's `obligations` array plus the delta vs the next attempt
  (`discharged_this_attempt: [...]`), so a row reads as a discharge step.
  Pre-restart rows get obligations recomputed at export time from stored
  per_level/detail (same recompute-and-say-so pattern as `hint_source`).
- **Task shapes:** "given failing obligation + code + hint, produce the
  rewrite that discharges it"; "given code + obligation ledger, name the
  obligation to discharge next"; "given before/after, state which obligations
  the edit discharged". All answerable offline from ledger data.
- **Same gates as the rest of Leg 2:** generator lands with its own tests +
  sample audit before collectors touch it; phases/weights per the build
  discipline above; corpus remains a PROPOSAL artifact until audited.
