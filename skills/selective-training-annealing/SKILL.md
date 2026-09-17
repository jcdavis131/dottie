---
name: selective-training-annealing
description: LLM pretraining data-ordering playbook distilled from ~90 papers: RHO-1 selective training mechanics, frontier-lab annealing recipes, initialization evidence, and open research directions. Use when designing training curricula, data mixtures, token-selection schemes, or LR schedules; when judging whether an ordering/selection claim is supported; or when scoping pretraining research. Not a substitute for the source writeup on fine detail.
---

# Selective Training, Annealing, and Initialization

Distilled from `selective-training-annealing-init-full-writeup.md`
(10,336 words, compiled 2026-09-07; SHA-256 in PROVENANCE.md).
Every number below traces to the source; evidence strength is marked
where the source marks it. See `references/` for the full detail.

## When to use this skill

- Designing or reviewing a pretraining data mixture, curriculum, or
  annealing phase.
- Deciding whether token selection (RHO-1 style) is worth the
  infrastructure cost for a given run.
- Checking a claim about initialization, warmup, or early-phase
  ordering against the literature.
- Scoping new research: the open gaps and directions live in
  `references/synthesis.md`.

## The load-bearing rules

1. **Selection by excess loss works, with a cliff.** Train only on
   tokens where the trainee underperforms a frozen reference model:
   `L_delta = L_theta - L_RM`, keep the top 60-70% per batch (hard
   mask). Dropping to 50% falls *below* the no-selection baseline.
   Verified only to 7B / under 100B tokens.
2. **Annealing = HQ mixture switch + LR collapse, always coupled.**
   No frontier lab changes one without the other. Anneal size varies
   wildly (0.26% to ~32% of budget); the coupling is the consensus,
   not the size.
3. **Place high-quality data at the forgetting minimum, not the very
   end.** TREC (single 2025 preprint, unreplicated): predict the
   optimizer's forgetting valley from AdamW hyperparameters *before*
   training and put the anneal mixture there. Late placement under
   decay-to-zero is explicitly suboptimal.
4. **Curriculum gains vanish under standard decay.** Ascending-quality
   ordering beats shuffling under constant LR but nearly disappears
   under cosine/WSD. Co-design the schedule with the curriculum or
   expect nothing.
5. **Initialization buys stability and efficiency, not final quality.**
   Small init at 1/sqrt(2N), 10-20% linear warmup, batch-size ramping
   from a near-zero critical batch size, curriculum-as-warmup (+3.5%,
   18-45% fewer steps to baseline). Final quality is dominated by peak
   LR, data, compute, and annealing design.
6. **The compositions are unexplored.** Selection x annealing,
   selection x schedule, and warmup-mixture design have no published
   results. That is where new work goes.

## Reference map

- `references/index.md` - what lives where.
- `references/rho1.md` - RHO-1: the 6-step loop, hyperparameters,
  results, limitations, reimplementation bill of materials.
- `references/annealing.md` - the universal 9-step pipeline, per-lab
  recipes, the comparison table, TREC placement rules.
- `references/initialization.md` - weight init, data-side init,
  warmup, early-phase dynamics, batch-size effects, the net verdict
  on "init matters as much as annealing."
- `references/synthesis.md` - the 10 research directions, the
  prioritized agenda, and the reimplementation checklists.

## Limits

- Nearly every positive result is verified at or below 7B / 1T tokens;
  the evidentiary bridge to frontier scale is thin.
- Claims are only as strong as their evidence rating in the source
  (STRONG / MODERATE / WEAK / THIN). Do not upgrade them.
- TREC, Luo et al.'s schedule-curriculum result, and several 2025-2026
  preprints are unreplicated. Treat as high-leverage hypotheses, not
  facts.
- This is a prototype skill: extraction was a single distillation pass
  plus an independent verification pass (see PROVENANCE.md). Fine
  numerical detail should be checked against the source writeup.
