# Research brief — MAI-Thinking-1 "Hill-Climbing Machine" → Ava ecosystem (2026-07-17)

**Solo personal project, no connection to employer, built with public/free-tier only**

> Token-efficient brief. Full mapping: `ava-agi-factory-v6-4/docs/RL_INTEGRATION.md`.
> Buildable contract: `ava-agi-factory-v6-4/specs/12_rl_training.md`. Source: review of the
> MAI-Thinking-1 technical-report analysis (Microsoft AI, Build 2026 — 1T/35B-active MoE
> reasoner, AIME'25 97.0, SWE-Bench Pro 52.8).

## The 6 findings that matter here

1. **Rank invariance is dead** — small-scale ablation winners can invert at scale. Only a
   ≥2-rung scaling ladder trend counts.
2. **Efficiency Gain (EG)** — price every lever as "compute baseline would need to match it";
   EG_FLOPs (algorithmic) vs EG_Time (wall-clock) decoupled, so un-kerneled wins survive review.
3. **GRPO discipline system** — entropy thermostat (integral controller widening/tightening the
   clip bound), outer ratio clip (hard circuit breaker over unclipped zones), self-distill
   recovery (bank verified traces; on crash SFT a fresh checkpoint from ~1M traces; diversity >
   quantity).
4. **Difficulty-scaled length penalty** — R_len inverse to historical pass rate: easy → harsh
   (snap to answer), hard → relaxed (budget to derive). Kills think-longer reward hacking.
5. **Verifiable environments only** — deterministic execution checks (SymPy, fail-to-pass tests
   in containers; 102M PRs → 265,617 envs, 5.5% survival) as the reward source; safety folded
   into the *same* return (unsafe compliance ≡ unnecessary refusal) — no alignment tax.
6. **Model tiering** — small sibling on the same harnesses takes ~90% of traffic; escalate to
   the big reasoner only for deep multi-step work (their Flash-5B solves with ~60% fewer tokens).

## Per-repo actions (landed ✅ / planned ⬜)

| Repo | Action |
|------|--------|
| `ava-agi-factory-v6-4` | ✅ `docs/RL_INTEGRATION.md` (adopt/adapt/reject map) · ✅ `specs/12_rl_training.md` GRPO-lite contract T12R.1–4 (blocked on T9.3/T9.5) · ✅ `efficiency_gain.py` + 15 tests (EG fit + ladder promote/hold verdicts) · ✅ T11.7 + `tasks/plan-rl.md` updated |
| `scout-rtx` | ✅ `programs/program-ava.md` promotion gate: 2-rung ladder + EG_Time logged in `ava-mapping.jsonl`; only `eg_verdict: promote` gets cherry-picked into `model_1b.py` |
| `scout-cli` | ✅ this brief · ⬜ `ava route` already tiers Ollama models (qwen3:32b → heuristic fallback) — finding 6 says formalize escalation the other way too: route routine plugin calls to the heuristic/small model and *escalate* to qwen3:32b only on low confidence; confidence threshold already exists in `_heuristic_route` |
| `ava-open-harness` | ⬜ per-task difficulty ledger (historical pass rates) is spec'd in T12R.1; when it exists, `frontier_rubric` categories can weight by difficulty tier the way finding 4 scales R_len |
| `ava-skills` | none — loader's wRRF progressive disclosure (+79% token cut) is already the token-budget mechanism; no change from this review |
| `personal-graphify` | none — graph-first querying is orthogonal; EG/ladder data stays in factory + rtx results |

## Cautions carried over

- **"reward" naming collision** — in the factory, `reward` = data-quality filter score. RL
  scalars are `rl_return`/`R_task`/`R_len`/`R_lang`, metrics namespaced `rl.*`. Keep it that way
  in any new plugin surfaces (e.g. `scout rtx results` columns).
- **Provenance humility** — MAI marketed "clean licensed lineage" while ingesting 24.2B Common
  Crawl pages. Ava's from-scratch/no-synthetic-pretraining claim stays honest only if datagen
  keeps its no-network rule (factory spec 02) and judges only grade, never generate training text.
- **No trillion-param cosplay** — LatentMoE/periodic-attention/512-expert routing rejected as
  out of scope; they solve inter-node bandwidth problems a single 4080 does not have.
