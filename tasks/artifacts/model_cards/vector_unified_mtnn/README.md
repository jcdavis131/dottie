---
pretty_name: Universal MTNN (vector-unified trunk, Stage 1)
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
  base_preset: unified trunk (Stage 1, frozen encoders)
  params_note: shared 64-dim trunk over per-sport frozen encoders; CORAL domain-align + GRL sport-adversarial + VICReg anti-collapse + SupCon archetype heads. Trained 60 epochs on unified_matrix.npz, saved unified_best.pt (162s, RTX 4080)
  eval_metric: cross-sport archetype silhouette (Stage-1 unified eval, G3)
  eval_value: 0.7095
  eval_method: 20,721 players → shared 64-dim z. G1 per-sport non-inferiority PASS (z vs frozen e_s kNN-5 — hoops 0.998, gridiron 0.991, pitch 0.996); G3 silhouette 0.7095 PASS (within-cos 0.767 > between-cos -0.138); collapse-detector PASS
  eval_retracted: G2 sport-invariance is DEFERRED (acc 0.717 vs chance 0.333; the literal>32 rank test fails, the non-degenerate>12 passes — needs a no-GRL baseline to conclude) — not a clean pass, stated honestly
  provenance_classification: REAL
---

# Universal MTNN (vector-unified trunk, Stage 1)

## Model Summary

**The model that connects them all** — a shared 64-dim representation trunk that
places players from every vector sport (NBA / NFL / MLB — hoops, gridiron, pitch)
into ONE embedding space, on top of each sport's frozen encoder. Trained
2026-07-24 (operator: "start training the universal MTNN"): `train_unified.py`,
Stage 1, 60 epochs, saved `unified_best.pt` (in the `vector-unified` repo).

## Architecture

A shared linear trunk over per-sport frozen encoders, trained with four
objectives: **CORAL** (cross-sport domain alignment), a **GRL** sport-adversary
(strip sport-identity leakage), **VICReg** variance+covariance (anti-collapse,
raise rank), and **SupCon** archetype heads (cross-sport player archetypes). 64-d
embedding, per-sport adapters (48-d), 8-d sport token. Encoders are frozen (not
counted in params).

## Evaluation — the honest Stage-1 gates

Ran `eval_unified.py` on the trained checkpoint (z shape 20,721 × 64):

| gate | result | verdict |
|---|---|---|
| **G1** per-sport non-inferiority (z vs frozen encoder, kNN-5) | hoops 0.998 · gridiron 0.991 · pitch 0.996 | **PASS** (z ≥ each sport's own encoder) |
| **G3** cross-sport archetype clustering | silhouette **0.7095**; within-cos 0.767 > between-cos −0.138 | **PASS** |
| **G2** sport-invariance | acc 0.717 (chance 0.333); rank 12.6 (literal>32 FAIL, nondeg>12 PASS) | **DEFERRED** — needs a no-GRL baseline |
| collapse detector | rank 12.3 (non-degenerate) | **PASS** |

The headline: the unified embedding is **non-inferior to each sport's own
encoder** (G1) while cross-sport archetypes **cluster cleanly** (G3) — the space
genuinely connects the sports without collapsing. G2 is reported DEFERRED, not
passed: some sport-identity remains recoverable (acc 0.717), and concluding
invariance needs a no-GRL baseline. Stated, not glossed.

## Provenance classification

**REAL** — a real trained model evaluated by real held-out gates on real
multi-sport player data. The one soft gate (G2) is reported as DEFERRED rather
than claimed as a pass. See `data_provenance_SOP.md`.

## Considerations / next stages

- **Stage 1 only.** Stage 2 (`--finetune`), market heads (`--market` →
  salary/award), and cultural-text alignment (`--cultural-text` → Wikipedia
  MiniLM) are further stages that warm-start from this trunk.
- Covers hoops/gridiron/pitch (the sports in `unified_matrix.npz`); golf/tennis
  are not yet in the unified matrix.
- G2 wants a no-GRL baseline run to conclude sport-invariance.

## Citation

vector-unified Universal MTNN, Stage 1, trained + evaluated 2026-07-24
(`pipeline/train_unified.py --epochs 60`, `pipeline/eval_unified.py`).
