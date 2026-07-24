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
