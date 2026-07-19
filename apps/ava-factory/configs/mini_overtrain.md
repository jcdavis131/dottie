# mini_overtrain — successor to mini for T2T / data-constrained scaling

Same ~171M architecture as ``mini.yaml``, intentionally longer unique-token
budget so tokens-per-param lands in the overtrain band (research brief / spec 14).

Live ``mini`` at ~1.63B tokens ≈ **9.5 TPP** (undertrain vs Chinchilla ~20).
Finishing the current 2.5B plan only reaches ≈ **14.6 TPP** — still short of
T2T. This preset targets **~40 TPP** ≈ **6.85B** unique tokens.

Do **not** switch the live trainer mid-run. Use for the next GO run after
``mini`` finishes or after an explicit stop+recreate.

```yaml
# inherit shape from mini; only training.tokens_total + phase budgets change.
# Concrete phase splits: keep p0–p5 proportions of mini, scaled × (6.85B/2.5B).
```

See ``tasks/plan-sota-pretrain-2026-07.md`` Phase 1 scaling notes.
