---
pretty_name: Universal MTNN (vector-unified trunk)
license: mit
language:
- en
tags:
- mtnn
- unified-representation
- cross-sport
- multi-task
- vector-site
- dottie
model_info:
  base_preset: unified trunk (frozen encoders; Stage 1 + market + cultural-text heads)
  params_note: shared 64-dim trunk over per-sport frozen encoders; CORAL domain-align + GRL sport-adversarial + VICReg anti-collapse + SupCon archetype heads. Trained 60 epochs on unified_matrix.npz, saved unified_best.pt (162s, RTX 4080)
  eval_metric: cross-sport archetype silhouette (Stage-1 unified eval, G3)
  eval_value: 0.7639
  eval_method: 20,721 players → shared 64-dim z. Trained through Stage 1 → +market ($/prestige) → +cultural-text (Wikipedia MiniLM). G1 per-sport non-inferiority PASS throughout; G3 cross-sport silhouette rises 0.7095→0.7424→0.7639 with each stage. Headline is the cultural stage (all heads). collapse-detector PASS.
  eval_retracted: G2 sport-invariance stays DEFERRED across all stages and WORSENS (acc 0.717→0.778→0.891) as sport-correlated market/cultural signal is added — Stage 2 (unfreeze encoders, unified_stage2_best.pt) is the structural fix, not these heads. Stated honestly, not a clean pass.
  provenance_classification: REAL
---

# Universal MTNN (vector-unified trunk)

## Model Summary

**The model that connects them all** — a shared 64-dim representation trunk that
places players from every vector sport (NBA / NFL / MLB — hoops, gridiron, pitch)
into ONE embedding space, on top of each sport's frozen encoder. Trained
2026-07-24 (operator: "start training the universal MTNN" → "green light all
optional next steps") through three stages: base trunk → `+market` ($/prestige
heads) → `+cultural-text` (Wikipedia MiniLM alignment). Checkpoints
`unified_best.pt` / `unified_market.pt` / `unified_cultural.pt` in the
`vector-unified` repo.

## Architecture

A shared linear trunk over per-sport frozen encoders, trained with four
objectives: **CORAL** (cross-sport domain alignment), a **GRL** sport-adversary
(strip sport-identity leakage), **VICReg** variance+covariance (anti-collapse,
raise rank), and **SupCon** archetype heads (cross-sport player archetypes). 64-d
embedding, per-sport adapters (48-d), 8-d sport token. Encoders are frozen (not
counted in params).

## Evaluation — honest gates across the training stages

Trained 2026-07-24 through three stages, each `eval_unified.py`'d on z (20,721 × 64):

| stage | ckpt | G1 non-inferiority | G3 silhouette | G2 sport-acc |
|---|---|---|---|---|
| **Stage 1** (base trunk) | unified_best.pt | PASS (0.998/0.991/0.996) | 0.7095 | 0.717 |
| **+ market** ($/prestige heads) | unified_market.pt | PASS | **0.7424** | 0.778 |
| **+ cultural-text** (Wikipedia MiniLM) | unified_cultural.pt | PASS | **0.7639** | 0.891 |

- **G1 per-sport non-inferiority: PASS every stage** — the unified z stays ≥ each
  sport's own frozen encoder.
- **G3 cross-sport archetype clustering rises 0.7095 → 0.7639** — the market ($ /
  prestige, sport-agnostic units) and cultural-text (encyclopedia bios) heads add
  genuine cross-sport structure. This is the "connect them all" payoff.
- **G2 sport-invariance stays DEFERRED and WORSENS (0.717 → 0.891)** — honest and
  expected: market/cultural signal is itself sport-correlated, so sport becomes
  MORE recoverable. The structural fix for G2 is **Stage 2** (`train_stage2.py`,
  which UNFREEZES the per-sport encoders so alignment can drift them into a shared
  basis); a `unified_stage2_best.pt` exists but the Stage-1 eval can't load its
  (different) structure, so no G2 number is claimed for it here.
- collapse detector PASS (rank ~12, non-degenerate) at every stage.

The headline: the unified embedding is **non-inferior to each sport's own
encoder** (G1) while cross-sport archetypes **cluster cleanly and improve** (G3)
— the space genuinely connects the sports without collapsing. G2 is reported
DEFERRED, not passed: some sport-identity remains recoverable (rising to acc
0.891 with the enrichment heads), and concluding
invariance needs a no-GRL baseline. Stated, not glossed.

## Provenance classification

**REAL** — a real trained model evaluated by real held-out gates on real
multi-sport player data. The one soft gate (G2) is reported as DEFERRED rather
than claimed as a pass. See `data_provenance_SOP.md`.

## Considerations / next stages

- **Stage 1 + market + cultural-text trained** (this session). **Stage 2
  (`train_stage2.py`, the structural G2 fix that unfreezes the per-sport encoders)
  is BLOCKED**: it loads the live hoops encoder, but the committed hoops MTNN
  checkpoint no longer matches current hoops code (`strict=True` fails — an
  `injury` tower was added, `towers.career` input 10→30, fusion 556→588). It needs
  the hoops encoder re-exported from current code in the hoops repo first. So G2
  remains unresolved by encoder-unfreeze until that upstream drift is fixed.
- Covers hoops/gridiron/pitch (the sports in `unified_matrix.npz`); golf/tennis
  are not yet in the unified matrix.
- G2 remains the open gate: enrichment heads raise sport-recoverability; only
  Stage 2 (encoder unfreeze) or a no-GRL baseline resolves it.

## Citation

vector-unified Universal MTNN, trained + evaluated 2026-07-24
(`train_unified.py --epochs 60` base / `--market` / `--cultural-text`;
`eval_unified.py --ckpt <name>`).
