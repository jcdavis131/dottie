# Data Provenance Audit — MASTER verdict (2026-07-24)

Answers the operator's directive: "carefully review all data pipelines for our
models to make sure this is 100% accurate and we aren't using bad data — garbage
in, garbage out." Three parallel read-only audits: training data, eval/probe
data, vector-site data. Detail in `provenance_audit_{training,evals,vectorsites}.md`.
Fix rules in `data_provenance_SOP.md`.

## Headline verdict

- **What TRAINS the model is CLEAN.** The live pipeline (dottie.train ← packed
  shards ← collector/sources.yaml) is provenance-clean: every generator computes
  or curates its answers (honest-synthetic), real HF sources are used, dedup +
  13-gram decontamination are real, the tokenizer is sha-pinned. No fabricated
  facts, np.random features, or mislabels reach the model. Garbage-in does NOT
  apply to training.
- **What MEASURES the model has a real bug.** The "held-out" perplexity bins are
  NOT provably disjoint from training (two uncorrelated split keys) — so the
  research loop's primary signal can't tell memorization from capability. This is
  the single most important finding.
- **What we SHIP publicly is mostly real, with one bad offender.** 3 of 4 vector
  sites train on real public data (nba.com, StatsBomb, nflverse). vector-equities
  ships fabrications (np.random "skills", hardcoded metric literals, a
  Math.random() "projection vs actual" table on a finance site). vector-pitch's
  dashboard is a fabricated marketing layer over an honest game+pipeline.

## Ranked remediation (severity × exposure)

| # | Issue | Where | Class | Action |
|---|---|---|---|---|
| 1 | Held-out ppl bins not disjoint from training (sha1%100 vs sha1[:8]/2³²) | ava-factory/scripts/build_eval_data.py:30 | eval integrity | Rebuild held-out via `split.assign_split()=='test'` (training's own key); assert membership; drop concept-doc fallback |
| 2 | Math.random() "Next FY Projection vs Actual" table on a public finance site | vector-equities index.html:291-294 | FABRICATION (public) | Delete the table |
| 3 | np.random skills + modulo archetypes + hardcoded metric literals in shipped assets | vector-equities export_v6_real_assets.py:211,214,215,263-267 | FABRICATION (public) | Strip; recompute from the real model head, or relabel SYNTHETIC + contamination block |
| 4 | Fabricated LLM/KV-cache/tok-s dashboard stack + wrong dims + hardcoded chart numbers | vector-pitch dashboard.html/.js | FABRICATION (public) | Delete non-existent-stack claims; fix 48-d→16-d, 17→3 families; relabel "92% win" as cosine threshold; recompute/delete hardcoded numbers |
| 5 | Errored (HTTP-500) run scored as "0% capability" | agent-eval run_eval.py + scoreboard.md | eval integrity | Exclude status∈{error,harness_error} from success math (NaN, not 0); render "errored" distinct; regenerate |
| 6 | Committed live HF_TOKEN | ava-factory .env | SECRET (operator) | Rotate the token + remove from git history — operator action |
| 7 | Baseline provenance flagged but not gated ("4.5 placeholder" can anchor promotions) | apps/dottie/dottie/research/evaluate.py | eval integrity | Promote provenance/contamination from recording to a hard promotion gate |
| 8 | Transductive CQS strip (recall@10 1.0 = memorization) hardcoded | vector-hoops model.html:324-329 | mislabel (public, mild) | Relabel TRANSDUCTIVE/train-set (honest held-out strip already shown beside it) |
| 9 | Dead garbage data path (stub tokenizer + mock trainer) | ava-factory streaming_data.py, train_1b_deepspeed.py | latent footgun | Delete or clearly quarantine (not wired live; zero current impact) |
| 10 | Stale config labels: sources.yaml/mini.yaml claim active synthetic sources are "weight 0 / post-mini" | ava-factory configs | transparency | Correct the labels to match live weights |
| 11 | ~66% of training tokens synthetic (honest-synthetic, not real text) | curriculum | directive reconciliation | Operator decision: raise real-text fraction vs accept computed-synthetic for math/logic/tool-use |

## What is GOOD (do not disturb)

Research `evaluate.py` (multi-seed gate, honest baseline provenance recording),
the judge (honest None on parse/backend failure), the probes (golds verified
correct — the ~0/200 is weak-model + brittle-scorer, not broken probes), and the
gridiron pipeline (real nflverse end-to-end, simulation honestly labeled) are the
most honest components. hoops/pitch/gridiron DATA and game logic are real.

## Execution order

Internal integrity first (1, 5, 7 — no public/destructive risk), then the public
fabrications worst-first (2, 3, 4, 8), then the operator-only/decision items
(6 secret, 9 delete, 10 labels, 11 curriculum mix).
