# Verification-as-engine: learnings from the Emira/LemmaScript pattern (2026-07-23)

Source: a LinkedIn post by Fernanda Graciolli (screenshot-transcribed), plus a
brief public-source check. Every claim below is tagged [post], [web], or
[repo] (measured in this repo). Implemented counterpart: obligation tracking
in `apps/dottie/dottie/research/validate.py` + tests in
`apps/dottie/tests/test_obligations.py`; curriculum counterpart appended to
`apps/ava-factory/docs/CURRICULUM_EXPANSION.md`.

## 1. Public sources found

More exists publicly than the post implied:

- **LemmaScript is real and open source** [web]: lemmascript.com 301-redirects
  to **lemmascript.org** — "TypeScript with syntax for contracts", compiling
  annotated TypeScript (`requires` / `ensures` / invariants / `decreases`)
  to **Dafny or Lean 4** for verification while the executable pipeline stays
  unchanged. Repo: github.com/midspiral/LemmaScript (per the site).
- **Midspiral** [web]: midspiral.com — Graciolli co-founded it; tagline "the
  correctness layer for AI-generated software"; blog post "From Intent to
  Proof: Dafny Verification for Web Apps".
- **Emira** [web]: listed on lemmascript.org only as "coming soon" — the agent
  itself is NOT public. The post's agent-thinking trace remains the only
  visible mechanic.
- Adjacent [web]: arxiv 2603.22114 "Lemma Discovery in Agentic Program
  Verification" — the same obligation/lemma loop as an academic topic.

## 2. The pattern, distilled

**Verification-as-engine vs verification-as-gate.** A gate answers pass/fail
after the work is done. An engine makes the *proof state* the working state:
the agent's plan IS the list of unproven obligations, and progress is defined
as obligations discharged, not lines written. The post's trace [post] shows
exactly this: "Merge clean, **188 verified, 2 new content ensures to prove**.
Adding the two needed lemmas (expenseById after replaceExpense, sameEntries
reflexivity) and wiring them into the editExpense_ensures body."

Three mechanics fall out of that trace:

1. **Obligation tracking** — every change carries machine-checkable proof
   obligations with *names*. The system can always enumerate: N verified, M
   still open, and which M.
2. **The discharge loop** — the agent's next action is not "fix the error" but
   "discharge obligation X", often by adding a *specific named lemma* and
   wiring it into the *specific ensures body* that needs it. Feedback is
   aimed, per-property, not a wall of diagnostics.
3. **Train on the workflow** — the endgame [post] is fine-tuning an open model
   (Kimi K3 produced the verified app core) ON the verification workflow so
   obligation-discharge becomes a native behavior, not a scaffold. The
   training data is the workflow's own traces.

## 3. What maps to our substrate

The apps/dottie research loop is already verification-shaped [repo]: the
6-stage validator (`syntax → contract → static → dry_run → integration_width
→ residual_stream`) is a fail-fast checker over untrusted LLM-generated torch
blocks; `as_feedback()` + `diagnose_failure` hints are the discharge loop's
prompt; `validation.history` in the ledger is the trace; the KG mines
failure→fix trajectories; `evaluate.py`'s multi-seed/capacity gates are the
promotion-side checkers. What was missing was the *nouns*: failures were
tracebacks + prose hints, not named properties with open/closed state.

| Emira mechanic [post]                  | Our analog [repo]                                        |
|----------------------------------------|----------------------------------------------------------|
| "188 verified, 2 ensures to prove"     | `PROOF OBLIGATIONS [11/15 discharged]` in as_feedback()  |
| named lemma per obligation             | named obligation + stage-scoped repair hint              |
| wiring lemmas into the ensures body    | corrector rewrite targeting the named property           |
| proof state persists with the code     | per-attempt `obligations` list in validation.history     |
| fine-tune on the workflow              | verification-trace corpus (CURRICULUM_EXPANSION Leg 2)   |

## 4. What does NOT map — and why

**Real formal proofs on torch blocks are impractical here.** Stated plainly:

- **No spec language for the property that matters.** LemmaScript verifies
  discrete/functional properties (sums preserved, entries equal) against
  Dafny/Lean semantics [web]. Our candidates are float tensor programs whose
  load-bearing properties — "learns", "beats baseline at matched capacity" —
  are *empirical distributions over seeds*, not first-order propositions. The
  ledger's own history proves the point: all 3 "sota" rows were artifacts
  until multi-seed/capacity gates, not proofs, caught them [repo].
- **Float semantics defeat SMT at this scale.** Verifying even
  shape-conservation across dynamic reshapes/einsums in full generality means
  symbolic tensor algebra over a moving API surface; NaN/stability properties
  over f32 rounding are exactly what made the degeneracy tolerance
  scale-aware rather than absolute (`const_tol` in validate.py) [repo].
- **Cost asymmetry.** Our checkers discharge all 15 obligations in ~1 s of
  CPU; a Lean encoding of one block would cost more than the candidate is
  worth (candidates are disposable; Emira's app core is not).

So we adopt the *epistemology* (named obligations, enumerated open state,
aimed discharge, trace-mining) with *empirical* checkers as the proof
calculus. Honesty rule carried over from the validator: a checker that cannot
run reports `skipped`, never `discharged`.

## 5. Design as implemented (item 2)

**Vocabulary** — `OBLIGATIONS` in validate.py: 15 named properties, ordered by
stage and by within-stage check order (the ids are a public contract; ledger,
KG, and exporters key on them):

| obligation_id        | stage             | property (abbrev.)                          |
|----------------------|-------------------|---------------------------------------------|
| parses               | syntax            | source parses to a valid AST                |
| module_skeleton      | contract          | nn.Module class with forward                |
| block_signature      | contract          | forward takes exactly one tensor            |
| sandbox_policy       | contract          | no illegal imports/calls                    |
| names_resolve        | static            | ruff F821/E9 clean                          |
| constructible        | dry_run           | imports + instantiates from declared kwargs |
| executes             | dry_run           | one CPU forward completes                   |
| output_contract      | dry_run           | returns a tensor                            |
| shape_conservation   | dry_run           | output shape == input shape                 |
| finite_output        | dry_run           | no NaN/Inf                                  |
| non_degeneracy       | dry_run           | not a constant-offset block                 |
| rank_health          | dry_run           | no hidden-dim rank collapse                 |
| param_capacity       | dry_run           | has learnable parameters                    |
| width_generalization | integration_width | runs at [*, 256, 256]                       |
| gradient_flow        | residual_stream   | runs on non-leaf grad-carrying input        |

**Statuses**: `discharged | failed | unchecked | skipped`. Attribution rules
(all test-encoded):

- Stage passed → its obligations `discharged`; stage skipped → `skipped`
  (never laundered); stage unreached → `unchecked`.
- Failing stage: stage-scoped patterns (mirroring `_LEVEL_HINTS` reasoning)
  name the `failed` obligation(s); an unclassifiable detail falls back to the
  stage's execution-shaped obligation — a broad honest attribution over a
  wrong specific one.
- Within a failing dry_run, earlier obligations are `discharged` only when
  PROVABLE: a validator-literal message emitted after the forward completed
  implies everything before it ran clean; a raw traceback implies nothing, so
  stage-mates stay `unchecked`. `contract` checks every property in one pass,
  so its unmatched obligations are genuinely `discharged`.

**Surfaces** (all additive; existing hint text byte-identical):

- `ValidationResult.obligations()` → `[{obligation_id, property, stage,
  status}, ...]` (JSON-serializable strings only).
- `as_feedback()` appends, after the existing REPAIR HINT:
  `PROOF OBLIGATIONS [11/15 discharged]:` / `DISCHARGE NEXT -> rank_health:
  ...` / `already discharged (do not break these): ...` / `blocked behind the
  failure (unchecked): ...` — the Emira mechanic: the corrector is aimed at a
  named property.
- `validate_with_correction` history entries and
  `implementation.validation` both gain `obligations`, so every ledger
  attempt row is an obligation snapshot and failed→discharged transitions are
  minable without re-deriving attribution from text. (This is the "first-class
  id" the KG ingest comment already asked for — `kg/ingest.py` prefers a
  structured field over its regex taxonomy mirror.)
- The daemon never live-reloads: these edits are inert until its next
  operator-ordered restart [repo].

## 6. Design for the curriculum leg (item 3)

Graciolli's endgame is fine-tuning on the verification workflow [post]. Our
exact equivalent is exporting **obligation → lemma/fix → discharged** traces
from our own ledger: the existing
`apps/dottie/scripts/export_repair_transcripts.py` already emits
failure→hint→corrected-code rows from recovered experiments under structural
honesty constraints (ledger COPY only; recovered experiments only; no
fabricated per-attempt diffs). The extension — specified in
CURRICULUM_EXPANSION.md's Leg-2 addendum — adds the per-attempt `obligations`
arrays so each row becomes "obligation X open → action → obligation X
discharged", i.e. the training signal *is* the discharge loop, not just the
final fix.

## 7. Follow-ups (not done here, on purpose)

- `kg/taxonomy.py` still mirrors `_HINTS` by regex; migrating it to consume
  obligation ids + a first-class `hint_id` remains the DeepRefine proposal's
  scope (another lane owned validate.py when that mirror was written).
- Obligation-aware exporter flag on export_repair_transcripts.py (design in
  §6): new history rows carry `obligations` only after the daemon's next
  restart, so the exporter extension is worth landing together with that
  restart, not before.
