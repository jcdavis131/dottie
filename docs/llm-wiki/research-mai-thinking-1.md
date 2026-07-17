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

## Second-pass deltas (deeper companion analysis, same day)

- **Recovery sampling** — random sampling of banked traces beat biased selection; prompt
  diversity > traces-per-prompt. Factory spec 12 recovery rule updated (uniform random after
  prompt-dedupe, no stratification).
- **Zero-init attention output** — homogenized tokens at init break softmax routing (their MoE
  gate ≈ Ava's J-Space Router). New factory hill-climb candidate **T11.8**: attention-output
  norm gains = 0, falsify on nano via routing-KL health.
- **Tool-use reward shaping** — graders reward *parallel* tool calls, penalize redundant ones.
  ⬜ scout-cli idea: `agent bus` already judges proposed automations via the Frontier rubric —
  add parallel-vs-redundant call efficiency as a rubric criterion when that surface next opens.
- **Mem0-style memory layer** — stateless model + external retrieval pre-prompt + post-hoc
  trace capture minting long-term memories; user sees only the sanitized answer. Ecosystem
  analog: `ava-skills` memory-router (ShardMemo Tier A/B/C) is the retrieval half; the
  trace-capture→memory-mint half doesn't exist anywhere yet. Idea only, no task filed.
- **RFT framing** — Frontier Tuning rewards optimal *action sequences* (institutional muscle
  memory → shorter paths → fewer tokens) instead of runtime context injection. Long-term
  ecosystem analog: `audit.jsonl` execution traces are the workflow-trace substrate an
  RFT-style pass would tune against.
- **Benchmark humility** — headline numbers self-reported; same model trails on Terminal-Bench
  2.0 (46.0 vs 59.1/75.1); SWE-Bench Pro has known FP/FN issues. Never adopt vendor numbers as
  targets; measure locally (factory frozen snapshots + falsification gates).

## Cautions carried over

- **"reward" naming collision** — in the factory, `reward` = data-quality filter score. RL
  scalars are `rl_return`/`R_task`/`R_len`/`R_lang`, metrics namespaced `rl.*`. Keep it that way
  in any new plugin surfaces (e.g. `scout rtx results` columns).
- **Provenance humility** — MAI marketed "clean licensed lineage" while ingesting 24.2B Common
  Crawl pages. Ava's from-scratch/no-synthetic-pretraining claim stays honest only if datagen
  keeps its no-network rule (factory spec 02) and judges only grade, never generate training text.
- **No trillion-param cosplay** — LatentMoE/periodic-attention/512-expert routing rejected as
  out of scope; they solve inter-node bandwidth problems a single 4080 does not have.
