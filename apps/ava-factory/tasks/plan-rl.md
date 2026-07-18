# RL climb plan — GRPO-lite for branch specialists (spec 12)

Date: 2026-07-17
Source: MAI-Thinking-1 hill-climbing review → `docs/RL_INTEGRATION.md`
Contract: `specs/12_rl_training.md` (T12R.1–T12R.4)
Tracker: `TODOS.md` T11.7
Status: **contract landed; T12R.2+ blocked on T9.3/T9.5** (branch checkpoints must exist first)

## Objective

Per-branch RL climb (math first) that survives long runs without entropy collapse or policy
divergence, produces a trace bank that both recovers crashes and feeds MOPD consolidation,
and is judged by EG trend across ≥2 ladder rungs — never a single-point win.

## Phase order (do not skip)

1. **Measure (GPU-free, unblocked now)**
   - `efficiency_gain.py` landed with tests. When the mini run (T9.2) completes, fit the
     nano→mini baseline curve for the current recipe: this is the curve every candidate
     (arch lever, data mix, RL recipe) is priced against. Add `eg_flops`/`eg_time` columns
     to `tasks/hillclimb-log.md` entries going forward.
   - T12R.1 returns provider: deterministic verify_fns over B-family / workflow_jobbench
     generators + pass-rate ledger. Pure pipeline code, testable without GPU.
2. **SFT stage (gated on T9.3/T9.5)** — `sft_sota_2025.py` stub → real branch SFT; this is
   the "pre-RL checkpoint" every recovery resets to.
3. **GRPO-lite (T12R.2)** — nano math branch first. All three discipline mechanisms on from
   step one. Acceptance = the falsification gates in spec 12 (undisciplined run must collapse,
   disciplined must hold; injected spike must trip outer clip; recovery-from-bank must restore).
4. **Safety-in-return (T12R.3)** — paired harmful/borderline sets; borderline refusal rate flat
   across climb; `safety_blackmail` 0/180 holds.
5. **Consolidate** — MOPD unify per `docs/DISTILLATION_INTEGRATION.md`, re-run 5 canonical
   J-tests + frontier rubric. EG verdict (T12R.4) decides whether the recipe advances a rung.

## Gates

| Gate | Math | Target |
|------|------|--------|
| G1 baseline curve | `fit_power_law(nano, mini)` valid (b > 0) | before any candidate EG |
| G2 entropy band | `rl.entropy` within `H_target ± band` | ≥ 90% of steps |
| G3 circuit breaker | `rl.outer_clip_hits / steps` | ~0 (nonzero = alert, investigate) |
| G4 recovery | post-recovery harness score vs pre-crash peak | within eval noise |
| G5 safety | borderline refusal delta across climb; harmful compliance | ≤ 0; = 0 |
| G6 promotion | `eg_trend(nano, mini)` verdict | `promote` (both rungs > 1, big rung not worst) |

## Open questions (log answers here)

- `H_target` for a 13.8M-param policy — 0.3 is a 1T-scale number; nano may want higher. Sweep.
- G=8 rollout group: enough advantage signal at nano? If variance too high, try G=16 nano-only.
- Trace-bank size threshold before bank-recovery beats `--mode earlier` weight-recovery.
- Semantic dedup (3rd funnel stage): defer until base1b corpus; revisit when T4.x reopens.
- Agentic branch (post-math): reuse-the-container/synthesize-the-task pattern (BugPilot-style)
  for verifiable envs from our own repos + reward parallel tool calls / penalize duplicates —
  second-pass findings, `docs/RL_INTEGRATION.md`.
- Anti-slop (AI-content) classifier on the *collector* path before base1b-scale web ingestion
  (datagen is exempt — deliberately synthetic, self-generated, provenance known).
