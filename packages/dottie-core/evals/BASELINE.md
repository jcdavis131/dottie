# Dottie-on-WorkGym baseline

Model: `heuristic-v0` via `DottieWorkGymPolicy` (dottie-heuristic-bridge-v0)
Date: 2026-10-12 · seeds 7–26 (n=20 per env)

| env | mean reward | notes |
|---|---|---|
| `workgym/inbox-triage-v0` | **1.000** | keyword sets hand-derived from the fixture distribution — a *tuned* baseline |
| `workgym/cron-ops-v0` | **0.900** | per-option keyword retrieval; misses `dead-trigger` (stopwords neutered the discriminative terms; `poll` in the logs outscored the right answer) |

## How to read this

- The inbox 1.0 is **not** a generalization claim. The keyword sets were written
  after reading the fixtures. It is the number a hand-tuned heuristic gets;
  a learned model must beat it *without* hand-tuned keywords to count as progress.
- The cron-ops 0.9 is the honest number: evidence→option keyword retrieval,
  no fixture-specific tuning beyond generic stopwords.
- `pair-programming-v0` and `pr-review-v0` have no dottie policy yet — the
  heuristic model cannot write code or read diffs. That's the next model.

## Reproduce

```
PYTHONPATH=/path/to/workgym python3 evals/workgym_eval.py --seeds 20
```

## Rules for challengers

1. No hand-tuned keywords for the eval fixtures.
2. Same seeds, same harness, same bridge.
3. A win is a higher mean with non-overlapping stderr, or a new env covered.
4. Never promote without a held-out eval win (standing rule).
