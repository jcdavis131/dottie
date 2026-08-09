---
generated_by: scripts/business/generators/changelog.py
generated_at: "2026-08-09T03:09:18+00:00"
classification: REAL
method: "Commit subject lines listed verbatim from read-only git history between the merge base and HEAD; subjects matching the naming policy are withheld."
measured: true
sources:
  - ref: "merge-base main..HEAD"
    sha: "6d7391f4c4934a5842fe6670dbd2ddef906a56fb"
  - ref: "HEAD"
    sha: "c770fc61b0dcddaa0af56a45bd91b4b7a23d7a29"
---

# Change log

- c770fc6 (2026-08-09) docs(curriculum): measured sizing of self-labeling training material in the monorepo
- b153d4a (2026-08-09) fix(factory): distill model-load bug + gated multi-tier distillation ladder
- a64e9d8 (2026-08-09) feat(memory): coarse-to-fine shard retrieval — lazy per-scope inverted index in mint, scope passthrough in router
- a5e84fb (2026-08-09) feat(harness): streaming timeline store — offset-indexed G_history stats feed graph-plan failure risk
- 9ef2762 (2026-08-09) docs(spec): LongCat 2.0 adoption spec — map sparse-attention/engram/muP/MOPD insights onto Dottie
