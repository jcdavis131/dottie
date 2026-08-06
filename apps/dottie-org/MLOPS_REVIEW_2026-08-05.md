# MLOps end-to-end review — every multi-tower MTNN on this box (2026-08-05)

Scope: raw data → features → normalization → towers → fusion → losses →
optimizer → LR → split/eval → export, for each network under `~/vector-*` plus
the shared lib in `apps/scout-cli/bigbang/plugins/vector/shared/`. Everything
below was read or measured this session; edits were made only in lanes not
claimed in-progress by Scout (COORDINATION.md: hoops-v6-fusion, gridiron-train,
unified-g2 are Scout's — findings only, no edits there).

## Verdict table

| network | towers → fusion | losses | optimizer / LR | split | state |
|---|---|---|---|---|---|
| **pitch** | 4-fam ResidualTower(16) → attn×gate fusion + ctx-emb → 24-d | arch CE + profile smooth-L1 (+ SupCon on pos, off by default) | AdamW 2e-3, const | LOCO by competition-season ✓ | beats PCA(3) 4/4 seed-verified; **loses to PCA(16)** knn5 −0.0375 (4.1× MDE). `--con-w 0.5` smoke beat PCA16 at 5 epochs; **5-seed full run in flight** |
| **equities career v5/v6** | 17× ResidualTower cat([x·m,m]) → causal transformer | temporal InfoNCE + fwd-ret MSE/rank/var + entry BCE + sector CE + vol/dd | AdamW 2e-3 (decay/no-decay groups), const | **was random-ticker with calendar overlap = leak** | **was unrunnable**: v5 NameError (stale `l` from lint rename), v6 self-matching InfoNCE + vacuous sector ids + fwd labels missing from every npz on disk. All fixed (`1015116`, `fd84d19`); walk-forward `--split temporal` added; **30-epoch ticker-vs-temporal A/B in flight** |
| **hoops** (Scout lane) | 18 towers, 64-d, v6 fusion in progress | — | — | player-split ✓ (leak fixed 1.0→0.977) | seed discipline + paired-floor already in repo; no edits from here |
| **gridiron** (Scout lane) | GatedFusion + season-emb → 32-d | regression heads | AdamW, const | rookie-season aware | own repo already flagged "CQS 63.16 is MAX of 3 seeds, one lucky seed" — Scout's baseline honesty work |
| **unified** (Scout lane) | frozen per-sport encoders → UnifiedTrunk d48→64 | task + SupCon(learnable per-sport temp) + CORAL + GRL(ramp) + VICReg | AdamW 1e-3, const; **warmup phases exist** (5ep task+CORAL before SupCon/GRL) | 50-shuffle null verified | most sophisticated loss stack; its SupCon is correct |
| **realty** | multi-tower | — | AdamW 1e-4 wd | **temporal ✓** ("train target year ≤ cut") | bit-identical reruns verified 08-05 |
| **tennis** | — | — | — | — | **full tree, ZERO commits** — at-risk state, needs an initial commit |
| **golf** | — | — | — | — | empty stub |
| **guard** | n/a (data dictionary) | — | — | — | new 08-05: names the 395 columns across six repos |
| **shared lib** (scout-cli) | ResidualTower + TransformerFusion(CLS) | info_nce/supcon/CORAL/VICReg/GRL | n/a (lib) | n/a | info_nce had self-in-denominator (floor = log 2 exactly) + fake stability claim → fixed `6c89614`, 3 RED-first tests |

## Cross-cutting findings (ranked by measured impact)

1. **InfoNCE was broken in 3 of 5 independent implementations.** Shared lib:
   self-similarity in denominator (perfect-pair floor = log 2, nan at small
   temp). Equities v5: NameError on first call since the ruff commit — the
   lint rename changed the loop var and not the body. Equities v6: target =
   anchor's own index (self-recognition; zero temporal content). Pitch and
   unified got it right — pitch even does max-subtraction + self-exclusion
   correctly. **Rule: a contrastive loss needs a test that anti-alignment
   scores WORSE than alignment; all three broken ones scored ~0 on both.**
2. **Split discipline is the difference between real and inflated numbers.**
   Correct: hoops player-split, pitch LOCO, realty temporal. Wrong: equities
   career random-ticker split shares 2015-2024 calendar time across arms —
   1-epoch smoke already shows ticker IC 0.1085 vs walk-forward IC 0.0122.
   The 30-epoch A/B will put a real number on the inflation.
3. **No trainer anywhere uses an LR schedule.** Constant AdamW everywhere
   (2e-3 pitch/equities, 1e-3 unified). Unified's loss-phase warmup is the
   only scheduling of any kind. Cosine decay is the cheapest untested lever
   in every lane — but per the pitch floor doctrine, it must clear paired
   MDE before it ships, and only ONE lever moves per experiment. The pitch
   con_w run is first; LR cycling is the queued second lever.
4. **Script-style trainers block testing.** Both equities career trainers
   execute at import — that is why NameError and self-matching NCE survived.
   career_losses.py is the pattern: extract the testable math. Pitch's
   train_mtnn.py has proper functions (and is the only trainer whose loss
   was ever seed-swept).
5. **Pitch trains with an all-ones mask** (`batch_fam` ignores the computed
   `M` matrix; only family-drop augmentation ever zeroes anything). If the
   corpus gains per-feature missingness, the mask channel is untrained.
   Not measured as a defect today (per-90 features are dense) — flagged.
6. **Labels can silently vanish.** Every equities npz on disk had `fwd=[]`
   — non-career rebuilds clobbered the career bundle, and the career
   trainer's first batch was the only thing that could notice. Rebuilt
   (coverage 4320/4831). A one-line coverage assert at bundle load would
   have caught this months earlier.

## Experiments in flight (both CPU; GPU is owned by dottie-factory-trainer-1)

- **pitch con_w=0.5, 5 seeds × 11 LOCO folds** on tm_full (isolated copy;
  shipped asset checksummed 88002e0d75ca012d). Success bar: mean knn5 −
  0.7874 (PCA16, deterministic) > 0 and clear of the con-arm sd; floor's
  paired-MDE doctrine applies. Cost side to report: recon MAE degradation.
- **equities v6 fixed-loss A/B: ticker vs temporal, 30 epochs each,
  seed 42.** Deliverable: the honest walk-forward IC, and the size of the
  ticker-split inflation.

## Queued next levers (one at a time, seed-swept, in lane)

1. Pitch: cosine LR schedule A/B (after con_w verdict).
2. Pitch: model selection currently on TRAIN loss ("best_val_loss" is
   misnamed) — hold out 15% of train for real early stopping.
3. Equities: sector-aware hard negatives in career_losses (v5's design,
   now testable).
4. Tennis: initial commit before anything else touches the tree.
5. Shared lib: adopt by an actual trainer or mark experimental — it has
   zero callers.
